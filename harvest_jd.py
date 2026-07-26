#!/usr/bin/env python3
"""
JD Harvester - pull peer job descriptions to mine for your own listings.

Scrapes one or more Workday companies, keeps only roles whose title matches a
level (senior/principal/lead/...) and a discipline (software/embedded/...), then
writes a clean, readable Markdown digest of the descriptions plus a JSON dump.

Use it when you are HIRING and want to see how competitors write their posts.

Usage:
    # Default: UK senior/principal software roles at the aerospace primes
    python harvest_jd.py

    # Any companies (keys from workday_scraper --list), any country
    python harvest_jd.py --companies airbus,thales,rtx_collins --uk
    python harvest_jd.py --companies nvidia,arm_scraper --country "United States of America"

    # Change what counts as a match
    python harvest_jd.py --level "principal|staff|architect" --field "software|firmware|avionics"

    # Search the DESCRIPTION body (FPGA/VHDL/C++ rarely appear in the title)
    python harvest_jd.py --search "FPGA" --keywords "fpga|vhdl|verilog"
    python harvest_jd.py --search "C++"                       # searchText narrows to C++ roles
    python harvest_jd.py --search "FPGA" --level "."          # any seniority

    # Skip the UK filter (scan all locations)
    python harvest_jd.py --no-uk
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scrapers"))
from workday_scraper import (  # noqa: E402
    WORKDAY_COMPANIES,
    HEADERS,
    fetch_job_details,
    get_location_facet_id,
)
import requests  # noqa: E402

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"

# Sensible default: the aerospace/defence primes verified on Workday
DEFAULT_COMPANIES = ["airbus", "thales", "rtx_collins"]
DEFAULT_LEVEL = r"senior|principal|lead|staff|architect|expert|snr"
DEFAULT_FIELD = (
    r"software|firmware|embedded|avionics|flight|control|"
    r"c\+\+|python|full[- ]?stack|back[- ]?end|platform|developer|programmer|"
    r"fpga|vhdl|verilog|rtl|hdl|dsp|hardware|electronics"
)


def strip_html(text: str) -> str:
    """Turn a Workday HTML description into readable plain text."""
    text = re.sub(r"(?i)</(p|div|li|h\d|br|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "  - ", text)
    text = re.sub(r"<[^>]+>", "", text)
    # decode the handful of entities Workday emits
    for a, b in [("&amp;", "&"), ("&#43;", "+"), ("&#39;", "'"), ("&quot;", '"'),
                 ("&nbsp;", " "), ("&#xa;", "\n"), ("&amp;#xa;", "\n"), ("​", "")]:
        text = text.replace(a, b)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def harvest_company(key, level_re, field_re, uk, country, cap, search_text="", keyword_re=None):
    if key not in WORKDAY_COMPANIES:
        print(f"  ! unknown company '{key}' (see: python scrapers/workday_scraper.py --list)")
        return []
    config = WORKDAY_COMPANIES[key]
    name = config["name"]

    facets = {}
    if uk:
        loc_id = get_location_facet_id(config, country)
        if loc_id:
            facets["locationCountry"] = [loc_id]
        else:
            print(f"  ! {name}: no '{country}' facet; scanning all locations")

    # When the caller supplies a body search or keyword filter, the title no longer
    # has to name the discipline (FPGA/VHDL etc. live in the description). searchText
    # narrows server-side (Workday searches title + body); keyword_re confirms after fetch.
    body_mode = bool(search_text) or bool(keyword_re)

    matched = {}
    offset = 0
    scanned = 0
    while offset < cap:
        try:
            r = requests.post(
                config["api_url"], headers=HEADERS,
                json={"appliedFacets": facets, "limit": 20, "offset": offset,
                      "searchText": search_text or ""},
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            print(f"  ! {name}: {e}")
            break
        postings = data.get("jobPostings", [])
        if not postings:
            break
        scanned += len(postings)
        for j in postings:
            t = j.get("title", "")
            if not level_re.search(t):
                continue
            if body_mode or field_re.search(t):
                matched[j.get("externalPath", "")] = j
        if len(postings) < 20:
            break
        offset += 20
        time.sleep(0.3)

    print(f"  {name}: {len(matched)} title-qualified (of {scanned} roles scanned)")

    rows = []
    kept = 0
    for path, j in matched.items():
        details = fetch_job_details(key, config, path)
        desc = strip_html(details.get("description", ""))
        title = j.get("title", "")
        # Confirm keyword actually appears in title or body (searchText is fuzzy)
        if keyword_re and not keyword_re.search(f"{title}\n{desc}"):
            time.sleep(0.2)
            continue
        rows.append({
            "company": name,
            "title": title,
            "location": j.get("locationsText", ""),
            "url": f"{config['careers_url']}{path}",
            "description": desc,
        })
        kept += 1
        time.sleep(0.2)
    if keyword_re:
        print(f"    -> {kept} kept after keyword filter")
    return rows


def write_markdown(rows, path, meta):
    lines = [f"# Peer job descriptions — {meta['when']}", ""]
    lines.append(f"_{len(rows)} roles · companies: {meta['companies']} · "
                 f"level: `{meta['level']}` · field: `{meta['field']}` · "
                 f"{'UK only' if meta['uk'] else 'all locations'}_")
    lines.append("")
    lines.append("## Index")
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. **{r['title']}** — {r['company']} · {r['location']}")
    lines.append("\n---\n")
    for i, r in enumerate(rows, 1):
        lines.append(f"## {i}. {r['title']}")
        lines.append(f"**{r['company']}** · {r['location']}  ")
        lines.append(f"<{r['url']}>")
        lines.append("")
        lines.append(r["description"] or "_(no description returned)_")
        lines.append("\n---\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description="Harvest peer job descriptions for hiring research.")
    p.add_argument("--companies", default=",".join(DEFAULT_COMPANIES),
                   help="Comma-separated company keys (default: airbus,thales,rtx_collins)")
    p.add_argument("--level", default=DEFAULT_LEVEL, help="Regex for seniority in title (use '.' to allow any)")
    p.add_argument("--field", default=DEFAULT_FIELD, help="Regex for discipline in title (ignored when --search/--keywords given)")
    p.add_argument("--search", default="", help="Body search (Workday searchText, matches title+description), e.g. 'FPGA' or 'C++'")
    p.add_argument("--keywords", default=None, help="Require this regex in title+description after fetch, e.g. 'fpga|vhdl|verilog'")
    p.add_argument("--uk", dest="uk", action="store_true", default=True, help="Filter to UK (default on)")
    p.add_argument("--no-uk", dest="uk", action="store_false", help="Scan all locations")
    p.add_argument("--country", default="United Kingdom", help="Country for the location filter")
    p.add_argument("--cap", type=int, default=400, help="Max postings to scan per company")
    p.add_argument("--out", default=None, help="Output basename (default: aero_jd_<timestamp>)")
    args = p.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    level_re = re.compile(rf"\b({args.level})\b", re.I)
    field_re = re.compile(f"({args.field})", re.I)
    keyword_re = re.compile(f"({args.keywords})", re.I) if args.keywords else None
    companies = [c.strip() for c in args.companies.split(",") if c.strip()]

    filt = f"search='{args.search}'" if args.search else f"field=/{args.field}/"
    print(f"Harvesting {companies} | level=/{args.level}/ {filt}"
          f"{' keywords=/' + args.keywords + '/' if args.keywords else ''} "
          f"{'UK' if args.uk else 'all'}")
    rows = []
    for key in companies:
        rows += harvest_company(key, level_re, field_re, args.uk, args.country, args.cap,
                                search_text=args.search, keyword_re=keyword_re)

    if not rows:
        print("\nNo matching roles found. Try --no-uk, loosen --level, or drop --keywords.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = args.out or f"aero_jd_{stamp}"
    md_path = OUTPUT_DIR / f"{base}.md"
    json_path = OUTPUT_DIR / f"{base}.json"
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(rows, md_path, {
        "when": stamp, "companies": ", ".join(companies),
        "level": args.level, "field": args.field, "uk": args.uk,
    })

    print(f"\n{len(rows)} descriptions harvested.")
    print(f"  Readable : {md_path}")
    print(f"  Raw JSON : {json_path}")
    print("  Excel    : run  python export_to_excel.py")


if __name__ == "__main__":
    main()
