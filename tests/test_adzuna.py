"""Unit tests for the Adzuna provider mapping (no network)."""
from scrapers.adzuna import to_job


def test_maps_structured_salary():
    r = {"title": "Principal Software Engineer",
         "company": {"display_name": "Rolls-Royce"},
         "location": {"display_name": "Derby, Derbyshire"},
         "description": "Great role.  ", "redirect_url": "https://adzuna/x",
         "created": "2026-07-26T10:00:00Z",
         "salary_min": 80000.0, "salary_max": 95000.0}
    j = to_job(r, "gb")
    assert j["company"] == "Rolls-Royce"
    assert j["salary_min"] == 80000 and j["salary_max"] == 95000
    assert j["salary_currency"] == "GBP" and j["salary_period"] == "year"
    assert j["source"] == "Adzuna"
    assert j["posted_date"] == "2026-07-26"


def test_us_currency_and_missing_salary():
    r = {"title": "SWE", "company": {}, "location": {},
         "description": "", "redirect_url": "u"}
    j = to_job(r, "us")
    assert j["salary_currency"] == "USD"
    assert j["salary_min"] is None and j["salary_max"] is None
    assert j["company"] == "?"
