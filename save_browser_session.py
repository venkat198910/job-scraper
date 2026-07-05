import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


SESSION_TARGETS = {
    "linkedin": {
        "url": "https://www.linkedin.com/login",
        "output": "linkedin_storage_state.json",
    },
    "workday": {
        "url": "https://www.myworkday.com/",
        "output": "workday_storage_state.json",
    },
    "naukri": {
        "url": "https://www.naukri.com/mnjuser/homepage",
        "output": "naukri_storage_state.json",
    },
    "naukri_gulf": {
        "url": "https://www.naukrigulf.com/mnjuser/homepage",
        "output": "naukri_gulf_storage_state.json",
    },
}


def save_session(target: str, output: str | None, wait_seconds: int, headless: bool, url: str | None) -> Path:
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
    args = parser.parse_args()

    output_path = save_session(args.target, args.output, args.wait_seconds, args.headless, args.url)
    print(f"Saved {args.target} session to: {output_path}")


if __name__ == "__main__":
    main()
