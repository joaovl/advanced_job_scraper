"""Unit tests for location -> country normalisation."""
from jobsdb.location import normalize_country


def test_uk_variants():
    for s in ["United Kingdom", "Bristol, England, United Kingdom",
              "GBR - Cheltenham", "Linthouse Glasgow", "London Area, United Kingdom"]:
        assert normalize_country(s) == "United Kingdom", s


def test_us_variants():
    for s in ["United States-Florida-Melbourne", "USA - North Charleston, SC",
              "US-IA-CEDAR RAPIDS-105 ~ 400 Collins Rd", "Ellsworth AFB"]:
        assert normalize_country(s) == "United States", s


def test_other_countries():
    assert normalize_country("Bengaluru - Indraprastha") == "India"
    assert normalize_country("Toulouse Area") == "France"
    assert normalize_country("Stuttgart") == "Germany"


def test_multiple_and_empty():
    assert normalize_country("2 Locations") == "Multiple"
    assert normalize_country("") is None
    assert normalize_country(None) is None
