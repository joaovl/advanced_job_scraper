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


def test_gb_token_and_bare_towns():
    # BAE UK / Babcock shapes: bare "GB" and UK towns not previously listed.
    assert normalize_country("Bristol, GB, BS16 1EJ") == "United Kingdom"
    assert normalize_country("Heybridge") == "United Kingdom"
    assert normalize_country("Leicester, GB, LE8 6LH") == "United Kingdom"


def test_iso_country_code_prefix():
    # Leonardo / Workday "CC - City" convention.
    assert normalize_country("GB - Basildon, Essex") == "United Kingdom"
    assert normalize_country("IT - Torino - C.so Francia") == "Italy"
    assert normalize_country("DE - Darmstadt - EUMETSAT") == "Germany"


def test_iso_prefix_needs_dash_not_bare_word():
    # A stray two-letter word in free text must NOT be read as a country code.
    assert normalize_country("Built in Newcastle office") != "India"
