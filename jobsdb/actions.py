#!/usr/bin/env python3
"""
Background actions driven from the web UI: refresh the job set and run the AI
match-filter, without leaving the page.

Tasks run in a daemon thread; progress is tracked in an in-memory registry the
Flask app polls via /api/task/<id>. One task of each kind at a time.
"""
import re
import sys
import threading
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from .db import get_engine

BASE_DIR = Path(__file__).parent.parent

# task_id -> {kind, status, progress, total, message, started, finished}
TASKS = {}
_lock = threading.Lock()
_running_kinds = set()


def _new_task(kind):
    tid = uuid.uuid4().hex[:12]
    TASKS[tid] = {"id": tid, "kind": kind, "status": "running", "progress": 0,
                  "total": 0, "message": "starting…",
                  "started": datetime.now().isoformat(timespec="seconds"),
                  "finished": None}
    return tid


def _finish(tid, ok=True, message="done"):
    TASKS[tid]["status"] = "done" if ok else "error"
    TASKS[tid]["message"] = message
    TASKS[tid]["finished"] = datetime.now().isoformat(timespec="seconds")


def start(kind, **kwargs):
    """Start a task if one of that kind isn't already running. Returns task id or None."""
    with _lock:
        if kind in _running_kinds:
            return None
        _running_kinds.add(kind)
    tid = _new_task(kind)
    fn = {"refresh": _run_refresh, "ai": _run_ai, "scrape": _run_scrape,
          "analyze": _run_analyze, "pipeline": _run_pipeline,
          "adzuna": _run_adzuna, "providers": _run_providers,
          "linkedin": _run_linkedin, "companies": _run_companies}.get(kind)
    if not fn:
        _finish(tid, False, f"unknown task '{kind}'")
        _running_kinds.discard(kind)
        return tid
    # Only pass kwargs the target accepts, so extra UI fields never break dispatch.
    import inspect
    accepted = set(inspect.signature(fn).parameters)
    kwargs = {k: v for k, v in kwargs.items() if k in accepted}
    threading.Thread(target=_wrap, args=(fn, tid, kwargs), daemon=True).start()
    return tid


def _wrap(fn, tid, kwargs):
    try:
        fn(tid, **kwargs)
    except Exception as e:
        _finish(tid, False, f"error: {e}")
    finally:
        _running_kinds.discard(TASKS[tid]["kind"])


# --- Refresh: run the monitor (Workday + LinkedIn), then ingest into PG --------
def _run_refresh(tid, no_linkedin=False):
    py = sys.executable
    TASKS[tid]["message"] = "running monitor (scraping)…"
    cmd = [py, str(BASE_DIR / "monitor_jobs.py")]
    if no_linkedin:
        cmd.append("--no-linkedin")
    subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 50
    TASKS[tid]["message"] = "ingesting into database…"
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, "jobs refreshed and ingested")


# --- Scrape all websites: run.py orchestrator, then ingest --------------------
def _run_scrape(tid, location="London", time_range="48h", workers=4, scope="all"):
    py = sys.executable
    TASKS[tid]["message"] = f"scraping all websites ({location}, {time_range})…"
    cmd = [py, str(BASE_DIR / "run.py"), "--location", location,
           "--time-range", time_range, "--workers", str(workers)]
    if scope == "linkedin":
        cmd.append("--linkedin-only")
    elif scope == "workday":
        cmd.append("--workday-only")
    TASKS[tid]["cmd"] = " ".join(cmd)
    subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=3600)
    TASKS[tid]["progress"] = 80
    TASKS[tid]["message"] = "ingesting into database…"
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, "scraping complete and ingested")


# --- Analyze: file-based AI analysis via analyze.py (Dashboard-compatible) -----
def _run_analyze(tid, backend="claude", model="haiku", min_score=7, limit=None):
    py = sys.executable
    TASKS[tid]["message"] = f"analysing latest jobs ({backend}/{model})…"
    cmd = [py, str(BASE_DIR / "analyze.py"), "--backend", backend, "--model", model,
           "--min-score", str(min_score)]
    if limit:
        cmd += ["--limit", str(limit)]
    TASKS[tid]["cmd"] = " ".join(cmd)
    r = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=3600)
    TASKS[tid]["progress"] = 100
    ok = r.returncode == 0
    _finish(tid, ok, "analysis complete" if ok else f"analyze error: {r.stderr[:160]}")


# --- Full pipeline: scrape everything, analyse, ingest (one command) ----------
def _run_pipeline(tid, location="London", time_range="48h", workers=4,
                  backend="claude", model="haiku", min_score=7):
    py = sys.executable
    TASKS[tid]["message"] = "1/3 scraping all websites…"
    subprocess.run([py, str(BASE_DIR / "run.py"), "--location", location,
                    "--time-range", time_range, "--workers", str(workers)],
                   cwd=str(BASE_DIR), capture_output=True, text=True, timeout=3600)
    TASKS[tid]["progress"] = 40
    TASKS[tid]["message"] = "2/3 AI analysis…"
    subprocess.run([py, str(BASE_DIR / "analyze.py"), "--backend", backend,
                    "--model", model, "--min-score", str(min_score)],
                   cwd=str(BASE_DIR), capture_output=True, text=True, timeout=3600)
    TASKS[tid]["progress"] = 80
    TASKS[tid]["message"] = "3/3 ingesting into database…"
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, "full pipeline complete")


def _keywords(kw):
    return [k.strip() for k in re.split(r"[;,]", kw or "") if k.strip()]


# --- LinkedIn: public guest search (no login/API key), then ingest -----------
def _run_linkedin(tid, keywords="software engineer", geo_id="90009496",
                  time_range="7d", max_jobs=50):
    py = sys.executable
    kws = _keywords(keywords) or ["software engineer"]
    ln = BASE_DIR / "scrapers" / "linkedin.py"
    for i, kw in enumerate(kws):
        TASKS[tid]["message"] = f"LinkedIn: '{kw}' ({i+1}/{len(kws)})"
        TASKS[tid]["progress"] = int(i * 85 / len(kws))
        slug = re.sub(r"[^a-z0-9]+", "_", kw.lower()).strip("_")
        out = str(BASE_DIR / "output" / f"linkedin_kw_{slug}.json")
        subprocess.run([py, str(ln), "-k", kw, "--geo-id", geo_id,
                        "-t", time_range, "-n", str(max_jobs), "-o", out, "--no-merge"],
                       cwd=str(BASE_DIR), capture_output=True, text=True, timeout=1200)
    TASKS[tid]["message"] = "ingesting…"
    TASKS[tid]["progress"] = 90
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, f"LinkedIn harvest done for {len(kws)} keyword(s)")


# --- Company sweep: search the UK aerospace repository for software roles -----
def _run_companies(tid, keywords="software engineer", source="linkedin",
                   country="gb", limit=10):
    py = sys.executable
    TASKS[tid]["message"] = f"searching {limit} companies for '{keywords}'…"
    cmd = [py, str(BASE_DIR / "scrapers" / "company_search.py"),
           "-k", keywords, "--source", source, "-c", country]
    if limit:
        cmd += ["--limit", str(limit)]
    subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 90
    TASKS[tid]["message"] = "ingesting…"
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, f"company sweep done ({limit} companies)")


# --- Providers: multi-source fetch (free + key-gated), then ingest -----------
def _run_providers(tid, keywords="software engineer", providers="free",
                   country="gb", location="", max_jobs=50):
    py = sys.executable
    kws = _keywords(keywords) or ["software engineer"]
    for i, kw in enumerate(kws):
        TASKS[tid]["message"] = f"providers [{providers}]: '{kw}' ({i+1}/{len(kws)})"
        TASKS[tid]["progress"] = int(i * 85 / len(kws))
        cmd = [py, "-m", "scrapers.providers", "-k", kw, "--providers", providers,
               "-c", country, "-n", str(max_jobs)]
        if location:
            cmd += ["-l", location]
        subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=1200)
    TASKS[tid]["message"] = "ingesting…"
    TASKS[tid]["progress"] = 90
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, f"providers harvest done for {len(kws)} keyword(s)")


# --- Adzuna: aggregator with structured salary, then ingest ------------------
def _run_adzuna(tid, keywords="software engineer", country="gb",
                location="", max_jobs=100):
    py = sys.executable
    kws = _keywords(keywords) or ["software engineer"]
    ad = BASE_DIR / "scrapers" / "adzuna.py"
    for i, kw in enumerate(kws):
        TASKS[tid]["message"] = f"Adzuna: '{kw}' ({i+1}/{len(kws)})"
        TASKS[tid]["progress"] = int(i * 85 / len(kws))
        cmd = [py, str(ad), "-k", kw, "-c", country, "-n", str(max_jobs)]
        if location:
            cmd += ["-l", location]
        subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=900)
    TASKS[tid]["message"] = "ingesting…"
    TASKS[tid]["progress"] = 90
    subprocess.run([py, "-m", "jobsdb.ingest"], cwd=str(BASE_DIR),
                   capture_output=True, text=True, timeout=1800)
    TASKS[tid]["progress"] = 100
    _finish(tid, True, f"Adzuna harvest done for {len(kws)} keyword(s)")


# --- AI filter: score jobs vs the target CV/profile ---------------------------
def _run_ai(tid, limit=60, only_unscored=True, competitor_only=False,
            new_only=False, backend=None, model=None):
    # Reuse the existing filter's scoring + config/CV loading.
    sys.path.insert(0, str(BASE_DIR))
    from analyze import load_config, load_cv, score_job_with_ai

    config = load_config()
    analysis = config.setdefault("analysis", {})
    if backend:
        analysis["backend"] = backend
    if model:
        analysis["model"] = model
    cv = load_cv()
    if not cv or len(cv) < 20:
        _finish(tid, False, "No CV/profile found. Put your profile in data/cv.txt")
        return

    where = ["length(description) > 200"]
    if only_unscored:
        where.append("ai_score IS NULL")
    if competitor_only:
        where.append("is_competitor = true")
    if new_only:
        where.append("is_new = true")
    wsql = " WHERE " + " AND ".join(where)

    engine = get_engine(create_db_if_missing=False)
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, title, company, location, description FROM jobs"
            + wsql + " ORDER BY is_competitor DESC, is_new DESC LIMIT :lim"),
            {"lim": limit}).mappings().all()

    TASKS[tid]["total"] = len(rows)
    if not rows:
        _finish(tid, True, "nothing to score (all matching jobs already scored)")
        return

    done = 0
    for r in rows:
        job = {"title": r["title"], "company": r["company"],
               "location": r["location"], "description": r["description"] or ""}
        res = score_job_with_ai(job, cv, config)
        reasons = "; ".join(res.get("reasons", []))[:1000]
        with engine.begin() as c:
            c.execute(text(
                "UPDATE jobs SET ai_score=:s, ai_match=:m, ai_reasons=:r, "
                "ai_scored_at=:t WHERE id=:i"),
                {"s": res.get("score", 0), "m": bool(res.get("match", False)),
                 "r": reasons, "t": datetime.now(timezone.utc), "i": r["id"]})
        done += 1
        TASKS[tid]["progress"] = int(done * 100 / len(rows))
        TASKS[tid]["message"] = f"scored {done}/{len(rows)} — {r['company']}: {r['title'][:40]}"
    _finish(tid, True, f"scored {done} jobs")
