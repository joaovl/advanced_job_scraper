#!/usr/bin/env python3
"""Parse salary from every job's description into the salary_* columns.

Run once after adding the salary columns (ingest does it for new rows):
    python -m jobsdb.backfill_salary
"""
from sqlalchemy import text

from .db import get_engine, init_schema
from .salary import parse_salary


def main():
    engine = get_engine(create_db_if_missing=True)
    init_schema(engine)
    with engine.connect() as c:
        rows = c.execute(text("SELECT id, description FROM jobs")).fetchall()

    parsed = 0
    with engine.begin() as c:
        for jid, desc in rows:
            s = parse_salary(desc)
            if not s:
                continue
            c.execute(text(
                "UPDATE jobs SET salary_min=:mn, salary_max=:mx, "
                "salary_currency=:cur, salary_period=:per WHERE id=:i"),
                {"mn": s["min"], "mx": s["max"], "cur": s["currency"],
                 "per": s["period"], "i": jid})
            parsed += 1
    print(f"Salary parsed for {parsed}/{len(rows)} jobs.")


if __name__ == "__main__":
    main()
