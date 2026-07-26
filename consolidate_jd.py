#!/usr/bin/env python3
"""
Consolidate multiple job-description JSON files (harvest_jd + linkedin_scraper
outputs) into a single deduped, readable Markdown digest for hiring research.

All inputs share the schema: {title, company, location, url, description, ...}.

Usage:
    python consolidate_jd.py output/primes_*.json output/linkedin_*.json --out master_jd
"""

import argparse
import glob
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"


def load(pattern_or_path):
    rows = []
    for path in glob.glob(pattern_or_path):
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print(f"  ! skip {path}: {e}")
            continue
        jobs = data if isinstance(data, list) else data.get("jobs", [])
        src = "LinkedIn" if "linkedin" in path.lower() else "Workday"
        for j in jobs:
            rows.append({
                "title": j.get("title", ""),
                "company": j.get("company", "?"),
                "location": j.get("location", ""),
                "url": j.get("url", ""),
                "description": (j.get("description", "") or "").strip(),
                "source": j.get("source", src),
            })
    return rows


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        key = r["url"] or f"{r['company']}|{r['title']}|{r['location']}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    p = argparse.ArgumentParser(description="Consolidate job JSONs into one digest.")
    p.add_argument("inputs", nargs="+", help="JSON files or globs")
    p.add_argument("--out", default="master_jd", help="Output basename")
    p.add_argument("--min-desc", type=int, default=200,
                   help="Drop rows with description shorter than this")
    args = p.parse_args()

    rows = []
    for pat in args.inputs:
        rows += load(pat)
    rows = dedupe(rows)
    rows = [r for r in rows if len(r["description"]) >= args.min_desc]
    rows.sort(key=lambda r: (r["source"], r["company"], r["title"]))

    if not rows:
        print("No rows after filtering.")
        return

    by_src = Counter(r["source"] for r in rows)
    by_co = Counter(r["company"] for r in rows)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    lines = [f"# Consolidated job-description library — {stamp}", ""]
    lines.append(f"_{len(rows)} unique roles · "
                 + " · ".join(f"{s}: {n}" for s, n in by_src.most_common()) + "_")
    lines.append("")
    lines.append("## Companies")
    for c, n in by_co.most_common():
        lines.append(f"- **{c}** — {n}")
    lines.append("\n## Index")
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. [{r['source']}] **{r['title']}** — {r['company']} · {r['location']}")
    lines.append("\n---\n")
    for i, r in enumerate(rows, 1):
        lines.append(f"## {i}. {r['title']}")
        lines.append(f"**{r['company']}** · {r['location']} · _{r['source']}_  ")
        if r["url"]:
            lines.append(f"<{r['url']}>")
        lines.append("")
        lines.append(r["description"])
        lines.append("\n---\n")

    md = OUTPUT_DIR / f"{args.out}.md"
    js = OUTPUT_DIR / f"{args.out}.json"
    md.write_text("\n".join(lines), encoding="utf-8")
    js.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{len(rows)} unique roles consolidated.")
    print("  Sources:", dict(by_src))
    print(f"  Companies: {len(by_co)}")
    print(f"  Readable : {md}")
    print(f"  Raw JSON : {js}")


if __name__ == "__main__":
    main()
