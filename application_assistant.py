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
from urllib.parse import urlparse

import app_settings
import config
import supabase_utils

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

APPLICATION_QUEUE_TABLE = "application_queue"
APPLICATION_QUEUE_STORAGE_BUCKET = getattr(config, "SUPABASE_RESUME_STORAGE_BUCKET", "resumes")
APPLICATION_QUEUE_STORAGE_PREFIX = "application_queue"
APPLICATION_SESSION_STORAGE_PREFIX = "application_sessions"
APPLICATION_DEBUG_DIR = Path(tempfile.gettempdir()) / "jobtrack_application_debug"
SAFE_FINAL_SUBMIT_TEXT = re.compile(r"^(submit application|submit|apply)$", re.IGNORECASE)
WORKDAY_URL_PATTERN = re.compile(r"(myworkdayjobs\.com|myworkdaysite\.com|workdayjobs\.com)", re.IGNORECASE)
PORTAL_PATTERNS = {
    "workday": WORKDAY_URL_PATTERN,
    "greenhouse": re.compile(r"(greenhouse\.io|boards\.greenhouse\.io)", re.IGNORECASE),
    "lever": re.compile(r"(lever\.co|jobs\.lever\.co)", re.IGNORECASE),
    "ashby": re.compile(r"(ashbyhq\.com|jobs\.ashbyhq\.com)", re.IGNORECASE),
    "smartrecruiters": re.compile(r"(smartrecruiters\.com|jobs\.smartrecruiters\.com)", re.IGNORECASE),
}
NEXT_BUTTON_TEXT = re.compile(
    r"^(next|continue|continue to next step|save and continue)$",
    re.IGNORECASE,
)
REVIEW_BUTTON_TEXT = re.compile(r"^(review|review application|review your application)$", re.IGNORECASE)
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


def detect_portal_for_url(apply_url: str) -> str:
    for portal, pattern in PORTAL_PATTERNS.items():
        if pattern.search(apply_url or ""):
            return portal
    if _is_linkedin_url(apply_url):
        return "linkedin"
    if _is_http_url(apply_url):
        return "company_portal"
    return "unknown"


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
    return str(job.get("apply_url") or job.get("job_url") or job.get("url") or "")


def _score(job: dict[str, Any]) -> int:
    try:
        return int(float(job.get("resume_score") or 0))
    except (TypeError, ValueError):
        return 0


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _candidate_age_minutes(candidate: ApplicationCandidate) -> float | None:
    posted_at = _parse_datetime(candidate.posted_at)
    scraped_at = _parse_datetime(candidate.scraped_at)
    freshest = max(
        [timestamp for timestamp in (posted_at, scraped_at) if timestamp is not None],
        default=None,
    )
    if not freshest:
        return None
    return (datetime.now(timezone.utc) - freshest).total_seconds() / 60


def _candidate_is_fresh(candidate: ApplicationCandidate, max_age_minutes: int | None) -> bool:
    if not max_age_minutes or max_age_minutes <= 0:
        return True
    age_minutes = _candidate_age_minutes(candidate)
    return age_minutes is not None and 0 <= age_minutes <= max_age_minutes


def _load_job_times(job_ids: list[str]) -> dict[str, dict[str, str]]:
    if not job_ids:
        return {}

    try:
        response = (
            supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME)
            .select("job_id, posted_at, scraped_at, apply_url, job_url")
            .in_("job_id", job_ids)
            .execute()
        )
    except Exception as exc:
        missing_column = supabase_utils._missing_schema_column(exc)
        if missing_column in {"apply_url", "job_url"}:
            logging.warning(
                "Supabase jobs table is missing %s. Loading candidate timestamps without portal URLs.",
                missing_column,
            )
            try:
                response = (
                    supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME)
                    .select("job_id, posted_at, scraped_at")
                    .in_("job_id", job_ids)
                    .execute()
                )
            except Exception as retry_exc:
                logging.warning("Could not load posted_at/scraped_at for candidates: %s", retry_exc)
                return {}
        else:
            logging.warning("Could not load posted_at/scraped_at for candidates: %s", exc)
            return {}

    job_times: dict[str, dict[str, str]] = {}
    for row in response.data or []:
        job_id = str(row.get("job_id") or "")
        if not job_id:
            continue
        job_times[job_id] = {
            "posted_at": str(row.get("posted_at") or ""),
            "scraped_at": str(row.get("scraped_at") or ""),
            "apply_url": str(row.get("apply_url") or ""),
            "job_url": str(row.get("job_url") or ""),
        }
    return job_times


def fetch_candidates(
    limit: int,
    min_score: int,
    provider: str | None = "linkedin",
    max_age_minutes: int | None = None,
    stale_fallback_limit: int | None = None,
) -> list[ApplicationCandidate]:
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

    rows = response.data or []
    job_times = _load_job_times(
        [str(job.get("job_id")) for job in rows if job.get("job_id") is not None]
    )

    candidates = []
    stale_candidates = []
    skipped_missing_resume = 0
    skipped_score = 0
    skipped_freshness = 0
    for job in response.data or []:
        if not job.get("customized_resume_id") or not job.get("resume_link"):
            skipped_missing_resume += 1
            continue
        if _score(job) < min_score:
            skipped_score += 1
            continue

        job_id = str(job["job_id"])
        timing = job_times.get(job_id, {})
        job_with_timing = {**job, **timing}
        posted_at = str(job.get("posted_at") or timing.get("posted_at") or "")
        scraped_at = str(job.get("scraped_at") or timing.get("scraped_at") or "")

        candidate = ApplicationCandidate(
            job_id=job_id,
            job_title=job.get("job_title") or "",
            company=job.get("company") or "",
            location=job.get("location") or "",
            provider=job.get("provider") or "",
            resume_score=_score(job),
            customized_resume_id=str(job["customized_resume_id"]),
            resume_link=str(job["resume_link"]),
            apply_url=build_apply_url(job_with_timing),
            application_type=detect_application_type(job_with_timing),
            scraped_at=scraped_at,
            posted_at=posted_at,
        )
        if not _candidate_is_fresh(candidate, max_age_minutes):
            skipped_freshness += 1
            age_minutes = _candidate_age_minutes(candidate)
            logging.info(
                "Skipping candidate %s due to freshness window: posted_at=%s scraped_at=%s age_minutes=%s max_age_minutes=%s",
                candidate.job_id,
                candidate.posted_at or None,
                candidate.scraped_at or None,
                None if age_minutes is None else round(age_minutes, 1),
                max_age_minutes,
            )
            stale_candidates.append(candidate)
            continue
        candidates.append(candidate)

    fallback_limit = stale_fallback_limit or limit
    if stale_candidates and len(candidates) < fallback_limit:
        remaining_slots = max(fallback_limit - len(candidates), 0)
        fallback_candidates = stale_candidates[:remaining_slots]
        candidates.extend(fallback_candidates)
        logging.warning(
            "Fresh application candidates were below target; adding %s older scored custom-resume candidate(s) after fresh candidates.",
            len(fallback_candidates),
        )
    if fallback_limit > 0:
        candidates = candidates[:fallback_limit]

    logging.info(
        "Application candidate scan: rpc_rows=%s kept=%s skipped_missing_resume=%s skipped_score=%s skipped_freshness=%s stale_fallback_available=%s max_age_minutes=%s",
        len(rows),
        len(candidates),
        skipped_missing_resume,
        skipped_score,
        skipped_freshness,
        len(stale_candidates),
        max_age_minutes,
    )

    return candidates


def candidate_pool_limit(limit: int, mode: str) -> int:
    """Scan a wider pool because top jobs may not match the requested apply flow."""
    if mode not in {"auto-apply", "prepare-company-portal"}:
        return limit
    return max(limit * 10, 50)


def count_submitted_today() -> int:
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    try:
        response = (
            supabase_utils.supabase.table(config.SUPABASE_TABLE_NAME)
            .select("job_id", count="exact")
            .eq("status", "applied")
            .gte("application_date", start_of_day.isoformat())
            .execute()
        )
        return int(response.count or len(response.data or []))
    except Exception as exc:
        logging.warning("Could not count today's submitted applications: %s", exc)
        return 0


def _daily_submit_available(submitted_today: int, daily_submit_limit: int) -> bool:
    return daily_submit_limit <= 0 or submitted_today < daily_submit_limit


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


def _safe_host_key(url: str) -> str:
    host = urlparse(url).netloc.lower() or "unknown"
    return re.sub(r"[^a-z0-9]+", "_", host).strip("_") or "unknown"


def _portal_session_storage_path(portal: str, apply_url: str) -> str:
    return f"{APPLICATION_SESSION_STORAGE_PREFIX}/{portal}_{_safe_host_key(apply_url)}.json"


def _portal_storage_state_path(portal: str, apply_url: str) -> str | None:
    env_path = os.environ.get(f"{portal.upper()}_STORAGE_STATE") or os.environ.get("PORTAL_STORAGE_STATE")
    if env_path and Path(env_path).exists():
        return env_path

    storage_path = _portal_session_storage_path(portal, apply_url)
    output_path = Path(tempfile.gettempdir()) / f"{portal}_{_safe_host_key(apply_url)}_storage_state.json"
    try:
        file_bytes = supabase_utils.supabase.storage.from_(APPLICATION_QUEUE_STORAGE_BUCKET).download(storage_path)
        output_path.write_bytes(bytes(file_bytes))
        logging.info("Loaded portal session from storage: %s", storage_path)
        return str(output_path)
    except Exception:
        return None


async def _save_portal_storage_state(context: Any, portal: str, apply_url: str, env_key: str, default_path: str) -> str:
    state_path = await _save_context_state(context, env_key, default_path)
    storage_path = _portal_session_storage_path(portal, apply_url)
    try:
        supabase_utils.supabase.storage.from_(APPLICATION_QUEUE_STORAGE_BUCKET).upload(
            path=storage_path,
            file=Path(state_path).read_bytes(),
            file_options={"content-type": "application/json", "upsert": "true"},
        )
        logging.info("Saved portal session to storage: %s", storage_path)
    except Exception as exc:
        logging.warning("Could not save portal session to storage %s: %s", storage_path, exc)
    return state_path


def queue_candidate(
    candidate: ApplicationCandidate,
    status: str = "application_ready",
    apply_url: str | None = None,
    portal: str | None = None,
    notes: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> bool:
    effective_apply_url = apply_url or candidate.apply_url
    effective_portal = portal or detect_portal(effective_apply_url, candidate.provider)
    result_notes = _queue_notes_from_result(result)
    payload = {
        "job_id": candidate.job_id,
        "customized_resume_id": candidate.customized_resume_id,
        "application_type": candidate.application_type,
        "portal": effective_portal,
        "status": status,
        "run_mode": "review",
        "apply_url": effective_apply_url,
        "resume_path": candidate.resume_link,
        "score": candidate.resume_score,
        "notes": {
            "job_title": candidate.job_title,
            "company": candidate.company,
            "location": candidate.location,
            "submit_policy": "never_submit_without_manual_confirmation",
            **result_notes,
            **(notes or {}),
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


def _queue_notes_from_result(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        return {}

    notes: dict[str, Any] = {}
    messages = result.get("messages")
    if isinstance(messages, list):
        notes["last_messages"] = [str(message) for message in messages[-12:]]

    missing_questions = result.get("missing_questions")
    if isinstance(missing_questions, list) and missing_questions:
        notes["missing_questions"] = [
            question
            for question in (_missing_question_payload(str(item)) for item in missing_questions)
            if question
        ]

    if result.get("resolved_apply_url"):
        notes["resolved_apply_url"] = str(result["resolved_apply_url"])

    return notes


def _missing_question_payload(label: str) -> dict[str, Any] | None:
    label = _compact_application_question_label(label)
    normalized = app_settings.normalize_question_key(label)
    if not normalized:
        return None
    answer = app_settings.find_application_question_answer(label)
    return {
        "label": label,
        "key": normalized,
        "suggestedAnswer": answer or "",
        "known": bool(answer),
    }


def _compact_application_question_label(label: str) -> str:
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    if not text:
        return ""

    question_match = re.search(r"[^?.!]{8,220}\?", text)
    if question_match:
        return question_match.group(0).strip()

    for marker in [
        "how many years",
        "how much experience",
        "do you have",
        "are you",
        "can you",
        "will you",
        "what is",
        "where are",
    ]:
        index = text.lower().find(marker)
        if index >= 0:
            return text[index : index + 220].strip(" -:")

    return text[:220].strip()


def download_resume(candidate: ApplicationCandidate) -> Path:
    file_bytes = supabase_utils.supabase.storage.from_(config.SUPABASE_STORAGE_BUCKET).download(
        candidate.resume_link
    )
    output_dir = Path(tempfile.gettempdir()) / "jobtrack_application_resumes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{candidate.job_id}.pdf"
    output_path.write_bytes(bytes(file_bytes))
    return output_path


async def _application_scope(page: Any) -> Any:
    for selector in [
        "div[role='dialog']:visible",
        ".jobs-easy-apply-modal:visible",
        ".artdeco-modal:visible",
        "[data-test-modal]:visible",
    ]:
        scope = page.locator(selector)
        if await scope.count() > 0:
            return scope.last
    return page


async def _click_first_button(
    page: Any,
    pattern: re.Pattern[str],
    messages: list[str],
    timeout: int = 5000,
    scope: Any | None = None,
) -> bool:
    root = scope or page
    button = root.get_by_role("button", name=pattern)
    if await button.count() == 0:
        if pattern.pattern == NEXT_BUTTON_TEXT.pattern:
            button = root.locator(
                "button[aria-label*='Next'], "
                "button[aria-label*='Continue'], "
                "button:has-text('Next'), "
                "button:has-text('Continue'), "
                "button:has-text('Save and continue')"
            )
        elif pattern.pattern == REVIEW_BUTTON_TEXT.pattern:
            button = root.locator(
                "button[aria-label*='Review'], "
                "button:has-text('Review')"
            )
        if await button.count() == 0:
            return False
    try:
        await button.first.click(timeout=timeout)
        try:
            label = await button.first.inner_text(timeout=1000)
        except Exception:
            label = await button.first.get_attribute("aria-label") or pattern.pattern
        messages.append(f"Clicked button: {label.strip() or pattern.pattern}")
        return True
    except Exception as exc:
        try:
            await button.first.evaluate("(element) => element.click()", timeout=2000)
            messages.append(f"Clicked button with DOM fallback: {pattern.pattern}")
            return True
        except Exception:
            messages.append(f"Detected button but could not click safely: {exc}")
            return False


async def _visible_button_labels(scope: Any, limit: int = 12) -> list[str]:
    labels: list[str] = []
    buttons = scope.locator("button")
    for index in range(min(await buttons.count(), limit)):
        button = buttons.nth(index)
        try:
            if not await button.is_visible(timeout=500):
                continue
            text = (await button.inner_text(timeout=500)).strip()
            aria = ((await button.get_attribute("aria-label")) or "").strip()
            label = text or aria
            if label:
                labels.append(label)
        except Exception:
            continue
    return labels


async def _find_submit_button(root: Any) -> Any:
    button = root.get_by_role("button", name=FINAL_SUBMIT_TEXT)
    if await button.count() > 0:
        return button
    return root.locator(
        "button[aria-label*='Submit application' i], "
        "button:has-text('Submit application'), "
        "button:has-text('Send application')"
    )


async def _save_application_debug_artifacts(page: Any, result: dict[str, Any], reason: str, scope: Any | None = None) -> None:
    APPLICATION_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    job_id = str(result.get("job_id") or "unknown")
    safe_reason = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_") or "debug"
    prefix = APPLICATION_DEBUG_DIR / f"{job_id}_{safe_reason}"
    try:
        await page.screenshot(path=str(prefix.with_suffix(".png")), full_page=True)
        Path(prefix.with_suffix(".html")).write_text(await page.content(), encoding="utf-8")
        result["messages"].append(f"Saved debug artifacts: {prefix.with_suffix('.png')} and {prefix.with_suffix('.html')}")
    except Exception as exc:
        result["messages"].append(f"Could not save debug artifacts for {reason}: {exc}")
    if scope is not None:
        try:
            await scope.screenshot(path=str(APPLICATION_DEBUG_DIR / f"{job_id}_{safe_reason}_modal.png"))
        except Exception:
            pass


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


async def _first_visible(locator: Any, limit: int = 20) -> Any | None:
    for index in range(min(await locator.count(), limit)):
        item = locator.nth(index)
        try:
            if await item.is_visible(timeout=500):
                return item
        except Exception:
            continue
    return None


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


def _is_linkedin_url(url: str) -> bool:
    return bool(re.search(r"(^https?://)?([^/]+\.)?linkedin\.com/", url or "", re.IGNORECASE))


def _is_http_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url or "", re.IGNORECASE))


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


async def resolve_linkedin_company_apply_url(
    candidate: ApplicationCandidate,
    headless: bool = False,
    manual_login_wait: int = 0,
) -> dict[str, Any]:
    """
    Opens a LinkedIn job and follows the normal Apply button to discover the
    company portal URL. Easy Apply jobs are intentionally left to Easy Apply mode.
    """
    from playwright.async_api import async_playwright

    storage_state = _linkedin_storage_state_path()
    result = {
        "job_id": candidate.job_id,
        "apply_url": candidate.apply_url,
        "resolved_apply_url": None,
        "status": "blocked",
        "portal": "linkedin",
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
                await page.wait_for_timeout(2000)
            else:
                result["status"] = "login_required"
                await browser.close()
                return result

        easy_apply = page.locator(
            f"a[href*='/jobs/view/{candidate.job_id}/apply/'][href*='openSDUIApplyFlow=true']"
        )
        if await easy_apply.count() > 0 or await page.get_by_role("button", name=re.compile(r"\bEasy Apply\b", re.IGNORECASE)).count() > 0:
            result["status"] = "easy_apply_available"
            result["messages"].append("LinkedIn Easy Apply detected; use Easy Apply mode for this job.")
            await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
            await browser.close()
            return result

        apply_controls = page.locator(
            "button:has-text('Apply'), a:has-text('Apply'), "
            "button[aria-label*='Apply' i], a[aria-label*='Apply' i]"
        )
        if await apply_controls.count() == 0:
            result["status"] = "no_external_apply"
            result["messages"].append("No normal Apply control detected on LinkedIn.")
            await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
            await browser.close()
            return result

        existing_pages = set(context.pages)
        try:
            href = await apply_controls.first.get_attribute("href")
            if _is_http_url(href or "") and not _is_linkedin_url(href or ""):
                result["resolved_apply_url"] = href
                result["apply_url"] = href
                result["portal"] = detect_portal_for_url(href or "")
                result["status"] = "external_apply_resolved"
                result["messages"].append(f"Resolved company portal URL from Apply link: {href}")
                await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
                await browser.close()
                return result
        except Exception:
            pass

        try:
            await apply_controls.first.click(timeout=15000)
            result["messages"].append("Clicked LinkedIn normal Apply control.")
        except Exception as exc:
            result["status"] = "blocked"
            result["messages"].append(f"LinkedIn Apply control was detected but could not be clicked: {exc}")
            await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
            await browser.close()
            return result

        candidate_pages = []
        try:
            popup = await page.wait_for_event("popup", timeout=7000)
            candidate_pages.append(popup)
        except Exception:
            pass

        await page.wait_for_timeout(5000)
        if page.url and _is_http_url(page.url) and not _is_linkedin_url(page.url):
            candidate_pages.append(page)
        for context_page in context.pages:
            if context_page not in existing_pages and context_page not in candidate_pages:
                candidate_pages.append(context_page)
        if page not in candidate_pages:
            candidate_pages.append(page)

        for candidate_page in candidate_pages:
            try:
                await candidate_page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            url = candidate_page.url
            if _is_http_url(url) and not _is_linkedin_url(url):
                result["resolved_apply_url"] = url
                result["apply_url"] = url
                result["portal"] = detect_portal_for_url(url)
                result["status"] = "external_apply_resolved"
                result["messages"].append(f"Resolved company portal URL: {url}")
                break

        if result["status"] != "external_apply_resolved":
            result["status"] = "external_apply_unresolved"
            result["messages"].append("Clicked Apply, but no external company portal URL was captured.")

        await _save_context_state(context, "LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json")
        await browser.close()

    return result


async def _upload_resume_if_possible(page: Any, resume_path: Path, messages: list[str], scope: Any | None = None) -> bool:
    root = scope or page
    file_inputs = root.locator("input[type='file']")
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


async def _fill_field_safely(field: Any, value: str, label: str, messages: list[str]) -> bool:
    try:
        tag_name = (await field.evaluate("el => el.tagName.toLowerCase()", timeout=2000)).lower()
    except Exception as exc:
        messages.append(f"Detected field for {label}, but could not inspect it: {exc}")
        return False

    try:
        if tag_name == "select":
            try:
                await field.select_option(label=value, timeout=3000)
            except Exception:
                try:
                    await field.select_option(value=value, timeout=3000)
                except Exception:
                    matched_value = await field.evaluate(
                        """(el, wanted) => {
                            const normalized = String(wanted).trim().toLowerCase();
                            const option = Array.from(el.options).find((item) =>
                                item.textContent.trim().toLowerCase().includes(normalized)
                            );
                            return option ? option.value : null;
                        }""",
                        value,
                    )
                    if not matched_value:
                        raise
                    await field.select_option(value=matched_value, timeout=3000)
            messages.append(f"Selected configured answer for: {label}")
            return True

        input_type = (await field.get_attribute("type")) or ""
        if tag_name == "input" and input_type.lower() in {"checkbox", "radio"}:
            if str(value).strip().lower() in {"yes", "true", "1", "checked"}:
                await field.check(timeout=3000)
                messages.append(f"Checked configured answer for: {label}")
                return True
            messages.append(f"Detected {input_type} for {label}; left unchecked for manual review.")
            return False

        contenteditable = (await field.get_attribute("contenteditable")) or ""
        if tag_name in {"input", "textarea"} or contenteditable.lower() == "true":
            fill_value = str(value)
            if _should_use_plain_decimal(label, input_type, fill_value):
                fill_value = _decimal_for_numeric_field(fill_value)
            await field.fill(fill_value, timeout=3000)
            role = (await field.get_attribute("role")) or ""
            autocomplete = (await field.get_attribute("aria-autocomplete")) or ""
            if _should_select_autocomplete_option(label, role, autocomplete):
                await _select_autocomplete_option(field, fill_value)
            messages.append(f"Filled configured answer for: {label}")
            return True

        messages.append(f"Detected unsupported field type '{tag_name}' for {label}; left for manual review.")
        return False
    except Exception as exc:
        messages.append(f"Could not fill configured answer for {label}; left for manual review: {exc}")
        return False


async def _fill_profile_defaults(page: Any, messages: list[str], scope: Any | None = None) -> None:
    for label, value in _load_profile_defaults().items():
        await _fill_label_if_present(page, label, value, messages, scope=scope)


def _portal_credentials() -> tuple[str, str]:
    profile = app_settings.get_application_profile()
    email = (
        os.environ.get("APPLICATION_PORTAL_EMAIL")
        or os.environ.get("APPLICATION_EMAIL")
        or profile.get("email")
        or ""
    )
    password = os.environ.get("APPLICATION_PORTAL_PASSWORD", "")
    return email.strip(), password.strip()


def _portal_credential_status() -> str | None:
    email, password = _portal_credentials()
    missing = []
    if not email:
        missing.append("APPLICATION_PORTAL_EMAIL or application profile email")
    if not password:
        missing.append("APPLICATION_PORTAL_PASSWORD")
    if missing:
        return "Missing portal credential(s): " + ", ".join(missing)
    return None


async def _click_named_control(page: Any, pattern: re.Pattern[str], messages: list[str], timeout: int = 5000) -> bool:
    for getter in [page.get_by_role("button", name=pattern), page.get_by_role("link", name=pattern)]:
        if await getter.count() == 0:
            continue
        try:
            await getter.first.click(timeout=timeout)
            messages.append(f"Clicked control: {pattern.pattern}")
            await page.wait_for_timeout(1500)
            return True
        except Exception:
            try:
                await getter.first.evaluate("(element) => element.click()", timeout=2000)
                messages.append(f"Clicked control with DOM fallback: {pattern.pattern}")
                await page.wait_for_timeout(1500)
                return True
            except Exception as exc:
                messages.append(f"Detected control but could not click safely: {exc}")
                return False
    return False


async def _detect_human_verification(page: Any) -> str | None:
    try:
        captcha = page.locator(
            "iframe[src*='recaptcha']:visible, iframe[src*='hcaptcha']:visible, "
            "[class*='captcha' i]:visible, [id*='captcha' i]:visible, "
            "text=/verify you are human|complete the captcha|security check/i"
        )
        if await captcha.count() > 0:
            return "captcha_required"
    except Exception:
        pass

    try:
        visible_text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        visible_text = ""
    if re.search(r"verification code|verify your email|email verification|one-time|one time|otp", visible_text, re.IGNORECASE):
        return "email_or_otp_verification_required"
    if re.search(r"security question|multi-factor|two-factor|2fa|mfa", visible_text, re.IGNORECASE):
        return "mfa_required"
    return None


async def _fill_portal_login_if_allowed(page: Any, allow_login: bool, messages: list[str]) -> bool:
    if not allow_login:
        messages.append("Portal login was detected or possible, but login is disabled. Enable it in settings or pass --allow-login.")
        return False

    email, password = _portal_credentials()
    credential_error = _portal_credential_status()
    if credential_error:
        messages.append(f"Portal login is allowed, but credentials are incomplete. {credential_error}.")
        return False

    email_inputs = page.locator(
        "input[type='email'], input[name*='email' i], input[id*='email' i], input[autocomplete='username']"
    )
    password_inputs = page.locator(
        "input[type='password'], input[name*='password' i], input[id*='password' i], input[autocomplete='current-password']"
    )

    filled_any = False
    visible_email = await _first_visible(email_inputs)
    if visible_email:
        try:
            await visible_email.fill(email, timeout=3000)
            messages.append("Filled portal email.")
            filled_any = True
        except Exception as exc:
            messages.append(f"Portal email field was detected but could not be filled safely: {exc}")

    visible_password = await _first_visible(password_inputs)
    if visible_password:
        try:
            await visible_password.fill(password, timeout=3000)
            messages.append("Filled portal password.")
            filled_any = True
        except Exception as exc:
            messages.append(f"Portal password field was detected but could not be filled safely: {exc}")

    if not filled_any:
        return False

    sign_in_button = page.get_by_role("button", name=re.compile(r"^(sign in|log in|login|continue)$", re.IGNORECASE))
    visible_button = await _first_visible(sign_in_button)
    if visible_button:
        try:
            await visible_button.click(timeout=5000)
            messages.append("Clicked portal login/continue.")
            await page.wait_for_timeout(2000)
        except Exception as exc:
            messages.append(f"Portal login button was detected but could not be clicked safely: {exc}")
    return True


async def _register_portal_account_if_allowed(page: Any, allow_register: bool, messages: list[str]) -> bool:
    if not allow_register:
        messages.append("Portal account creation is disabled. Pass --allow-register to create first-time company accounts.")
        return False

    email, password = _portal_credentials()
    profile = app_settings.get_application_profile()
    credential_error = _portal_credential_status()
    if credential_error:
        messages.append(f"Portal registration is allowed, but credentials are incomplete. {credential_error}.")
        return False

    opened = await _click_named_control(
        page,
        re.compile(r"(create account|create an account|sign up|register|new user|start here)", re.IGNORECASE),
        messages,
        timeout=6000,
    )
    if not opened:
        messages.append("No portal registration control detected.")
        return False

    field_values = {
        "First Name": profile.get("firstName", ""),
        "Last Name": profile.get("lastName", ""),
        "Full Name": profile.get("fullName", ""),
        "Name": profile.get("fullName", ""),
        "Email": email,
        "Email Address": email,
        "Username": email,
        "Password": password,
        "Create Password": password,
        "New Password": password,
        "Confirm Password": password,
        "Verify Password": password,
        "Retype Password": password,
    }
    for label, value in field_values.items():
        if value:
            await _fill_label_if_present(page, label, value, messages)

    selector_values = {
        "input[name*='first' i], input[id*='first' i], input[autocomplete='given-name']": profile.get("firstName", ""),
        "input[name*='last' i], input[id*='last' i], input[autocomplete='family-name']": profile.get("lastName", ""),
        "input[name*='name' i], input[id*='name' i], input[autocomplete='name']": profile.get("fullName", ""),
        "input[type='email'], input[name*='email' i], input[id*='email' i], input[autocomplete='email'], input[autocomplete='username']": email,
    }
    for selector, value in selector_values.items():
        if not value:
            continue
        fields = page.locator(selector)
        visible_field = await _first_visible(fields)
        if visible_field:
            try:
                await visible_field.fill(value, timeout=3000)
            except Exception:
                pass

    password_inputs = page.locator("input[type='password']")
    for index in range(min(await password_inputs.count(), 5)):
        password_input = password_inputs.nth(index)
        try:
            if not await password_input.is_visible(timeout=500):
                continue
            await password_input.fill(password, timeout=3000)
        except Exception:
            pass

    await _click_named_control(
        page,
        re.compile(r"^(create account|register|sign up|submit|continue|next)$", re.IGNORECASE),
        messages,
        timeout=8000,
    )
    await page.wait_for_timeout(2500)

    verification_status = await _detect_human_verification(page)
    if verification_status:
        messages.append(f"Registration reached human verification gate: {verification_status}")
        return False

    messages.append("Attempted first-time portal account registration.")
    return True


async def _ensure_portal_auth(
    page: Any,
    allow_login: bool,
    allow_register: bool,
    result: dict[str, Any],
) -> None:
    content = await page.content()
    if not re.search(r"sign\s*in|log\s*in|login|create\s*account|register|sign\s*up", content, re.IGNORECASE):
        return

    verification_status = await _detect_human_verification(page)
    if verification_status:
        result["status"] = verification_status
        result["messages"].append(f"Human verification required before portal automation can continue: {verification_status}")
        return

    logged_in = await _fill_portal_login_if_allowed(page, allow_login, result["messages"])
    await page.wait_for_timeout(2000)

    if await _detect_human_verification(page):
        result["status"] = str(await _detect_human_verification(page))
        result["messages"].append("Login reached a human verification gate.")
        return

    post_login_content = await page.content()
    if logged_in and not re.search(r"invalid password|incorrect|account not found|create\s*account|register|sign\s*up", post_login_content, re.IGNORECASE):
        result["messages"].append("Portal login appears complete or in progress.")
        return

    registered = await _register_portal_account_if_allowed(page, allow_register, result["messages"])
    if registered:
        result["messages"].append("Portal registration attempted; continuing application flow.")
    else:
        result["status"] = "portal_auth_required"


async def _detect_required_unfilled(page: Any, scope: Any | None = None) -> list[str]:
    labels = []
    root = scope or page
    required_controls = root.locator(
        "input[required], textarea[required], select[required], [aria-required='true']"
    )
    count = await required_controls.count()
    for index in range(min(count, 25)):
        control = required_controls.nth(index)
        try:
            if not await control.is_visible(timeout=500):
                continue
        except Exception:
            continue
        try:
            control_type = ((await control.get_attribute("type")) or "").lower()
            if control_type == "file":
                continue
        except Exception:
            pass
        try:
            value = await control.input_value(timeout=1000)
            if value:
                continue
        except Exception:
            pass
        label = await _field_label_text(control, index)
        if "resume/cv" in label.lower() and "required" in label.lower():
            continue
        normalized_label = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
        if normalized_label in {"select", "choose"}:
            continue
        if _answer_for_required_label(label):
            continue
        labels.append(label)
    return labels


async def _control_has_value(control: Any) -> bool:
    try:
        control_type = ((await control.get_attribute("type")) or "").lower()
        if control_type in {"file", "hidden", "submit", "button", "checkbox", "radio"}:
            return True
    except Exception:
        pass

    try:
        value = await control.input_value(timeout=800)
        return bool(str(value or "").strip())
    except Exception:
        pass

    try:
        value = await control.text_content(timeout=800)
        return bool(str(value or "").strip())
    except Exception:
        return False


def _is_noise_application_label(label: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()
    if not normalized:
        return True
    if normalized in {"select", "choose", "search", "filter", "type message here", "enter manually"}:
        return True
    if "resume/cv" in normalized or "resume cv" in normalized:
        return True
    return False


async def _fill_known_visible_fields(page: Any, messages: list[str], scope: Any | None = None) -> None:
    root = scope or page
    controls = root.locator(
        "input:not([type='file']):not([type='hidden']):not([type='submit']):not([type='button']), "
        "textarea, select, [contenteditable='true']"
    )
    count = await controls.count()
    for index in range(min(count, 60)):
        control = controls.nth(index)
        try:
            if not await control.is_visible(timeout=500):
                continue
        except Exception:
            continue
        if await _control_has_value(control):
            continue

        label = await _field_label_text(control, index)
        if _is_noise_application_label(label):
            continue
        answer = _answer_for_required_label(label)
        if not answer:
            continue
        await _fill_field_safely(control, str(answer), label, messages)


async def _detect_visible_unanswered_questions(page: Any, scope: Any | None = None) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    root = scope or page
    controls = root.locator(
        "input:not([type='file']):not([type='hidden']):not([type='submit']):not([type='button']), "
        "textarea, select, [contenteditable='true']"
    )
    count = await controls.count()
    for index in range(min(count, 60)):
        control = controls.nth(index)
        try:
            if not await control.is_visible(timeout=500):
                continue
        except Exception:
            continue
        if await _control_has_value(control):
            continue

        label = await _field_label_text(control, index)
        if _is_noise_application_label(label):
            continue
        if _answer_for_required_label(label):
            continue
        key = app_settings.normalize_question_key(label)
        if key and key not in seen:
            labels.append(label)
            seen.add(key)

    return labels


def _digits_for_lpa(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+)?)", value or "")
    if not match:
        return value
    if re.search(r"lpa|lakh|lac", value or "", re.IGNORECASE):
        return str(int(float(match.group(1)) * 100000))
    return re.sub(r"[^\d]", "", value) or value


def _decimal_for_numeric_field(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return match.group(0) if match else str(value)


def _should_use_plain_decimal(label: str, input_type: str, value: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()
    if input_type.lower() == "number":
        return True
    if not re.search(r"[a-zA-Z]", str(value or "")):
        return False
    return any(
        token in normalized
        for token in [
            "ctc",
            "notice period",
            "years of experience",
            "year of experience",
            "how many years",
        ]
    )


def _should_select_autocomplete_option(label: str, role: str, autocomplete: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()
    if role.lower() == "combobox" or bool(autocomplete):
        return True
    return any(token in normalized for token in ["location", "city", "country", "address"])


async def _select_autocomplete_option(field: Any, value: str) -> None:
    try:
        await field.press("ArrowDown", timeout=1000)
        await field.press("Enter", timeout=1000)
        return
    except Exception:
        pass

    try:
        await field.evaluate(
            """(el, wanted) => {
                const normalizedWanted = String(wanted || '').trim().toLowerCase();
                const option = Array.from(document.querySelectorAll('[role="option"], [role="listbox"] *'))
                    .find((node) => {
                        const text = (node.innerText || node.textContent || '').trim();
                        const rect = node.getBoundingClientRect();
                        return text
                            && rect.width > 0
                            && rect.height > 0
                            && (!normalizedWanted || text.toLowerCase().includes(normalizedWanted));
                    });
                if (option) option.click();
            }""",
            value,
        )
    except Exception:
        pass


def _answer_for_required_label(label: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()
    answers = app_settings.get_application_auto_answers()
    profile = app_settings.get_application_profile()
    if not normalized:
        return None

    if "current gross compensation" in normalized or "current compensation" in normalized or "current salary" in normalized:
        return _digits_for_lpa(answers.get("indiaCurrentCtc", ""))
    if "expected gross compensation" in normalized or "expected compensation" in normalized or "expected salary" in normalized:
        return _digits_for_lpa(answers.get("indiaExpectedCtc", ""))
    if "target salary" in normalized or "salary expectation" in normalized or "salary expectations" in normalized:
        return answers.get("indiaExpectedCtc", "50 LPA")
    if "available to start" in normalized or "availability" in normalized or "available from" in normalized:
        return answers.get("availableFrom", "After 30 days notice")
    if "notice" in normalized:
        return _decimal_for_numeric_field(answers.get("noticePeriod", ""))
    if "how did you hear" in normalized:
        return "LinkedIn"
    if "specially able" in normalized or "disability" in normalized:
        return "No"
    if "privacy policy" in normalized or "terms" in normalized:
        return "Yes"
    if "employment status" in normalized:
        return answers.get("employmentType", "Full-time")
    if "rest" in normalized or "representational state transfer" in normalized:
        return profile.get("devopsExperience", "") or profile.get("sreExperience", "") or "7"
    if "java" in normalized:
        return "0"
    learned_answer = app_settings.find_application_question_answer(label)
    if learned_answer:
        return learned_answer
    if "total work experience" in normalized or "total years of experience" in normalized:
        return profile.get("totalExperience", "9.6")
    if "relevant work experience" in normalized or "years of work experience" in normalized or "years of experience" in normalized:
        return profile.get("devopsExperience", "") or profile.get("sreExperience", "") or "7"
    if "country" in normalized:
        return answers.get("country", "India")
    if "candidate location" in normalized or normalized == "location" or "current location" in normalized:
        return answers.get("currentLocation") or profile.get("currentLocation", "")
    if "city" in normalized:
        return profile.get("addressCity", "")
    if normalized == "state" or normalized.startswith("state ") or " address state" in normalized:
        return profile.get("addressState", "")
    if "phone" in normalized or "mobile" in normalized:
        return profile.get("phone", "")
    if "email" in normalized:
        return profile.get("email", "")
    if "linkedin" in normalized:
        return profile.get("linkedinUrl", "")
    if ("authorized" in normalized or "authorised" in normalized) and "india" in normalized:
        return answers.get("indiaWorkAuthorization", "")
    if "authorized" in normalized or "authorised" in normalized or "work authorization" in normalized:
        return answers.get("workAuthorization", "")
    if "sponsor" in normalized or "visa" in normalized:
        return answers.get("needSponsorship", "")
    if "relocat" in normalized:
        return answers.get("willingToRelocate", "")
    if "experience" in normalized:
        learned_answer = app_settings.find_application_question_answer(label)
        return learned_answer or profile.get("totalExperience", "")
    if "cross cutting platform" in normalized or "served multiple products" in normalized or "multiple products or teams" in normalized:
        return (
            "I led reusable CI/CD and Kubernetes platform improvements used across multiple application teams, "
            "standardizing deployment pipelines, observability, and infrastructure modules so teams could release "
            "more reliably with less manual operational work."
        )
    if "influenced product" in normalized or "engineering direction" in normalized:
        return (
            "I influenced engineering direction by using production reliability data, deployment metrics, and incident "
            "patterns to recommend platform changes, improve release quality, and prioritize automation that reduced "
            "manual effort for multiple teams."
        )
    if "mentored" in normalized or "guided engineers" in normalized or "technical bar" in normalized:
        return (
            "I mentor engineers through code reviews, CI/CD design reviews, runbook improvements, and hands-on guidance "
            "for Kubernetes, Terraform, monitoring, and incident response practices."
        )
    if "ai tools" in normalized or "leveraging ai" in normalized or "day to day development" in normalized:
        return (
            "I use AI tools to speed up troubleshooting, draft automation scripts, improve documentation, review CI/CD "
            "changes, and explore test cases while still validating outputs against logs, code, and production constraints."
        )
    return None


async def _field_label_text(field: Any, index: int) -> str:
    try:
        return await field.evaluate(
            """(el, fallbackIndex) => {
                const values = [];
                const add = (value) => {
                    if (value && String(value).trim()) values.push(String(value).trim());
                };
                if (el.labels) {
                    Array.from(el.labels).forEach((label) => add(label.innerText || label.textContent));
                }
                const container = el.closest("label, .field, .application-question, [data-testid], div");
                if (container) add(container.innerText || container.textContent);
                const describedBy = el.getAttribute("aria-describedby");
                if (describedBy) {
                    describedBy.split(/\\s+/).forEach((id) => {
                        const node = document.getElementById(id);
                        if (node) add(node.innerText || node.textContent);
                    });
                }
                add(el.getAttribute("aria-label"));
                add(el.getAttribute("name"));
                add(el.getAttribute("id"));
                const placeholder = /^(select|select\\.\\.\\.|choose|choose\\.\\.\\.|attach|enter manually|google drive)$/i;
                return values.find((value) => !placeholder.test(value.trim())) || values.find(Boolean) || `required-field-${fallbackIndex + 1}`;
            }""",
            index,
        )
    except Exception:
        return f"required-field-{index + 1}"


async def _fill_known_required_fields(page: Any, messages: list[str], scope: Any | None = None) -> None:
    root = scope or page
    controls = root.locator("input[required], textarea[required], select[required], [aria-required='true']")
    count = await controls.count()
    for index in range(min(count, 40)):
        control = controls.nth(index)
        try:
            if not await control.is_visible(timeout=500):
                continue
        except Exception:
            continue
        try:
            current_value = await control.input_value(timeout=1000)
            if current_value:
                continue
        except Exception:
            pass

        label = await _field_label_text(control, index)
        answer = _answer_for_required_label(label)
        if not answer:
            continue
        await _fill_field_safely(control, str(answer), label, messages)


async def _fill_common_portal_widgets(page: Any, portal: str, messages: list[str]) -> None:
    answers = app_settings.get_application_auto_answers()
    profile = app_settings.get_application_profile()
    location = answers.get("currentLocation") or profile.get("currentLocation", "")
    country = answers.get("country", "India")

    if portal == "greenhouse":
        for selector, value, label in [
            ("input[id*='candidate-location' i], input[name*='candidate-location' i], input[aria-label*='location' i]", location, "Candidate Location"),
            ("input[id*='country' i], input[name*='country' i], select[id*='country' i], select[name*='country' i]", country, "Country"),
        ]:
            if not value:
                continue
            fields = page.locator(selector)
            if await fields.count() > 0:
                await _fill_field_safely(fields.first, value, label, messages)
                try:
                    await page.keyboard.press("Enter")
                except Exception:
                    pass

        yes_no_answers = {
            "authorized": answers.get("indiaWorkAuthorization", "Yes"),
            "sponsor": answers.get("indiaNeedSponsorship", "No"),
            "visa": answers.get("indiaNeedSponsorship", "No"),
            "relocat": answers.get("willingToRelocate", "Yes"),
        }
        radios = page.locator("input[type='radio']")
        for index in range(min(await radios.count(), 40)):
            radio = radios.nth(index)
            try:
                if await radio.is_checked(timeout=500):
                    continue
                label = await _field_label_text(radio, index)
                desired = None
                for key, value in yes_no_answers.items():
                    if key in label.lower():
                        desired = str(value).strip().lower()
                        break
                if desired not in {"yes", "no"}:
                    continue
                value_attr = ((await radio.get_attribute("value")) or "").lower()
                radio_label = label.lower()
                if desired in value_attr or re.search(rf"\b{desired}\b", radio_label):
                    await radio.check(timeout=2000)
                    messages.append(f"Selected configured radio answer for: {label}")
            except Exception:
                continue


async def _maybe_submit(page: Any, allow_submit: bool, result: dict[str, Any], scope: Any | None = None) -> None:
    root = scope or page
    await _fill_common_portal_widgets(page, str(result.get("portal") or ""), result["messages"])
    await _fill_known_required_fields(page, result["messages"], scope=root)
    await _fill_known_visible_fields(page, result["messages"], scope=root)
    required_unfilled = await _detect_required_unfilled(page, scope=root)
    if required_unfilled:
        result["status"] = "manual_review_required"
        result["missing_questions"] = required_unfilled
        result["messages"].append(f"Required fields/questions need review: {required_unfilled}")
        return

    submit = await _find_submit_button(root)
    if await submit.count() == 0:
        submit = await _find_submit_button(page)
    if await submit.count() == 0:
        visible_buttons = await _visible_button_labels(root)
        result["status"] = "manual_review_required"
        if not result.get("missing_questions"):
            result["missing_questions"] = await _detect_visible_unanswered_questions(page, scope=root)
        result["messages"].append("No final submit/apply button detected.")
        if visible_buttons:
            result["messages"].append(f"Visible buttons at final check: {visible_buttons}")
        await _save_application_debug_artifacts(page, result, "no_final_submit", scope=root)
        return

    if not allow_submit:
        result["status"] = "manual_review_required"
        result["messages"].append("Final submit/apply button detected. Submit blocked because --allow-submit was not provided.")
        return

    try:
        await submit.first.click(timeout=10000)
    except Exception:
        await submit.first.evaluate("(element) => element.click()", timeout=2000)
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

        easy_apply = page.locator(
            f"a[href*='/jobs/view/{candidate.job_id}/apply/'][href*='openSDUIApplyFlow=true']"
        )
        easy_apply_source = "current job apply link"
        if await easy_apply.count() == 0:
            easy_apply = page.locator(
                f"a[aria-label='Easy Apply to this job'][href*='/jobs/view/{candidate.job_id}/apply/']"
            )
            easy_apply_source = "current job aria apply link"
        if await easy_apply.count() == 0:
            easy_apply = page.get_by_role("button", name=re.compile(r"\bEasy Apply\b", re.IGNORECASE))
            easy_apply_source = "button"
        if await easy_apply.count() == 0:
            easy_apply = page.locator("button:has-text('Easy Apply')")

        if await easy_apply.count() > 0:
            try:
                await easy_apply.first.click(timeout=15000)
                result["messages"].append(f"Easy Apply {easy_apply_source} clicked.")
                await page.wait_for_timeout(3000)
            except PlaywrightTimeoutError:
                result["status"] = "blocked"
                result["messages"].append(f"Easy Apply {easy_apply_source} was detected but could not be clicked before timeout.")
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

        application_scope = await _application_scope(page)

        file_inputs = application_scope.locator("input[type='file']")
        if await file_inputs.count() > 0:
            await file_inputs.first.set_input_files(str(resume_path))
            result["messages"].append("Custom resume uploaded.")
        else:
            result["messages"].append("Resume upload input not found on the first step.")

        if phone_number:
            phone_inputs = application_scope.locator(
                "input[name*='phone' i], input[id*='phone' i], input[aria-label*='phone' i]"
            )
            if await phone_inputs.count() > 0:
                await _fill_field_safely(phone_inputs.first, phone_number, "Phone", result["messages"])

        for label, value in default_answers.items():
            field = application_scope.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
            if await field.count() > 0:
                await _fill_field_safely(field.first, str(value), label, result["messages"])

        for _ in range(8):
            application_scope = await _application_scope(page)
            final_submit = await _find_submit_button(application_scope)
            if await final_submit.count() > 0:
                break
            clicked = await _click_first_button(
                page,
                NEXT_BUTTON_TEXT,
                result["messages"],
                timeout=5000,
                scope=application_scope,
            )
            if not clicked:
                review_button = application_scope.get_by_role("button", name=REVIEW_BUTTON_TEXT)
                if await review_button.count() > 0:
                    break
                visible_buttons = await _visible_button_labels(application_scope)
                if visible_buttons:
                    result["messages"].append(f"Could not advance Easy Apply step. Visible buttons: {visible_buttons}")
                break
            await page.wait_for_timeout(2000)
            application_scope = await _application_scope(page)
            await _upload_resume_if_possible(page, resume_path, result["messages"], scope=application_scope)
            if phone_number:
                phone_inputs = application_scope.locator(
                    "input[name*='phone' i], input[id*='phone' i], input[aria-label*='phone' i]"
                )
                if await phone_inputs.count() > 0:
                    await _fill_field_safely(phone_inputs.first, phone_number, "Phone", result["messages"])
            for label, value in default_answers.items():
                field = application_scope.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
                if await field.count() > 0:
                    await _fill_field_safely(field.first, str(value), label, result["messages"])

        application_scope = await _application_scope(page)
        final_submit = await _find_submit_button(application_scope)
        if await final_submit.count() == 0:
            reviewed = await _click_first_button(
                page,
                REVIEW_BUTTON_TEXT,
                result["messages"],
                timeout=5000,
                scope=application_scope,
            )
            if reviewed:
                await page.wait_for_timeout(2500)

        application_scope = await _application_scope(page)
        await _maybe_submit(page, allow_submit, result, scope=application_scope)
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


async def _fill_label_if_present(
    page: Any,
    label: str,
    value: str,
    messages: list[str],
    scope: Any | None = None,
) -> None:
    root = scope or page
    field = root.get_by_label(re.compile(re.escape(label), re.IGNORECASE))
    visible_field = await _first_visible(field)
    if not visible_field:
        return

    try:
        await _fill_field_safely(visible_field, value, label, messages)
    except Exception:
        messages.append(f"Detected profile field but left for manual review: {label}")


async def prepare_workday_profile(
    apply_url: str,
    resume_file: str | None = None,
    candidate: ApplicationCandidate | None = None,
    headless: bool = False,
    allow_submit: bool = False,
    allow_login: bool = False,
    allow_register: bool = False,
) -> dict[str, Any]:
    """
    Opens a Workday application/profile page, uploads the selected resume when possible,
    fills only configured safe profile fields, and stops before submit.
    """
    from playwright.async_api import async_playwright

    if not WORKDAY_URL_PATTERN.search(apply_url):
        raise ValueError("The provided URL does not look like a Workday application URL.")

    resume_path = _first_existing_resume_path(resume_file, candidate)
    storage_state = _portal_storage_state_path("workday", apply_url)
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

        if re.search(r"sign\s*in|login|create\s*account|register", await page.content(), re.IGNORECASE):
            result["messages"].append("Workday login/create-account step detected.")
            await _ensure_portal_auth(page, allow_login, allow_register, result)
            if result["status"] in {"portal_auth_required", "captcha_required", "email_or_otp_verification_required", "mfa_required"}:
                await _save_portal_storage_state(context, "workday", apply_url, "WORKDAY_STORAGE_STATE_OUT", "workday_storage_state.json")
                await browser.close()
                return result

        for button_name in [
            r"Apply",
            r"Apply Manually",
            r"Autofill with Resume",
            r"Use My Last Application",
        ]:
            button = page.get_by_role("button", name=re.compile(button_name, re.IGNORECASE))
            visible_button = await _first_visible(button)
            if visible_button:
                try:
                    await visible_button.click(timeout=5000)
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

        await _save_portal_storage_state(context, "workday", apply_url, "WORKDAY_STORAGE_STATE_OUT", "workday_storage_state.json")
        await browser.close()

    return result


async def prepare_company_portal(
    apply_url: str,
    resume_file: str | None = None,
    candidate: ApplicationCandidate | None = None,
    headless: bool = False,
    allow_submit: bool = False,
    allow_login: bool = False,
    allow_register: bool = False,
) -> dict[str, Any]:
    portal = detect_portal_for_url(apply_url)
    if portal == "unknown":
        portal = detect_portal(apply_url, candidate.provider if candidate else "")
    if not _is_http_url(apply_url):
        return {
            "job_id": candidate.job_id if candidate else None,
            "apply_url": apply_url,
            "resume_path": str(_first_existing_resume_path(resume_file, candidate)),
            "status": "external_apply_unresolved",
            "portal": portal,
            "messages": [f"Company portal URL is not a valid HTTP URL: {apply_url}"],
        }

    if portal == "workday":
        return await prepare_workday_profile(
            apply_url=apply_url,
            resume_file=resume_file,
            candidate=candidate,
            headless=headless,
            allow_submit=allow_submit,
            allow_login=allow_login,
            allow_register=allow_register,
        )

    from playwright.async_api import async_playwright

    resume_path = _first_existing_resume_path(resume_file, candidate)
    storage_state = _portal_storage_state_path(portal, apply_url)
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
        try:
            response = await page.goto(apply_url, wait_until="domcontentloaded", timeout=90000)
            if page.url.startswith("chrome-error://") or response is None:
                result["status"] = "external_apply_unresolved"
                result["messages"].append(f"Could not open company portal URL: {apply_url}")
                await browser.close()
                return result
        except Exception as exc:
            result["status"] = "external_apply_unresolved"
            result["messages"].append(f"Could not open company portal URL: {exc}")
            await browser.close()
            return result
        try:
            await _ensure_portal_auth(page, allow_login, allow_register, result)
        except Exception as exc:
            result["status"] = "automation_error"
            result["messages"].append(f"Portal login/auth automation failed safely: {exc}")
            await _save_portal_storage_state(context, portal, apply_url, f"{portal.upper()}_STORAGE_STATE_OUT", f"{portal}_storage_state.json")
            await browser.close()
            return result
        if result["status"] in {"portal_auth_required", "captcha_required", "email_or_otp_verification_required", "mfa_required"}:
            await _save_portal_storage_state(context, portal, apply_url, f"{portal.upper()}_STORAGE_STATE_OUT", f"{portal}_storage_state.json")
            await browser.close()
            return result

        try:
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
        except Exception as exc:
            result["status"] = "automation_error"
            result["messages"].append(f"Company portal automation failed safely: {exc}")
        _update_job_after_submission(candidate, result)
        await _save_portal_storage_state(context, portal, apply_url, f"{portal.upper()}_STORAGE_STATE_OUT", f"{portal}_storage_state.json")
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
    parser.add_argument(
        "--max-job-age-minutes",
        type=int,
        default=None,
        help="Only process jobs posted/scraped within this many minutes. 0 disables the freshness filter.",
    )
    parser.add_argument(
        "--daily-submit-limit",
        type=int,
        default=None,
        help="Maximum applications to submit per UTC day. 0 disables the cap.",
    )
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
        "--allow-register",
        action="store_true",
        help="Allow creating first-time company portal accounts using configured application profile and portal credentials.",
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
    effective_allow_register = args.allow_register or bool(automation_settings.get("allowPortalRegister"))
    max_job_age_minutes = (
        args.max_job_age_minutes
        if args.max_job_age_minutes is not None
        else int(automation_settings.get("maxJobAgeMinutes") or 0)
    )
    daily_submit_limit = (
        args.daily_submit_limit
        if args.daily_submit_limit is not None
        else int(automation_settings.get("maxDailyApplications") or 0)
    )

    if args.mode in {"prepare-workday-profile", "prepare-company-portal"} and args.apply_url:
        if args.mode == "prepare-workday-profile":
            result = await prepare_workday_profile(
                apply_url=args.apply_url,
                resume_file=args.resume_file,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                allow_login=effective_allow_login,
                allow_register=effective_allow_register,
            )
        else:
            result = await prepare_company_portal(
                apply_url=args.apply_url,
                resume_file=args.resume_file,
                headless=effective_headless,
                allow_submit=effective_allow_submit,
                allow_login=effective_allow_login,
                allow_register=effective_allow_register,
            )
        print(json.dumps(result, indent=2))
        if result.get("status") == "submitted":
            print("\nSubmitted because --allow-submit was explicitly provided and no unknown required fields were detected.")
        else:
            print("\nStopped before final submit.")
        return

    provider = None if args.provider == "all" else args.provider
    candidates = fetch_candidates(
        limit=candidate_pool_limit(args.limit, args.mode),
        min_score=args.min_score,
        provider=provider,
        max_age_minutes=max_job_age_minutes if args.mode in {"auto-apply", "prepare-company-portal"} else None,
        stale_fallback_limit=args.limit if args.mode in {"auto-apply", "prepare-company-portal"} else None,
    )
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
    submitted_today = count_submitted_today() if effective_allow_submit else 0

    for candidate in candidates:
        if args.mode == "prepare-workday-profile":
            submit_allowed = effective_allow_submit and _daily_submit_available(
                submitted_today,
                daily_submit_limit,
            )
            if effective_allow_submit and not submit_allowed:
                logging.info("Daily submit limit reached: %s", daily_submit_limit)
                break
            if detect_portal(candidate.apply_url, candidate.provider) != "workday":
                logging.info("Skipping non-Workday candidate %s.", candidate.job_id)
                continue
            result = await prepare_workday_profile(
                apply_url=candidate.apply_url,
                resume_file=args.resume_file,
                candidate=candidate,
                headless=effective_headless,
                allow_submit=submit_allowed,
                allow_login=effective_allow_login,
                allow_register=effective_allow_register,
            )
            queue_candidate(candidate, status=result["status"], result=result)
            results.append(result)
            print(json.dumps(result, indent=2))
            if result.get("status") == "submitted":
                submitted_today += 1
            continue

        if args.mode == "prepare-company-portal":
            submit_allowed = effective_allow_submit and _daily_submit_available(
                submitted_today,
                daily_submit_limit,
            )
            if effective_allow_submit and not submit_allowed:
                logging.info("Daily submit limit reached: %s", daily_submit_limit)
                break
            apply_url = candidate.apply_url
            if detect_portal(candidate.apply_url, candidate.provider) == "linkedin":
                resolve_result = await resolve_linkedin_company_apply_url(
                    candidate,
                    headless=effective_headless,
                    manual_login_wait=args.manual_login_wait,
                )
                if resolve_result.get("status") != "external_apply_resolved":
                    queue_candidate(
                        candidate,
                        status=str(resolve_result.get("status") or "company_portal_review"),
                        result=resolve_result,
                    )
                    results.append(resolve_result)
                    print(json.dumps(resolve_result, indent=2))
                    continue
                apply_url = str(resolve_result["resolved_apply_url"])

            result = await prepare_company_portal(
                apply_url=apply_url,
                resume_file=args.resume_file,
                candidate=candidate,
                headless=effective_headless,
                allow_submit=submit_allowed,
                allow_login=effective_allow_login,
                allow_register=effective_allow_register,
            )
            queue_candidate(
                candidate,
                status=result["status"],
                apply_url=apply_url,
                portal=str(result.get("portal") or detect_portal(apply_url, candidate.provider)),
                notes={"resolved_from": candidate.apply_url} if apply_url != candidate.apply_url else None,
                result=result,
            )
            results.append(result)
            print(json.dumps(result, indent=2))
            if result.get("status") == "submitted":
                submitted_today += 1
            if result.get("status") in progress_statuses:
                progress_count += 1
                if progress_count >= args.limit:
                    logging.info("Reached requested company portal progress limit: %s", args.limit)
                    break
            continue

        if args.mode == "auto-apply":
            submit_allowed = effective_allow_submit and _daily_submit_available(
                submitted_today,
                daily_submit_limit,
            )
            if effective_allow_submit and not submit_allowed:
                logging.info("Daily submit limit reached: %s", daily_submit_limit)
                break
            if detect_portal(candidate.apply_url, candidate.provider) != "linkedin":
                logging.info("Skipping non-LinkedIn candidate %s in auto-apply mode.", candidate.job_id)
                queue_candidate(candidate, status="company_portal_review")
                continue
            result = await prepare_linkedin_easy_apply(
                candidate,
                headless=effective_headless,
                allow_submit=submit_allowed,
                manual_login_wait=args.manual_login_wait,
            )
            queue_candidate(candidate, status=result["status"], result=result)
            results.append(result)
            print(json.dumps(result, indent=2))
            if result.get("status") == "submitted":
                submitted_today += 1
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
        queue_candidate(candidate, status=result["status"], result=result)
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
