#!/usr/bin/env python3
"""
Company careers-site crawler — jobs straight from the source, across locations.

Detects which Applicant Tracking System (ATS) a company uses from its careers
page, then pulls jobs from that ATS's public API. Covers the common platforms:
Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee, Workable, Personio,
BambooHR, and Workday. Output is the standard job schema (with location), written
to output/careers_*.json for jobsdb.ingest.

Usage:
  python scrapers/careers.py --all -k software            # sweep the repository
  python scrapers/careers.py --company "Vertical Aerospace" --site vertical-aerospace.com
  python scrapers/careers.py --detect vertical-aerospace.com
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent.parent
OUTPUT_DIR = BASE_DIR / "output"
REPO = BASE_DIR / "data" / "uk_aerospace_companies.json"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"}

SOFTWARE = re.compile(
    r"(software|firmware|embedded|avionics|flight|control|c\+\+|python|"
    r"back[- ]?end|front[- ]?end|full[- ]?stack|develop|programmer|devops|sre|"
    r"data engineer|machine learning|robotics|autonomy|gnc|systems engineer)", re.I)

# ATS host signatures -> (platform, capture groups). Order matters.
PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9]+)", re.I)),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board\?for=([a-z0-9]+)", re.I)),
    ("lever",      re.compile(r"jobs\.lever\.co/([a-z0-9-]+)", re.I)),
    ("ashby",      re.compile(r"jobs\.ashbyhq\.com/([a-z0-9-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9]+)", re.I)),
    ("recruitee",  re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I)),
    ("workable",   re.compile(r"apply\.workable\.com/([a-z0-9-]+)", re.I)),
    ("personio",   re.compile(r"([a-z0-9-]+)\.jobs\.personio\.com", re.I)),
    ("bamboohr",   re.compile(r"([a-z0-9-]+)\.bamboohr\.com", re.I)),
    ("workday",    re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:en-US/|wday/cxs/[a-z0-9-]+/)?([A-Za-z0-9_]+)", re.I)),
]


def _std(title, company, location, url, desc, platform):
    from jobsdb.salary import parse_salary
    s = parse_salary(desc or "") or {}
    return {"title": (title or "").strip(), "company": company, "location": location or "",
            "url": url or "", "description": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", desc or "")).strip(),
            "posted_date": "", "source": f"Careers:{platform}",
            "salary_min": s.get("min"), "salary_max": s.get("max"),
            "salary_currency": s.get("currency"), "salary_period": s.get("period", "year")}


def detect(domain):
    """Fetch likely careers pages and return (platform, token, extra) or None.

    Fails fast: a few candidate URLs, short timeout, stop at the first ATS hit.
    """
    cands = [f"https://{domain}/careers", f"https://careers.{domain}",
             f"https://jobs.{domain}", f"https://{domain}"]
    for url in cands:
        try:
            r = requests.get(url, headers=H, timeout=8, allow_redirects=True)
        except requests.RequestException:
            continue
        blob = r.url + " " + r.text
        for platform, pat in PATTERNS:
            m = pat.search(blob)
            if m:
                return (platform, m.group(1), m.groups())
    return None


# ---------------- ATS fetchers (public list APIs) ----------------
def fetch_greenhouse(token, company):
    j = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                     headers=H, timeout=25).json()
    return [_std(x.get("title"), company, (x.get("location") or {}).get("name"),
                 x.get("absolute_url"), x.get("content"), "greenhouse")
            for x in j.get("jobs", [])]


def fetch_lever(token, company):
    j = requests.get(f"https://api.lever.co/v0/postings/{token}?mode=json",
                     headers=H, timeout=25).json()
    return [_std(x.get("text"), company, (x.get("categories") or {}).get("location"),
                 x.get("hostedUrl"), x.get("descriptionPlain"), "lever") for x in j]


def fetch_ashby(token, company):
    j = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                     headers=H, timeout=25).json()
    return [_std(x.get("title"), company, x.get("location"), x.get("jobUrl"),
                 x.get("descriptionPlain") or x.get("descriptionHtml"), "ashby")
            for x in j.get("jobs", [])]


def fetch_smartrecruiters(token, company):
    out, offset = [], 0
    while True:
        j = requests.get(f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
                         params={"limit": 100, "offset": offset}, headers=H, timeout=25).json()
        content = j.get("content", [])
        for x in content:
            loc = x.get("location", {})
            locs = ", ".join(filter(None, [loc.get("city"), loc.get("country")]))
            out.append(_std(x.get("name"), company, locs,
                            f"https://jobs.smartrecruiters.com/{token}/{x.get('id')}", "", "smartrecruiters"))
        if len(content) < 100:
            break
        offset += 100
    return out


def fetch_recruitee(token, company):
    j = requests.get(f"https://{token}.recruitee.com/api/offers/", headers=H, timeout=25).json()
    return [_std(x.get("title"), company, x.get("location"), x.get("careers_url"),
                 x.get("description"), "recruitee") for x in j.get("offers", [])]


def fetch_workable(token, company):
    r = requests.get(f"https://{token}.workable.com/spi/v3/jobs", headers=H, timeout=25)
    j = r.json()
    return [_std(x.get("title"), company, x.get("location", {}).get("location_str"),
                 x.get("url") or x.get("shortlink"), x.get("description"), "workable")
            for x in j.get("jobs", [])]


def fetch_personio(token, company):
    import xml.etree.ElementTree as ET
    r = requests.get(f"https://{token}.jobs.personio.com/xml", headers=H, timeout=25)
    root = ET.fromstring(r.content)
    out = []
    for pos in root.iter("position"):
        g = lambda t: (pos.findtext(t) or "")
        out.append(_std(g("name"), company, g("office"),
                        f"https://{token}.jobs.personio.com/job/{g('id')}",
                        g("jobDescriptions"), "personio"))
    return out


def fetch_bamboohr(token, company):
    j = requests.get(f"https://{token}.bamboohr.com/careers/list", headers=H, timeout=25).json()
    out = []
    for x in j.get("result", []):
        loc = x.get("location") or {}
        locs = ", ".join(filter(None, [loc.get("city"), loc.get("state"), loc.get("country")]))
        out.append(_std(x.get("jobOpeningName"), company, locs,
                        f"https://{token}.bamboohr.com/careers/{x.get('id')}", "", "bamboohr"))
    return out


def fetch_workday(groups, company):
    sub, wd, site = groups[0], groups[1], groups[2]
    api = f"https://{sub}.{wd}.myworkdayjobs.com/wday/cxs/{sub}/{site}/jobs"
    out, off = [], 0
    while off < 400:
        r = requests.post(api, headers={**H, "Content-Type": "application/json"},
                          json={"appliedFacets": {}, "limit": 20, "offset": off, "searchText": ""}, timeout=25)
        jp = r.json().get("jobPostings", [])
        if not jp:
            break
        base = f"https://{sub}.{wd}.myworkdayjobs.com/en-US/{site}"
        for x in jp:
            out.append(_std(x.get("title"), company, x.get("locationsText"),
                            base + x.get("externalPath", ""), "", "workday"))
        if len(jp) < 20:
            break
        off += 20
    return out


FETCHERS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
            "smartrecruiters": fetch_smartrecruiters, "recruitee": fetch_recruitee,
            "workable": fetch_workable, "personio": fetch_personio, "bamboohr": fetch_bamboohr}


def scrape_company(name, domain, keyword=None):
    det = detect(domain)
    if not det:
        return None, []
    platform, token, groups = det
    try:
        if platform == "workday":
            jobs = fetch_workday(groups, name)
        else:
            jobs = FETCHERS[platform](token, name)
    except Exception as e:
        return platform, []
    if keyword:
        kw = keyword.lower()
        jobs = [j for j in jobs if SOFTWARE.search(j["title"]) or kw in j["title"].lower()]
    else:
        jobs = [j for j in jobs if SOFTWARE.search(j["title"])]
    return platform, jobs


def load_repo():
    d = json.load(open(REPO, encoding="utf-8"))
    return [(c["name"], c.get("site", "")) for c in d.get("companies", []) if c.get("site")]


def main():
    p = argparse.ArgumentParser(description="Company careers-site crawler (multi-ATS).")
    p.add_argument("--all", action="store_true", help="Sweep the company repository")
    p.add_argument("--company", help="Company name")
    p.add_argument("--site", help="Company domain (with --company)")
    p.add_argument("--detect", help="Just detect the ATS for a domain")
    p.add_argument("-k", "--keyword", default=None, help="Extra keyword filter (default: software titles)")
    p.add_argument("--limit", type=int, help="First N companies (with --all)")
    args = p.parse_args()

    sys.path.insert(0, str(BASE_DIR))

    if args.detect:
        print(detect(args.detect) or "no known ATS detected")
        return

    targets = []
    if args.all:
        targets = load_repo()
        if args.limit:
            targets = targets[:args.limit]
    elif args.company and args.site:
        targets = [(args.company, args.site)]
    else:
        p.error("use --all, or --company NAME --site DOMAIN, or --detect DOMAIN")

    OUTPUT_DIR.mkdir(exist_ok=True)
    all_jobs, summary = [], {}
    for i, (name, site) in enumerate(targets, 1):
        print(f"  [{i}/{len(targets)}] {name} ({site}) …", end=" ", flush=True)
        platform, jobs = scrape_company(name, site, args.keyword)
        summary[name] = (platform, len(jobs))
        all_jobs += jobs
        print(f"{platform or 'no ATS'}: {len(jobs)} software roles")

    slug = re.sub(r"[^a-z0-9]+", "_", (args.company or "all").lower()).strip("_")
    out = OUTPUT_DIR / f"careers_{slug}_{datetime.now():%Y%m%d}.json"
    json.dump(all_jobs, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    hiring = {k: v for k, v in summary.items() if v[1] > 0}
    print(f"\n{len(hiring)}/{len(targets)} companies with software roles; {len(all_jobs)} total -> {out}")
    print("Ingest with:  python -m jobsdb.ingest")


if __name__ == "__main__":
    main()
