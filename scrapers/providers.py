#!/usr/bin/env python3
"""
Unified multi-provider job fetcher.

Pulls jobs from several public job APIs and normalises them to the standard
schema (title, company, location, url, description, posted_date, source,
salary_min/max/currency/period). Salary is parsed from free-text where a
provider doesn't give structured numbers.

Free, no key:   arbeitnow, remotive, themuse, jobicy
Key required:   adzuna, reed, jooble   (skipped gracefully if unconfigured)

Credentials via env or config.json:
    ADZUNA_APP_ID / ADZUNA_APP_KEY        (config "adzuna": {app_id, app_key})
    REED_API_KEY                          (config "reed": {api_key})
    JOOBLE_API_KEY                        (config "jooble": {api_key})

Usage:
    python -m scrapers.providers -k "software engineer" --providers free
    python -m scrapers.providers -k "principal software engineer" --providers all -c gb -l London
    python -m scrapers.providers --list
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
sys.path.insert(0, str(BASE_DIR))
from jobsdb.salary import parse_salary  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
FREE = ("arbeitnow", "remotive", "themuse", "jobicy")
KEYED = ("adzuna", "reed", "jooble")


def _cfg(name):
    cfg = BASE_DIR / "config.json"
    if cfg.exists():
        return json.load(open(cfg, encoding="utf-8")).get(name, {})
    return {}


def _std(title, company, location, url, description, posted, source,
         smin=None, smax=None, cur=None, per="year"):
    if smin is None and smax is None and description:
        s = parse_salary(description) or {}
        smin, smax, cur, per = s.get("min"), s.get("max"), s.get("currency"), s.get("period", "year")
    return {"title": (title or "").strip(), "company": company or "?",
            "location": location or "", "url": url or "",
            "description": re.sub(r"\s+", " ", description or "").strip(),
            "posted_date": (posted or "")[:10], "source": source,
            "salary_min": int(smin) if smin else None,
            "salary_max": int(smax) if smax else None,
            "salary_currency": cur, "salary_period": per}


def _matches(kw, *fields):
    blob = " ".join(f or "" for f in fields).lower()
    return all(w in blob for w in kw.lower().split())


# ---------------- free providers ----------------
def arbeitnow(kw, country, location, n):
    r = requests.get("https://www.arbeitnow.com/api/job-board-api", headers=UA, timeout=20)
    out = []
    for j in r.json().get("data", []):
        if not _matches(kw, j.get("title"), " ".join(j.get("tags", []))):
            continue
        out.append(_std(j.get("title"), j.get("company_name"), j.get("location"),
                        j.get("url"), j.get("description"), "", "Arbeitnow"))
    return out[:n]


def remotive(kw, country, location, n):
    r = requests.get("https://remotive.com/api/remote-jobs",
                     params={"search": kw, "limit": n}, headers=UA, timeout=20)
    out = []
    for j in r.json().get("jobs", []):
        out.append(_std(j.get("title"), j.get("company_name"), j.get("candidate_required_location"),
                        j.get("url"), j.get("description"), j.get("publication_date"),
                        "Remotive", *_salary_from_text(j.get("salary"))))
    return out[:n]


def themuse(kw, country, location, n):
    out = []
    for page in range(1, 4):
        r = requests.get("https://www.themuse.com/api/public/jobs",
                         params={"category": "Software Engineering", "page": page},
                         headers=UA, timeout=20)
        for j in r.json().get("results", []):
            locs = ", ".join(x.get("name", "") for x in j.get("locations", []))
            if not _matches(kw, j.get("name"), locs):
                continue
            out.append(_std(j.get("name"), (j.get("company") or {}).get("name"), locs,
                            (j.get("refs") or {}).get("landing_page"),
                            j.get("contents"), j.get("publication_date"), "TheMuse"))
        if len(out) >= n:
            break
    return out[:n]


def jobicy(kw, country, location, n):
    r = requests.get("https://jobicy.com/api/v2/remote-jobs",
                     params={"count": n, "tag": kw}, headers=UA, timeout=20)
    out = []
    for j in r.json().get("jobs", []):
        smin, smax = j.get("annualSalaryMin"), j.get("annualSalaryMax")
        out.append(_std(j.get("jobTitle"), j.get("companyName"), j.get("jobGeo"),
                        j.get("url"), j.get("jobExcerpt"), j.get("pubDate"), "Jobicy",
                        smin, smax, j.get("salaryCurrency")))
    return out[:n]


def _salary_from_text(txt):
    s = parse_salary(txt or "") or {}
    return (s.get("min"), s.get("max"), s.get("currency"), s.get("period", "year"))


# ---------------- key-gated providers ----------------
def adzuna(kw, country, location, n):
    from scrapers.adzuna import scrape
    return scrape(kw, country, location, n)


def reed(kw, country, location, n):
    key = os.environ.get("REED_API_KEY") or _cfg("reed").get("api_key")
    if not key:
        print("  reed: no REED_API_KEY (get one free at reed.co.uk/developers) — skipped")
        return []
    out, taken = [], 0
    r = requests.get("https://www.reed.co.uk/api/1.0/search",
                     params={"keywords": kw, "locationName": location, "resultsToTake": n},
                     auth=(key, ""), headers=UA, timeout=25)
    for j in r.json().get("results", []):
        out.append(_std(j.get("jobTitle"), j.get("employerName"), j.get("locationName"),
                        j.get("jobUrl"), j.get("jobDescription"), j.get("date"), "Reed",
                        j.get("minimumSalary"), j.get("maximumSalary"), "GBP"))
        taken += 1
        if taken >= n:
            break
    return out


def jooble(kw, country, location, n):
    key = os.environ.get("JOOBLE_API_KEY") or _cfg("jooble").get("api_key")
    if not key:
        print("  jooble: no JOOBLE_API_KEY (get one free at jooble.org/api/about) — skipped")
        return []
    r = requests.post(f"https://jooble.org/api/{key}",
                      json={"keywords": kw, "location": location}, timeout=25)
    out = []
    for j in r.json().get("jobs", [])[:n]:
        out.append(_std(j.get("title"), j.get("company"), j.get("location"),
                        j.get("link"), j.get("snippet"), j.get("updated"), "Jooble",
                        *_salary_from_text(j.get("salary"))))
    return out


REGISTRY = {"arbeitnow": arbeitnow, "remotive": remotive, "themuse": themuse,
            "jobicy": jobicy, "adzuna": adzuna, "reed": reed, "jooble": jooble}


def run(keyword, providers, country="gb", location="", max_jobs=50):
    all_jobs = []
    for name in providers:
        fn = REGISTRY.get(name)
        if not fn:
            print(f"  unknown provider '{name}'")
            continue
        try:
            jobs = fn(keyword, country, location, max_jobs)
            print(f"  {name}: {len(jobs)} jobs")
            all_jobs += jobs
        except Exception as e:
            print(f"  {name}: error {str(e)[:80]}")
    return all_jobs


def main():
    p = argparse.ArgumentParser(description="Multi-provider job fetcher.")
    p.add_argument("-k", "--keywords", help="Search keyword(s)")
    p.add_argument("--providers", default="free",
                   help="'free', 'all', or comma-separated names")
    p.add_argument("-c", "--country", default="gb")
    p.add_argument("-l", "--location", default="")
    p.add_argument("-n", "--max-jobs", type=int, default=50)
    p.add_argument("--list", action="store_true", help="List providers and exit")
    args = p.parse_args()

    if args.list:
        print("free (no key):", ", ".join(FREE))
        print("key required :", ", ".join(KEYED))
        return
    if not args.keywords:
        p.error("-k/--keywords is required")

    sel = {"free": list(FREE), "all": list(FREE) + list(KEYED)}.get(
        args.providers, [x.strip() for x in args.providers.split(",") if x.strip()])
    print(f"Providers {sel} | '{args.keywords}' | {args.country} {args.location}")
    jobs = run(args.keywords, sel, args.country, args.location, args.max_jobs)

    OUTPUT_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", args.keywords.lower()).strip("_")
    out = OUTPUT_DIR / f"provider_{slug}_{datetime.now():%Y%m%d}.json"
    json.dump(jobs, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    with_sal = sum(1 for j in jobs if j["salary_max"])
    print(f"\nTotal {len(jobs)} jobs ({with_sal} with salary) -> {out}")


if __name__ == "__main__":
    main()
