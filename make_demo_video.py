"""
make_demo_video.py — Records the screen while the automated demo plays.

Usage:
    python3 make_demo_video.py

Output:
    cloud_ops_demo.mp4  (in the same folder)

Requirements:
    - ffmpeg (brew install ffmpeg)
    - playwright (pip install playwright && playwright install chromium)
    - macOS Screen Recording permission granted to Terminal/iTerm
      (System Settings → Privacy & Security → Screen Recording → enable Terminal)
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

# ── Config ────────────────────────────────────────────────────────────────────
APP_URL      = "https://cloud-ops-streamlit-974082774877.us-central1.run.app"
BASE_DIR     = Path(__file__).parent
OUTPUT_FILE  = BASE_DIR / "cloud_ops_demo.mp4"
FFMPEG       = "/usr/local/bin/ffmpeg"
SCREEN_DEV   = "1"          # "Capture screen 0" = device index 1 on this machine
FRAMERATE    = 30
COUNTDOWN    = 6            # seconds before browser opens (lets ffmpeg warm up)

# ── Timing constants (seconds) ────────────────────────────────────────────────
PAUSE_SHORT  = 1.5
PAUSE_MEDIUM = 3.0
PAUSE_LONG   = 5.0
PAUSE_CARD   = 2.5


# ── Helpers ───────────────────────────────────────────────────────────────────
def slow_scroll(page: Page, distance: int = 1200, step: int = 350, delay: float = 0.45):
    scrolled = 0
    while scrolled < distance:
        page.mouse.wheel(0, step)
        scrolled += step
        time.sleep(delay)


def scroll_to_top(page: Page):
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(1.2)


def wait_for_streamlit(page: Page, timeout: int = 30000):
    try:
        page.wait_for_selector("div[data-testid='stAppViewContainer']", timeout=timeout)
        time.sleep(2)
    except Exception:
        time.sleep(4)


def click_sidebar_radio(page: Page, label: str):
    try:
        page.locator(f"label:has-text('{label}')").first.click()
        time.sleep(2)
        wait_for_streamlit(page)
    except Exception:
        print(f"  [warn] Could not click sidebar item: {label}")


def click_button(page: Page, label: str, timeout: int = 10000):
    try:
        btn = page.get_by_role("button", name=label).first
        btn.wait_for(state="visible", timeout=timeout)
        btn.scroll_into_view_if_needed()
        time.sleep(0.5)
        btn.click()
        time.sleep(2)
    except Exception:
        print(f"  [warn] Could not click button: {label}")


# ── Demo Walkthrough ──────────────────────────────────────────────────────────
def run_demo(page: Page):

    # Scene 1 — App loads
    print("  📍 Scene 1/10 — App loading...")
    page.goto(APP_URL, wait_until="domcontentloaded", timeout=60000)
    wait_for_streamlit(page)
    time.sleep(PAUSE_LONG)

    # Scene 2 — Load demo data
    print("  📍 Scene 2/10 — Loading demo data...")
    click_button(page, "🎯 Load Demo Data")
    wait_for_streamlit(page, timeout=20000)
    time.sleep(PAUSE_LONG)

    # Scene 3 — Overview metrics
    print("  📍 Scene 3/10 — Overview page...")
    scroll_to_top(page)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=600)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=500)
    time.sleep(PAUSE_LONG)
    scroll_to_top(page)
    time.sleep(PAUSE_SHORT)

    # Scene 4 — Phase 1: all findings
    print("  📍 Scene 4/10 — Phase 1: all findings...")
    click_sidebar_radio(page, "Phase 1")
    wait_for_streamlit(page)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=500)
    time.sleep(PAUSE_MEDIUM)
    scroll_to_top(page)

    # Scene 5 — Filter Critical
    print("  📍 Scene 5/10 — Critical findings...")
    try:
        sev_select = page.locator("div[data-testid='stMultiSelect']").first
        sev_select.scroll_into_view_if_needed()
        time.sleep(0.5)
        sev_input = sev_select.locator("input")
        sev_input.click()
        sev_input.fill("critical")
        time.sleep(0.5)
        page.locator("li[role='option']:has-text('critical')").first.click()
        page.keyboard.press("Escape")
        wait_for_streamlit(page)
    except Exception:
        print("  [warn] Severity filter not interacted")
    time.sleep(PAUSE_MEDIUM)
    slow_scroll(page, distance=450, step=180, delay=0.7)
    time.sleep(PAUSE_CARD)
    slow_scroll(page, distance=450, step=180, delay=0.7)
    time.sleep(PAUSE_CARD)
    slow_scroll(page, distance=450, step=180, delay=0.7)
    time.sleep(PAUSE_LONG)

    # Scene 6 — Filter High (cost findings)
    print("  📍 Scene 6/10 — High / cost findings...")
    scroll_to_top(page)
    try:
        remove_btns = page.locator("span[data-baseweb='tag'] span[role='presentation']")
        if remove_btns.count() > 0:
            remove_btns.first.click()
            time.sleep(0.5)
        sev_select = page.locator("div[data-testid='stMultiSelect']").first
        sev_input = sev_select.locator("input")
        sev_input.click()
        sev_input.fill("high")
        time.sleep(0.5)
        page.locator("li[role='option']:has-text('high')").first.click()
        page.keyboard.press("Escape")
        wait_for_streamlit(page)
    except Exception:
        print("  [warn] High filter not applied")
    time.sleep(PAUSE_MEDIUM)
    slow_scroll(page, distance=450, step=180, delay=0.7)
    time.sleep(PAUSE_CARD)
    slow_scroll(page, distance=450, step=180, delay=0.7)
    time.sleep(PAUSE_CARD)
    slow_scroll(page, distance=450, step=180, delay=0.7)
    time.sleep(PAUSE_LONG)

    # Scene 7 — Phase 2: Actions
    print("  📍 Scene 7/10 — Phase 2: Actions...")
    scroll_to_top(page)
    click_sidebar_radio(page, "Phase 2")
    wait_for_streamlit(page)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=550, step=180, delay=0.55)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=550, step=180, delay=0.55)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=600, step=180, delay=0.55)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=600, step=180, delay=0.55)
    time.sleep(PAUSE_LONG)

    # Scene 8 — Phase 3: Autonomous
    print("  📍 Scene 8/10 — Phase 3: Autonomous...")
    scroll_to_top(page)
    click_sidebar_radio(page, "Phase 3")
    wait_for_streamlit(page)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=500, step=200, delay=0.6)
    time.sleep(PAUSE_LONG)
    slow_scroll(page, distance=500, step=200, delay=0.6)
    time.sleep(PAUSE_LONG)

    # Scene 9 — Project switcher
    print("  📍 Scene 9/10 — Project switcher / credential upload...")
    scroll_to_top(page)
    click_sidebar_radio(page, "Overview")
    wait_for_streamlit(page)
    time.sleep(PAUSE_SHORT)
    try:
        switcher = page.locator("details summary:has-text('Switch GCP Project')").first
        switcher.scroll_into_view_if_needed()
        switcher.click()
        time.sleep(PAUSE_LONG)
    except Exception:
        print("  [warn] Could not open project switcher")
    time.sleep(PAUSE_LONG)

    # Scene 10 — Final Overview shot
    print("  📍 Scene 10/10 — Final shot...")
    scroll_to_top(page)
    time.sleep(PAUSE_LONG)
    time.sleep(PAUSE_LONG)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()

    print("\n🎬  Cloud Ops AI — Demo Video Recorder")
    print("=" * 50)

    # Start ffmpeg screen recording
    ffmpeg_cmd = [
        FFMPEG,
        "-y",                              # overwrite output
        "-f", "avfoundation",
        "-framerate", str(FRAMERATE),
        "-capture_cursor", "1",            # show mouse cursor
        "-i", f"{SCREEN_DEV}",             # screen device
        "-vf", "scale=1440:-2",            # normalise width
        "-vcodec", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-crf", "18",                      # high quality
        str(OUTPUT_FILE),
    ]

    print("\n▶  Starting screen recording...")
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)  # let ffmpeg warm up

    if ffmpeg_proc.poll() is not None:
        print("\n❌  ffmpeg failed to start.")
        print("    Make sure Terminal has Screen Recording permission:")
        print("    System Settings → Privacy & Security → Screen Recording → enable Terminal\n")
        sys.exit(1)

    print(f"✅  Recording started (PID {ffmpeg_proc.pid})")
    print(f"\n⏳  Browser opens in {COUNTDOWN} seconds...")
    print("    ⚠️  VS Code and all other windows will be hidden automatically.\n")
    for i in range(COUNTDOWN, 0, -1):
        print(f"    {i}...")
        time.sleep(1)

    # Hide every app except Terminal/iTerm so only the browser is visible
    hide_script = """
    tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
        repeat with p in (every application process whose visible is true)
            if name of p is not frontApp then
                set visible of p to false
            end if
        end repeat
    end tell
    """
    subprocess.run(["osascript", "-e", hide_script], capture_output=True)

    # Run the Playwright demo
    try:
        with sync_playwright() as p:
            print("\n  Opening browser...\n")
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--start-maximized",
                    "--kiosk",                      # fullscreen, no browser chrome
                    "--disable-infobars",
                    "--disable-notifications",
                    "--noerrdialogs",
                ],
                slow_mo=55,
            )
            context = browser.new_context(
                viewport=None,                      # use actual screen size
                no_viewport=True,
            )
            page = context.new_page()
            run_demo(page)
            context.close()
            browser.close()

    except Exception as e:
        print(f"\n❌  Demo error: {e}")
    finally:
        # Stop ffmpeg gracefully
        print("\n⏹  Stopping recording...")
        try:
            ffmpeg_proc.stdin.write(b"q")
            ffmpeg_proc.stdin.flush()
        except Exception:
            pass
        try:
            ffmpeg_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ffmpeg_proc.send_signal(signal.SIGTERM)
            time.sleep(2)

    if OUTPUT_FILE.exists() and OUTPUT_FILE.stat().st_size > 100_000:
        size_mb = OUTPUT_FILE.stat().st_size / 1_048_576
        print(f"\n✅  Video saved: {OUTPUT_FILE}")
        print(f"   Size: {size_mb:.1f} MB")
        print("\n💡  Next steps:")
        print("   1. Open in QuickTime to preview")
        print("   2. Trim start/end if needed (QuickTime → Edit → Trim)")
        print("   3. Add music/voiceover in iMovie or CapCut")
        print("   4. Export and post to LinkedIn\n")
        # Auto-open in QuickTime
        subprocess.Popen(["open", str(OUTPUT_FILE)])
    else:
        print("\n⚠️   Output file is missing or too small.")
        print("   If you see a black video, grant Screen Recording permission to Terminal:")
        print("   System Settings → Privacy & Security → Screen Recording → enable Terminal\n")


if __name__ == "__main__":
    main()
