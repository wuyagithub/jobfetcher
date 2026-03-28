"""
LinkedIn Cookie Manager — export / load / validate browser sessions.

Usage:
    python cookie_manager.py --export          # Export current browser cookies to JSON
    python cookie_manager.py --validate        # Validate stored cookies
    python cookie_manager.py --load             # Test load cookies into new context

The exported cookie file is stored at data/linkedin_cookies.json
and is automatically used by scrape_all_jobs.py in headless mode.

NOTE: You must be logged into LinkedIn in the browser first.
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

COOKIE_FILE = Path(__file__).parent / "data" / "linkedin_cookies.json"
LINKEDIN_BASE = "https://www.linkedin.com"

# Essential cookies needed for LinkedIn auth
ESSENTIAL_COOKIES = ["li_at", "csrfToken", "JSESSIONID"]


# ── Export ────────────────────────────────────────────────────────────────────


def export_from_browser():
    """Export cookies from an active Playwright browser session.

    This opens a visible browser — you must be logged into LinkedIn.
    The browser will stay open for 10 seconds to allow manual login
    if not already authenticated.
    """
    import asyncio
    from playwright.async_api import async_playwright

    print("[Cookie Manager] Opening browser for cookie export...")
    print("[Cookie Manager] Please ensure you are logged into LinkedIn")

    async def _capture():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                channel="chrome",
            )
            context = await browser.new_context()
            page = await context.new_page()

            # Navigate to LinkedIn home to trigger auth
            await page.goto(LINKEDIN_BASE, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(5000)

            # Check if logged in
            title = await page.title()
            if "Feed" not in title and "LinkedIn" not in title:
                print("[Cookie Manager] WARNING: May not be logged in. Please log in manually.")
                await page.wait_for_timeout(10000)

            # Get all cookies
            cookies = await context.cookies()

            # Filter to only LinkedIn domains
            linkedin_cookies = [c for c in cookies if "linkedin" in c.get("domain", "")]

            await browser.close()
            return linkedin_cookies

    cookies = asyncio.run(_capture())

    if not cookies:
        print("[Cookie Manager] ERROR: No cookies captured. Are you logged into LinkedIn?")
        sys.exit(1)

    # Check for essential cookies
    cookie_names = {c["name"] for c in cookies}
    missing = [n for n in ESSENTIAL_COOKIES if n not in cookie_names]
    if missing:
        print(f"[Cookie Manager] WARNING: Missing recommended cookies: {missing}")

    # Save to file
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)

    print(f"[Cookie Manager] Exported {len(cookies)} cookies to {COOKIE_FILE}")
    print(f"  Cookie names: {sorted(cookie_names)}")

    if "li_at" in cookie_names:
        print("[Cookie Manager] SUCCESS: li_at token found — auth should work")


# ── Validate ─────────────────────────────────────────────────────────────────


def validate_cookies():
    """Validate stored cookies by checking LinkedIn feed access."""
    if not COOKIE_FILE.exists():
        print(f"[Cookie Manager] Cookie file not found: {COOKIE_FILE}")
        print("  Run: python cookie_manager.py --export")
        return False

    with open(COOKIE_FILE, encoding="utf-8") as f:
        cookies = json.load(f)

    cookie_dict = {c["name"]: c["value"] for c in cookies}

    # Check essential
    missing = [n for n in ESSENTIAL_COOKIES if n not in cookie_dict]
    if missing:
        print(f"[Cookie Manager] MISSING essential cookies: {missing}")
        return False

    # Test with httpx
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "csrfToken": cookie_dict.get("csrfToken", ""),
    }

    try:
        response = httpx.get(
            f"{LINKEDIN_BASE}/feed",
            cookies=cookies,
            headers=headers,
            timeout=15,
            follow_redirects=True,
        )

        if response.status_code == 200:
            print("[Cookie Manager] VALID: Cookies are working")
            return True
        elif response.status_code == 401:
            print("[Cookie Manager] EXPIRED: Cookies are no longer valid")
            return False
        else:
            print(f"[Cookie Manager] Status {response.status_code}: {response.url}")
            return False

    except httpx.RequestError as e:
        print(f"[Cookie Manager] Request error: {e}")
        return False


# ── Load / Test ──────────────────────────────────────────────────────────────


def load_cookies_test():
    """Test loading cookies into a new Playwright context."""
    if not COOKIE_FILE.exists():
        print(f"[Cookie Manager] Cookie file not found: {COOKIE_FILE}")
        return False

    import asyncio
    from playwright.async_api import async_playwright

    with open(COOKIE_FILE, encoding="utf-8") as f:
        cookies = json.load(f)

    async def _test():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.add_cookies(cookies)

            page = await context.new_page()
            await page.goto(f"{LINKEDIN_BASE}/feed", wait_until="domcontentloaded", timeout=20000)

            title = await page.title()
            await browser.close()

            if "Feed" in title or "LinkedIn" in title:
                print(f"[Cookie Manager] SUCCESS: Loaded cookies, page title: {title}")
                return True
            else:
                print(f"[Cookie Manager] WARNING: Page title unexpected: {title}")
                return False

    try:
        return asyncio.run(_test())
    except Exception as e:
        print(f"[Cookie Manager] ERROR: {e}")
        return False


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="LinkedIn Cookie Manager")
    parser.add_argument("--export", action="store_true", help="Export cookies from browser")
    parser.add_argument("--validate", action="store_true", help="Validate stored cookies")
    parser.add_argument("--load", action="store_true", help="Test loading cookies in Playwright")
    args = parser.parse_args()

    if args.export:
        export_from_browser()
    elif args.validate:
        validate_cookies()
    elif args.load:
        load_cookies_test()
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python cookie_manager.py --export    # First-time setup")
        print("  python cookie_manager.py --validate # Check if still valid")
        print("  python cookie_manager.py --load       # Test Playwright session")


if __name__ == "__main__":
    main()
