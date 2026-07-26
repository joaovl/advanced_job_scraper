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


def test_run_dispatch_validation(client):
    assert client.post("/api/run/bogus").status_code == 400
    assert client.get("/api/task/nope").status_code == 404
