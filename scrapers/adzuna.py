#!/usr/bin/env python3
"""
Adzuna job scraper — an aggregator with STRUCTURED salary ranges (great for UK).

Adzuna's API returns salary_min/salary_max as numbers, so these listings fill in
the salary data that most company descriptions omit. Free tier: register at
https://developer.adzuna.com/ for an app_id + app_key.

Credentials (either):
    env  ADZUNA_APP_ID / ADZUNA_APP_KEY
    or   config.json  {"adzuna": {"app_id": "...", "app_key": "..."}}

Usage:
    python scrapers/adzuna.py -k "software engineer" -c gb -l London -n 100
    python scrapers/adzuna.py -k "principal software engineer" -c gb
Output: output/adzuna_<slug>.json in the standard job schema (with salary fields).
"""
import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
API = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
CURRENCY = {"gb": "GBP", "us": "USD", "de": "EUR", "fr": "EUR", "es": "EUR",
            "it": "EUR", "nl": "EUR", "ca": "CAD", "au": "AUD", "in": "INR"}


def _creds():
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        cfg = BASE_DIR / "config.json"
        if cfg.exists():
            a = json.load(open(cfg, encoding="utf-8")).get("adzuna", {})
            app_id = app_id or a.get("app_id")
            app_key = app_key or a.get("app_key")
    return app_id, app_key


def to_job(result, country):
    """Map one Adzuna API result to the standard job schema."""
    smin, smax = result.get("salary_min"), result.get("salary_max")
    return {
        "title": result.get("title", "").strip(),
        "company": (result.get("company") or {}).get("display_name", "") or "?",
        "location": (result.get("location") or {}).get("display_name", ""),
        "url": result.get("redirect_url", ""),
        "description": re.sub(r"\s+", " ", result.get("description", "") or "").strip(),
        "posted_date": (result.get("created", "") or "")[:10],
        "source": "Adzuna",
        "salary_min": int(smin) if smin else None,
        "salary_max": int(smax) if smax else None,
        "salary_currency": CURRENCY.get(country, "GBP"),
        "salary_period": "year",
    }


def scrape(keyword, country="gb", where="", max_jobs=100):
    app_id, app_key = _creds()
    if not (app_id and app_key):
        print("No Adzuna credentials. Get a free key at https://developer.adzuna.com/ "
              "then set ADZUNA_APP_ID / ADZUNA_APP_KEY (or config.json 'adzuna').")
        return []
    jobs, page, per = [], 1, 50
    while len(jobs) < max_jobs and page <= 20:
        params = {"app_id": app_id, "app_key": app_key, "what": keyword,
                  "results_per_page": per, "content-type": "application/json"}
        if where:
            params["where"] = where
        try:
            r = requests.get(API.format(country=country, page=page),
                             params=params, timeout=30)
            r.raise_for_status()
            results = r.json().get("results", [])
        except requests.RequestException as e:
            print(f"  Adzuna error: {e}")
            break
        if not results:
            break
        jobs += [to_job(x, country) for x in results]
        page += 1
        time.sleep(0.4)
    return jobs[:max_jobs]


def main():
    p = argparse.ArgumentParser(description="Adzuna job scraper (structured salary).")
    p.add_argument("-k", "--keywords", required=True, help="What to search")
    p.add_argument("-c", "--country", default="gb", help="Country code (gb, us, de, ...)")
    p.add_argument("-l", "--location", default="", help="Where (e.g. London)")
    p.add_argument("-n", "--max-jobs", type=int, default=100)
    p.add_argument("-o", "--output", default=None)
    args = p.parse_args()

    jobs = scrape(args.keywords, args.country, args.location, args.max_jobs)
    OUTPUT_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", args.keywords.lower()).strip("_")
    out = OUTPUT_DIR / (args.output or f"adzuna_{slug}_{datetime.now():%Y%m%d}.json")
    json.dump(jobs, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with_sal = sum(1 for j in jobs if j["salary_max"])
    print(f"Adzuna: {len(jobs)} jobs ({with_sal} with salary) -> {out}")


if __name__ == "__main__":
    main()
