#!/usr/bin/env python3
"""
Daily update: refresh jobs from every pinned company, fold into Postgres, and
report what changed — designed to run unattended on a schedule.

Pipeline:
  1. careers crawler across ALL companies in data/uk_aerospace_companies.json
  2. (optional) job-board providers + LinkedIn public search
  3. ingest into Postgres (idempotent; sets is_new on genuinely new roles)
  4. print today's NEW roles + a UK hiring-intelligence summary

Usage:
  python daily_update.py                  # sweep + ingest + summary
  python daily_update.py --providers      # also pull free job-board providers
  python daily_update.py --linkedin       # also pull LinkedIn public search
  python daily_update.py --no-scrape      # ingest existing output + summarise only
  python daily_update.py --keyword ""     # widen careers filter (default: software)

Schedule (Windows Task Scheduler), daily at 07:00:
  schtasks /Create /SC DAILY /ST 07:00 /TN "JobsDaily" ^
    /TR "cmd /c cd /d C:\\tmp\\job-scraper-clean && python daily_update.py --providers >> output\\daily.log 2>&1"
Or cron:  0 7 * * *  cd /path/repo && python daily_update.py --providers >> output/daily.log 2>&1
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent


def run(cmd, desc, cwd=None):
    print(f"\n>>> {desc}", flush=True)
    r = subprocess.run([sys.executable, *cmd], cwd=str(cwd or BASE))
    ok = r.returncode == 0
    print(f"    {'OK' if ok else 'FAILED (continuing)'}: {desc}", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser(description="Daily job refresh + ingest + report.")
    ap.add_argument("--keyword", default="software", help="Careers title filter (default: software)")
    ap.add_argument("--providers", action="store_true", help="Also pull job-board providers")
    ap.add_argument("--linkedin", action="store_true", help="Also pull LinkedIn public search")
    ap.add_argument("--no-scrape", action="store_true", help="Skip scraping; ingest existing output + report")
    args = ap.parse_args()

    start = datetime.now()
    print("=" * 70)
    print(f"DAILY UPDATE — {start:%Y-%m-%d %H:%M:%S}")
    print("=" * 70)

    if not args.no_scrape:
        careers = ["scrapers/careers.py", "--all"]
        if args.keyword:
            careers += ["-k", args.keyword]
        run(careers, "Careers sweep (all pinned companies)")

        if args.providers and (BASE / "scrapers" / "providers.py").exists():
            run(["scrapers/providers.py", "--free"], "Job-board providers (free)")

        if args.linkedin and (BASE / "scrap_with_batch" / "linkedin_scraper.py").exists():
            run(["scrap_with_batch/linkedin_scraper.py", "-a", "-l", "United Kingdom"],
                "LinkedIn public search", cwd=BASE / "scrap_with_batch")

    run(["-m", "jobsdb.ingest"], "Ingest into Postgres")

    # --- report: what's new + UK hiring intelligence ---
    from sqlalchemy import text
    from jobsdb.db import get_engine
    from jobsdb import skills
    eng = get_engine()
    with eng.connect() as c:
        new_n = c.execute(text("SELECT count(*) FROM jobs WHERE is_new")).scalar()
        total = c.execute(text("SELECT count(*) FROM jobs")).scalar()
        new_uk = c.execute(text(
            "SELECT company, count(*) FROM jobs WHERE is_new AND job_country='United Kingdom' "
            "GROUP BY company ORDER BY 2 DESC LIMIT 12")).all()

    print("\n" + "=" * 70)
    print(f"NEW this run: {new_n}  (DB total {total})")
    print("=" * 70)
    if new_uk:
        print("\nNew UK roles by employer:")
        for co, cnt in new_uk:
            print(f"  {cnt:4}  {co}")

    print("\n" + skills.report(eng, uk=True, new_days=1, top=15))
    print(f"\nDone in {datetime.now() - start}.")


if __name__ == "__main__":
    main()
