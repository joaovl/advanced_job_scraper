"""Favourites: PIN gate + CRUD + label filtering."""
import pytest

from jobsdb import auth


@pytest.fixture(autouse=True)
def _fav_env(monkeypatch):
    # Host-only, non-secure cookie so the test client resends it over http.
    monkeypatch.setenv("MEETINGS_COOKIE_SECURE", "0")
    monkeypatch.delenv("MEETINGS_COOKIE_DOMAIN", raising=False)
    monkeypatch.setenv("FAV_PIN", "125433")


def test_pin_verify():
    assert auth.verify_pin("125433")
    assert not auth.verify_pin("000000")
    assert not auth.verify_pin("")


def test_favourites_locked_without_pin(client):
    assert client.get("/api/favs").status_code == 401
    assert client.post("/api/fav", json={"job_id": 1}).status_code == 401
    assert client.get("/api/fav/state").get_json()["unlocked"] is False
    assert client.get("/api/fav/ids").get_json()["ids"] == []      # locked -> empty, not error


def test_favourites_crud_and_labels(client):
    assert client.post("/api/fav/unlock", json={"pin": "000000"}).status_code == 401
    assert client.post("/api/fav/unlock", json={"pin": "125433"}).status_code == 200
    # cookie now set on the client; subsequent calls are authorised
    assert client.get("/api/fav/state").get_json()["unlocked"] is True

    jid = client.get("/api/jobs?limit=1").get_json()["rows"][0]["id"]
    assert client.post("/api/fav", json={"job_id": jid, "labels": "personal, company"}).status_code == 200

    d = client.get("/api/favs").get_json()
    assert any(f["job_id"] == jid for f in d["favs"])
    assert "personal" in d["labels"] and "company" in d["labels"]
    assert jid in client.get("/api/fav/ids").get_json()["ids"]

    # label filter
    only = client.get("/api/favs?label=company").get_json()
    assert any(f["job_id"] == jid for f in only["favs"])
    assert client.get("/api/favs?label=nonesuch").get_json()["total"] == 0

    # remove
    assert client.delete(f"/api/fav/{jid}").status_code == 200
    assert not any(f["job_id"] == jid for f in client.get("/api/favs").get_json()["favs"])
