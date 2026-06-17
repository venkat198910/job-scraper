import argparse
import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass
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


def linkedin_job_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}"


def detect_portal(apply_url: str, provider: str = "") -> str:
    if WORKDAY_URL_PATTERN.search(apply_url or ""):
        return "workday"
    if (provider or "").lower() == "linkedin":
        return "linkedin"
    return (provider or "unknown").lower()


def detect_application_type(job: dict[str, Any]) -> str:
    provider = (job.get("provider") or "").lower()
    apply_url = build_apply_url(job)
    if detect_portal(apply_url, provider) == "workday":
        return "workday_profile_review"
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
            )
        )

    return candidates


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


async def prepare_linkedin_easy_apply(candidate: ApplicationCandidate, headless: bool = False) -> dict[str, Any]:
    """
    Opens LinkedIn, detects Easy Apply, uploads the custom resume when possible,
    and stops before final submit. This is intentionally manual-review only.
    """
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    resume_path = download_resume(candidate)
    storage_state = os.environ.get("LINKEDIN_STORAGE_STATE")
    phone_number = os.environ.get("APPLICATION_PHONE", "")
    default_answers = json.loads(os.environ.get("APPLICATION_DEFAULT_ANSWERS_JSON", "{}") or "{}")

    result = {
        "job_id": candidate.job_id,
        "apply_url": candidate.apply_url,
        "resume_path": str(resume_path),
        "status": "blocked",
        "messages": [],
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless)
        context_options = {}
        if storage_state and Path(storage_state).exists():
            context_options["storage_state"] = storage_state
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        await page.goto(candidate.apply_url, wait_until="domcontentloaded", timeout=60000)

        if "login" in page.url.lower():
            result["messages"].append("LinkedIn login required. Set LINKEDIN_STORAGE_STATE after logging in once.")
            await browser.close()
            return result

        try:
            easy_apply = page.get_by_role("button", name=re.compile("Easy Apply", re.IGNORECASE)).first
            await easy_apply.click(timeout=15000)
        except PlaywrightTimeoutError:
            result["messages"].append("Easy Apply button was not detected.")
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

        submit_buttons = page.get_by_role("button", name=SAFE_FINAL_SUBMIT_TEXT)
        if await submit_buttons.count() > 0:
            result["messages"].append("Final submit button detected. Stopping before submit.")

        result["status"] = "manual_review_required"
        await context.storage_state(path=os.environ.get("LINKEDIN_STORAGE_STATE_OUT", "linkedin_storage_state.json"))
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
    env_defaults.update({str(key): str(value) for key, value in profile.items() if value})
    return {key: value for key, value in env_defaults.items() if value}


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
        browser = await playwright.chromium.launch(headless=headless)
        context_options = {}
        if storage_state and Path(storage_state).exists():
            context_options["storage_state"] = storage_state
        context = await browser.new_context(**context_options)
        page = await context.new_page()
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=90000)

        if re.search(r"sign\s*in|login|create\s*account", await page.content(), re.IGNORECASE):
            result["messages"].append("Workday login/create-account step detected. Complete it manually first.")

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

        file_inputs = page.locator("input[type='file']")
        if await file_inputs.count() > 0:
            await file_inputs.first.set_input_files(str(resume_path))
            result["messages"].append("Custom resume selected for Workday upload.")
        else:
            result["messages"].append("No Workday file input detected on the current step.")

        for label, value in profile_defaults.items():
            await _fill_label_if_present(page, label, value, result["messages"])

        final_submit = page.get_by_role("button", name=SAFE_FINAL_SUBMIT_TEXT)
        if await final_submit.count() > 0:
            result["messages"].append("Final submit/apply button detected. Stopping before submit.")

        await context.storage_state(path=os.environ.get("WORKDAY_STORAGE_STATE_OUT", "workday_storage_state.json"))
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
        choices=["plan", "queue", "prepare-easy-apply", "prepare-workday-profile"],
        default="plan",
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-score", type=int, default=app_settings.get_min_score())
    parser.add_argument("--provider", choices=["linkedin", "all"], default="linkedin")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--apply-url", help="Manual apply URL, useful for Workday/company portals.")
    parser.add_argument("--resume-file", help="Local resume PDF path for manual Workday/company portal preparation.")
    args = parser.parse_args()

    if args.mode == "prepare-workday-profile" and args.apply_url:
        result = await prepare_workday_profile(
            apply_url=args.apply_url,
            resume_file=args.resume_file,
            headless=args.headless,
        )
        print(json.dumps(result, indent=2))
        print("\nStopped before final submit.")
        return

    provider = None if args.provider == "all" else args.provider
    candidates = fetch_candidates(limit=args.limit, min_score=args.min_score, provider=provider)
    print_candidates(candidates)

    if args.mode == "plan":
        print("\nPlan mode only. No queue rows, browser actions, or submissions were performed.")
        return

    if args.mode == "queue":
        queued = sum(1 for candidate in candidates if queue_candidate(candidate))
        print(f"\nQueued {queued} candidate(s) as application_ready. No browser actions or submissions were performed.")
        return

    for candidate in candidates:
        if args.mode == "prepare-workday-profile":
            if detect_portal(candidate.apply_url, candidate.provider) != "workday":
                logging.info("Skipping non-Workday candidate %s.", candidate.job_id)
                continue
            result = await prepare_workday_profile(
                apply_url=candidate.apply_url,
                resume_file=args.resume_file,
                candidate=candidate,
                headless=args.headless,
            )
            queue_candidate(candidate, status=result["status"])
            print(json.dumps(result, indent=2))
            continue

        if candidate.provider != "linkedin":
            logging.info("Skipping non-LinkedIn candidate %s in Easy Apply mode.", candidate.job_id)
            continue
        result = await prepare_linkedin_easy_apply(candidate, headless=args.headless)
        queue_candidate(candidate, status=result["status"])
        print(json.dumps(result, indent=2))

    print("\nStopped before final submit for every candidate.")


if __name__ == "__main__":
    asyncio.run(main())
