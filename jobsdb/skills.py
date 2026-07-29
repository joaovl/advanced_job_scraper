#!/usr/bin/env python3
"""
Competitor / market intelligence over the jobs DB.

Answers the recruiting questions: who is hiring, for what skills, and what value
(salary, seniority) are they offering? Extracts a controlled vocabulary of
engineering skills from each role's title+description and aggregates it, with
salary percentiles and a seniority breakdown, for:

    the whole UK market       python -m jobsdb.skills --uk
    a single company          python -m jobsdb.skills --company "Leonardo UK"
    the competitor set        python -m jobsdb.skills --competitors
    new roles in last N days  python -m jobsdb.skills --uk --new-days 7

Skill detection is a curated regex vocabulary (below) — precision over recall,
so counts are trustworthy rather than fuzzy.
"""
import argparse
import re
from collections import Counter

from sqlalchemy import text

from .db import get_engine

# canonical skill -> alternation of surface forms. Word-boundaried, case-insensitive.
# Kept deliberately unambiguous (no bare "C"/"go"/"R") so counts don't inflate.
SKILL_TERMS = {
    # languages
    "C++": r"c\+\+|\bcpp\b",
    "Python": r"\bpython\b",
    "Rust": r"\brust\b",
    "Java": r"\bjava\b(?!script)",
    "JavaScript": r"\bjavascript\b|\btypescript\b",
    "C#": r"\bc#\b|\.net\b",
    "MATLAB/Simulink": r"\bmatlab\b|\bsimulink\b",
    "Ada": r"\bada\b|spark ada",
    "Go": r"\bgolang\b",
    # embedded / aerospace-critical
    "Embedded": r"\bembedded\b",
    "Firmware": r"\bfirmware\b",
    "RTOS": r"\brtos\b|vxworks|freertos|integrity rtos",
    "DO-178C": r"do-?178",
    "DO-254": r"do-?254",
    "ARINC": r"\barinc\b",
    "AUTOSAR": r"\bautosar\b",
    "FPGA/HDL": r"\bfpga\b|\bvhdl\b|\bverilog\b",
    "Safety-critical": r"safety[- ]critical|misra|iec ?61508|def ?stan",
    "GNC": r"\bgnc\b|guidance,? navigation",
    "Autonomy/Robotics": r"\bautonomy\b|autonomous|\brobotics?\b|\bros2?\b|slam\b",
    "Model-Based": r"model[- ]based|\bmbse\b|\bmbd\b",
    # platform / cloud / data
    "Linux": r"\blinux\b",
    "Docker": r"\bdocker\b",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "AWS": r"\baws\b|amazon web services",
    "Azure": r"\bazure\b",
    "CI/CD": r"\bci/?cd\b|jenkins|gitlab ci|github actions",
    "Machine Learning": r"machine learning|deep learning|\bml\b|neural network",
    "SQL/Databases": r"\bsql\b|postgres|mysql",
    # practice
    "Agile/Scrum": r"\bagile\b|\bscrum\b",
    "Security Clearance": r"security clearance|\bsc cleared\b|\bdv cleared\b|dv clearance",
}
SKILL_RE = {k: re.compile(v, re.I) for k, v in SKILL_TERMS.items()}

SENIORITY = {
    "Principal": re.compile(r"\bprincipal\b", re.I),
    "Lead/Staff": re.compile(r"\blead\b|\bstaff\b|\bhead of\b", re.I),
    "Senior": re.compile(r"\bsenior\b|\bsnr\b|\bsr\.?\b", re.I),
    "Graduate/Junior": re.compile(r"\bgraduate\b|\bjunior\b|\bintern\b|\bapprentice\b|early career", re.I),
}


def extract_skills(text_blob):
    """Return the set of canonical skills mentioned in a title+description blob."""
    return {name for name, rx in SKILL_RE.items() if rx.search(text_blob or "")}


def seniority_of(title):
    for level, rx in SENIORITY.items():          # Principal wins over Senior, etc.
        if rx.search(title or ""):
            return level
    return "Mid/Other"


def _where(company=None, competitors=False, uk=False, new_days=None):
    conds, params = ["1=1"], {}
    if company:
        conds.append("company = :company")
        params["company"] = company
    if competitors:
        conds.append("is_competitor")
    if uk:
        conds.append("job_country = 'United Kingdom'")
    if new_days:
        conds.append("first_seen >= now() - (:nd || ' days')::interval")
        params["nd"] = str(int(new_days))
    return " AND ".join(conds), params


def report(engine, company=None, competitors=False, uk=False, new_days=None, top=20):
    where, params = _where(company, competitors, uk, new_days)
    with engine.connect() as c:
        rows = c.execute(text(
            f"SELECT company, title, description, salary_min, salary_max, salary_currency "
            f"FROM jobs WHERE {where}"), params).all()

    n = len(rows)
    skill_counts = Counter()
    seniority_counts = Counter()
    company_counts = Counter()
    sals = []
    for co, title, desc, smin, smax, cur in rows:
        blob = f"{title} {desc or ''}"
        for s in extract_skills(blob):
            skill_counts[s] += 1
        seniority_counts[seniority_of(title)] += 1
        company_counts[co] += 1
        val = smax or smin
        if val and (cur in (None, "GBP", "£")) and 15000 <= val <= 400000:
            sals.append(val)

    scope = (company or ("competitors" if competitors else "market"))
    if uk:
        scope += " · UK"
    if new_days:
        scope += f" · new in {new_days}d"

    out = [f"# Hiring intelligence — {scope}", "",
           f"**{n} roles** analysed.", ""]

    out.append("## Skills in demand")
    if skill_counts:
        for skill, cnt in skill_counts.most_common(top):
            bar = "#" * max(1, round(30 * cnt / skill_counts.most_common(1)[0][1]))
            out.append(f"  {skill:20} {cnt:4}  {bar}")
    else:
        out.append("  (no skills matched)")

    out.append("")
    out.append("## Seniority mix")
    for level in ("Principal", "Lead/Staff", "Senior", "Mid/Other", "Graduate/Junior"):
        if seniority_counts.get(level):
            out.append(f"  {level:16} {seniority_counts[level]:4}")

    out.append("")
    out.append("## Value offered (GBP, from roles that state pay)")
    if sals:
        sals.sort()
        def pct(p): return sals[min(len(sals) - 1, int(p * len(sals)))]
        out.append(f"  roles with salary : {len(sals)}")
        out.append(f"  median            : £{pct(0.5):,.0f}")
        out.append(f"  25th–75th pct     : £{pct(0.25):,.0f} – £{pct(0.75):,.0f}")
        out.append(f"  range             : £{sals[0]:,.0f} – £{sals[-1]:,.0f}")
    else:
        out.append("  (no roles state salary in this scope)")

    if not company:
        out.append("")
        out.append("## Top hiring employers")
        for co, cnt in company_counts.most_common(top):
            out.append(f"  {cnt:4}  {co}")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Hiring intelligence over the jobs DB.")
    ap.add_argument("--company", help="Single company name (exact)")
    ap.add_argument("--competitors", action="store_true", help="Only competitor-labelled roles")
    ap.add_argument("--uk", action="store_true", help="Restrict to UK roles")
    ap.add_argument("--new-days", type=int, help="Only roles first seen in the last N days")
    ap.add_argument("--top", type=int, default=20, help="Rows per section (default 20)")
    args = ap.parse_args()

    print(report(get_engine(), company=args.company, competitors=args.competitors,
                 uk=args.uk, new_days=args.new_days, top=args.top))


if __name__ == "__main__":
    main()
