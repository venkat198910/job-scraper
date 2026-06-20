import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app_settings
import config
import supabase_utils

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

APPLICATION_QUEUE_TABLE = "application_queue"
APPLICATION_QUEUE_STORAGE_BUCKET = getattr(config, "SUPABASE_RESUME_STORAGE_BUCKET", "resumes")
APPLICATION_QUEUE_STORAGE_PREFIX = "application_queue"
SAFE_FINAL_SUBMIT_TEXT = re.compile(r"^(submit application|submit|apply)$", re.IGNORECASE)
WORKDAY_URL_PATTERN = re.compile(r"(myworkdayjobs\.com|myworkdaysite\.com|workdayjobs\.com)", re.IGNORECASE)
PORTAL_PATTERNS = {
    "workday": WORKDAY_URL_PATTERN,
    "greenhouse": re.compile(r"(greenhouse\.io|boards\.greenhouse\.io)", re.IGNORECASE),
    "lever": re.compile(r"(lever\.co|jobs\.lever\.co)", re.IGNORECASE),
    "ashby": re.compile(r"(ashbyhq\.com|jobs\.ashbyhq\.com)", re.IGNORECASE),
    "smartrecruiters": re.compile(r"(smartrecruiters\.com|jobs\.smartrecruiters\.com)", re.IGNORECASE),
}
NEXT_BUTTON_TEXT = re.compile(r"^(next|continue|save and continue|review|review application)$", re.IGNORECASE)
FINAL_SUBMIT_TEXT = re.compile(r"^(submit application|submit|apply|send application)$", re.IGNORECASE)


@dataclass
class ApplicationCandidate:
    job_id: str
    job_title: str
    company: str
    location: str
    provider: str
    resume_score: int
    customized_resume_id: str
    resume_link: str
    apply_url: str
    application_type: str
    scraped_at: str = ""
    posted_at: str = ""


def linkedin_job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}"


def detect_portal(apply_url: str, provider: str = "") -> str:
    for portal, pattern in PORTAL_PATTERNS.items():
        if pattern.search(apply_url or ""):
            return portal
    if (provider or "").lower() == "linkedin":
        return "linkedin"
    return (provider or "unknown").lower()


def detect_application_type(job: dict[str, Any]) -> str:
    provider = (job.get("provider") or "").lower()
    apply_url = build_apply_url(job)
    if detect_portal(apply_url, provider) == "workday":
        return "workday_profile_review"
    if detect_portal(apply_url, provider) in {"greenhouse", "lever", "ashby", "smartrecruiters"}:
        return f"{detect_portal(apply_url, provider)}_review"
    if provider == "linkedin":
        return "linkedin_easy_apply_review"
    return "company_portal_review"


def build_apply_url(job: dict[str, Any]) -> str:
    provider = (job.get("provider") or "").lower()
    if provider == "linkedin":
        return linkedin_job_url(str(job["job_id"]))
    return str(job.get("apply_url") or job.get("url") or "")


def _score(job: dict[str, Any]) -> int:
    try:
        return int(float(job.get("resume_score") or 0))
    except (TypeError, ValueError):
        return 0


def fetch_candidates(limit: int, min_score: int, provider: str | None = "linkedin") -> list[ApplicationCandidate]:
    response = supabase_utils.supabase.rpc(
        "get_top_scored_jobs_custom_sort",
        {
            "p_page_number": 1,
            "p_page_size": limit,
            "p_provider": provider,
            "p_min_score": min_score,
            "p_max_score": 100,
            "p_is_interested_option": None,
            "p_search_query": None,
        },
    ).execute()

    candidates = []
    for job in response.data or []:
        if not job.get("customized_resume_id") or not job.get("resume_link"):
            continue
        if _score(job) < min_score:
            continue

        application_type = detect_application_type(job)
        candidates.append(
            ApplicationCandidate(
                job_id=str(job["job_id"]),
                job_title=job.get("job_title") or "",
                company=job.get("company") or "",
                location=job.get("location") or "",
                provider=job.get("provider") or "",
                resume_score=_score(job),
                customized_resume_id=str(job["customized_resume_id"]),
                resume_link=str(job["resume_link"]),
                apply_url=build_apply_url(job),
                application_type=application_type,
                scraped_at=str(job.get("scraped_at") or ""),
                posted_at=str(job.get("posted_at") or ""),
            )
        )

    return candidates


def candidate_pool_limit(limit: int, mode: str) -> int:
    """Scan a wider pool for auto-apply because many top jobs are not Easy Apply."""
    if mode != "auto-apply":
        return limit
    return max(limit * 10, 50)


def _write_json_env_to_file(env_key: str, output_path: str) -> str | None:
    value = os.environ.get(env_key, "").strip()
    if not value:
        return None

    path = Path(output_path)
    path.write_text(value, encoding="utf-8")
    return str(path)


def _linkedin_storage_state_path() -> str | None:
    storage_state = os.environ.get("LINKEDIN_STORAGE_STATE")
    if storage_state and Path(storage_state).exists():
        return storage_state

    return _write_json_env_to_file("LINKEDIN_STORAGE_STATE_JSON", "linkedin_storage_state.json")


def queue_candidate(candidate: ApplicationCandidate, status: str = "application_ready") -> bool:
    payload = {
        "job_id": candidate.job_id,
        "customized_resume_id": candidate.customized_resume_id,
        "application_type": candidate.application_type,
        "portal": detect_portal(candidate.apply_url, candidate.provider),
        "status": status,
        "run_mode": "review",
        "apply_url": candidate.apply_url,
        "resume_path": candidate.resume_link,
        "score": candidate.resume_score,
        "notes": {
            "job_title": candidate.job_title,
            "company": candidate.company,
            "location": candidate.location,
            "submit_policy": "never_submit_without_manual_confirmation",
        },
    }

    try:
        supabase_utils.supabase.table(APPLICATION_QUEUE_TABLE).upsert(
            payload,
            on_conflict="job_id,application_type",
        ).execute()
        return True
    except Exception as exc:
        logging.warning("Could not write application_queue row for %s; using storage fallback: %s", candidate.job_id, exc)
        return queue_candidate_to_storage(candidate, payload)


def queue_candidate_to_storage(candidate: ApplicationCandidate, payload: dict[str, Any]) -> bool:
    storage_path = (
        f"{APPLICATION_QUEUE_STORAGE_PREFIX}/"
        f"{candidate.job_id}_{candidate.application_type}.json"
    )
    try:
        supabase_utils.supabase.storage.from_(APPLICATION_QUEUE_STORAGE_BUCKET).upload(
            path=storage_path,
            file=json.dumps(payload, indent=2).encode("utf-8"),
            file_options={"content-type": "application/json", "upsert": "true"},
        )
        logging.info("Queued application candidate in storage fallback: %s", storage_path)
        return True
    except Exception as exc:
        logging.error("Could not queue application candidate %s: %s", candidate.job_id, exc)
        return False


def download_resume(candidate: ApplicationCandidate) -> Path:
    file_bytes = supabase_utils.supabase.storage.from_(config.SUPABASE_STORAGE_BUCKET).download(
        candidate.resume_link
    )
    output_dir = Path(tempfile.gettempdir()) / "jobtrack_application_resumes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{candidate.job_id}.pdf"
    output_path.write_bytes(bytes(file_bytes))
    return output_path


async def _click_first_button(page: Any, pattern: re.Pattern[str], messages: list[str], timeout: int = 5000) -> bool:
    button = page.get_by_role("button", name=pattern)
    if await button.count() == 0:
        return False
    try:
        await button.first.click(timeout=timeout)
        messages.append(f"Clicked button: {pattern.pattern}")
        return True
    except Exception as exc:
        messages.append(f"Detected button but could not click safely: {exc}")
        return False


async def _launch_chromium(playwright: Any, headless: bool) -> Any:
    cdp_url = os.environ.get("PLAYWRIGHT_CDP_URL", "").strip()
    if cdp_url:
        return await playwright.chromium.connect_over_cdp(cdp_url)

    launch_options: dict[str, Any] = {"headless": headless}
    executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if executable_path:
        launch_options["executable_path"] = executable_path
    return await playwright.chromium.launch(**launch_options)


async def _save_context_state(context: Any, env_key: str, default_path: str) -> str:
    state_path = os.environ.get(env_key, default_path)
    await context.storage_state(path=state_path)
    return state_path


async def _page_has_button(page: Any, pattern: re.Pattern[str]) -> bool:
    return await page.get_by_role("button", name=pattern).count() > 0


async def _linkedin_login_visible(page: Any) -> bool:
    if "login" in page.url.lower() or "uas/login" in page.url.lower():
        return True
    try:
        if await page.get_by_role("link", name=re.compile(r"^sign in$", re.IGNORECASE)).count() > 0:
            return True
        if await page.get_by_role("button", name=re.compile(r"^sign in$", re.IGNORECASE)).count() > 0:
            return True
    except Exception:
        return False
    return False


async def _wait_for_manual_linkedin_login(page: Any, context: Any, result: dict[str, Any], wait_seconds: int) -> bool:
    if wait_seconds <= 0:
        result["messages"].append("LinkedIn login required. Run again with --manual-login-wait after opening Chrome, then log in once.")
        return False

    result["messages"].append(f"Waiting up to {wait_seconds}s for manual LinkedIn login.")
    await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
    deadline = datetime.now(timezone.utc).timestamp() + wait_seconds
    while datetime.now(timezone.utc).timestamp() < deadline:
        await page.wait_for_timeout(2000)
        if not await _linkedin_login_visible(page):
            state_path = await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
            result["messages"].append(f"LinkedIn session saved to {state_path}. Set LINKEDIN_STORAGE_STATE to this path for scheduled runs.")
            return True

    result["messages"].append("Manual LinkedIn login was not completed before the wait timeout.")
    return False


async def _upload_resume_if_possible(page: Any, resume_path: Path, messages: list[str]) -> bool:
    file_inputs = page.locator("input[type='file']")
    if await file_inputs.count() == 0:
        messages.append("No resume upload input detected on the current step.")
        return False

    try:
        await file_inputs.first.set_input_files(str(resume_path))
        messages.append("Custom resume selected for upload.")
        return True
    except Exception as exc:
        messages.append(f"Resume upload input detected but upload failed safely: {exc}")
        return False


async def _fill_profile_defaults(page: Any, messages: list[str]) -> None:
    for label, value in _load_profile_defaults().items():
        await _fill_label_if_present(page, label, value, messages)


async def _fill_portal_login_if_allowed(page: Any, allow_login: bool, messages: list[str]) -> bool:
    if not allow_login:
        messages.append("Portal login was detected or possible, but login is disabled. Enable it in settings or pass --allow-login.")
        return False

    email = (
        os.environ.get("APPLICATION_PORTAL_EMAIL")
        or os.environ.get("APPLICATION_EMAIL")
        or app_settings.get_application_profile().get("email")
        or ""
    )
    password = os.environ.get("APPLICATION_PORTAL_PASSWORD", "")
    if not email or not password:
        messages.append("Portal login is allowed, but APPLICATION_PORTAL_EMAIL/APPLICATION_PORTAL_PASSWORD is not fully configured.")
        return False

    email_inputs = page.locator(
        "input[type='email'], input[name*='email' i], input[id*='email' i], input[autocomplete='username']"
    )
    password_inputs = page.locator(
        "input[type='password'], input[name*='password' i], input[id*='password' i], input[autocomplete='current-password']"
    )

    filled_any = False
    if await email_inputs.count() > 0:
        await email_inputs.first.fill(email, timeout=3000)
        messages.append("Filled portal email.")
        filled_any = True
    if await password_inputs.count() > 0:
        await password_inputs.first.fill(password, timeout=3000)
        messages.append("Filled portal password.")
        filled_any = True

    if not filled_any:
        return False

    sign_in_button = page.get_by_role("button", name=re.compile(r"^(sign in|log in|login|continue)$", re.IGNORECASE))
    if await sign_in_button.count() > 0:
        await sign_in_button.first.click(timeout=5000)
        messages.append("Clicked portal login/continue.")
        await page.wait_for_timeout(2000)
    return True


async def _detect_required_unfilled(page: Any) -> list[str]:
    labels = []
    required_controls = page.locator(
        "input[required], textarea[required], select[required], [aria-required='true']"
    )
    count = await required_controls.count()
    for index in range(min(count, 25)):
        control = required_controls.nth(index)
        try:
            value = await control.input_value(timeout=1000)
            if value:
                continue
        except Exception:
            pass
        try:
            aria_label = await control.get_attribute("aria-label")
            name = await control.get_attribute("name")
            control_id = await control.get_attribute("id")
            labels.append(aria_label or name or control_id or f"required-field-{index + 1}")
        except Exception:
            labels.append(f"required-field-{index + 1}")
    return labels


async def _maybe_submit(page: Any, allow_submit: bool, result: dict[str, Any]) -> None:
    required_unfilled = await _detect_required_unfilled(page)
    if required_unfilled:
        result["status"] = "manual_review_required"
        result["messages"].append(f"Required fields/questions need review: {required_unfilled}")
        return

    submit = page.get_by_role("button", name=FINAL_SUBMIT_TEXT)
    if await submit.count() == 0:
        result["status"] = "manual_review_required"
        result["messages"].append("No final submit/apply button detected.")
        return

    if not allow_submit:
        result["status"] = "manual_review_required"
        result["messages"].append("Final submit/apply button detected. Submit blocked because --allow-submit was not provided.")
        return

    await submit.first.click(timeout=10000)
    result["status"] = "submitted"
    result["messages"].append("Application submitted because --allow-submit was explicitly provided.")


def _update_job_after_submission(candidate: ApplicationCandidate | None, result: dict[str, Any]) -> None:
    if not candidate or result.get("status") != "submitted":
        return
    try:
        supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME).update(
            {"status": "applied", "application_date": datetime.now(timezone.utc).isoformat()}
        ).eq("job_id", candidate.job_id).execute()
    except Exception as exc:
        logging.warning("Submitted, but could not update job %s as applied: %s", candidate.job_id, exc)


async def prepare_linkedin_easy_apply(
    candidate: ApplicationCandidate,
    headless: bool = False,
    allow_submit: bool = False,
    manual_login_wait: int = 0,
) -> dict[str, Any]:
    """
    Opens LinkedIn, detects Easy Apply, uploads the custom resume when possible,
    and stops before final submit. This is intentionally manual-review only.
    """
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    resume_path = download_resume(candidate)
    storage_state = _linkedin_storage_state_path()
    phone_number = (
        os.environ.get("APPLICATION_PHONE")
        or app_settings.get_application_profile().get("phone")
        or ""
    )
    default_answers = app_settings.get_application_auto_answer_defaults()
    env_default_answers = json.loads(os.environ.get("APPLICATION_DEFAULT_ANSWERS_JSON", "{}") or "{}")
    default_answers.update({str(key): str(value) for key, value in env_default_answers.items()})

    result = {
        "job_id": candidate.job_id,
        "apply_url": candidate.apply_url,
        "resume_path": str(resume_path),
        "status": "blocked",
        "messages": [],
    }

    async with async_playwright() as playwright:
        browser = await _launch_chromium(playwright, headless=headless)
        context_options = {}
        if storage_state and Path(storage_state).exists():
            context_options["storage_state"] = storage_state
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        await page.goto(candidate.apply_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        if await _linkedin_login_visible(page):
            if await _wait_for_manual_linkedin_login(page, context, result, manual_login_wait):
                await page.goto(candidate.apply_url, wait_until="domcontentloaded", timeout=60000)
            else:
                result["status"] = "login_required"
                await browser.close()
                return result

        easy_apply = page.get_by_role("button", name=re.compile(r"\bEasy Apply\b", re.IGNORECASE))
        if await easy_apply.count() == 0:
            easy_apply = page.locator("button:has-text('Easy Apply')")

        if await easy_apply.count() > 0:
            try:
                await easy_apply.first.click(timeout=15000)
                result["messages"].append("Easy Apply button clicked.")
            except PlaywrightTimeoutError:
                result["status"] = "blocked"
                result["messages"].append("Easy Apply button was detected but could not be clicked before timeout.")
                await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
                await browser.close()
                return result
        else:
            if await _linkedin_login_visible(page):
                result["status"] = "login_required"
                result["messages"].append("LinkedIn sign-in prompt is visible, so Easy Apply cannot be prepared yet.")
            elif await _page_has_button(page, re.compile(r"^Apply$", re.IGNORECASE)):
                result["status"] = "external_apply"
                result["messages"].append("LinkedIn shows a normal Apply button, not Easy Apply.")
            else:
                result["status"] = "not_easy_apply"
                result["messages"].append("Easy Apply button was not detected.")
            await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
            await browser.close()
            return result

        file_inputs = page.locator("input[type='file']")
        if await file_inputs.count() > 0:
            await file_inputs.first.set_input_files(str(resume_path))
            result["messages"].append("Custom resume uploaded.")
        else:
            result["messages"].append("Resume upload input not found on the first step.")

        if phone_number:
            phone_inputs = page.locator(
                "input[name*='phone' i], input[id*='phone' i], input[aria-label*='phone' i]"
            )
            if await phone_inputs.count() > 0:
                await phone_inputs.first.fill(phone_number)
                result["messages"].append("Phone field filled.")

        for label, value in default_answers.items():
            field = page.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
            if await field.count() > 0:
                await field.first.fill(str(value))
                result["messages"].append(f"Filled configured answer for: {label}")

        for _ in range(4):
            if await page.get_by_role("button", name=FINAL_SUBMIT_TEXT).count() > 0:
                break
            clicked = await _click_first_button(page, NEXT_BUTTON_TEXT, result["messages"], timeout=3000)
            if not clicked:
                break
            await page.wait_for_timeout(1000)

        await _maybe_submit(page, allow_submit, result)
        _update_job_after_submission(candidate, result)

        await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
        await browser.close()

    return result


def _first_existing_resume_path(resume_file: str | None, candidate: ApplicationCandidate | None = None) -> Path:
    if resume_file:
        path = Path(resume_file).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Resume file not found: {path}")
        return path

    if candidate:
        return download_resume(candidate)

    raise ValueError("A resume file or application candidate is required.")


def _load_profile_defaults() -> dict[str, str]:
    defaults = app_settings.get_application_profile_defaults()
    defaults.update(app_settings.get_application_auto_answer_defaults())
    profile_json = os.environ.get("APPLICATION_PROFILE_JSON", "{}") or "{}"
    try:
        profile = json.loads(profile_json)
    except json.JSONDecodeError:
        logging.warning("APPLICATION_PROFILE_JSON is not valid JSON. Ignoring it.")
        profile = {}

    env_defaults = {
        "First Name": os.environ.get("APPLICATION_FIRST_NAME", ""),
        "Last Name": os.environ.get("APPLICATION_LAST_NAME", ""),
        "Email": os.environ.get("APPLICATION_EMAIL", ""),
        "Phone": os.environ.get("APPLICATION_PHONE", ""),
        "Address": os.environ.get("APPLICATION_ADDRESS", ""),
        "City": os.environ.get("APPLICATION_CITY", ""),
        "Country": os.environ.get("APPLICATION_COUNTRY", ""),
        "LinkedIn Profile": os.environ.get("APPLICATION_LINKEDIN", ""),
    }
    env_defaults = {key: value for key, value in env_defaults.items() if value}
    defaults.update(env_defaults)
    defaults.update(
        {
            str(key): str(value)
            for key, value in profile.items()
            if value
        }
    )
    return {key: value for key, value in defaults.items() if value}


async def _fill_label_if_present(page: Any, label: str, value: str, messages: list[str]) -> None:
    field = page.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
    if await field.count() == 0:
        return

    try:
        await field.first.fill(value, timeout=3000)
        messages.append(f"Filled Workday field: {label}")
    except Exception:
        # Some Workday controls are custom comboboxes/selects; leave them for manual review.
        messages.append(f"Detected Workday field but left for manual review: {label}")


async def prepare_workday_profile(
    apply_url: str,
    resume_file: str | None = None,
    candidate: ApplicationCandidate | None = None,
    headless: bool = False,
    allow_submit: bool = False,
    allow_login: bool = False,
) -> dict[str, Any]:
    """
    Opens a Workday application/profile page, uploads the selected resume when possible,
    fills only configured safe profile fields, and stops before submit.
    """
    from playwright.async_api import async_playwright

    if not WORKDAY_URL_PATTERN.search(apply_url):
        raise ValueError("The provided URL does not look like a Workday application URL.")

    resume_path = _first_existing_resume_path(resume_file, candidate)
    storage_state = os.environ.get("WORKDAY_STORAGE_STATE")
    profile_defaults = _load_profile_defaults()
    result = {
        "job_id": candidate.job_id if candidate else None,
        "apply_url": apply_url,
        "resume_path": str(resume_path),
        "status": "manual_review_required",
        "portal": "workday",
        "messages": [],
    }

    async with async_playwright() as playwright:
        browser = await _launch_chromium(playwright, headless=headless)
        context_options = {}
        if storage_state and Path(storage_state).exists():
            context_options["storage_state"] = storage_state
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=90000)

        if re.search(r"sign\s*in|login|create\s*account", await page.content(), re.IGNORECASE):
            result["messages"].append("Workday login/create-account step detected. Complete it manually first.")
            await _fill_portal_login_if_allowed(page, allow_login, result["messages"])

        for button_name in [
            r"Apply",
            r"Apply Manually",
            r"Autofill with Resume",
            r"Use My Last Application",
        ]:
            button = page.get_by_role("button", name=re.compile(button_name, re.IGNORECASE))
            if await button.count() > 0:
                try:
                    await button.first.click(timeout=5000)
                    result["messages"].append(f"Clicked Workday action: {button_name}")
                    break
                except Exception:
                    result["messages"].append(f"Detected Workday action but could not click safely: {button_name}")

        await _upload_resume_if_possible(page, resume_path, result["messages"])

        for label, value in profile_defaults.items():
            await _fill_label_if_present(page, label, value, result["messages"])

        for _ in range(8):
            if await page.get_by_role("button", name=FINAL_SUBMIT_TEXT).count() > 0:
                break
            clicked = await _click_first_button(page, NEXT_BUTTON_TEXT, result["messages"], timeout=5000)
            if not clicked:
                break
            await page.wait_for_timeout(1500)
            await _upload_resume_if_possible(page, resume_path, result["messages"])
            await _fill_profile_defaults(page, result["messages"])

        await _maybe_submit(page, allow_submit, result)
        _update_job_after_submission(candidate, result)

        await context.storage_state(path=os.environ.get("WORKDAY_STORAGE_STATE_OUT", "workday_storage_state.json"))
        await browser.close()

    return result


async def prepare_company_portal(
    apply_url: str,
    resume_file: str | None = None,
    candidate: ApplicationCandidate | None = None,
    headless: bool = False,
    allow_submit: bool = False,
    allow_login: bool = False,
) -> dict[str, Any]:
    portal = detect_portal(apply_url, candidate.provider if candidate else "")
    if portal == "workday":
        return await prepare_workday_profile(
            apply_url=apply_url,
            resume_file=resume_file,
            candidate=candidate,
            headless=headless,
            allow_submit=allow_submit,
            allow_login=allow_login,
        )

    from playwright.async_api import async_playwright

    resume_path = _first_existing_resume_path(resume_file, candidate)
    storage_state = os.environ.get(f"{portal.upper()}_STORAGE_STATE") or os.environ.get("PORTAL_STORAGE_STATE")
    result = {
        "job_id": candidate.job_id if candidate else None,
        "apply_url": apply_url,
        "resume_path": str(resume_path),
        "status": "manual_review_required",
        "portal": portal,
        "messages": [],
    }

    async with async_playwright() as playwright:
        browser = await _launch_chromium(playwright, headless=headless)
        context_options = {}
        if storage_state and Path(storage_state).exists():
            context_options["storage_state"] = storage_state
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=90000)
        await _fill_portal_login_if_allowed(page, allow_login, result["messages"])

        await _click_first_button(page, re.compile(r"^(apply|apply now|start application)$", re.IGNORECASE), result["messages"], timeout=5000)
        await _upload_resume_if_possible(page, resume_path, result["messages"])
        await _fill_profile_defaults(page, result["messages"])

        for _ in range(6):
            if await page.get_by_role("button", name=FINAL_SUBMIT_TEXT).count() > 0:
                break
            clicked = await _click_first_button(page, NEXT_BUTTON_TEXT, result["messages"], timeout=4000)
            if not clicked:
                break
            await page.wait_for_timeout(1200)
            await _upload_resume_if_possible(page, resume_path, result["messages"])
            await _fill_profile_defaults(page, result["messages"])

        await _maybe_submit(page, allow_submit, result)
        _update_job_after_submission(candidate, result)
        await context.storage_state(path=os.environ.get(f"{portal.upper()}_STORAGE_STATE_OUT", f"{portal}_storage_state.json"))
        await browser.close()

    return result


def print_candidates(candidates: list[ApplicationCandidate]) -> None:
    if not candidates:
        print("No application candidates found.")
        return

    for index, candidate in enumerate(candidates, start=1):
        print(
            f"{index}. [{candidate.resume_score}] {candidate.job_title} | {candidate.company} | "
            f"{candidate.location} | {candidate.apply_url} | resume={candidate.resume_link}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare application candidates without auto-submitting.")
    parser.add_argument(
        "--mode",
        choices=[
            "plan",
            "queue",
            "prepare-easy-apply",
            "prepare-workday-profile",
            "prepare-company-portal",
            "auto-apply",
        ],
        default="plan",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-score", type=int, default=app_settings.get_min_score())
    parser.add_argument("--provider", choices=["linkedin", "all"], default="linkedin")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--apply-url", help="Manual apply URL, useful for Workday/company portals.")
    parser.add_argument("--resume-file", help="Local resume PDF path for manual Workday/company portal preparation.")
    parser.add_argument(
        "--allow-submit",
        action="store_true",
        help="Explicitly allow final submission when no unknown required fields are detected.",
    )
    parser.add_argument(
        "--allow-login",
        action="store_true",
        help="Allow filling and submitting portal login forms using APPLICATION_PORTAL_EMAIL/APPLICATION_PORTAL_PASSWORD.",
    )
    parser.add_argument(
        "--manual-login-wait",
        type=int,
        default=0,
        help="For LinkedIn, wait this many seconds for you to complete manual login and save storage state.",
    )
    args = parser.parse_args()
    automation_settings = app_settings.get_application_automation()
    effective_headless = args.headless or bool(automation_settings.get("headlessBrowser"))
    effective_allow_submit = args.allow_submit or bool(automation_settings.get("allowFinalSubmit"))
    effective_allow_login = args.allow_login or bool(automation_settings.get("allowPortalLogin"))

    if args.mode in {"prepare-workday-profile", "prepare-company-portal"} and args.apply_url:
        if args.mode == "prepare-workday-profile":
            result = await prepare_workday_profile(
                apply_url=args.apply_url,
                resume_file=args.resume_file,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                allow_login=effective_allow_login,
            )
        else:
            result = await prepare_company_portal(
                apply_url=args.apply_url,
                resume_file=args.resume_file,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                allow_login=effective_allow_login,
            )
        print(json.dumps(result, indent=2))
        if result.get("status") == "submitted":
            print("\nSubmitted because --allow-submit was explicitly provided and no unknown required fields were detected.")
        else:
            print("\nStopped before final submit.")
        return

    provider = None if args.provider == "all" else args.provider
    candidates = fetch_candidates(limit=candidate_pool_limit(args.limit, args.mode), min_score=args.min_score, provider=provider)
    print_candidates(candidates)

    if args.mode == "plan":
        print("\nPlan mode only. No queue rows, browser actions, or submissions were performed.")
        return

    if args.mode == "queue":
        queued = sum(1 for candidate in candidates if queue_candidate(candidate))
        print(f"\nQueued {queued} candidate(s) as application_ready. No browser actions or submissions were performed.")
        return

    results: list[dict[str, Any]] = []
    progress_statuses = {"manual_review_required", "submitted"}
    progress_count = 0

    for candidate in candidates:
        if args.mode == "prepare-workday-profile":
            if detect_portal(candidate.apply_url, candidate.provider) != "workday":
                logging.info("Skipping non-Workday candidate %s.", candidate.job_id)
                continue
            result = await prepare_workday_profile(
                apply_url=candidate.apply_url,
                resume_file=args.resume_file,
                candidate=candidate,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                allow_login=effective_allow_login,
            )
            queue_candidate(candidate, status=result["status"])
            results.append(result)
            print(json.dumps(result, indent=2))
            continue

        if args.mode == "prepare-company-portal":
            if detect_portal(candidate.apply_url, candidate.provider) == "linkedin":
                logging.info("Skipping LinkedIn candidate %s in company portal mode.", candidate.job_id)
                continue
            result = await prepare_company_portal(
                apply_url=candidate.apply_url,
                resume_file=args.resume_file,
                candidate=candidate,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                allow_login=effective_allow_login,
            )
            queue_candidate(candidate, status=result["status"])
            results.append(result)
            print(json.dumps(result, indent=2))
            continue

        if args.mode == "auto-apply":
            if detect_portal(candidate.apply_url, candidate.provider) != "linkedin":
                logging.info("Skipping non-LinkedIn candidate %s in auto-apply mode.", candidate.job_id)
                queue_candidate(candidate, status="company_portal_review")
                continue
            result = await prepare_linkedin_easy_apply(
                candidate,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                manual_login_wait=args.manual_login_wait,
            )
            queue_candidate(candidate, status=result["status"])
            results.append(result)
            print(json.dumps(result, indent=2))
            if result.get("status") in progress_statuses:
                progress_count += 1
                if progress_count >= args.limit:
                    logging.info("Reached requested auto-apply progress limit: %s", args.limit)
                    break
            continue

        if candidate.provider != "linkedin":
            logging.info("Skipping non-LinkedIn candidate %s in Easy Apply mode.", candidate.job_id)
            continue
        result = await prepare_linkedin_easy_apply(
            candidate,
            headless=effective_headless,
            allow_submit=effective_allow_submit,
            manual_login_wait=args.manual_login_wait,
        )
        queue_candidate(candidate, status=result["status"])
        results.append(result)
        print(json.dumps(result, indent=2))

    if effective_allow_submit:
        print("\nSubmit was allowed only where no unknown required fields were detected.")
    else:
        print("\nStopped before final submit for every candidate.")

    if args.mode == "auto-apply":
        progressed = [result for result in results if result.get("status") in progress_statuses]
        if candidates and not progressed:
            statuses = sorted({str(result.get("status")) for result in results})
            print(
                "\nAuto-apply did not reach any application form. "
                f"Statuses: {statuses}. Check LinkedIn session secret or Easy Apply availability."
            )
            sys.exit(2)


if __name__ == "__main__":
    asyncio.run(main())
