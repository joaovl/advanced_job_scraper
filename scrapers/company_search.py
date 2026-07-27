#!/usr/bin/env python3
"""
Find which UK aerospace companies are hiring software specialists now.

Reads the company repository (data/uk_aerospace_companies.json) and searches a
source for a role keyword at each company, writing standard-schema JSON to
output/companies_*.json (ingested into the DB by jobsdb.ingest).

Sources:
  linkedin   public LinkedIn search "<company> <keyword>" (no key; slower)
  providers  the multi-provider fetcher (reed/adzuna need a free key)

Usage:
  python scrapers/company_search.py -k "software engineer" --limit 5
  python scrapers/company_search.py -k "software" --source providers -c gb
  python scrapers/company_search.py --companies "BAE Systems,Leonardo UK" -k "avionics software"
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
REPO = BASE_DIR / "data" / "uk_aerospace_companies.json"


def load_companies():
    data = json.load(open(REPO, encoding="utf-8"))
    return [c["name"] for c in data.get("companies", [])]


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def search_linkedin(company, keyword, max_jobs, geo_id, out):
    subprocess.run([sys.executable, str(BASE_DIR / "scrapers" / "linkedin.py"),
                    "-k", f"{company} {keyword}", "--geo-id", geo_id,
                    "-t", "30d", "-n", str(max_jobs), "--no-description",
                    "-o", out, "--no-merge"],
                   cwd=str(BASE_DIR), capture_output=True, text=True, timeout=300)


def search_providers(company, keyword, country, max_jobs, out):
    subprocess.run([sys.executable, "-m", "scrapers.providers",
                    "-k", f"{company} {keyword}", "--providers", "all",
                    "-c", country, "-n", str(max_jobs)],
                   cwd=str(BASE_DIR), capture_output=True, text=True, timeout=300)


def main():
    p = argparse.ArgumentParser(description="Search UK aerospace companies for software roles.")
    p.add_argument("-k", "--keywords", default="software engineer")
    p.add_argument("--source", choices=["linkedin", "providers"], default="linkedin")
    p.add_argument("--companies", help="Comma-separated names (default: the repository)")
    p.add_argument("-c", "--country", default="gb")
    p.add_argument("--geo-id", default="90009496")
    p.add_argument("-n", "--max-jobs", type=int, default=25)
    p.add_argument("--limit", type=int, help="Only the first N companies")
    args = p.parse_args()

    companies = ([c.strip() for c in args.companies.split(",")] if args.companies
                 else load_companies())
    if args.limit:
        companies = companies[:args.limit]

    print(f"Searching {len(companies)} companies for '{args.keywords}' via {args.source}")
    OUTPUT_DIR.mkdir(exist_ok=True)
    found = {}
    for i, co in enumerate(companies, 1):
        out = str(OUTPUT_DIR / f"companies_{_slug(co)}.json")
        print(f"  [{i}/{len(companies)}] {co} …", end=" ", flush=True)
        try:
            if args.source == "linkedin":
                search_linkedin(co, args.keywords, args.max_jobs, args.geo_id, out)
            else:
                search_providers(co, args.keywords, args.country, args.max_jobs, out)
            n = 0
            if Path(out).exists():
                d = json.load(open(out, encoding="utf-8"))
                n = len(d if isinstance(d, list) else d.get("jobs", []))
            found[co] = n
            print(f"{n} roles")
        except Exception as e:
            print(f"error: {str(e)[:50]}")
            found[co] = 0

    hiring = {k: v for k, v in found.items() if v > 0}
    print(f"\n{len(hiring)}/{len(companies)} companies have matching roles.")
    for co, n in sorted(hiring.items(), key=lambda x: -x[1]):
        print(f"  {n:3}  {co}")
    print("\nIngest with:  python -m jobsdb.ingest")


if __name__ == "__main__":
    main()
