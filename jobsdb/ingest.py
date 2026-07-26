#!/usr/bin/env python3
"""
Ingest all scraped/harvested/monitored JSON into Postgres.

Sources folded in:
  - output/*.json                (harvest_jd, linkedin, gap, consolidated)
  - output/monitor_state/seen.json (the monitor's tracked set: status + history)

Idempotent upsert keyed by job_key (url, else company|title|location):
  - new rows        -> inserted, is_new=True
  - existing rows   -> description/last_seen refreshed, is_new=False, first_seen kept
  - rows in the DB that are still in the monitor state stay 'open'; ones the last
    monitor run dropped are marked 'closed'.

Usage:
    python -m jobsdb.ingest                 # ingest everything
    python -m jobsdb.ingest --reset         # drop + recreate the table first
"""
import argparse
import glob
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import get_engine, init_schema, jobs, metadata
from .salary import parse_salary
from .location import normalize_country

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
STATE_FILE = OUTPUT_DIR / "monitor_state" / "seen.json"

# Competitor labels (kept in sync with monitor_jobs.COMPETITORS).
COMPETITORS = [
    "BAE", "PHASA", "Prismatic", "Sceye", "Skydweller", "AeroVironment",
    "Sunglider", "HAPSMobile", "Stratobus", "Aurora", "Odysseus", "Archangel",
    "Shield AI", "Anduril", "Airbus", "Thales", "Leonardo", "Westland",
    "Lockheed", "General Atomics", "SoftBank", "NTT",
]


def job_key(company, title, location, url):
    if url:
        return url.split("?")[0]
    return f"{company}|{title}|{location}".lower()


def label_competitor(company, title, desc):
    blob = f"{company} {title} {(desc or '')[:400]}".lower()
    hits = [c for c in COMPETITORS if c.lower() in blob]
    return ", ".join(sorted(set(hits)))


def clean(desc):
    if not desc:
        return ""
    return re.sub(r"<[^>]+>", " ", desc).strip()


# Only these output files feed the aviation/aerospace + competitor library.
# (Skips the old generic fintech scrapes like stripe_full_*, revolut_*, etc.)
INCLUDE_GLOBS = [
    "primes_*.json", "aalto_*.json", "aero_jd_*.json", "gap_*.json",
    "linkedin_aero_*.json", "linkedin_flightsw*.json", "master_jd*.json",
    # broader keyword harvests + salary-rich providers
    "linkedin_jobs*.json", "linkedin_kw_*.json", "adzuna_*.json",
]


def _relevant_files():
    files = set()
    for pat in INCLUDE_GLOBS:
        files.update(glob.glob(str(OUTPUT_DIR / pat)))
    return sorted(files)


def collect_rows():
    """Read the relevant job JSONs into a dict keyed by job_key (best desc wins)."""
    rows = {}
    for path in _relevant_files():
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        jl = data if isinstance(data, list) else data.get("jobs", [])
        default_src = "LinkedIn" if "linkedin" in path.lower() else "Workday"
        for j in jl:
            company = j.get("company", "?") or "?"
            title = j.get("title", "") or ""
            location = j.get("location", "") or ""
            url = (j.get("url", "") or "").split("?")[0]
            key = job_key(company, title, location, url)
            desc = clean(j.get("description", ""))
            prev = rows.get(key)
            if prev and len(prev["description"]) >= len(desc):
                continue  # keep the richer description
            # Structured salary from the source (e.g. Adzuna), if provided.
            structured_sal = None
            if j.get("salary_min") is not None or j.get("salary_max") is not None:
                structured_sal = {
                    "min": j.get("salary_min"), "max": j.get("salary_max"),
                    "currency": j.get("salary_currency") or "GBP",
                    "period": j.get("salary_period") or "year",
                }
            rows[key] = {
                "job_key": key, "source": j.get("source", default_src),
                "company": company, "title": title, "location": location,
                "url": url, "description": desc,
                "posted_date": j.get("posted_date", "") or "",
                "salary": structured_sal, "raw": j,
            }
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="Drop and recreate the jobs table")
    args = ap.parse_args()

    engine = get_engine()
    if args.reset:
        metadata.drop_all(engine)
    init_schema(engine)
    now = datetime.now(timezone.utc)

    rows = collect_rows()
    print(f"Collected {len(rows)} unique roles from output/*.json")

    # Monitor state = the currently-open set (drives status + history).
    state = {}
    if STATE_FILE.exists():
        state = json.load(open(STATE_FILE, encoding="utf-8"))
    open_keys = set(state.keys())

    # Existing keys in DB (to compute is_new).
    with engine.connect() as c:
        existing = {r[0] for r in c.execute(text("SELECT job_key FROM jobs"))}

    inserted = updated = 0
    with engine.begin() as c:
        for key, r in rows.items():
            comp = label_competitor(r["company"], r["title"], r["description"])
            first_seen = None
            if key in state and state[key].get("first_seen"):
                try:
                    first_seen = datetime.fromisoformat(state[key]["first_seen"])
                except Exception:
                    first_seen = now
            first_seen = first_seen or now
            is_new = key not in existing
            # Everything we just ingested was seen in the data => open. The monitor
            # owns true CLOSED detection over time; harvest snapshots are all open.
            status = "open"
            # Prefer a source-provided salary; otherwise parse it from the text.
            sal = r.get("salary") or parse_salary(r["description"]) or {}
            country = normalize_country(r["location"])

            stmt = pg_insert(jobs).values(
                job_key=key, source=r["source"], company=r["company"],
                title=r["title"], location=r["location"], url=r["url"],
                description=r["description"], competitor=comp,
                is_competitor=bool(comp), posted_date=r["posted_date"],
                status=status, is_new=is_new, first_seen=first_seen, last_seen=now,
                raw=r["raw"],
                salary_min=sal.get("min"), salary_max=sal.get("max"),
                salary_currency=sal.get("currency"), salary_period=sal.get("period"),
                job_country=country,
                search=text("to_tsvector('english', :ft)").bindparams(
                    ft=f"{r['company']} {r['title']} {r['description']}"),
            ).on_conflict_do_update(
                index_elements=["job_key"],
                set_={
                    "source": r["source"], "company": r["company"],
                    "title": r["title"], "location": r["location"], "url": r["url"],
                    "description": r["description"], "competitor": comp,
                    "is_competitor": bool(comp), "status": status, "is_new": False,
                    "last_seen": now, "raw": r["raw"],
                    "salary_min": sal.get("min"), "salary_max": sal.get("max"),
                    "salary_currency": sal.get("currency"),
                    "salary_period": sal.get("period"), "job_country": country,
                    "search": text("to_tsvector('english', :ft)").bindparams(
                        ft=f"{r['company']} {r['title']} {r['description']}"),
                },
            )
            c.execute(stmt)
            inserted += 1 if is_new else 0
            updated += 0 if is_new else 1

    with engine.connect() as c:
        total = c.execute(text("SELECT count(*) FROM jobs")).scalar()
        comp_n = c.execute(text("SELECT count(*) FROM jobs WHERE is_competitor")).scalar()
        new_n = c.execute(text("SELECT count(*) FROM jobs WHERE is_new")).scalar()
    print(f"Ingest done: +{inserted} new, {updated} updated. "
          f"Total {total} rows ({comp_n} competitor, {new_n} new).")


if __name__ == "__main__":
    main()
