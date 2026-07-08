import argparse
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from save_browser_session import SESSION_TARGETS, save_session, update_github_secret


SESSION_CHECKS = {
    "naukri": {
        "url": "https://www.naukri.com/devops-engineer-jobs-in-bengaluru?k=DevOps%20Engineer&l=Bengaluru&jobAge=1&sort=date",
        "success_markers": ("job", "devops", "apply", "save"),
        "blocked_markers": (
            "access denied",
            "captcha",
            "recaptcha",
            "verify",
            "human verification",
            "permission to access",
            "login to continue",
        ),
    },
    "naukri_gulf": {
        "url": "https://www.naukrigulf.com/devops-engineer-jobs-in-dubai?k=DevOps%20Engineer&l=Dubai&sort=date",
        "success_markers": ("job", "devops", "apply", "save"),
        "blocked_markers": (
            "access denied",
            "captcha",
            "recaptcha",
            "verify",
            "human verification",
            "permission to access",
            "login to continue",
        ),
    },
}


def _storage_state_arg(target: str, output: str | None) -> str | None:
    path = Path(output or SESSION_TARGETS[target]["output"]).resolve()
    return str(path) if path.exists() else None


def session_is_usable(target: str, output: str | None, headless: bool) -> tuple[bool, str]:
    check = SESSION_CHECKS[target]
    storage_state = _storage_state_arg(target, output)
    if not storage_state:
        return False, "storage state file is missing"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                storage_state=storage_state,
                viewport={"width": 1366, "height": 900},
                locale="en-US",
                timezone_id="Asia/Kolkata",
            )
            page = context.new_page()
            try:
                page.goto(check["url"], wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    pass
                body_text = page.locator("body").inner_text(timeout=10000).lower()
            finally:
                browser.close()
    except Exception as exc:
        return False, f"session check failed: {exc}"

    for marker in check["blocked_markers"]:
        if marker in body_text:
            return False, f"blocked marker detected: {marker}"

    if any(marker in body_text for marker in check["success_markers"]):
        return True, "session can load job/search content"

    return False, "job/search content was not detected"


def refresh_target(
    target: str,
    output: str | None,
    repo: str,
    wait_seconds: int,
    check_headless: bool,
    update_secret: bool,
    auto_login: bool,
) -> bool:
    ok, reason = session_is_usable(target, output, check_headless)
    if ok:
        print(f"{target}: OK - {reason}")
        return False

    print(f"{target}: refresh required - {reason}")
    output_path = save_session(
        target=target,
        output=output,
        wait_seconds=wait_seconds,
        headless=False,
        url=None,
        auto_login=auto_login,
    )
    print(f"{target}: saved refreshed session to {output_path}")

    ok_after, reason_after = session_is_usable(target, str(output_path), check_headless)
    if not ok_after:
        print(f"{target}: refreshed session still looks unusable - {reason_after}")
        return True

    print(f"{target}: refreshed session verified - {reason_after}")
    if update_secret:
        update_github_secret(target, output_path, repo)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Keep browser sessions fresh. When a session is stale, this opens a "
            "real browser for login, saves storage_state, and optionally updates "
            "the matching GitHub Actions secret."
        )
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        choices=sorted(SESSION_CHECKS),
        default=["naukri", "naukri_gulf"],
        help="Session targets to check.",
    )
    parser.add_argument(
        "--repo",
        default="venkat198910/job-scraper",
        help="GitHub repository for secret updates.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=600,
        help="How long to wait for login when stdin is unavailable.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Keep checking forever.",
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=60,
        help="Loop interval in minutes.",
    )
    parser.add_argument(
        "--no-secret-update",
        action="store_true",
        help="Refresh local JSON only; do not update GitHub secrets.",
    )
    parser.add_argument(
        "--auto-login",
        action="store_true",
        help="Try username/password auto-login from env vars before prompting.",
    )
    parser.add_argument(
        "--headed-check",
        action="store_true",
        help="Use a visible browser for session checks too.",
    )
    args = parser.parse_args()

    while True:
        print("\nChecking browser sessions...")
        for target in args.targets:
            refresh_target(
                target=target,
                output=None,
                repo=args.repo,
                wait_seconds=args.wait_seconds,
                check_headless=not args.headed_check,
                update_secret=not args.no_secret_update,
                auto_login=args.auto_login,
            )

        if not args.loop:
            break

        sleep_seconds = max(1, args.interval_minutes) * 60
        print(f"Sleeping {args.interval_minutes} minute(s) before next session check...")
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
