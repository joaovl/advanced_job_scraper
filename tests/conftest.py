"""Pytest fixtures: a seeded, isolated Postgres test database + Flask client.

Uses a SEPARATE database (aalto_jobs_test) so tests never touch real data.
Set before any jobsdb import so the app binds to the test DB.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# Point everything at the isolated test database (container defaults otherwise).
os.environ.pop("DATABASE_URL", None)
os.environ["PGDATABASE"] = os.environ.get("TEST_PGDATABASE", "aalto_jobs_test")
os.environ.setdefault("PGHOST", "localhost")
os.environ.setdefault("PGPORT", "5433")
os.environ.setdefault("PGUSER", "postgres")
os.environ.setdefault("PGPASSWORD", "aalto")

import pytest  # noqa: E402
from jobsdb.db import get_engine  # noqa: E402
from seed import seed, EXPECT  # noqa: E402


@pytest.fixture(scope="session")
def engine():
    return get_engine(create_db_if_missing=True)     # creates aalto_jobs_test if missing


@pytest.fixture()
def seeded(engine):
    """Re-seed to the known dataset before EACH test, so tests are isolated
    even though some of them mutate the database."""
    rows = seed(engine)
    return {"engine": engine, "rows": rows, "expect": EXPECT}


@pytest.fixture()
def client(seeded):
    import jobsdb.app as appmod
    appmod.app.config.update(TESTING=True)
    return appmod.app.test_client()
