#!/usr/bin/env python3
"""
Watchable end-to-end UI tests (Playwright, headed Chrome).

Opens a real Chrome window and drives the app the way a user would, moving the
mouse and drawing a red ring where it clicks, with a caption of each step, so you
can SEE it run on this machine. Covers: landing page, nav, library search +
filters + sort, job expand, Run Center command building, dashboard, builder.

Prereqs:
  - The app running:  python -m jobsdb.app     (http://localhost:5000)
  - Playwright:       pip install playwright && python -m playwright install chromium

Run:
  python tests/ui_e2e.py                 # headed, slow, visible clicks
  BASE_URL=http://localhost:5000 python tests/ui_e2e.py
  HEADLESS=1 python tests/ui_e2e.py      # no window (CI)
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("BASE_URL", "http://localhost:5000")
HEADLESS = os.environ.get("HEADLESS") == "1"
SLOWMO = int(os.environ.get("SLOWMO", "550"))

# Injected on every page: a red click-ring + a step caption banner.
OVERLAY_JS = r"""
window.__mark = function(x, y){
  let d = document.getElementById('__e2e_ring');
  if(!d){ d = document.createElement('div'); d.id='__e2e_ring';
          document.body.appendChild(d); }
  d.style.cssText = 'position:fixed;left:'+(x-20)+'px;top:'+(y-20)+'px;width:40px;'+
    'height:40px;border:3px solid #ff3b6b;border-radius:50%;z-index:2147483647;'+
    'pointer-events:none;box-shadow:0 0 0 4px rgba(255,59,107,.30);';
  d.animate([{transform:'scale(1.7)',opacity:1},{transform:'scale(1)',opacity:.85}],
    {duration:350});
};
window.__step = function(t){
  let b = document.getElementById('__e2e_step');
  if(!b){ b = document.createElement('div'); b.id='__e2e_step';
          document.body.appendChild(b); }
  b.style.cssText = 'position:fixed;left:50%;top:14px;transform:translateX(-50%);'+
    'z-index:2147483647;background:#111a26;color:#e8ecf3;border:1px solid #4fb3bf;'+
    'padding:8px 16px;border-radius:20px;font:600 13px/1 Segoe UI,system-ui;'+
    'pointer-events:none;box-shadow:0 6px 20px rgba(0,0,0,.4)';
  b.textContent = t;
};
"""

results = []


def check(name, ok, detail=""):
    results.append(ok)
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f"  ({detail})" if detail else ""))


def step(page, text):
    page.evaluate("(t)=>window.__step(t)", text)
    print(f"\n> {text}")
    time.sleep(0.4)


def click(page, selector, note=None):
    """Move the mouse to the element, ring it, then click — all visible."""
    el = page.locator(selector).first
    el.scroll_into_view_if_needed()
    box = el.bounding_box()
    if not box:
        check(f"click {selector}", False, "not visible")
        return
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(cx, cy, steps=18)
    page.evaluate("([x,y])=>window.__mark(x,y)", [cx, cy])
    time.sleep(0.45)
    el.click()
    time.sleep(0.6)


def run():
    with sync_playwright() as p:
        # Prefer real Chrome; fall back to bundled Chromium.
        try:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO,
                                        channel="chrome", args=["--start-maximized"])
        except Exception:
            browser = p.chromium.launch(headless=HEADLESS, slow_mo=SLOWMO,
                                        args=["--start-maximized"])
        ctx = browser.new_context(no_viewport=True)
        ctx.add_init_script(OVERLAY_JS)
        page = ctx.new_page()

        # 1. Landing page
        step(page, "1. Open the landing page")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(800)
        check("home: title is Job Command Center", "Job Command Center" in page.title() or
              page.locator("h1", has_text="Job Command Center").count() > 0)
        check("home: stat tiles loaded", page.locator(".stat").count() >= 3)
        check("home: no aeroplane/emoji brand", "Job Command Center" ==
              page.locator("nav .brand").inner_text().strip())

        # 2. Nav to Library
        step(page, "2. Navigate to the Library")
        click(page, "nav a[href='/library']")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".job", timeout=8000)
        n_all = page.locator(".job").count()
        check("library: shows job rows", n_all > 0, f"{n_all} rows")

        # 3. Search
        step(page, "3. Search for 'engineer'")
        page.fill("#q", "engineer")
        page.wait_for_timeout(1200)
        check("library: search returns results", page.locator(".job").count() > 0,
              f"{page.locator('.job').count()} rows")
        page.fill("#q", "")
        page.wait_for_timeout(900)

        # 4. Competitor filter
        step(page, "4. Filter to competitors only")
        click(page, ".chip.comp")
        page.wait_for_timeout(1000)
        check("library: competitor filter active",
              "on" in (page.locator(".chip.comp").get_attribute("class") or ""))
        check("library: competitor rows shown", page.locator(".job").count() > 0,
              f"{page.locator('.job').count()} rows")
        click(page, ".chip.comp")   # toggle off
        page.wait_for_timeout(700)

        # 5. New filter
        step(page, "5. Toggle the 'New' filter")
        click(page, ".chip.new")
        page.wait_for_timeout(800)
        check("library: new filter active",
              "on" in (page.locator(".chip.new").get_attribute("class") or ""))
        click(page, ".chip.new")
        page.wait_for_timeout(600)

        # 6. Sort by score
        step(page, "6. Sort by AI score")
        click(page, "#sortscore")
        page.wait_for_timeout(900)
        check("library: sort-by-score toggled",
              "on" in (page.locator("#sortscore").get_attribute("class") or ""))

        # 7. Expand a job description
        step(page, "7. Open a job to read its description")
        click(page, ".job .row")
        page.wait_for_timeout(900)
        check("library: description expands", page.locator(".desc.open").count() > 0)

        # 8. Run Center — command building
        step(page, "8. Go to the Run Center")
        click(page, "nav a[href='/run']")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#p_cmd", timeout=6000)
        cmd_before = page.locator("#p_cmd").inner_text()
        check("run: pipeline command rendered", "run.py" in cmd_before)

        step(page, "9. Change location — command should update")
        page.fill("#p_loc", "Bristol")
        page.wait_for_timeout(700)
        cmd_after = page.locator("#p_cmd").inner_text()
        check("run: command reflects new location", "Bristol" in cmd_after)

        step(page, "10. Copy the generated command")
        click(page, "button[data-copy='p_cmd']")
        page.wait_for_timeout(600)

        # 11. Dashboard
        step(page, "11. Open the analytics Dashboard")
        click(page, "nav a[href^='/dashboard']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1200)
        check("dashboard: loaded", "Dashboard" in page.title() or
              page.locator("text=Analytics").count() > 0)

        # 12. Command Builder
        step(page, "12. Open the Command Builder")
        click(page, "nav a[href='/builder']")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        check("builder: loaded", page.locator("text=Command").count() > 0)

        step(page, "Done — all steps executed")
        page.wait_for_timeout(1500)
        ctx.close()
        browser.close()


if __name__ == "__main__":
    print(f"E2E UI tests against {BASE}  (headless={HEADLESS})")
    try:
        run()
    except Exception as e:
        print(f"\nERROR during run: {e}")
        sys.exit(2)
    passed = sum(results)
    total = len(results)
    print(f"\n=== {passed}/{total} checks passed ===")
    sys.exit(0 if passed == total else 1)
