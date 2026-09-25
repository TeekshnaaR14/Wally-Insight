"""
Script to take full-page screenshots of the Wally web app in all combinations:
- 4 pages: login, dashboards (index), transactions, settings
- 2 themes: light, dark
- 2 viewports: desktop (1280x800), mobile (390x844)
All authenticated pages are captured while logged in.

Usage:
  python3 utils/take_screenshots.py [--password PASSWORD]
"""

import time
import argparse
import requests
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost"
ASSETS_DIR = "assets"

DESKTOP_VIEWPORT = {"width": 1280, "height": 800}
MOBILE_VIEWPORT = {"width": 390, "height": 844}

PAGES = [
    {"name": "login", "path": "/login"},
    {"name": "dashboards", "path": "/"},
    {"name": "transactions", "path": "/transactions"},
    {"name": "settings", "path": "/settings"},
]

THEMES = ["light", "dark"]


def enable_login_and_get_cookie(password):
    """Enable login with given password and return the auth cookie."""
    session = requests.Session()

    # Enable login by setting the password
    session.post(f"{BASE_URL}/api/login/password", json={"password": password})

    # Now log in to get the access_token cookie
    resp = session.post(f"{BASE_URL}/api/login", json={"password": password})
    if resp.status_code != 200:
        raise Exception(f"Login failed: {resp.status_code} {resp.text}")

    cookie = session.cookies.get("access_token")
    if not cookie:
        raise Exception("No access_token cookie received after login")

    print(f"Logged in successfully. Cookie obtained.")
    return cookie


def disable_login():
    """Disable login page after screenshots are done."""
    requests.post(f"{BASE_URL}/api/login/password", json={"password": None})
    print("Login page disabled (restored to original state).")


def wait_for_page_ready(page, page_name):
    """Wait for the page to be fully loaded and rendered."""
    page.wait_for_load_state("networkidle")

    # Wait for i18n to show the page (body gets opacity: 1)
    page.wait_for_function("document.body.classList.contains('i18n-loaded')", timeout=10000)

    if page_name == "dashboards":
        # Wait for the chart canvas to be present
        try:
            page.wait_for_selector("canvas", timeout=10000)
        except Exception:
            pass

        # Disable Chart.js animations and force a re-render for a clean capture
        page.evaluate("""() => {
            if (typeof Chart !== 'undefined') {
                Chart.defaults.animation = false;
                Chart.defaults.animations = {};
                Chart.defaults.transitions = { active: { animation: { duration: 0 } } };
            }
        }""")

        # Trigger a chart resize to ensure it renders at the correct dimensions
        page.evaluate("""() => {
            if (typeof chart !== 'undefined' && chart) {
                chart.options.animation = false;
                chart.resize();
                chart.update('none');
            }
        }""")

        # Give the chart a moment to fully re-render
        time.sleep(2)

    elif page_name == "transactions":
        try:
            page.wait_for_selector(".ag-root-wrapper", timeout=10000)
        except Exception:
            pass
        time.sleep(1.5)

    elif page_name == "settings":
        try:
            page.wait_for_selector(".ag-root-wrapper", timeout=10000)
        except Exception:
            pass
        time.sleep(1.5)

    elif page_name == "login":
        time.sleep(1)

    # Extra settle time
    time.sleep(0.5)


def take_screenshots(password):
    # Step 1: Enable login and authenticate
    auth_cookie = enable_login_and_get_cookie(password)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for page_info in PAGES:
                for theme in THEMES:
                    for viewport, suffix in [(DESKTOP_VIEWPORT, ""), (MOBILE_VIEWPORT, "-mobile")]:
                        filename = f"{page_info['name']}-{theme}{suffix}.png"
                        filepath = f"{ASSETS_DIR}/{filename}"

                        print(f"Taking screenshot: {filename} ...", end=" ", flush=True)

                        context = browser.new_context(
                            viewport=viewport,
                            device_scale_factor=2,
                            color_scheme=theme,
                        )

                        # Add auth cookie to the context
                        context.add_cookies([{
                            "name": "access_token",
                            "value": auth_cookie,
                            "domain": "localhost",
                            "path": "/",
                        }])

                        page = context.new_page()

                        if page_info["name"] == "login":
                            # Block the /api/login/check so the login page doesn't
                            # redirect us away (since we're authenticated)
                            page.route("**/api/login/check", lambda route: route.fulfill(
                                status=401,
                                content_type="application/json",
                                body="false",
                            ))

                        # Set theme via init script so it's applied before page renders
                        page.add_init_script(f"""
                            localStorage.setItem('theme', '{theme}');
                            document.documentElement.setAttribute('data-bs-theme', '{theme}');
                        """)

                        # For dashboards, disable Chart.js animations before chart loads
                        if page_info["name"] == "dashboards":
                            page.add_init_script("""
                                Object.defineProperty(window, '__chartAnimOff__', { value: true });
                                const origDefineProperty = Object.defineProperty;
                                let chartPatched = false;
                                // Patch Chart defaults as soon as Chart.js is loaded
                                const interval = setInterval(() => {
                                    if (typeof Chart !== 'undefined' && !chartPatched) {
                                        Chart.defaults.animation = false;
                                        Chart.defaults.animations = {};
                                        chartPatched = true;
                                        clearInterval(interval);
                                    }
                                }, 50);
                            """)

                        # Navigate to the page
                        url = f"{BASE_URL}{page_info['path']}"
                        page.goto(url, wait_until="domcontentloaded")

                        # Wait for everything to render
                        wait_for_page_ready(page, page_info["name"])

                        # Take full-page screenshot
                        page.screenshot(path=filepath, full_page=True)

                        print("done")

                        context.close()

            browser.close()
    finally:
        # Always restore: disable login
        disable_login()

    print("\nAll screenshots generated successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Take Wally screenshots")
    parser.add_argument("--password", default="123", help="Login password (default: 123)")
    args = parser.parse_args()

    take_screenshots(args.password)
