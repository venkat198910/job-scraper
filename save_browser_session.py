import argparse
import os
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


SESSION_TARGETS = {
    "linkedin": {
        "url": "https://www.linkedin.com/login",
        "output": "linkedin_storage_state.json",
        "secret": "LINKEDIN_STORAGE_STATE_JSON",
    },
    "workday": {
        "url": "https://www.myworkday.com/",
        "output": "workday_storage_state.json",
        "secret": "WORKDAY_STORAGE_STATE_JSON",
    },
    "naukri": {
        "url": "https://www.naukri.com/mnjuser/homepage",
        "output": "naukri_storage_state.json",
        "secret": "NAUKRI_STORAGE_STATE_JSON",
    },
    "naukri_gulf": {
        "url": "https://www.naukrigulf.com/mnjuser/homepage",
        "output": "naukri_gulf_storage_state.json",
        "secret": "NAUKRI_GULF_STORAGE_STATE_JSON",
    },
}


def _credential_env_names(target: str) -> tuple[str, str]:
    if target == "naukri_gulf":
        return "NAUKRI_GULF_USERNAME", "NAUKRI_GULF_PASSWORD"
    if target == "naukri":
        return "NAUKRI_USERNAME", "NAUKRI_PASSWORD"
    return f"{target.upper()}_USERNAME", f"{target.upper()}_PASSWORD"


def _get_credentials(target: str) -> tuple[str, str]:
    username_name, password_name = _credential_env_names(target)
    username = (
        os.environ.get(username_name)
        or os.environ.get("APPLICATION_PORTAL_EMAIL")
        or ""
    ).strip()
    password = (
        os.environ.get(password_name)
        or os.environ.get("APPLICATION_PORTAL_PASSWORD")
        or ""
    )
    return username, password


def _first_visible(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None


def _click_first_visible(page, selectors: list[str]) -> bool:
    locator = _first_visible(page, selectors)
    if not locator:
        return False
    try:
        locator.click(timeout=5000)
        return True
    except Exception:
        return False


def _fill_first_visible(page, selectors: list[str], value: str) -> bool:
    locator = _first_visible(page, selectors)
    if not locator:
        return False
    try:
        locator.fill(value, timeout=5000)
        return True
    except Exception:
        return False


def attempt_auto_login(target: str, page) -> bool:
    username, password = _get_credentials(target)
    if not username or not password:
        print(f"{target}: auto-login skipped because username/password env vars are missing.")
        return False

    if target not in {"naukri", "naukri_gulf"}:
        print(f"{target}: auto-login is not implemented for this target.")
        return False

    print(f"{target}: attempting username/password auto-login.")
    _click_first_visible(
        page,
        [
            "text=/^login$/i",
            "button:has-text('Login')",
            "a:has-text('Login')",
            "[data-ga-track*='login' i]",
        ],
    )
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    username_filled = _fill_first_visible(
        page,
        [
            "input[type='email']",
            "input[name='email']",
            "input[name='username']",
            "input[name='userName']",
            "input[id*='email' i]",
            "input[id*='username' i]",
            "input[placeholder*='email' i]",
            "input[placeholder*='username' i]",
            "input[placeholder*='mobile' i]",
        ],
        username,
    )
    password_filled = _fill_first_visible(
        page,
        [
            "input[type='password']",
            "input[name='password']",
            "input[id*='password' i]",
            "input[placeholder*='password' i]",
        ],
        password,
    )

    if not username_filled or not password_filled:
        print(f"{target}: could not find login fields for auto-login.")
        return False

    clicked = _click_first_visible(
        page,
        [
            "button[type='submit']",
            "button:has-text('Login')",
            "button:has-text('Sign in')",
            "input[type='submit']",
        ],
    )
    if not clicked:
        try:
            page.keyboard.press("Enter")
        except Exception:
            pass

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PlaywrightTimeoutError:
        pass
    except Exception:
        pass

    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        pass

    if any(marker in body_text for marker in ("otp", "captcha", "recaptcha", "verify", "verification")):
        print(f"{target}: auto-login reached human verification. Manual action is still required.")
        return False

    print(f"{target}: auto-login submitted. Saving session after current page state.")
    return True


def save_session(
    target: str,
    output: str | None,
    wait_seconds: int,
    headless: bool,
    url: str | None,
    auto_login: bool = False,
) -> Path:
    config = SESSION_TARGETS[target]
    start_url = url or config["url"]
    output_path = Path(output or config["output"]).resolve()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)

        auto_login_done = attempt_auto_login(target, page) if auto_login else False
        if not auto_login_done:
            print()
            print(f"Opened {target}: {start_url}")
            print("Complete login in the browser window.")
            print("After login, press Enter here to save the browser session.")
            print(f"This command will also auto-save after {wait_seconds} seconds if you wait.")
            print()

            try:
                input("Press Enter after login: ")
            except EOFError:
                try:
                    page.wait_for_timeout(wait_seconds * 1000)
                except PlaywrightTimeoutError:
                    pass

        context.storage_state(path=str(output_path))
        browser.close()

    return output_path


def update_github_secret(target: str, output_path: Path, repo: str) -> None:
    secret_name = SESSION_TARGETS[target]["secret"]
    with output_path.open("rb") as session_file:
        subprocess.run(
            ["gh", "secret", "set", secret_name, "-R", repo],
            stdin=session_file,
            check=True,
        )
    print(f"Updated GitHub secret {secret_name} for {repo}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Save a logged-in browser session for job automation.")
    parser.add_argument(
        "target",
        choices=sorted(SESSION_TARGETS),
        help="Session target to generate.",
    )
    parser.add_argument(
        "--output",
        help="Output JSON path. Defaults to <target>_storage_state.json.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=300,
        help="Fallback wait time when stdin is not interactive.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless. Usually not useful for first-time login.",
    )
    parser.add_argument(
        "--url",
        help="Override login/start URL. Useful for tenant-specific Workday career sites.",
    )
    parser.add_argument(
        "--update-github-secret",
        action="store_true",
        help="After saving, update the matching GitHub Actions secret using gh.",
    )
    parser.add_argument(
        "--auto-login",
        action="store_true",
        help="Try to fill username/password from env vars before prompting.",
    )
    parser.add_argument(
        "--repo",
        default="venkat198910/job-scraper",
        help="GitHub repository for --update-github-secret.",
    )
    args = parser.parse_args()

    output_path = save_session(
        args.target,
        args.output,
        args.wait_seconds,
        args.headless,
        args.url,
        auto_login=args.auto_login,
    )
    print(f"Saved {args.target} session to: {output_path}")
    if args.update_github_secret:
        update_github_secret(args.target, output_path, args.repo)


if __name__ == "__main__":
    main()
