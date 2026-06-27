import argparse
import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app_settings
import application_assistant as assistant
import llm_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

LIVE_AGENT_DIR = Path(tempfile.gettempdir()) / "jobtrack_live_agent"
MAX_TEXT = 9000


def _normalize_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _live_session_id() -> str:
    return str(os.environ.get("JOBTRACK_LIVE_SESSION_ID") or "").strip()


def _safe_session_id(session_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", session_id)


def _session_file(session_id: str) -> Path:
    LIVE_AGENT_DIR.mkdir(parents=True, exist_ok=True)
    return LIVE_AGENT_DIR / f"{_safe_session_id(session_id)}.json"


def _answer_file(session_id: str) -> Path:
    LIVE_AGENT_DIR.mkdir(parents=True, exist_ok=True)
    return LIVE_AGENT_DIR / f"{_safe_session_id(session_id)}.answer.json"


def _write_session(session_id: str, payload: dict[str, Any]) -> None:
    if not session_id:
        return
    payload = {
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    _session_file(session_id).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_live_answer(session_id: str) -> dict[str, str]:
    path = _answer_file(session_id)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    answers: dict[str, str] = {}
    for item in payload.get("answers", []):
        if not isinstance(item, dict):
            continue
        key = _normalize_key(item.get("key") or item.get("label") or "")
        answer = str(item.get("answer") or "").strip()
        if key and answer:
            answers[key] = answer
    return answers


def _save_answer_memory(answers: dict[str, str]) -> None:
    if not answers:
        return
    try:
        settings = app_settings.get_app_settings(force_refresh=True)
        existing = settings.get("applicationQuestionAnswers")
        if not isinstance(existing, dict):
            existing = {}
        existing.update(answers)
        settings["applicationQuestionAnswers"] = existing
        assistant.supabase_utils.supabase.table(app_settings.SETTINGS_TABLE).upsert(
            {
                "id": app_settings.SETTINGS_ID,
                "settings": app_settings.normalize_settings(settings),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="id",
        ).execute()
        app_settings.get_app_settings(force_refresh=True)
    except Exception as exc:
        logging.warning("Could not save answer memory: %s", exc)


async def _wait_for_user_answer(
    session_id: str,
    question: str,
    target_id: str | None,
    messages: list[str],
    remember: bool = True,
) -> dict[str, str]:
    answer_path = _answer_file(session_id)
    if answer_path.exists():
        try:
            answer_path.unlink()
        except Exception:
            pass
    key = _normalize_key(question)
    _write_session(
        session_id,
        {
            "status": "waiting_for_answers",
            "questions": [{"label": question, "key": key, "suggestedAnswer": "", "known": False}],
            "messages": messages[-10:],
        },
    )
    timeout_seconds = int(os.environ.get("JOBTRACK_LIVE_ANSWER_TIMEOUT_SECONDS") or "1200")
    deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
    while datetime.now(timezone.utc).timestamp() < deadline:
        answers = _read_live_answer(session_id)
        if answers:
            if remember:
                _save_answer_memory(answers)
            messages.append(f"User answered: {question}")
            return answers
        await asyncio.sleep(1)
    messages.append(f"Timed out waiting for answer: {question}")
    return {}


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


async def _snapshot(page: Any) -> dict[str, Any]:
    try:
        body_text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""
    data = await page.evaluate(
        """() => {
            const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
            };
            const labelFor = (el) => {
                const bits = [];
                const add = (v) => { if (v && String(v).trim()) bits.push(String(v).trim()); };
                if (el.labels) Array.from(el.labels).forEach((label) => add(label.innerText || label.textContent));
                add(el.getAttribute('aria-label'));
                add(el.getAttribute('placeholder'));
                add(el.getAttribute('name'));
                add(el.getAttribute('id'));
                const container = el.closest('label, [role="group"], .field, .form-group, .application-question, div');
                if (container) add((container.innerText || container.textContent || '').slice(0, 300));
                return bits.find(Boolean) || '';
            };
            const elements = [];
            const form_fields = [];
            const buttons_links = [];
            const selector = [
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"])',
                'textarea',
                'select',
                '[contenteditable="true"]',
                'button',
                'a[href]',
                '[role="button"]'
            ].join(',');
            Array.from(document.querySelectorAll(selector)).forEach((el, index) => {
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || '';
                const type = (el.getAttribute('type') || '').toLowerCase();
                const isHiddenCheckbox = tag === 'input' && type === 'checkbox' && !visible(el);
                if (!visible(el) && !isHiddenCheckbox) return;
                const text = ((el.innerText || el.textContent || '')).trim();
                const id = `agent_${index}`;
                el.setAttribute('data-jobtrack-agent-id', id);
                const item = {
                    id,
                    tag,
                    role,
                    type,
                    text: text.slice(0, 180),
                    label: labelFor(el).slice(0, 300),
                    value: (el.value || '').slice(0, 120),
                    checked: Boolean(el.checked),
                    disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
                    href: (el.getAttribute('href') || '').slice(0, 220)
                };
                elements.push(item);
                const labelText = `${item.label} ${item.text} ${item.id}`.toLowerCase();
                if (labelText.includes('honeypot')) return;
                const isField = ['input', 'textarea', 'select'].includes(tag) || el.getAttribute('contenteditable') === 'true';
                if (isField) form_fields.push(item);
                if (!isField) buttons_links.push(item);
            });
            return { title: document.title, url: location.href, form_fields, buttons_links, elements };
        }"""
    )
    data["body_text"] = re.sub(r"\s+", " ", body_text)[:MAX_TEXT]
    return data


def _profile_context() -> dict[str, Any]:
    profile = app_settings.get_application_profile()
    answers = app_settings.get_application_auto_answers()
    known_questions = app_settings.get_app_settings().get("applicationQuestionAnswers", {})
    if not isinstance(known_questions, dict):
        known_questions = {}
    email, _password = assistant._portal_credentials()
    return {
        "profile": profile,
        "auto_answers": answers,
        "known_question_answers": known_questions,
        "portal_email": email or profile.get("email", ""),
        "password_policy": "For password fields use value PORTAL_PASSWORD. The executor will replace it securely.",
        "resume_policy": "Use upload_resume for resume/CV/file upload fields.",
    }


def _agent_prompt(snapshot: dict[str, Any], candidate: Any, resume_path: Path, messages: list[str]) -> str:
    context = _profile_context()
    return f"""
You are JobTrack Apply Agent, an autonomous job application browser agent.

Goal: complete and submit the job application for the candidate, using the supplied resume and profile.
Act like a Naukri Neo Pro style agent: fill known fields yourself, ask the user only when the answer is truly unknown, then continue immediately.

Hard rules:
- Use only target_id values visible in Page snapshot.
- For fill/select/upload_resume, use target_id from Page snapshot form_fields only.
- For click/submit, use target_id from Page snapshot buttons_links only.
- Never invent credentials. For password fields use exact value PORTAL_PASSWORD.
- For resume/CV uploads, use action type upload_resume.
- If a question can be answered from profile, auto_answers, or known_question_answers, fill it without asking.
- Ask the user only for a missing answer that is not inferable.
- Do not stop at manual review unless blocked by captcha, OTP/MFA, broken page, or no meaningful action remains.
- If there is a final submit/apply button and all visible required fields are handled, use submit.
- Return only JSON.

Candidate:
{json.dumps(candidate.__dict__, ensure_ascii=False)}

Resume path:
{str(resume_path)}

Profile/settings:
{json.dumps(context, ensure_ascii=False)}

Recent agent messages:
{json.dumps(messages[-12:], ensure_ascii=False)}

Page snapshot:
{json.dumps(snapshot, ensure_ascii=False)}

Return JSON with this schema:
{{
  "thought": "short reason",
  "status_message": "message for user",
  "actions": [
    {{"type": "fill", "target_id": "agent_0", "value": "text"}},
    {{"type": "select", "target_id": "agent_1", "value": "India"}},
    {{"type": "check", "target_id": "agent_1"}},
    {{"type": "click", "target_id": "agent_2"}},
    {{"type": "upload_resume", "target_id": "agent_3"}},
    {{"type": "ask_user", "target_id": "agent_4", "question": "How many years of experience do you have in Microservices?"}},
    {{"type": "submit", "target_id": "agent_5"}},
    {{"type": "wait"}}
  ],
  "done": false,
  "blocked_reason": ""
}}
"""


async def _locator_by_id(page: Any, target_id: str) -> Any:
    direct = page.locator(f"[data-jobtrack-agent-id='{target_id}']")
    if await direct.count() > 0:
        return direct.first

    escaped = re.sub(r"(['\"\\\\])", r"\\\1", target_id)
    semantic = page.locator(
        f"#{escaped}, "
        f"[name='{escaped}'], "
        f"[aria-label='{escaped}'], "
        f"[placeholder='{escaped}'], "
        f"[id*='{escaped}' i], "
        f"[name*='{escaped}' i], "
        f"[aria-label*='{escaped}' i], "
        f"[placeholder*='{escaped}' i]"
    )
    if await semantic.count() > 0:
        return semantic.first

    normalized_target = _normalize_key(target_id)
    controls = page.locator(
        "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select, [contenteditable='true'], button, a[href], [role='button']"
    )
    for index in range(min(await controls.count(), 120)):
        control = controls.nth(index)
        try:
            if not await control.is_visible(timeout=300):
                continue
            label = await assistant._field_label_text(control, index)
            text = ((await control.inner_text(timeout=300)) or "") if await control.count() else ""
            haystack = _normalize_key(f"{label} {text}")
            if normalized_target and (normalized_target in haystack or haystack in normalized_target):
                return control
        except Exception:
            continue
    return direct.first


async def _is_editable_field(element: Any) -> bool:
    try:
        return bool(
            await element.evaluate(
                """(el) => {
                    const tag = el.tagName.toLowerCase();
                    const type = (el.getAttribute('type') || '').toLowerCase();
                    return tag === 'textarea'
                        || tag === 'select'
                        || el.getAttribute('contenteditable') === 'true'
                        || (tag === 'input' && !['hidden','submit','button','checkbox','radio','file'].includes(type));
                }"""
            )
        )
    except Exception:
        return False


async def _fallback_fill_field(page: Any, target_id: str, value: str) -> bool:
    normalized_target = _normalize_key(target_id)
    normalized_value = _normalize_key(value)
    field_hints: list[str] = []
    if "@" in value:
        field_hints.extend(["email", "e mail"])
    if re.search(r"\+?\d[\d\s-]{7,}", value):
        field_hints.extend(["phone", "mobile", "telephone"])
    if any(token in normalized_value for token in ["venkateswarlu", "derangula"]):
        field_hints.extend(["name", "full name", "first name", "last name"])
    if any(token in normalized_value for token in ["bengaluru", "karnataka", "india", "puram"]):
        field_hints.extend(["address", "city", "location", "state", "country"])
    field_hints.append(normalized_target)

    controls = page.locator(
        "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file']), textarea, select, [contenteditable='true']"
    )
    for hint in [item for item in field_hints if item]:
        for index in range(min(await controls.count(), 120)):
            control = controls.nth(index)
            try:
                if not await control.is_visible(timeout=300):
                    continue
                try:
                    existing = await control.input_value(timeout=300)
                    if str(existing or "").strip():
                        continue
                except Exception:
                    pass
                label = await assistant._field_label_text(control, index)
                haystack = _normalize_key(label)
                if hint in haystack or haystack in hint:
                    await control.fill(value, timeout=5000)
                    return True
            except Exception:
                continue
    return False


async def _upload_resume_fallback(page: Any, resume_path: Path) -> bool:
    inputs = page.locator("input[type='file']")
    for index in range(min(await inputs.count(), 12)):
        field = inputs.nth(index)
        try:
            await field.set_input_files(str(resume_path), timeout=8000)
            return True
        except Exception:
            continue
    upload_buttons = page.get_by_role(
        "button",
        name=re.compile(r"(upload|resume|cv|attach|import)", re.IGNORECASE),
    )
    if await upload_buttons.count() > 0:
        try:
            await upload_buttons.first.click(timeout=5000)
            await page.wait_for_timeout(1500)
        except Exception:
            pass
        inputs = page.locator("input[type='file']")
        for index in range(min(await inputs.count(), 12)):
            field = inputs.nth(index)
            try:
                await field.set_input_files(str(resume_path), timeout=8000)
                return True
            except Exception:
                continue
    return False


async def _click_fallback(page: Any, preferred: str = "") -> bool:
    patterns = []
    if preferred:
        patterns.append(re.escape(preferred))
    patterns.extend([
        r"^(next|continue|save and continue|review|apply now|apply|submit|send application)$",
        r"(next|continue|review|apply|submit|send)",
    ])
    for pattern in patterns:
        button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
        if await button.count() == 0:
            button = page.get_by_role("link", name=re.compile(pattern, re.IGNORECASE))
        if await button.count() > 0:
            try:
                await button.first.click(timeout=8000)
            except Exception:
                await button.first.evaluate("(el) => el.click()", timeout=3000)
            return True
    return False


async def _execute_action(page: Any, action: dict[str, Any], resume_path: Path, allow_submit: bool, session_id: str, messages: list[str]) -> str:
    action_type = str(action.get("type") or "").strip().lower()
    target_id = str(action.get("target_id") or "").strip()
    value = str(action.get("value") or "")
    if value == "PORTAL_PASSWORD":
        _email, password = assistant._portal_credentials()
        value = password

    if action_type == "wait":
        await page.wait_for_timeout(2000)
        return "waited"

    if action_type == "ask_user":
        question = str(action.get("question") or "Please provide the missing application answer.").strip()
        answers = await _wait_for_user_answer(session_id, question, target_id or None, messages)
        answer = next((item for item in answers.values() if item), "")
        if answer and target_id:
            field = await _locator_by_id(page, target_id)
            await field.fill(answer, timeout=5000)
            try:
                await field.press("Enter", timeout=1000)
            except Exception:
                pass
        return "asked_user"

    if not target_id:
        return "missing_target"

    element = await _locator_by_id(page, target_id)

    if action_type == "fill":
        if await _is_editable_field(element):
            await element.fill(value, timeout=5000)
        elif not await _fallback_fill_field(page, target_id, value):
            await element.fill(value, timeout=5000)
        return f"filled {target_id}"

    if action_type == "select":
        try:
            await element.select_option(label=value, timeout=3000)
        except Exception:
            try:
                await element.select_option(value=value, timeout=3000)
            except Exception:
                if await _is_editable_field(element):
                    await element.fill(value, timeout=5000)
                    await element.press("Enter", timeout=1000)
                elif not await _fallback_fill_field(page, target_id, value):
                    await element.fill(value, timeout=5000)
        return f"selected {target_id}"

    if action_type == "check":
        try:
            await element.check(timeout=5000, force=True)
        except Exception:
            await element.evaluate(
                """(el) => {
                    el.checked = true;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                timeout=3000,
            )
        return f"checked {target_id}"

    if action_type == "upload_resume":
        try:
            await element.set_input_files(str(resume_path), timeout=8000)
        except Exception:
            if not await _upload_resume_fallback(page, resume_path):
                raise
        return f"uploaded resume {target_id}"

    if action_type == "click":
        try:
            href = await element.get_attribute("href")
        except Exception:
            href = None
        if href and re.match(r"^https?://", href):
            await page.goto(href, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(6000)
            return f"navigated {target_id}"
        try:
            await element.click(timeout=8000)
        except Exception:
            try:
                await element.evaluate("(el) => el.click()", timeout=3000)
            except Exception:
                if not await _click_fallback(page):
                    raise
        return f"clicked {target_id}"

    if action_type == "submit":
        try:
            label = await element.evaluate(
                """(el) => [
                    el.innerText || el.textContent || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || ''
                ].join(' ')"""
            )
        except Exception:
            label = ""
        if not re.search(r"\b(submit|send application|submit application|finish application)\b", label, re.IGNORECASE):
            try:
                await element.click(timeout=8000)
            except Exception:
                try:
                    await element.evaluate("(el) => el.click()", timeout=3000)
                except Exception:
                    if not await _click_fallback(page, label):
                        raise
            return f"clicked non-final submit candidate {target_id}"
        if not allow_submit:
            return "final_submit_blocked_by_flag"
        try:
            await element.click(timeout=10000)
        except Exception:
            try:
                await element.evaluate("(el) => el.click()", timeout=3000)
            except Exception:
                if not await _click_fallback(page, label):
                    raise
        return f"submitted {target_id}"

    return f"unknown_action {action_type}"


def _is_human_gate(text: str) -> str | None:
    if re.search(r"captcha|verify you are human|robot", text, re.IGNORECASE):
        return "captcha_required"
    if re.search(r"otp|one.?time|verification code|multi.?factor|two.?factor|mfa", text, re.IGNORECASE):
        return "otp_or_mfa_required"
    return None


async def _handle_otp_or_mfa_gate(page: Any, session_id: str, messages: list[str]) -> bool:
    if not session_id:
        return False
    answers = await _wait_for_user_answer(
        session_id,
        "Enter the OTP / verification code shown or received for this application portal.",
        None,
        messages,
        remember=False,
    )
    code = next((value for value in answers.values() if str(value).strip()), "")
    if not code:
        return False

    fields = page.locator(
        "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file']), textarea"
    )
    filled = False
    for index in range(min(await fields.count(), 12)):
        field = fields.nth(index)
        try:
            if not await field.is_visible(timeout=500):
                continue
            current = await field.input_value(timeout=500)
            if current:
                continue
            await field.fill(code, timeout=5000)
            filled = True
            messages.append("Filled OTP / verification code from live UI.")
            break
        except Exception:
            continue
    if not filled:
        return False

    for pattern in [
        r"^(verify|continue|next|submit|confirm)$",
        r"(verify|continue|next|submit|confirm)",
    ]:
        button = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
        if await button.count() > 0:
            try:
                await button.first.click(timeout=8000)
                await page.wait_for_timeout(3000)
                messages.append("Submitted OTP / verification step.")
                return True
            except Exception:
                pass
    try:
        await fields.first.press("Enter", timeout=1000)
        await page.wait_for_timeout(3000)
        messages.append("Submitted OTP / verification step with Enter.")
        return True
    except Exception:
        return filled


async def _handle_captcha_gate(page: Any, session_id: str, messages: list[str]) -> bool:
    if not session_id:
        return False
    answers = await _wait_for_user_answer(
        session_id,
        "Human verification / captcha is shown in the opened browser. Solve it there, then type done here and click Send Answer & Continue.",
        None,
        messages,
        remember=False,
    )
    confirmed = any(str(value).strip() for value in answers.values())
    if not confirmed:
        return False

    await page.wait_for_timeout(3000)
    snapshot = await _snapshot(page)
    if _is_human_gate(snapshot.get("body_text", "")) == "captcha_required":
        messages.append("Captcha still appears after your confirmation.")
        return False
    messages.append("Human verification completed; continuing application.")
    return True


async def _handle_known_oracle_steps(page: Any, messages: list[str]) -> bool:
    url = page.url.lower()
    if "oraclecloud.com" not in url:
        return False
    profile = app_settings.get_application_profile()
    email = profile.get("email", "")
    changed = False

    apply_now = page.get_by_text(re.compile(r"^apply now$", re.IGNORECASE))
    if await apply_now.count() > 0 and "/apply/" not in url:
        await apply_now.first.click(timeout=10000)
        await page.wait_for_timeout(3000)
        messages.append("Oracle step: clicked Apply Now.")
        changed = True

    email_inputs = page.locator("input[type='email'], input[id*='email' i], input[name*='email' i]")
    if email and await email_inputs.count() > 0:
        try:
            current = await email_inputs.first.input_value(timeout=1000)
        except Exception:
            current = ""
        if not current:
            await email_inputs.first.fill(email, timeout=5000)
            messages.append("Oracle step: filled email.")
            changed = True

    terms = page.locator("input[type='checkbox'][id*='legal' i], input[type='checkbox'][id*='disclaimer' i]")
    if await terms.count() > 0:
        try:
            if not await terms.first.is_checked(timeout=1000):
                label = page.get_by_text(re.compile(r"I agree with the terms and conditions", re.IGNORECASE))
                if await label.count() > 0:
                    await label.first.click(timeout=5000)
                else:
                    await terms.first.check(timeout=5000, force=True)
                messages.append("Oracle step: accepted terms.")
                changed = True
        except Exception:
            await terms.first.evaluate(
                """(el) => {
                    el.checked = true;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }"""
            )
            messages.append("Oracle step: accepted terms with DOM fallback.")
            changed = True

    if changed:
        next_button = page.get_by_role("button", name=re.compile(r"^next$", re.IGNORECASE))
        if await next_button.count() > 0:
            try:
                await next_button.first.click(timeout=10000)
                await page.wait_for_timeout(4000)
                messages.append("Oracle step: clicked Next.")
            except Exception:
                pass
    return changed


async def run_agent(job_id: str, headless: bool, allow_submit: bool, max_steps: int) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    session_id = _live_session_id()
    candidate = assistant.fetch_candidate_from_queue(job_id)
    if not candidate:
        return {"job_id": job_id, "status": "not_found", "messages": [f"No queued application found for {job_id}."]}

    resume_path = assistant.download_resume(candidate)
    messages: list[str] = ["LLM Apply Agent started."]
    result = {
        "job_id": candidate.job_id,
        "apply_url": candidate.apply_url,
        "resume_path": str(resume_path),
        "status": "running",
        "portal": candidate.portal if hasattr(candidate, "portal") else candidate.provider,
        "messages": messages,
    }
    _write_session(session_id, {"status": "agent_running", "messages": messages[-10:]})

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context_options: dict[str, Any] = {}
        state_path = assistant._linkedin_storage_state_path() if assistant._is_linkedin_url(candidate.apply_url) else None
        if state_path and Path(state_path).exists():
            context_options["storage_state"] = state_path
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1365, "height": 768},
            **context_options,
        )
        page = await context.new_page()
        await page.goto(candidate.apply_url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(8000)

        for step in range(1, max_steps + 1):
            if await _handle_known_oracle_steps(page, messages):
                await page.wait_for_timeout(1500)
            snapshot = await _snapshot(page)
            gate = _is_human_gate(snapshot.get("body_text", ""))
            if gate:
                if gate == "otp_or_mfa_required" and await _handle_otp_or_mfa_gate(page, session_id, messages):
                    await page.wait_for_timeout(1500)
                    continue
                if gate == "captcha_required" and await _handle_captcha_gate(page, session_id, messages):
                    await page.wait_for_timeout(1500)
                    continue
                result["status"] = gate
                messages.append(f"Human verification gate detected: {gate}")
                break

            _write_session(
                session_id,
                {
                    "status": "agent_thinking",
                    "job_id": candidate.job_id,
                    "portal": result.get("portal"),
                    "messages": messages[-10:] + [f"Analyzing page step {step}."],
                },
            )

            try:
                raw = llm_client.primary_client.generate_content(
                    _agent_prompt(snapshot, candidate, resume_path, messages),
                    system_prompt="You are a careful browser automation agent. Return valid JSON only.",
                    temperature=0.1,
                    model_override=os.environ.get("LLM_AGENT_MODEL", "gpt-4o-mini"),
                )
                decision = _extract_json(raw)
            except Exception as exc:
                result["status"] = "llm_error"
                messages.append(f"LLM agent failed: {exc}")
                break

            status_message = str(decision.get("status_message") or decision.get("thought") or "Agent decided next action.")
            messages.append(status_message)
            _write_session(
                session_id,
                {
                    "status": "agent_acting",
                    "job_id": candidate.job_id,
                    "portal": result.get("portal"),
                    "messages": messages[-10:],
                },
            )

            actions = decision.get("actions") if isinstance(decision.get("actions"), list) else []
            if decision.get("done"):
                result["status"] = "submitted" if "submitted" in " ".join(messages).lower() else "completed"
                break
            if not actions:
                result["status"] = "manual_review_required"
                messages.append(str(decision.get("blocked_reason") or "LLM found no safe next action."))
                break

            submitted = False
            for action in actions[:4]:
                try:
                    before_url = page.url
                    outcome = await _execute_action(page, action, resume_path, allow_submit, session_id, messages)
                    messages.append(outcome)
                    if str(action.get("type")).lower() == "submit" and allow_submit:
                        submitted = True
                except Exception as exc:
                    messages.append(f"Action failed safely: {action} -> {exc}")
                    if str(action.get("type")).lower() == "ask_user":
                        result["status"] = "manual_review_required"
                        break
                await page.wait_for_timeout(1000)
                action_type = str(action.get("type") or "").lower()
                if action_type in {"click", "submit"} or page.url != before_url:
                    await page.wait_for_timeout(4000)
                    break

            if submitted:
                result["status"] = "submitted"
                break

        else:
            result["status"] = "max_steps_reached"
            messages.append(f"Stopped after {max_steps} LLM agent steps.")

        if result["status"] == "submitted":
            assistant._update_job_after_submission(candidate, result)
            assistant.queue_candidate(candidate, status="submitted", result=result)
        else:
            assistant.queue_candidate(candidate, status=result["status"], result=result)

        try:
            if assistant._is_linkedin_url(candidate.apply_url):
                await assistant._save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
        except Exception:
            pass
        await browser.close()

    result["messages"] = messages[-40:]
    _write_session(
        session_id,
        {
            "status": result["status"],
            "job_id": candidate.job_id,
            "portal": result.get("portal"),
            "messages": result["messages"][-12:],
        },
    )
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-driven live application agent.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--allow-submit", action="store_true")
    parser.add_argument("--max-steps", type=int, default=25)
    args = parser.parse_args()
    result = await run_agent(args.job_id, headless=args.headless, allow_submit=args.allow_submit, max_steps=args.max_steps)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
