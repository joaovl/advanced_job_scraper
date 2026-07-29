"""Unit tests for ingest de-duplication keying.

Guards the dedup bug fixed in 5a424a6: ATS platforms (BrassRing/Phenom/…) that
carry the unique job id in the URL query string were all collapsing to a single
key when the query was stripped, dropping every job but one.
"""
from jobsdb.ingest import job_key


def test_strips_tracking_query():
    # Marketing/tracking params are noise -> key on the clean path.
    assert job_key("BAE", "Eng", "Bristol",
                   "https://x.com/job/123?utm_source=linkedin&ref=feed") == "https://x.com/job/123"


def test_keeps_id_bearing_query():
    # When the query carries the job id, it MUST stay in the key.
    for u in ["https://x.com/search?jobid=42",
              "https://x.com/s?foo=1&req_id=9",
              "https://x.com/s?bar=2&job_id=9",
              "https://x.com/p?posting=7",
              "https://x.com/g?id=5"]:
        assert job_key("C", "T", "L", u) == u, u


def test_brassring_ids_stay_distinct():
    # The exact shape of the original bug: same path, different jobId in query.
    a = "https://sjobs.brassring.com/TGnewUI/Search/Home?jobId=100"
    b = "https://sjobs.brassring.com/TGnewUI/Search/Home?jobId=200"
    assert job_key("Co", "T", "L", a) != job_key("Co", "T", "L", b)


def test_falls_back_to_company_title_location_without_url():
    assert job_key("Acme Ltd", "Engineer", "London", "") == "acme ltd|engineer|london"
