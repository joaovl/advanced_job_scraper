"""End-to-end UI tests that assert the UI shows the CORRECT data.

Launches a real server against the isolated, seeded test DB on its own port,
drives it with Playwright, and cross-checks what the page renders against the
known seed expectations (not just "element exists").

Headless by default; set HEADED=1 to watch it in a window.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from seed import seed, EXPECT  # noqa: E402

ROOT = Path(__file__).parent.parent
HEADED = os.environ.get("HEADED") == "1"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session")
def live_server(engine):
    seed(engine)                                   # seed the test DB the server will read
    port = _free_port()
    env = dict(os.environ, PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-m", "jobsdb.app"],
                            cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    # wait for readiness
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(base + "/api/stats", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError("server did not start")
    yield base
    proc.terminate()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=not HEADED, channel="chrome",
                                  slow_mo=400 if HEADED else 0)
        except Exception:
            b = p.chromium.launch(headless=not HEADED, slow_mo=400 if HEADED else 0)
        yield b
        b.close()


@pytest.fixture()
def page(browser, live_server, engine):
    seed(engine)                                   # fresh data for each test
    pg = browser.new_page()
    pg.goto(live_server, wait_until="networkidle")
    yield pg
    pg.close()


def _rows(page):
    return page.locator(".job")


def test_home_stats_match_api(page, live_server):
    api = page.request.get(live_server + "/api/stats").json()["summary"]
    tiles = page.locator(".stat").all_inner_texts()
    joined = " ".join(tiles)
    assert str(api["total"]) in joined
    assert str(api["competitor"]) in joined          # UI tiles reflect real numbers


def test_library_shows_all_rows(page, live_server):
    page.goto(live_server + "/library", wait_until="networkidle")
    page.wait_for_selector(".job")
    assert _rows(page).count() == EXPECT["total"]


def test_competitor_filter_matches_expected(page, live_server):
    page.goto(live_server + "/library", wait_until="networkidle")
    page.wait_for_selector(".job")
    page.click(".chip.comp")
    page.wait_for_timeout(600)
    assert _rows(page).count() == EXPECT["competitor"]
    # every visible row carries the RIVAL badge
    n = _rows(page).count()
    rivals = page.locator(".job .badge.comp").count()
    assert rivals == n


def test_search_is_relevant(page, live_server):
    page.goto(live_server + "/library", wait_until="networkidle")
    page.wait_for_selector(".job")
    page.fill("#q", "FPGA")
    page.wait_for_timeout(900)
    assert _rows(page).count() == EXPECT["fpga"]
    for t in _rows(page).all_inner_texts():
        assert "fpga" in t.lower()


def test_min_score_filter(page, live_server):
    page.goto(live_server + "/library", wait_until="networkidle")
    page.wait_for_selector(".job")
    page.select_option("#minscore", "8")
    page.wait_for_timeout(700)
    assert _rows(page).count() == EXPECT["min8"]


def test_sort_by_score_descending(page, live_server):
    page.goto(live_server + "/library", wait_until="networkidle")
    page.wait_for_selector(".job")
    page.click(".chip[data-f='scored']")
    page.wait_for_timeout(500)
    page.click("#sortscore")
    page.wait_for_timeout(700)
    badges = page.locator(".job .badge.score").all_inner_texts()
    nums = [int(b.split("/")[0].replace("★", "").strip()) for b in badges if "/" in b]
    assert nums == sorted(nums, reverse=True) and len(nums) >= 3


def test_expand_job_shows_description(page, live_server):
    page.goto(live_server + "/library", wait_until="networkidle")
    page.wait_for_selector(".job")
    page.click(".job .row")
    page.wait_for_timeout(700)
    opened = page.locator(".desc.open")
    assert opened.count() == 1
    assert len(opened.first.inner_text()) > 20
