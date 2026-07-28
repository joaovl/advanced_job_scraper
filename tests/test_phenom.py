"""Offline tests for the Phenom People fetcher in scrapers.careers.

No network: we monkeypatch requests.get with a canned Phenom search page whose
`eagerLoadRefineSearch` blob mirrors the real jobs.baesystems.com / careers.rtx.com
shape (title, cityStateCountry, country, applyUrl, descriptionTeaser, jobId).
"""
import json

import scrapers.careers as C


# A trimmed Phenom search page. The description deliberately contains a literal
# "{brace}" inside a JSON string to exercise the string-aware brace matcher, and
# a salary so _std's parse_salary has something to find.
_JOBS = [
    {"title": "Senior Software Engineer", "cityStateCountry": "Frimley, England, United Kingdom",
     "country": "United Kingdom", "applyUrl": "https://jobs.example.com/job/1",
     "descriptionTeaser": "Build flight control software {embedded}. £60,000 - £80,000 a year.",
     "jobId": "1", "jobSeqNo": "SEQ1"},
    {"title": "Procurement Manager", "cityStateCountry": "Barrow-in-Furness, England, United Kingdom",
     "country": "United Kingdom", "applyUrl": "https://jobs.example.com/job/2",
     "descriptionTeaser": "Manage suppliers.", "jobId": "2", "jobSeqNo": "SEQ2"},
    {"title": "Software Developer", "cityStateCountry": "Mount Laurel, New Jersey, United States",
     "country": "United States", "applyUrl": "https://jobs.example.com/job/3",
     "descriptionTeaser": "US role.", "jobId": "3", "jobSeqNo": "SEQ3"},
]


def _canned_page(jobs):
    blob = {"status": 200, "hits": len(jobs), "totalHits": len(jobs),
            "data": {"jobs": jobs, "aggregations": []}}
    return ('<!doctype html><html><head></head><body><script>'
            'phApp.ddo = {"eagerLoadRefineSearch":' + json.dumps(blob) +
            ',"other":{"x":1}};</script></body></html>')


class _Resp:
    def __init__(self, text):
        self.text = text


def _patch(monkeypatch, jobs):
    page = _canned_page(jobs)

    def fake_get(url, params=None, headers=None, timeout=None):
        # from=0 returns the page; any later page is empty so the loop stops.
        if params and int(params.get("from", 0)) > 0:
            return _Resp(_canned_page([]))
        return _Resp(page)

    monkeypatch.setattr(C.requests, "get", fake_get)


def test_phenom_extract_parses_blob_with_literal_braces():
    obj = C._phenom_extract(_canned_page(_JOBS))
    assert obj is not None
    assert obj["totalHits"] == 3
    assert len(obj["data"]["jobs"]) == 3
    # the "{embedded}" brace inside the description must not break brace balancing
    assert "{embedded}" in obj["data"]["jobs"][0]["descriptionTeaser"]


def test_phenom_extract_missing_blob_returns_none():
    assert C._phenom_extract("<html>no phenom here</html>") is None


def test_fetch_phenom_maps_to_std_schema(monkeypatch):
    _patch(monkeypatch, _JOBS)
    jobs = C.fetch_phenom("jobs.example.com", "BAE Systems")
    assert len(jobs) == 3
    j = jobs[0]
    assert j["title"] == "Senior Software Engineer"
    assert j["company"] == "BAE Systems"
    assert j["location"] == "Frimley, England, United Kingdom"
    assert j["url"] == "https://jobs.example.com/job/1"
    assert j["source"] == "Careers:phenom"
    assert j["salary_min"] == 60000 and j["salary_max"] == 80000


def test_fetch_phenom_country_filter(monkeypatch):
    _patch(monkeypatch, _JOBS)
    jobs = C.fetch_phenom("jobs.example.com?country=United Kingdom", "BAE Systems")
    assert {j["location"].split(",")[-1].strip() for j in jobs} == {"United Kingdom"}
    assert len(jobs) == 2  # US role filtered out


def test_scrape_company_phenom_software_filter(monkeypatch):
    """Explicit ats=phenom path skips detection and applies the SOFTWARE filter,
    dropping the non-software Procurement role."""
    _patch(monkeypatch, _JOBS)
    platform, jobs = C.scrape_company("BAE Systems", "baesystems.com",
                                      ats="phenom", token="jobs.example.com")
    assert platform == "phenom"
    titles = {j["title"] for j in jobs}
    assert "Senior Software Engineer" in titles
    assert "Software Developer" in titles
    assert "Procurement Manager" not in titles
