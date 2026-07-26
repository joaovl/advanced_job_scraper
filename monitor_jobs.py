#!/usr/bin/env python3
"""
Job monitor for aviation / aerospace and AALTO HAPS competitors.

Tracks the set of open roles across (a) Workday aerospace primes and
(b) LinkedIn keyword searches that reach non-Workday competitors
(BAE PHASA-35, Sceye, Skydweller, AeroVironment, ...). On each run it
diffs the live set against the last snapshot and reports:

    NEW      - roles that appeared since the last run (with full description)
    CLOSED   - roles that were open last run and are now gone

State lives in output/monitor_state/seen.json; reports in output/monitor_reports/.
Run it on a schedule (Windows Task Scheduler / cron) to get a rolling watch.

Usage:
    python monitor_jobs.py                 # full run (Workday + LinkedIn)
    python monitor_jobs.py --no-linkedin   # Workday only (fast, reliable)
    python monitor_jobs.py --no-desc       # skip fetching NEW descriptions
    python monitor_jobs.py --list          # show what's configured
"""

import argparse
import json
import re
import subprocess
import sys
import time
import hashlib
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scrapers"))
from workday_scraper import (  # noqa: E402
    WORKDAY_COMPANIES, HEADERS, fetch_job_details, get_location_facet_id,
)
import requests  # noqa: E402

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
STATE_DIR = OUTPUT_DIR / "monitor_state"
REPORT_DIR = OUTPUT_DIR / "monitor_reports"
STATE_FILE = STATE_DIR / "seen.json"
LINKEDIN_SCRIPT = BASE_DIR / "scrap_with_batch" / "linkedin_scraper.py"

# --- What we watch ---------------------------------------------------------
# Workday: (company_key, searchText). Company keys come from workday_scraper.
WORKDAY_QUERIES = [
    ("airbus", "software"),
    ("thales", "software"),
    ("boeing", "software"),
    ("rtx_collins", "avionics software"),
    ("northrop_grumman", "software"),
]

# Only keep roles whose title looks like engineering software / avionics / HAPS.
TITLE_KEEP = re.compile(
    r"(software|firmware|embedded|avionics|flight|control|systems eng|"
    r"c\+\+|python|autonomy|guidance|navigation|GNC|HAPS|stratospher)",
    re.I,
)

# LinkedIn: keyword searches that also reach non-Workday competitors.
LINKEDIN_QUERIES = [
    # Role-based (any employer)
    ("avionics software engineer", "United Kingdom"),
    ("flight software engineer DO-178C", "United Kingdom"),
    ("embedded software engineer HAPS UAV", "United Kingdom"),
    ("guidance navigation control software aerospace", "United Kingdom"),
    # Named competitors / primes (keeps them watched even off Workday)
    ("BAE Systems software engineer avionics", "United Kingdom"),
    ("Leonardo software engineer avionics", "United Kingdom"),      # incl. Westland/Yeovil
    ("Prismatic PHASA-35 software engineer", "United Kingdom"),
    ("Sceye stratospheric software engineer", "United States"),
    ("Skydweller Aero software engineer", "United States"),
    ("AeroVironment software engineer UAV", "United States"),
]

# Reference only (labels competitor hits in the report).
COMPETITORS = [
    "BAE", "PHASA", "Prismatic", "Sceye", "Skydweller", "AeroVironment",
    "Sunglider", "HAPSMobile", "Stratobus", "Aurora", "Odysseus",
    "Archangel", "Shield AI", "Anduril", "Airbus", "Thales", "Leonardo",
    "Westland", "Lockheed", "General Atomics", "SoftBank", "NTT",
]


def job_key(company, title, location, url):
    if url:
        return url.split("?")[0]
    return f"{company}|{title}|{location}".lower()


def desc_hash(text):
    return hashlib.sha1((text or "").encode("utf-8", "ignore")).hexdigest()[:12]


def label_competitor(company, title, desc):
    blob = f"{company} {title} {desc[:400]}".lower()
    hits = [c for c in COMPETITORS if c.lower() in blob]
    return ", ".join(sorted(set(hits))) if hits else ""


# --- Workday listing (no descriptions; cheap) ------------------------------
def list_workday(company_key, search_text, cap=160):
    if company_key not in WORKDAY_COMPANIES:
        print(f"  ! unknown workday company '{company_key}'")
        return []
    config = WORKDAY_COMPANIES[company_key]
    name = config["name"]
    rows, offset = [], 0
    while offset < cap:
        try:
            r = requests.post(
                config["api_url"], headers=HEADERS,
                json={"appliedFacets": {}, "limit": 20, "offset": offset,
                      "searchText": search_text},
                timeout=30,
            )
            r.raise_for_status()
            postings = r.json().get("jobPostings", [])
        except requests.RequestException as e:
            print(f"  ! {name}: {e}")
            break
        if not postings:
            break
        for j in postings:
            title = j.get("title", "")
            if not TITLE_KEEP.search(title):
                continue
            path = j.get("externalPath", "")
            rows.append({
                "company": name,
                "title": title,
                "location": j.get("locationsText", ""),
                "url": f"{config['careers_url']}{path}",
                "source": "Workday",
                "_path": path,
                "_key_co": company_key,
            })
        if len(postings) < 20:
            break
        offset += 20
        time.sleep(0.25)
    print(f"  {name} ('{search_text}'): {len(rows)} software/aero roles")
    return rows


# --- LinkedIn listing (via existing scraper, no descriptions) --------------
def list_linkedin(keywords, location, max_jobs=25):
    if not LINKEDIN_SCRIPT.exists():
        print("  ! linkedin_scraper.py not found; skipping LinkedIn")
        return []
    tmp = STATE_DIR / "_ln_tmp.json"
    tmp.unlink(missing_ok=True)
    cmd = [sys.executable, str(LINKEDIN_SCRIPT), "-k", keywords, "-l", location,
           "-n", str(max_jobs), "-t", "30d", "--no-description",
           "-o", str(tmp), "--no-merge"]
    try:
        subprocess.run(cmd, timeout=150, capture_output=True, text=True)
    except Exception as e:
        print(f"  ! LinkedIn '{keywords[:30]}': {e}")
        return []
    if not tmp.exists():
        return []
    data = json.load(open(tmp, encoding="utf-8"))
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    rows = []
    for j in jobs:
        rows.append({
            "company": j.get("company", "?"),
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "url": (j.get("url", "") or "").split("?")[0],
            "source": "LinkedIn",
            "_path": None,
            "_key_co": None,
        })
    print(f"  LinkedIn ('{keywords[:40]}'): {len(rows)} roles")
    return rows


# Lazily-built LinkedIn scraper instance, reused to fetch single descriptions.
_LN = None


def _linkedin_scraper():
    global _LN
    if _LN is None:
        try:
            sys.path.insert(0, str(BASE_DIR / "scrap_with_batch"))
            from linkedin_scraper import LinkedInScraper  # noqa: E402
            _LN = LinkedInScraper(max_workers=1)
        except Exception as e:
            print(f"  ! could not init LinkedIn scraper for descriptions: {e}")
            _LN = False
    return _LN or None


def enrich_description(row, do_fetch):
    """Fetch a full description for a NEW role only (Workday or LinkedIn)."""
    if not do_fetch:
        return ""
    if row["source"] == "Workday" and row.get("_path"):
        d = fetch_job_details(row["_key_co"], WORKDAY_COMPANIES[row["_key_co"]], row["_path"])
        return re.sub(r"<[^>]+>", " ", d.get("description", "") or "")
    if row["source"] == "LinkedIn" and row.get("url"):
        ln = _linkedin_scraper()
        if not ln:
            return ""
        try:
            # LinkedIn URLs are ".../jobs/view/<slug>-<numeric_id>"; the numeric
            # id is the trailing run of digits.
            m = re.search(r"(\d{6,})", row["url"])
            job_id = m.group(1) if m else ln._extract_job_id(row["url"])
            if not job_id:
                return ""
            desc = ln._fetch_description_via_api(job_id)
            return re.sub(r"<[^>]+>", " ", desc or "")
        except Exception:
            return ""
    return ""


def main():
    p = argparse.ArgumentParser(description="Monitor aerospace / competitor job postings.")
    p.add_argument("--no-linkedin", action="store_true", help="Workday only")
    p.add_argument("--no-desc", action="store_true", help="Do not fetch descriptions for NEW roles")
    p.add_argument("--list", action="store_true", help="Show configured watch list and exit")
    args = p.parse_args()

    if args.list:
        print("Workday queries:")
        for c, q in WORKDAY_QUERIES:
            print(f"  {c:18} search='{q}'")
        print("LinkedIn queries:")
        for k, l in LINKEDIN_QUERIES:
            print(f"  '{k}' @ {l}")
        print("Competitor labels:", ", ".join(COMPETITORS))
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")

    # 1. Collect the live set
    print("Collecting Workday...")
    live = {}
    for c, q in WORKDAY_QUERIES:
        for row in list_workday(c, q):
            live[job_key(row["company"], row["title"], row["location"], row["url"])] = row
    if not args.no_linkedin:
        print("Collecting LinkedIn...")
        for k, l in LINKEDIN_QUERIES:
            for row in list_linkedin(k, l):
                live.setdefault(job_key(row["company"], row["title"], row["location"], row["url"]), row)

    print(f"\nLive set: {len(live)} unique roles")

    # Which sources did we actually query this run? Roles from sources we did NOT
    # query must be carried forward untouched, not treated as closed.
    collected_sources = {"Workday"}
    if not args.no_linkedin:
        collected_sources.add("LinkedIn")

    # 2. Load previous snapshot
    prev = {}
    if STATE_FILE.exists():
        prev = json.load(open(STATE_FILE, encoding="utf-8"))
    first_run = not prev

    new_keys = [k for k in live if k not in prev]
    # CLOSED only counts roles whose source we queried this run.
    closed_keys = [k for k, r in prev.items()
                   if k not in live and r.get("source") in collected_sources]

    # 3. Enrich NEW roles with descriptions
    print(f"NEW: {len(new_keys)}  CLOSED: {len(closed_keys)}  "
          f"({'first run - baseline' if first_run else 'diff vs last run'})")
    new_rows = []
    for k in new_keys:
        row = live[k]
        desc = enrich_description(row, do_fetch=not args.no_desc)
        row_out = {kk: vv for kk, vv in row.items() if not kk.startswith("_")}
        row_out["description"] = desc.strip()
        row_out["competitor"] = label_competitor(row["company"], row["title"], desc)
        row_out["first_seen"] = now
        new_rows.append(row_out)
        time.sleep(0.15)

    # 4. Update state.
    #    Carry forward prev roles from sources we did NOT query this run, so a
    #    --no-linkedin run doesn't wipe LinkedIn roles from the snapshot.
    snapshot = {}
    for k, rec in prev.items():
        if rec.get("source") not in collected_sources and k not in live:
            snapshot[k] = rec
    for k, row in live.items():
        rec = prev.get(k, {})
        snapshot[k] = {
            "company": row["company"], "title": row["title"],
            "location": row["location"], "url": row["url"], "source": row["source"],
            "first_seen": rec.get("first_seen", now), "last_seen": now,
        }
    json.dump(snapshot, open(STATE_FILE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    # 5. Write report
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = REPORT_DIR / f"report_{stamp}.md"
    lines = [f"# Job monitor report — {now}", ""]
    lines.append(f"_Live: {len(live)} roles · **NEW: {len(new_keys)}** · "
                 f"**CLOSED: {len(closed_keys)}** · "
                 f"{'baseline run' if first_run else 'diff vs previous run'}_")
    lines.append("")

    lines.append(f"## 🟢 New roles ({len(new_rows)})")
    if not new_rows:
        lines.append("_None since last run._")
    for i, r in enumerate(sorted(new_rows, key=lambda x: (x["source"], x["company"])), 1):
        tag = f" · ⚔️ {r['competitor']}" if r["competitor"] else ""
        lines.append(f"\n### {i}. {r['title']}")
        lines.append(f"**{r['company']}** · {r['location']} · _{r['source']}_{tag}  ")
        if r["url"]:
            lines.append(f"<{r['url']}>")
        if r["description"]:
            lines.append("")
            lines.append(r["description"][:4000])
        lines.append("")

    lines.append(f"\n## 🔴 Closed roles ({len(closed_keys)})")
    if not closed_keys:
        lines.append("_None._")
    for k in closed_keys:
        r = prev[k]
        lines.append(f"- **{r['title']}** — {r['company']} · {r['location']} "
                     f"(open since {r.get('first_seen', '?')[:10]})")

    report.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nReport : {report}")
    print(f"State  : {STATE_FILE} ({len(snapshot)} roles tracked)")
    if first_run:
        print("This was the baseline. Re-run later to see NEW / CLOSED deltas.")


if __name__ == "__main__":
    main()
