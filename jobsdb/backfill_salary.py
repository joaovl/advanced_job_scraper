#!/usr/bin/env python3
"""Parse salary from every job's description into the salary_* columns.

Run once after adding the salary columns (ingest does it for new rows):
    python -m jobsdb.backfill_salary
"""
from sqlalchemy import text

from .db import get_engine, init_schema
from .salary import parse_salary
from .location import normalize_country


def main():
    engine = get_engine(create_db_if_missing=True)
    init_schema(engine)
    with engine.connect() as c:
        rows = c.execute(text("SELECT id, description, location FROM jobs")).fetchall()

    parsed = countries = 0
    with engine.begin() as c:
        for jid, desc, loc in rows:
            country = normalize_country(loc)
            if country:
                countries += 1
            s = parse_salary(desc)
            if s:
                parsed += 1
            c.execute(text(
                "UPDATE jobs SET salary_min=:mn, salary_max=:mx, "
                "salary_currency=:cur, salary_period=:per, job_country=:ct WHERE id=:i"),
                {"mn": s["min"] if s else None, "mx": s["max"] if s else None,
                 "cur": s["currency"] if s else None, "per": s["period"] if s else None,
                 "ct": country, "i": jid})
    print(f"Salary parsed for {parsed}/{len(rows)} jobs; country set for {countries}.")


if __name__ == "__main__":
    main()
