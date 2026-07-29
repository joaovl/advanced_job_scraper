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


# --- WordPress REST job board (BAE Systems UK), offline ---

_WP_PAGE = [
    {"title": {"rendered": "Software Engineer &amp; Tester"},
     "acf": {"location_from_ats": "Warton", "location_country": "United Kingdom"},
     "link": "https://jobsearch.baesystems.com/job/software-engineer-1"},
    {"title": {"rendered": "Procurement Lead"},
     "acf": {"city_1": "Rochester"},
     "link": "https://jobsearch.baesystems.com/job/procurement-2"},
]


class _WPResp:
    headers = {"X-WP-TotalPages": "1"}          # single page -> loop stops after page 1

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def test_wordpress_parses_and_forwards_country(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(params or {})
        seen["url"] = url
        return _WPResp(_WP_PAGE)

    monkeypatch.setattr(C.requests, "get", fake_get)
    jobs = C.fetch_wordpress("jobsearch.baesystems.com?country=38", "BAE Systems")
    assert seen["url"] == "https://jobsearch.baesystems.com/wp-json/wp/v2/jobs"
    assert seen["country"] == "38"                       # token query forwarded (UK scope)
    assert len(jobs) == 2                                # fetcher itself does not filter
    assert jobs[0]["title"] == "Software Engineer & Tester"   # HTML entity unescaped
    assert jobs[0]["location"] == "Warton"                    # ACF location_from_ats
    assert jobs[1]["location"] == "Rochester"                 # falls back to city_1
    assert jobs[0]["source"] == "Careers:wordpress"


_WP_TAXO_PAGE = [
    {"title": {"rendered": "Systems Engineer"}, "acf": {}, "link": "https://roke.co.uk/job/1",
     "_embedded": {"wp:term": [[{"taxonomy": "job-category", "name": "Engineering"}],
                               [{"taxonomy": "job-location", "name": "Romsey"}]]}},
]


def test_wordpress_singular_type_and_taxonomy_location(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen.update(params or {})
        return _WPResp(_WP_TAXO_PAGE)

    monkeypatch.setattr(C.requests, "get", fake_get)
    jobs = C.fetch_wordpress("roke.co.uk?type=job", "Roke")
    assert seen["url"] == "https://roke.co.uk/wp-json/wp/v2/job"   # singular post type from ?type=
    assert "type" not in seen                                     # consumed, not forwarded as a query param
    assert jobs[0]["location"] == "Romsey"                        # pulled from the job-location taxonomy


# ============================================================================
# Field-mapping tests for each ATS fetcher's JSON/XML parsing (offline).
# These lock the mapping from each platform's response shape to the standard
# job schema, so a field rename in a fetcher is caught immediately.
# ============================================================================

class _JsonResp:
    def __init__(self, data, headers=None):
        self._d, self.headers = data, headers or {}

    def json(self):
        return self._d


def test_greenhouse_maps_fields(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        {"jobs": [{"title": "Backend Engineer", "location": {"name": "London, UK"},
                   "absolute_url": "https://boards.gh/acme/1", "content": "Build APIs."}]}))
    j = C.fetch_greenhouse("acme", "Acme")[0]
    assert (j["title"], j["location"], j["url"], j["source"]) == (
        "Backend Engineer", "London, UK", "https://boards.gh/acme/1", "Careers:greenhouse")


def test_lever_maps_fields(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        [{"text": "Site Reliability Engineer", "categories": {"location": "Remote - UK"},
          "hostedUrl": "https://jobs.lever.co/acme/1", "descriptionPlain": "Keep it up."}]))
    j = C.fetch_lever("acme", "Acme")[0]
    assert (j["title"], j["location"], j["url"], j["source"]) == (
        "Site Reliability Engineer", "Remote - UK", "https://jobs.lever.co/acme/1", "Careers:lever")


def test_ashby_maps_fields(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        {"jobs": [{"title": "C++ Engineer", "location": "Bristol",
                   "jobUrl": "https://jobs.ashbyhq.com/acme/1", "descriptionPlain": "d"}]}))
    j = C.fetch_ashby("acme", "Acme")[0]
    assert (j["title"], j["location"], j["source"]) == ("C++ Engineer", "Bristol", "Careers:ashby")


def test_bamboohr_joins_location(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        {"result": [{"jobOpeningName": "Firmware Engineer",
                     "location": {"city": "Harwell", "state": None, "country": "UK"}, "id": "7"}]}))
    j = C.fetch_bamboohr("astroscale", "Astroscale")[0]
    assert j["title"] == "Firmware Engineer"
    assert j["location"] == "Harwell, UK"                       # None state dropped
    assert j["url"] == "https://astroscale.bamboohr.com/careers/7"


def test_smartrecruiters_maps_and_stops(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        {"content": [{"name": "Data Engineer", "location": {"city": "London", "country": "uk"}, "id": "9"}]}))
    j = C.fetch_smartrecruiters("Acme", "Acme")[0]
    assert j["title"] == "Data Engineer" and j["location"] == "London, uk"
    assert j["url"] == "https://jobs.smartrecruiters.com/Acme/9"


def test_recruitee_maps_fields(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        {"offers": [{"title": "Full Stack Developer", "location": "Oxford",
                     "careers_url": "https://acme.recruitee.com/o/1", "description": "d"}]}))
    j = C.fetch_recruitee("acme", "Acme")[0]
    assert (j["title"], j["location"], j["source"]) == (
        "Full Stack Developer", "Oxford", "Careers:recruitee")


def test_workable_maps_fields(monkeypatch):
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _JsonResp(
        {"jobs": [{"title": "Platform Engineer", "location": {"location_str": "Cambridge, UK"},
                   "url": "https://acme.workable.com/j/1", "description": "d"}]}))
    j = C.fetch_workable("acme", "Acme")[0]
    assert j["title"] == "Platform Engineer" and j["location"] == "Cambridge, UK"


_PERSONIO_XML = (b'<?xml version="1.0"?><workzag-jobs><position>'
                 b'<id>5</id><name>Embedded Engineer</name><office>Bristol</office>'
                 b'<jobDescriptions><jobDescription><value>Great role</value>'
                 b'</jobDescription></jobDescriptions></position></workzag-jobs>')


def test_personio_maps_fields(monkeypatch):
    class _XmlResp:
        content = _PERSONIO_XML
    monkeypatch.setattr(C.requests, "get", lambda *a, **k: _XmlResp())
    j = C.fetch_personio("acme", "Acme")[0]
    assert j["title"] == "Embedded Engineer" and j["location"] == "Bristol"
    assert j["url"] == "https://acme.jobs.personio.com/job/5"


def test_algolia_maps_and_joins_location(monkeypatch):
    monkeypatch.setattr(C.requests, "post", lambda *a, **k: _JsonResp(
        {"hits": [{"title": "Software Engineer", "display_location": ["Stevenage", "Bristol"],
                   "jd_url": "/job/1", "description": "d"},
                  {"title": "QA", "city": "Bolton", "apply_url": "https://a/2", "description": "d"}],
         "nbPages": 1}))
    jobs = C.fetch_algolia("APP:KEY:idx", "MBDA")
    assert jobs[0]["location"] == "Stevenage, Bristol"          # list joined
    assert jobs[0]["url"] == "/job/1" and jobs[0]["source"] == "Careers:algolia"
    assert jobs[1]["location"] == "Bolton"
