"""One-time interactive login. Opens a headed browser, you complete SSO,
then presses Enter in the terminal to persist storage_state.json."""
import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from paths import STORAGE_STATE

load_dotenv()
BASE_URL = os.environ.get("HAYSTACK_BASE_URL", "https://your-org.haystack.so")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{BASE_URL}/dashboard")
        print(f"Complete SSO in the browser, land on the dashboard, then press Enter here.")
        input()
        context.storage_state(path=str(STORAGE_STATE))
        print(f"Saved session to {STORAGE_STATE}")
        browser.close()


if __name__ == "__main__":
    main()
