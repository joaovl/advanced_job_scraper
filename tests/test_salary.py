"""Unit tests for salary parsing."""
from jobsdb.salary import parse_salary


def test_range_usd():
    s = parse_salary("The salary range is $135,803.00 to $204,500.00 USD")
    assert s == {"min": 135803, "max": 204500, "currency": "USD", "period": "year"}


def test_range_gbp_with_k():
    s = parse_salary("£55k to £70k depending on experience")
    assert s["min"] == 55000 and s["max"] == 70000 and s["currency"] == "GBP"


def test_up_to_is_max_only():
    s = parse_salary("Up to £80,000")
    assert s["min"] is None and s["max"] == 80000


def test_single_value():
    s = parse_salary("circa £60,000 per annum")
    assert s["min"] == s["max"] == 60000


def test_hourly():
    s = parse_salary("$45 per hour")
    assert s["max"] == 45 and s["period"] == "hour"


def test_ignores_401k_and_vague():
    assert parse_salary("401(k) matching and great benefits") is None
    assert parse_salary("Competitive salary and bonus") is None
    assert parse_salary("Founded in 2019, over 5000 employees") is None


def test_currency_code():
    assert parse_salary("GBP 90,000 per year")["max"] == 90000
