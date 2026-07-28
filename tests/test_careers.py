"""Offline tests for the careers crawler's ATS detection + normalisation."""
import scrapers.careers as C


def _match(blob):
    for platform, pat in C.PATTERNS:
        m = pat.search(blob)
        if m:
            return platform, m.group(1)
    return None


def test_detects_common_ats_from_urls():
    cases = {
        "https://boards.greenhouse.io/vertical/jobs": ("greenhouse", "vertical"),
        "iframe src=https://job-boards.greenhouse.io/orbex": ("greenhouse", "orbex"),
        "https://jobs.lever.co/spire/x": ("lever", "spire"),
        "https://jobs.ashbyhq.com/vertical-aerospace": ("ashby", "vertical-aerospace"),
        "https://careers.smartrecruiters.com/Ubisoft": ("smartrecruiters", "Ubisoft"),
        "https://astroscale.bamboohr.com/careers": ("bamboohr", "astroscale"),
        "https://myco.recruitee.com/": ("recruitee", "myco"),
    }
    for blob, expected in cases.items():
        assert _match(blob) == expected, blob


def test_workday_detection_captures_parts():
    m = C.PATTERNS[-1][1].search("https://ag.wd3.myworkdayjobs.com/en-US/Airbus")
    assert m.groups() == ("ag", "wd3", "Airbus")


def test_std_schema_and_salary():
    j = C._std("Senior Software Engineer", "Acme", "Bristol", "http://x",
               "Great role. £70,000 - £90,000.", "greenhouse")
    assert j["source"] == "Careers:greenhouse"
    assert j["location"] == "Bristol"
    assert j["salary_min"] == 70000 and j["salary_max"] == 90000


def test_software_filter():
    assert C.SOFTWARE.search("Senior Software Engineer")
    assert C.SOFTWARE.search("Avionics Firmware Developer")
    assert not C.SOFTWARE.search("Procurement Manager")


# --- SuccessFactors (SAP CSB) fetcher, offline ---

# One rendered search page: two data rows (a software role + a non-software role),
# with an HTML entity in the title and a jobLocation cell — mimics careers.qinetiq.com.
_SF_PAGE = """
<html><body>
<span>Results 1 - 2 of <b>2</b></span>
<table>
<tr class="data-row odd">
  <td><a class="jobTitle-link" href="/job/Bristol-Senior-Software-Engineer-C-Autonomy/111/">
      Software Engineer (Control &amp; Autonomy)</a></td>
  <td><span class="jobLocation sort">x</span></td>
  <td><span class="jobLocation">Bristol, England, United Kingdom</span></td>
  <td><span class="jobLocation visible-phone">Bristol</span></td>
</tr>
<tr class="data-row even">
  <td><a class="jobTitle-link" href="/job/Farnborough-Procurement-Manager/222/">
      Procurement Manager</a></td>
  <td><span class="jobLocation">Farnborough, England, United Kingdom</span></td>
</tr>
</table>
</body></html>
"""


class _FakeResp:
    def __init__(self, text):
        self.text = text


def _mock_get(*a, **k):
    return _FakeResp(_SF_PAGE)


def test_successfactors_parses_rows(monkeypatch):
    monkeypatch.setattr(C.requests, "get", _mock_get)
    jobs = C.fetch_successfactors("careers.qinetiq.com", "QinetiQ")
    assert len(jobs) == 2                                    # fetcher itself does not filter
    j = jobs[0]
    assert j["title"] == "Software Engineer (Control & Autonomy)"   # entity unescaped, tags stripped
    assert j["location"] == "Bristol, England, United Kingdom"      # real location from jobLocation cell
    assert j["url"] == "https://careers.qinetiq.com/job/Bristol-Senior-Software-Engineer-C-Autonomy/111/"
    assert j["source"] == "Careers:successfactors"


def test_successfactors_accepts_full_base_url(monkeypatch):
    monkeypatch.setattr(C.requests, "get", _mock_get)
    jobs = C.fetch_successfactors("https://careers.qinetiq.com/", "QinetiQ")
    assert jobs[0]["url"].startswith("https://careers.qinetiq.com/job/")


# --- Workday explicit-config token (searchText + per-tenant country facet) ---

def test_parse_workday_token_with_facet_and_search():
    groups, st, facets = C._parse_workday_token(
        "rollsroyce/wd3/professional?searchText=software&facet=Country:ABC123")
    assert groups == [("rollsroyce", "wd3", "professional")]
    assert st == "software"
    assert facets == {"Country": ["ABC123"]}          # tenant-specific facet key preserved


def test_parse_workday_token_plain_and_multisite():
    groups, st, facets = C._parse_workday_token("leonardocompany/wd3/SiteA,SiteB")
    assert groups == [("leonardocompany", "wd3", "SiteA"),
                      ("leonardocompany", "wd3", "SiteB")]
    assert st == "" and facets == {}


def test_fetch_workday_pages_to_total_and_forwards_facets(monkeypatch):
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        off = json["offset"]

        class R:
            def json(self):
                if off == 0:
                    return {"total": 3, "jobPostings": [
                        {"title": "SW Eng", "locationsText": "Derby", "externalPath": "/job/x"},
                        {"title": "Principal SW", "locationsText": "Bristol", "externalPath": "/job/y"},
                        {"title": "QA", "locationsText": "Luton", "externalPath": "/job/z"}]}
                return {"total": 3, "jobPostings": []}
        return R()

    monkeypatch.setattr(C.requests, "post", fake_post)
    jobs = C.fetch_workday(("rollsroyce", "wd3", "professional"), "Rolls-Royce",
                           "software", {"Country": ["ABC"]})
    assert len(jobs) == 3
    assert calls[0]["searchText"] == "software"
    assert calls[0]["appliedFacets"] == {"Country": ["ABC"]}
    assert jobs[0]["url"] == "https://rollsroyce.wd3.myworkdayjobs.com/en-US/professional/job/x"
    assert jobs[0]["source"] == "Careers:workday"
    assert len(calls) == 1                              # stops once offset reaches total (no over-paging)


# --- SuccessFactors token now carries keyword + location filter ---

def test_successfactors_forwards_keyword_and_location(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params or {})
        return _FakeResp(_SF_PAGE)

    monkeypatch.setattr(C.requests, "get", fake_get)
    jobs = C.fetch_successfactors(
        "jobs.babcockinternational.com?q=software&locationsearch=United Kingdom", "Babcock")
    assert seen["q"] == "software"
    assert seen["locationsearch"] == "United Kingdom"
    assert jobs[0]["url"].startswith("https://jobs.babcockinternational.com/")


def test_explicit_ats_skips_detection_and_filters(monkeypatch):
    # Explicit ats must NOT call detect() (which would hit the network)...
    monkeypatch.setattr(C, "detect", lambda d: (_ for _ in ()).throw(AssertionError("detect called")))
    monkeypatch.setattr(C.requests, "get", _mock_get)
    platform, jobs = C.scrape_company("QinetiQ", "qinetiq.com",
                                      ats="successfactors", token="careers.qinetiq.com")
    assert platform == "successfactors"
    # ...and the default (software) title filter drops the Procurement Manager row.
    assert [j["title"] for j in jobs] == ["Software Engineer (Control & Autonomy)"]
