"""API contract tests — assert filters/search/sort/stats return CORRECT data."""
import csv
import io


def rows(client, qs=""):
    r = client.get("/api/jobs?limit=500" + (("&" + qs) if qs else ""))
    assert r.status_code == 200
    return r.get_json()


def test_stats_math_is_consistent(client, seeded):
    e = seeded["expect"]
    s = client.get("/api/stats").get_json()["summary"]
    assert s["total"] == e["total"]
    assert s["competitor"] == e["competitor"]
    assert s["new"] == e["new"]
    assert s["scored"] == e["scored"]
    assert s["matched"] == e["matched"]


def test_no_filter_returns_all(client, seeded):
    assert rows(client)["total"] == seeded["expect"]["total"]


def test_competitor_filter_returns_only_competitors(client, seeded):
    d = rows(client, "competitor=1")
    assert d["total"] == seeded["expect"]["competitor"]
    assert all(r["is_competitor"] for r in d["rows"])            # every row really is one
    assert all(r["competitor"] for r in d["rows"])               # label populated


def test_new_filter_returns_only_new(client, seeded):
    d = rows(client, "new=1")
    assert d["total"] == seeded["expect"]["new"]
    assert all(r["is_new"] for r in d["rows"])


def test_search_matches_term_in_every_row(client, seeded):
    d = rows(client, "q=FPGA")
    assert d["total"] == seeded["expect"]["fpga"]
    for r in d["rows"]:
        blob = f"{r['company']} {r['title']} {r['snippet']}".lower()
        assert "fpga" in blob                                    # relevance is real


def test_search_abbreviation_equivalence(client):
    def ids(q):
        return {r["id"] for r in rows(client, "q=" + q.replace(" ", "+"))["rows"]}
    full = ids("principal software engineer")
    abbr = ids("principal sw engineer")
    loose = ids("principal engineer")
    assert full and full == abbr                 # "sw" resolves to "software"
    assert full.issubset(loose)                  # dropping a word only widens results
    assert ids("sr engineer") == ids("senior engineer")


def test_min_score_filter(client, seeded):
    d = rows(client, "min_score=8")
    assert d["total"] == seeded["expect"]["min8"]
    assert all(r["ai_score"] is not None and r["ai_score"] >= 8 for r in d["rows"])


def test_scored_filter_only_scored(client):
    d = rows(client, "scored=1")
    assert all(r["ai_score"] is not None for r in d["rows"])


def test_sort_by_score_is_descending(client):
    d = rows(client, "scored=1&sort=score")
    scores = [r["ai_score"] for r in d["rows"]]
    assert scores == sorted(scores, reverse=True)               # genuinely ordered


def test_source_filter(client, seeded):
    assert rows(client, "source=Workday")["total"] == seeded["expect"]["workday"]
    assert rows(client, "source=LinkedIn")["total"] == seeded["expect"]["linkedin"]


def test_job_detail_returns_description(client):
    first = rows(client)["rows"][0]
    j = client.get(f"/api/job/{first['id']}").get_json()
    assert j["id"] == first["id"]
    assert len(j["description"]) > 10
    assert "search" not in j and "raw" not in j                  # internal fields stripped


def test_export_csv_matches_filter(client, seeded):
    r = client.get("/api/export.csv?competitor=1")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    data = list(csv.DictReader(io.StringIO(body)))
    assert len(data) == seeded["expect"]["competitor"]
    assert set(data[0].keys()) >= {"company", "title", "source", "competitor", "url"}


def test_analysis_json_shape_and_decisions(client, seeded):
    d = client.get("/api/analysis.json").get_json()
    assert len(d["results"]) == seeded["expect"]["scored"]       # only scored jobs
    for r in d["results"]:
        assert r["decision"] in ("MATCHED", "REJECTED")
        assert (r["decision"] == "MATCHED") == (r["score"] >= 7)  # decision matches score


def test_prefix_search_matches_partial_words(client):
    # "engin" should match "engineer"; every result really contains eng*
    d = rows(client, "q=engin")
    assert d["total"] > 0
    assert all("engineer" in (r["title"] + r["snippet"]).lower() or
               "engineering" in (r["title"] + r["snippet"]).lower() for r in d["rows"])


def test_has_salary_and_min_salary_filters(client, seeded):
    d = rows(client, "has_salary=1")
    assert d["total"] == seeded["expect"]["salaried"]
    assert all(r["salary_max"] is not None for r in d["rows"])
    # £70-90k and $120-150k both clear 60k
    assert rows(client, "min_salary=60000")["total"] == seeded["expect"]["salaried"]
    assert rows(client, "min_salary=200000")["total"] == 0


def test_sort_by_salary_descending(client):
    d = rows(client, "has_salary=1&sort=salary")
    sal = [r["salary_max"] for r in d["rows"]]
    assert sal == sorted(sal, reverse=True)


def test_country_filter(client, seeded):
    assert rows(client, "country=United+Kingdom")["total"] == seeded["expect"]["uk"]
    d = rows(client, "country=United+Kingdom")
    assert all(r["company"] for r in d["rows"])   # sanity: rows returned
    assert rows(client, "country=United+States")["total"] == seeded["expect"]["us"]


def test_salaries_endpoint(client):
    d = client.get("/api/salaries").get_json()
    assert {c["currency"] for c in d["currencies"]} == {"GBP", "USD"}
    assert d["currency"] in ("GBP", "USD")
    assert all("median" in lv for lv in d["by_level"])
    # by_location present with country names
    assert any(x["country"] for x in d["by_location"])


def test_salaries_uk_only(client):
    d = client.get("/api/salaries?country=United+Kingdom&currency=GBP").get_json()
    locs = {x["country"] for x in d["by_location"]}
    assert locs == {"United Kingdom"}             # UK filter really isolates UK
    assert d["by_location"][0]["median"] is not None


def test_stats_reports_salaried(client, seeded):
    assert client.get("/api/stats").get_json()["summary"]["salaried"] == seeded["expect"]["salaried"]


def test_run_dispatch_validation(client):
    # /api/run and /api/task are behind the TOTP gate — unlock first, then the
    # underlying validation (400 unknown kind, 404 unknown task) should show.
    import time
    from jobsdb import auth
    cookie = auth.sign(int(time.time()) + 3600)
    try:
        client.set_cookie(auth.COOKIE, cookie)
    except TypeError:
        client.set_cookie("localhost", auth.COOKIE, cookie)
    assert client.post("/api/run/bogus").status_code == 400
    assert client.get("/api/task/nope").status_code == 404


def test_jobs_multi_company_filter(client):
    import urllib.parse
    stats = client.get("/api/stats").get_json()
    cos = [c["company"] for c in stats["companies"][:2]]
    if len(cos) < 2:
        return
    counts = {c["company"]: c["n"] for c in stats["companies"]}
    qs = "&".join("company=" + urllib.parse.quote(c) for c in cos)
    d = client.get("/api/jobs?" + qs).get_json()
    assert {r["company"] for r in d["rows"]} <= set(cos)          # only selected companies
    assert d["total"] == counts[cos[0]] + counts[cos[1]]         # union of both


def test_title_include_exclude_partition(client):
    import re as _re
    import collections
    rows = client.get("/api/jobs?limit=500").get_json()["rows"]
    words = collections.Counter()
    for r in rows:
        for w in _re.findall(r"[a-z][a-z+#]{2,}", (r["title"] or "").lower()):
            words[w] += 1
    common = [w for w, c in words.most_common() if 1 <= c < len(rows)]
    if not common:
        return
    word = common[0]
    pat = r"(^|[^a-z0-9])" + _re.escape(word) + r"([^a-z0-9]|$)"
    inc = client.get("/api/jobs?title_inc=" + word).get_json()
    exc = client.get("/api/jobs?title_exc=" + word).get_json()
    assert all(_re.search(pat, r["title"].lower()) for r in inc["rows"])       # include: all contain it
    assert not any(_re.search(pat, r["title"].lower()) for r in exc["rows"])    # exclude: none contain it
    assert inc["total"] + exc["total"] == len(rows)                            # they partition the set


def test_wordish_excludes_substring_not_word(client):
    # 'ada' must not match 'Canada'-style substrings — word-boundaried.
    from jobsdb.app import _wordish
    import re as _re
    assert _re.search(_wordish("ada"), "senior ada developer")
    assert not _re.search(_wordish("ada"), "engineer in canada")
    assert _re.search(_wordish("c++"), "strong c++ and rust")


def test_run_routes_gated_without_cookie(client):
    assert client.post("/api/run/refresh").status_code == 401     # gated api
    assert client.get("/run").status_code == 302                  # gated page -> /unlock
