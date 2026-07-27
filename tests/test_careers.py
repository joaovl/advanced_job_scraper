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
