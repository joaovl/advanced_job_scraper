"""Unit tests for the multi-provider normaliser (no network)."""
import scrapers.providers as P


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


def test_std_parses_salary_from_text():
    j = P._std("SWE", "Acme", "London", "u",
               "Great role. Salary: £70,000 - £90,000 per annum.", "2026-07-01", "X")
    assert j["salary_min"] == 70000 and j["salary_max"] == 90000
    assert j["salary_currency"] == "GBP" and j["source"] == "X"
    assert j["posted_date"] == "2026-07-01"


def test_std_keeps_structured_salary():
    j = P._std("SWE", "Acme", "UK", "u", "no pay text", "", "X",
               smin=80000, smax=95000, cur="GBP")
    assert (j["salary_min"], j["salary_max"], j["salary_currency"]) == (80000, 95000, "GBP")


def test_matches_all_words():
    assert P._matches("principal software", "Principal Software Engineer", "")
    assert not P._matches("principal software", "Senior Data Analyst", "")


def test_remotive_mapping(monkeypatch):
    payload = {"jobs": [{
        "title": "Senior Software Engineer", "company_name": "Remotely",
        "candidate_required_location": "UK", "url": "https://r/1",
        "description": "Build things.", "publication_date": "2026-07-10T00:00:00",
        "salary": "£60,000 - £80,000"}]}
    monkeypatch.setattr(P.requests, "get", lambda *a, **k: FakeResp(payload))
    jobs = P.remotive("software", "gb", "", 10)
    assert len(jobs) == 1
    j = jobs[0]
    assert j["source"] == "Remotive" and j["company"] == "Remotely"
    assert j["salary_min"] == 60000 and j["salary_max"] == 80000


def test_jobicy_structured_salary(monkeypatch):
    payload = {"jobs": [{
        "jobTitle": "Software Engineer", "companyName": "Jobco", "jobGeo": "Anywhere",
        "url": "https://j/1", "jobExcerpt": "x", "pubDate": "2026-07-05",
        "annualSalaryMin": 90000, "annualSalaryMax": 120000, "salaryCurrency": "USD"}]}
    monkeypatch.setattr(P.requests, "get", lambda *a, **k: FakeResp(payload))
    j = P.jobicy("software", "us", "", 5)[0]
    assert j["salary_min"] == 90000 and j["salary_currency"] == "USD"


def test_registry_and_selection():
    assert set(P.FREE).issubset(set(P.REGISTRY))
    assert set(P.KEYED).issubset(set(P.REGISTRY))
