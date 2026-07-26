# Aalto Job Library — Postgres + Web UI

A searchable store for the aviation/aerospace and HAPS-competitor roles collected
by `harvest_jd.py`, `monitor_jobs.py`, and the LinkedIn scraper.

## Stack
- **Postgres** (local Docker container, port 5433) — single `jobs` table with
  full-text search, first/last-seen history, competitor + source + new flags.
- **Flask web UI** (`http://localhost:5000`) — search, filter, read descriptions,
  export CSV.

## One-time / each session
```powershell
# 1. Bring up the DB (Docker Desktop must be running) and ingest the data
powershell -ExecutionPolicy Bypass -File jobsdb\setup_db.ps1

# 2. Launch the web interface
python -m jobsdb.app          # http://localhost:5000
```

## Refresh the data
After running the harvesters/monitor again:
```powershell
python -m jobsdb.ingest        # upsert: new roles flagged is_new, descriptions refreshed
```
`--reset` rebuilds the table from scratch.

## Connection
Defaults target the Docker container (postgres/aalto @ localhost:5433/aalto_jobs).
Point at any Postgres by setting `DATABASE_URL`, or individual `PG*` env vars
(`PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE`).

## Web UI features
Everything runs from `http://localhost:5000` — no separate scripts needed:
- **↻ Refresh jobs** — runs the monitor (Workday + LinkedIn) then ingests, live
- **🤖 AI score** — scores jobs against the target profile using the existing
  `job_filter_ai.py` (Claude or Ollama backend), with a progress bar
- **Search** — full-text across company / title / description
- **⚔️ Competitors** — filter to BAE, Leonardo/Westland, Sceye, AeroVironment,
  Prismatic (PHASA-35), General Atomics, etc.
- **🟢 New** — roles inserted at the last ingest
- **🤖 Scored / min-score / sort-by-score** — surface the best AI matches
- **Company sidebar** — click to filter; competitor companies marked ⚔️
- **⭳ Export CSV** — the current filtered view

## AI matching profile
The AI filter ranks each job against `N8n/data/your_cv.txt` — edit that file to
your ideal-candidate profile (or paste a CV). Higher score = closer match.
Backend + model come from `N8n/config.json` (or the UI selector). Claude needs
the `claude` CLI; Ollama needs a local `ollama serve`.

## What feeds it
`jobsdb/ingest.py` reads only the aerospace/competitor outputs
(`output/primes_*`, `aalto_*`, `aero_jd_*`, `gap_*`, `linkedin_aero_*`,
`linkedin_flightsw*`, `master_jd*`) — not the old generic scrapes.
