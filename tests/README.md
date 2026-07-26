# Tests

Two layers: a rigorous **deterministic pytest suite** (exact assertions against a
seeded, isolated database) and a **watchable Chrome demo** you can run to see it
click through the app.

## 1. Deterministic suite (pytest)

Runs against a separate database `aalto_jobs_test` (never touches real data),
seeded with 12 hand-checked rows (`seed.py`) so every assertion is exact.

```
python -m pytest tests -q --ignore=tests/ui_e2e.py
```

- **`test_api.py`** — the API contract is *correct*, not just present:
  competitor/new/scored/min-score/source filters return exactly the right rows;
  full-text search is relevant; `sort=score` is truly descending; `/api/stats`
  math is consistent; CSV export and `/api/analysis.json` match the filter;
  run-dispatch validation.
- **`test_actions.py`** — running a task *actually mutates the DB*: the AI
  scoring task (LLM stubbed with a deterministic scorer) scores the unscored
  rows, respects `competitor_only`, and writes scores + reasons.
- **`test_e2e.py`** — launches a real server on the seeded DB and cross-checks
  what the **UI renders** against the known data: row counts per filter, badge
  presence, search relevance, min-score subset, descending score order, expand.

Requirements: `pytest`, `playwright` (+ `python -m playwright install chromium`),
and the Docker test DB reachable (defaults: `localhost:5433`, `postgres`/`aalto`).
Point elsewhere with `PGHOST/PGPORT/PGUSER/PGPASSWORD` or `TEST_PGDATABASE`.

## 2. Watchable Chrome demo (`ui_e2e.py`)

Drives the **running** app in a real Chrome window — moves the mouse, rings each
click, captions each step — and cross-checks the UI against the live API as it
goes (competitor count == API, search count == API, scores descending, …).

```
python -m jobsdb.app          # terminal 1 (http://localhost:5000)
python tests/ui_e2e.py        # terminal 2 — watch it run
SLOWMO=900 python tests/ui_e2e.py     # slower
HEADLESS=1 python tests/ui_e2e.py     # no window
```

Prints `PASS/FAIL` per check and a final `N/N checks passed`.
Watch the deterministic E2E instead with: `HEADED=1 python -m pytest tests/test_e2e.py`.
