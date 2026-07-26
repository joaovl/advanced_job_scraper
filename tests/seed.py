"""Deterministic seed data for the test database.

12 rows with known, hand-checked properties so tests can assert exact counts
and subsets instead of "> 0".
"""
from datetime import datetime, timezone
from sqlalchemy import text
from jobsdb.db import jobs, metadata, init_schema
from jobsdb.salary import parse_salary

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)

# (company, title, source, is_competitor, is_new, ai_score, description)
SEED = [
    ("BAE Systems",   "Senior FPGA Engineer",        "LinkedIn", True,  True,  9,  "VHDL and FPGA design for avionics, DO-178C and DO-254. Salary: £70,000 - £90,000 per annum."),
    ("Prismatic",     "Principal FPGA Engineer",     "LinkedIn", True,  True,  8,  "PHASA-35 HAPS FPGA and VHDL firmware, real-time."),
    ("Leonardo",      "Avionics Software Engineer",  "LinkedIn", True,  False, 7,  "Embedded C++ avionics software to DO-178C. Yeovil."),
    ("Sceye",         "Software Architect",          "LinkedIn", True,  False, 6,  "Stratospheric platform software, python and C++."),
    ("Airbus",        "Senior Avionics Developer",   "Workday",  False, True,  9,  "Avionics software, DO-178C, real-time C. The salary range is $120,000.00 to $150,000.00 USD."),
    ("Thales",        "Embedded C/C++ Engineer",     "Workday",  False, True,  8,  "Embedded C and C++ with DO-178 verification, MISRA."),
    ("Boeing",        "Flight Software Engineer",    "Workday",  False, False, 5,  "Flight software in C for commercial platforms."),
    ("Northrop",      "Radar Software Engineer",     "Workday",  False, False, 4,  "Radar signal processing software, C and C++."),
    ("Wise",          "Backend Engineer",            "LinkedIn", False, False, 2,  "Python and Go backend for fintech payments."),
    ("Roku",          "Senior Software Engineer",    "LinkedIn", False, True,  None, "C++ embedded media platform software."),
    ("RTX / Collins", "Principal Software Engineer", "Workday",  False, False, None, "Foundation software, LynxOS-178, obsolescence."),
    ("Airbus",        "Data Engineer",               "Workday",  False, False, None, "Data pipelines in python, not embedded."),
]


# Neutral filler so every description exceeds the 200-char floor the AI task uses
# to skip stubs. Contains no 'fpga'/'avionics' so it can't skew keyword tests.
FILLER = (" This role involves collaborating with cross-functional teams and "
          "following the full software development lifecycle with strong "
          "engineering practices, code reviews and quality standards throughout "
          "delivery, mentoring peers and contributing to technical direction.")


def seed(engine):
    """Truncate and load the deterministic dataset. Returns list of dict rows."""
    init_schema(engine)
    rows = []
    with engine.begin() as c:
        c.execute(text("TRUNCATE jobs RESTART IDENTITY"))
        for i, (co, title, src, comp, new, score, desc) in enumerate(SEED):
            desc = desc + FILLER
            key = f"seed://{i}"
            match = (score is not None and score >= 7)
            sal = parse_salary(desc) or {}
            c.execute(text(
                "INSERT INTO jobs (job_key, source, company, title, location, url, "
                "description, competitor, is_competitor, status, is_new, ai_score, "
                "ai_match, ai_reasons, salary_min, salary_max, salary_currency, "
                "salary_period, first_seen, last_seen, search) VALUES "
                "(:k,:src,:co,:t,:loc,:u,:d,:comp,:isc,'open',:new,:sc,:m,:rz,"
                ":smin,:smax,:scur,:sper,:fs,:ls, to_tsvector('english', :ft))"),
                {"k": key, "src": src, "co": co, "t": title, "loc": "UK",
                 "u": f"https://example.test/{i}", "d": desc,
                 "comp": co if comp else "", "isc": comp, "new": new,
                 "sc": score, "m": (match if score is not None else None),
                 "rz": ("strong match" if match else "") if score is not None else None,
                 "smin": sal.get("min"), "smax": sal.get("max"),
                 "scur": sal.get("currency"), "sper": sal.get("period"),
                 "fs": NOW, "ls": NOW, "ft": f"{co} {title} {desc}"})
            rows.append({"i": i, "company": co, "title": title, "source": src,
                         "is_competitor": comp, "is_new": new, "ai_score": score,
                         "ai_match": match if score is not None else None, "desc": desc})
    return rows


# Precomputed expectations (hand-checked against SEED above)
EXPECT = {
    "total": 12,
    "competitor": 4,          # BAE, Prismatic, Leonardo, Sceye
    "new": 5,                 # rows 0,1,4,5,9
    "scored": 9,              # rows with ai_score not None
    "matched": 5,             # score >= 7: rows 0,1,2,4,5
    "salaried": 2,            # rows 0 (GBP 70-90k) and 4 (USD 120-150k)
    "fpga": 2,                # 'FPGA' in text: rows 0,1
    "min8": 4,                # ai_score >= 8: rows 0,1,4,5
    "workday": 6,
    "linkedin": 6,
}
