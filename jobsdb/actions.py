#!/usr/bin/env python3
"""
Background actions driven from the web UI: refresh the job set and run the AI
match-filter, without leaving the page.

Tasks run in a daemon thread; progress is tracked in an in-memory registry the
Flask app polls via /api/task/<id>. One task of each kind at a time.
"""
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
    fn = {"refresh": _run_refresh, "ai": _run_ai}.get(kind)
    if not fn:
        _finish(tid, False, f"unknown task '{kind}'")
        _running_kinds.discard(kind)
        return tid
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
