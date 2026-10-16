"""Browser smoke test: starts the real server on a throw-away database, drives the UI with headless Chromium,
and exits non-zero on any failure.

    pip install playwright && playwright install chromium
    python e2e/browser_smoke.py
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.environ.get("PORT", "8799"))
URL = f"http://127.0.0.1:{PORT}/"


def wait_ready():
    for _ in range(60):
        try:
            urllib.request.urlopen(URL + "api/health", timeout=1)
            return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("server did not start")


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        raise SystemExit(1)


def main():
    tmp = tempfile.mkdtemp()
    env = dict(os.environ, LIVINGDOC_DB=f"{tmp}/a.db", LIVINGDOC_HUB=f"{tmp}/h.db", LIVINGDOC_SCANNER_INBOX=f"{tmp}/in", LLM_TIMEOUT="2", LIVINGDOC_FORESIGHT_LIVE="0", LIVINGDOC_WORKERS="0")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)], cwd=ROOT / "backend", env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    errors = []
    try:
        wait_ready()
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1360, "height": 1000})
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.goto(URL)
            pg.wait_for_selector("#doc table", timeout=15000)
            check(pg.locator("tbody tr[data-item]").count() >= 8, "inventory table renders seeded items")

            pg.fill("#note-text", "Sold 4 milks, used 2 coffee beans, Dave paid Rs 500 cash, reminded me to order beans")
            pg.click("#note-submit")
            pg.wait_for_selector("#note-result .result", timeout=15000)
            check("Milk" in pg.inner_text("#note-result"), "note is applied and the result is shown")
            check(pg.locator("#doc >> text=order beans").count() > 0, "promise appears on the page")

            pg.click("summary:has-text('Simulate')")
            pg.select_option("#scan-item", "Ghee"); pg.fill("#scan-qty", "3"); pg.select_option("#scan-dir", "out")
            pg.click("#scan-btn")
            pg.wait_for_selector("#move-feed li:has-text('Ghee')", timeout=8000)
            check(True, "scanner event shows up in the movement feed")

            pg.click("button[lang=hi]"); pg.wait_for_selector("h2:has-text('मौजूदा स्टॉक')", timeout=8000)
            pg.click("button[lang=gu]"); pg.wait_for_selector("h2:has-text('હાલનો સ્ટોક')", timeout=8000)
            check(True, "Hindi and Gujarati switch the whole page")
            pg.click("button[lang=en]")

            pg.click("#settings-btn"); pg.wait_for_selector("#settings-dialog[open]")
            pg.fill("#fe-name", "Holi"); pg.fill("#fe-date", "2027-03-04"); pg.click("#fe-add")
            pg.wait_for_selector("#settings-dialog td:has-text('Holi')")
            check(True, "festival can be added from settings")
            pg.keyboard.press("Escape")

            pg.fill("#note-text", "Remind me to call <img src=x onerror=window.__xss=1> now")
            pg.click("#note-submit"); pg.wait_for_timeout(1500)
            check(pg.evaluate("window.__xss !== 1"), "markup in notes is shown as text, never executed")

            # ---- Forecast & Pricing ----
            pg.wait_for_selector("#fp-section svg.chart", timeout=30000)
            check(pg.locator("#fp-assumed").inner_text().strip() != "" and "assumed" in pg.inner_text("#fp-meta"), "forecast chart renders and assumptions are labelled")
            pg.click("#fp-tab-pricing"); pg.wait_for_selector("#fp-price-table tbody tr", timeout=30000)
            check(pg.locator("#fp-price-table tr[data-product='Flour']").get_attribute("data-label") != "SURGE", "essentials are never surged")
            check(pg.locator("#fp-prices-assumed").count() == 1, "placeholder prices are flagged on the pricing tab")
            pg.click("#fp-tab-owner"); pg.wait_for_selector("#fp-log-form", timeout=30000)
            pg.click("button:has-text('Load 21 simulated days')"); pg.wait_for_selector("#fp-demo-banner", timeout=60000)
            pg.click("#fp-tab-score"); pg.wait_for_selector("#fp-verdict li", timeout=30000)
            check(pg.locator("#fp-demo-banner").count() == 1, "demo mode is clearly labelled and the scorecard fills up")
            pg.click("#fp-demo-banner button"); pg.wait_for_selector("#fp-demo-banner", state="detached", timeout=60000)
            pg.click("#fp-tab-owner"); pg.wait_for_selector("#fp-factor-form", timeout=30000)
            soon = (date.today() + timedelta(days=3)).isoformat()
            pg.fill("#fp-f-name", "Wedding next door"); pg.fill("#fp-f-from", soon); pg.fill("#fp-f-to", soon); pg.fill("#fp-f-effect", "40")
            pg.click("#fp-factor-form button[type=submit]"); pg.wait_for_selector("#fp-factors tr[data-factor='Wedding next door']", timeout=60000)
            pg.fill("#fp-a-orders", "150"); pg.click("#fp-log-form button[type=submit]")
            pg.wait_for_selector("#fp-actuals tbody tr", timeout=60000)
            check(True, "owner can add a factor and log an actual day")
            pg.click("#fp-tab-setup"); pg.wait_for_selector("#fp-products tbody tr", timeout=30000)
            check(pg.locator("#fp-festivals tbody tr").count() >= 5, "festival calendar is editable in Setup")
            pg.click("button[lang=hi]"); pg.wait_for_selector("#fp-tab-forecast:has-text('पूर्वानुमान')", timeout=30000)
            pg.click("button[lang=gu]"); pg.wait_for_selector("#fp-tab-forecast:has-text('અનુમાન')", timeout=30000)
            check(True, "Forecast & Pricing is translated into Hindi and Gujarati")
            pg.click("button[lang=en]"); pg.wait_for_selector("#fp-tab-forecast:has-text('Forecast')", timeout=30000)
            pg.click("#fp-tab-forecast"); pg.wait_for_selector("#fp-section svg.chart", timeout=30000)

            pg.set_viewport_size({"width": 390, "height": 900}); pg.wait_for_timeout(300)
            check(not pg.evaluate("document.documentElement.scrollWidth > window.innerWidth"), "no horizontal scrolling on a phone-sized screen")
            b.close()
        check(not errors, f"no console or page errors {errors}")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
