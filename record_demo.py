"""
record_demo.py — Automated browser walkthrough for Cloud Ops AI demo video.

HOW TO USE:
  1. Start macOS screen recording:  Cmd + Shift + 5  → "Record Entire Screen"
  2. In a terminal run:  python3 record_demo.py
  3. The browser will open and navigate through the full demo automatically
  4. Stop the screen recording when the browser closes
  5. Optionally add a voiceover or music in iMovie / CapCut

The script opens a large browser window, loads demo data, and walks through
all 3 phases with smooth scrolling, hover highlights, and timed pauses so
every section is readable on camera.
"""

import time
from playwright.sync_api import sync_playwright, Page

APP_URL = "https://cloud-ops-streamlit-974082774877.us-central1.run.app"

# ── Timing constants (seconds) ────────────────────────────────────────────────
PAUSE_SHORT   = 1.5   # brief pause between actions
PAUSE_MEDIUM  = 3.0   # reading pause
PAUSE_LONG    = 5.0   # section pause — let viewer absorb the screen
PAUSE_CARD    = 2.5   # pause per finding card
SCROLL_STEP   = 400   # pixels per scroll


def slow_scroll(page: Page, distance: int = 1200, step: int = SCROLL_STEP, delay: float = 0.4):
    """Scroll smoothly down by `distance` pixels."""
    scrolled = 0
    while scrolled < distance:
        page.mouse.wheel(0, step)
        scrolled += step
        time.sleep(delay)


def scroll_to_top(page: Page):
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(1)


def wait_for_streamlit(page: Page, timeout: int = 30000):
    """Wait until Streamlit finishes loading (spinner disappears)."""
    try:
        page.wait_for_selector("div[data-testid='stAppViewContainer']", timeout=timeout)
        time.sleep(2)
    except Exception:
        time.sleep(4)


def click_sidebar_radio(page: Page, label: str):
    """Click a sidebar radio button by visible label text."""
    try:
        page.locator(f"label:has-text('{label}')").first.click()
        time.sleep(2)
        wait_for_streamlit(page)
    except Exception:
        print(f"  [warn] Could not click sidebar item: {label}")


def click_button(page: Page, label: str, timeout: int = 8000):
    """Click a button by visible text."""
    try:
        btn = page.get_by_role("button", name=label).first
        btn.wait_for(state="visible", timeout=timeout)
        btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        btn.click()
        time.sleep(2)
    except Exception:
        print(f"  [warn] Could not click button: {label}")


def highlight_element(page: Page, selector: str):
    """Briefly highlight an element with a yellow border for visual emphasis."""
    try:
        page.evaluate(f"""
            var el = document.querySelector('{selector}');
            if (el) {{
                el.style.outline = '3px solid #FFD700';
                el.style.outlineOffset = '4px';
                setTimeout(() => {{ el.style.outline = ''; el.style.outlineOffset = ''; }}, 2000);
            }}
        """)
        time.sleep(2)
    except Exception:
        pass


def run_demo():
    with sync_playwright() as p:
        print("\n🎬  Cloud Ops AI — Demo Recording")
        print("=" * 50)
        print("  Starting browser...")

        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--disable-infobars"],
            slow_mo=60,
        )

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
        )
        page = context.new_page()

        # ── SCENE 1: Landing ──────────────────────────────────────────────────
        print("\n📍 Scene 1 — Loading the app...")
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
        wait_for_streamlit(page)
        time.sleep(PAUSE_LONG)

        # ── SCENE 2: Load Demo Data ───────────────────────────────────────────
        print("📍 Scene 2 — Loading demo data...")
        click_button(page, "🎯 Load Demo Data")
        wait_for_streamlit(page, timeout=20000)
        time.sleep(PAUSE_LONG)

        # ── SCENE 3: Overview Page ────────────────────────────────────────────
        print("📍 Scene 3 — Overview page...")
        scroll_to_top(page)
        time.sleep(PAUSE_MEDIUM)

        # Let the overview metrics sink in
        time.sleep(PAUSE_LONG)

        # Scroll down to see the severity breakdown and agent breakdown
        slow_scroll(page, distance=600)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=600)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=400)
        time.sleep(PAUSE_MEDIUM)

        # ── SCENE 4: Phase 1 — Scan (All findings) ───────────────────────────
        print("📍 Scene 4 — Phase 1 Scan page (all findings)...")
        scroll_to_top(page)
        click_sidebar_radio(page, "Phase 1")
        wait_for_streamlit(page)
        time.sleep(PAUSE_LONG)

        # Show all findings briefly
        slow_scroll(page, distance=500)
        time.sleep(PAUSE_MEDIUM)
        scroll_to_top(page)

        # ── SCENE 5: Filter to Critical ──────────────────────────────────────
        print("📍 Scene 5 — Filter to Critical findings...")
        try:
            # Click the severity multiselect and pick Critical
            sev_select = page.locator("div[data-testid='stMultiSelect']").first
            sev_select.scroll_into_view_if_needed()
            time.sleep(PAUSE_SHORT)

            # Clear existing selections and type Critical
            sev_input = sev_select.locator("input")
            sev_input.click()
            time.sleep(0.5)
            sev_input.fill("critical")
            time.sleep(0.5)
            page.locator("li[role='option']:has-text('critical')").first.click()
            time.sleep(PAUSE_SHORT)
            # Close the dropdown
            page.keyboard.press("Escape")
            wait_for_streamlit(page)
        except Exception:
            print("  [warn] Could not interact with severity filter")

        time.sleep(PAUSE_MEDIUM)

        # Scroll through critical findings slowly — let each one be read
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_CARD)
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_CARD)
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_CARD)
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_LONG)

        # ── SCENE 6: Filter to High — show cost findings ──────────────────────
        print("📍 Scene 6 — Filter to High findings...")
        scroll_to_top(page)
        try:
            sev_select = page.locator("div[data-testid='stMultiSelect']").first
            sev_select.scroll_into_view_if_needed()
            sev_input = sev_select.locator("input")

            # Remove critical tag first
            page.locator("span[data-baseweb='tag']").first.locator("span[role='presentation']").click()
            time.sleep(0.5)

            sev_input.click()
            sev_input.fill("high")
            time.sleep(0.5)
            page.locator("li[role='option']:has-text('high')").first.click()
            page.keyboard.press("Escape")
            wait_for_streamlit(page)
        except Exception:
            print("  [warn] Could not switch to high filter")

        time.sleep(PAUSE_MEDIUM)
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_CARD)
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_CARD)
        slow_scroll(page, distance=400, step=200, delay=0.6)
        time.sleep(PAUSE_LONG)

        # ── SCENE 7: Phase 2 — Actions ────────────────────────────────────────
        print("📍 Scene 7 — Phase 2 Actions page...")
        scroll_to_top(page)
        click_sidebar_radio(page, "Phase 2")
        wait_for_streamlit(page)
        time.sleep(PAUSE_LONG)

        # Scroll through executed actions (show success outcomes)
        slow_scroll(page, distance=500, step=200, delay=0.5)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=500, step=200, delay=0.5)
        time.sleep(PAUSE_LONG)

        # Continue scrolling to approved, pending, skipped
        slow_scroll(page, distance=600, step=200, delay=0.5)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=600, step=200, delay=0.5)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=400, step=200, delay=0.5)
        time.sleep(PAUSE_MEDIUM)

        # ── SCENE 8: Phase 3 — Autonomous ────────────────────────────────────
        print("📍 Scene 8 — Phase 3 Autonomous page...")
        scroll_to_top(page)
        click_sidebar_radio(page, "Phase 3")
        wait_for_streamlit(page)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=500, step=200, delay=0.6)
        time.sleep(PAUSE_LONG)

        slow_scroll(page, distance=500, step=200, delay=0.6)
        time.sleep(PAUSE_LONG)

        # ── SCENE 9: Switch GCP Project (show multi-customer capability) ─────
        print("📍 Scene 9 — Show project switcher / credential upload...")
        scroll_to_top(page)
        click_sidebar_radio(page, "Overview")
        wait_for_streamlit(page)
        time.sleep(PAUSE_SHORT)

        try:
            switcher = page.locator("details summary:has-text('Switch GCP Project')").first
            switcher.scroll_into_view_if_needed()
            switcher.click()
            time.sleep(PAUSE_MEDIUM)
            # Show the expander content — let it be readable
            time.sleep(PAUSE_LONG)
        except Exception:
            print("  [warn] Could not open project switcher expander")

        time.sleep(PAUSE_LONG)

        # ── SCENE 10: Return to Overview — final shot ─────────────────────────
        print("📍 Scene 10 — Final shot on Overview...")
        scroll_to_top(page)
        time.sleep(PAUSE_LONG)
        time.sleep(PAUSE_LONG)

        print("\n✅  Demo walkthrough complete.")
        print("   Stop your screen recording now (Cmd + Shift + 5 → Stop).")
        print("   The browser will close in 10 seconds...\n")
        time.sleep(10)

        context.close()
        browser.close()


if __name__ == "__main__":
    run_demo()
