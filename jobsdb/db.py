#!/usr/bin/env python3
"""
Postgres storage layer for the job library.

Connection comes from the DATABASE_URL environment variable, e.g.:
    postgresql+psycopg2://postgres:PASSWORD@localhost:5432/aalto_jobs

If unset, defaults to a local 'aalto_jobs' database on the running Postgres 16
instance (postgres user, no password / trust auth). Override with DATABASE_URL.

Schema: a single `jobs` table keyed by a stable job_key, with first/last-seen
history, a competitor label, source (Workday/LinkedIn), open/closed status, and
a full-text search vector over company + title + description.
"""
import os
from sqlalchemy import (
    create_engine, MetaData, Table, Column, Integer, Text, Boolean,
    TIMESTAMP, text,
)
from sqlalchemy.engine import URL
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR


def get_url():
    """Connection source, in priority order:

    1. DATABASE_URL (full SQLAlchemy URL)
    2. PG* env vars (PGUSER/PGPASSWORD/PGHOST/PGPORT/PGDATABASE) — safest for
       passwords with special characters, since URL.create escapes them.
    3. Local defaults (postgres@localhost:5432/aalto_jobs).
    """
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    # Defaults match the local Docker Postgres created by jobsdb/setup_db.ps1
    # (port 5433, user/pw postgres/aalto). Override with PG* env or DATABASE_URL.
    return URL.create(
        "postgresql+psycopg2",
        username=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "aalto"),
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5433")),
        database=os.environ.get("PGDATABASE", "aalto_jobs"),
    )


def get_engine(create_db_if_missing=True):
    url = get_url()
    # pool_pre_ping avoids stale-connection 500s after the DB/idle recycles.
    eng = create_engine(url, future=True, pool_pre_ping=True)
    if create_db_if_missing:
        try:
            with eng.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception:
            _create_database(url)
            eng = create_engine(url, future=True)
    return eng


def _create_database(url):
    """Connect to the maintenance 'postgres' db and CREATE DATABASE."""
    from sqlalchemy.engine.url import make_url
    u = make_url(url)
    dbname = u.database
    admin = u.set(database="postgres")
    admin_eng = create_engine(admin, future=True, isolation_level="AUTOCOMMIT")
    with admin_eng.connect() as c:
        exists = c.execute(
            text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": dbname}
        ).scalar()
        if not exists:
            c.execute(text(f'CREATE DATABASE "{dbname}"'))


metadata = MetaData()

jobs = Table(
    "jobs", metadata,
    Column("id", Integer, primary_key=True),
    Column("job_key", Text, unique=True, nullable=False),
    Column("source", Text),              # Workday | LinkedIn
    Column("company", Text),
    Column("title", Text),
    Column("location", Text),
    Column("url", Text),
    Column("description", Text),
    Column("competitor", Text),          # matched competitor label(s), '' if none
    Column("is_competitor", Boolean, default=False),
    Column("posted_date", Text),
    Column("status", Text, default="open"),   # open | closed
    Column("is_new", Boolean, default=True),  # newly inserted at last ingest
    Column("first_seen", TIMESTAMP(timezone=True)),
    Column("last_seen", TIMESTAMP(timezone=True)),
    # AI match scoring (job_filter_ai): score 1-10 vs the target CV/profile
    Column("ai_score", Integer),
    Column("ai_match", Boolean),
    Column("ai_reasons", Text),
    Column("ai_scored_at", TIMESTAMP(timezone=True)),
    Column("search", TSVECTOR),
    Column("raw", JSONB),
)


def init_schema(engine):
    metadata.create_all(engine)
    with engine.begin() as c:
        # Full-text index and a helper index for common filters.
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_search ON jobs USING GIN(search)"))
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)"))
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_flags ON jobs(source, is_competitor, is_new, status)"))
        # Add AI columns to pre-existing tables (no-op if already present).
        for col, typ in [("ai_score", "INTEGER"), ("ai_match", "BOOLEAN"),
                         ("ai_reasons", "TEXT"), ("ai_scored_at", "TIMESTAMPTZ")]:
            c.execute(text(f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {col} {typ}"))
        c.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_ai ON jobs(ai_score)"))


if __name__ == "__main__":
    eng = get_engine()
    init_schema(eng)
    with eng.connect() as c:
        n = c.execute(text("SELECT count(*) FROM jobs")).scalar()
    u = get_url()
    where = u.render_as_string(hide_password=True) if hasattr(u, "render_as_string") else str(u)
    print(f"Connected: {where.split('@')[-1]}  | jobs rows: {n}")
