"""Execution tests — prove that RUNNING a task actually mutates the database.

The LLM call is stubbed with a deterministic scorer so the test is fast and
repeatable; everything else (DB reads/writes, filtering, progress, stats) is real.
"""
import pytest
from sqlalchemy import text

from jobsdb import actions
from seed import seed


@pytest.fixture()
def stub_scorer(monkeypatch):
    """Deterministic replacement for analyze.score_job_with_ai."""
    import analyze

    def fake_score(job, cv, config):
        text_blob = f"{job.get('title','')} {job.get('description','')}".lower()
        score = 9 if "avionics" in text_blob else 6 if "fpga" in text_blob else 3
        return {"score": score, "match": score >= 7,
                "reasons": [f"stub scored {score}"]}

    monkeypatch.setattr(analyze, "score_job_with_ai", fake_score)
    monkeypatch.setattr(analyze, "load_cv", lambda *a, **k: "TEST CV avionics embedded")
    monkeypatch.setattr(analyze, "load_config", lambda *a, **k: {"analysis": {}})
    return fake_score


def _unscored(engine):
    with engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM jobs WHERE ai_score IS NULL")).scalar()


def _run_sync(kind, **kw):
    """Run a task body synchronously (no thread) and return its record."""
    tid = actions._new_task(kind)
    {"ai": actions._run_ai}[kind](tid, **kw)
    return actions.TASKS[tid]


def test_ai_task_scores_unscored_rows(seeded, engine, stub_scorer):
    seed(engine)  # ensure clean seeded state
    before = _unscored(engine)
    assert before == 3                                    # Roku, RTX, Airbus-Data

    rec = _run_sync("ai", only_unscored=True, limit=50, backend="claude", model="haiku")

    assert rec["status"] == "done", rec["message"]
    assert rec["total"] == before                         # scored exactly the unscored set
    assert _unscored(engine) == 0                         # DB really changed

    # The stub's rules held: previously-null avionics row -> 9, etc.
    with engine.connect() as c:
        r = c.execute(text("SELECT ai_score, ai_reasons FROM jobs "
                            "WHERE title='Principal Software Engineer'")).first()
    assert r[0] == 3 and "stub scored" in (r[1] or "")     # RTX foundation sw -> 3


def test_ai_task_respects_competitor_only(seeded, engine, stub_scorer):
    seed(seeded["engine"])                                 # reset
    # wipe scores so everything is a candidate again
    with engine.begin() as c:
        c.execute(text("UPDATE jobs SET ai_score=NULL, ai_match=NULL"))

    _run_sync("ai", only_unscored=True, competitor_only=True, limit=50,
              backend="claude", model="haiku")

    with engine.connect() as c:
        scored_non_comp = c.execute(text(
            "SELECT count(*) FROM jobs WHERE ai_score IS NOT NULL "
            "AND is_competitor = false")).scalar()
        scored_comp = c.execute(text(
            "SELECT count(*) FROM jobs WHERE ai_score IS NOT NULL "
            "AND is_competitor = true")).scalar()
    assert scored_non_comp == 0                            # only competitors were touched
    assert scored_comp == 4
