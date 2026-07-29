"""Unit tests for the hiring-intelligence skill/seniority extraction."""
from jobsdb.skills import extract_skills, seniority_of


def test_extract_core_and_aerospace_skills():
    s = extract_skills(
        "Senior C++ engineer, Python, embedded RTOS, DO-178C avionics, Kubernetes on AWS")
    assert {"C++", "Python", "Embedded", "RTOS", "DO-178C", "Kubernetes", "AWS"} <= s


def test_java_not_matched_inside_javascript():
    s = extract_skills("JavaScript developer building web apps")
    assert "JavaScript" in s
    assert "Java" not in s                       # word boundary prevents the false positive


def test_extract_handles_empty():
    assert extract_skills("") == set()
    assert extract_skills(None) == set()


def test_seniority_precedence():
    assert seniority_of("Principal Software Engineer") == "Principal"
    assert seniority_of("Senior Lead Engineer") == "Lead/Staff"      # lead outranks senior
    assert seniority_of("Software Engineer") == "Mid/Other"
    assert seniority_of("Graduate Software Engineer") == "Graduate/Junior"
