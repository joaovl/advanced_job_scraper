"""Tests for the TOTP session gate (jobsdb/auth.py)."""
import time

import pytest
from flask import Flask, jsonify

import jobsdb.auth as A

SECRET = "JBSWY3DPEHPK3PXP"          # RFC 4648 base32 test secret


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("MEETINGS_TOTP_SECRET", SECRET)
    monkeypatch.delenv("MEETINGS_SESSION_SECRET", raising=False)


def test_sign_valid_roundtrip():
    assert A.valid(A.sign(int(time.time()) + 3600))


def test_expired_cookie_rejected():
    assert not A.valid(A.sign(int(time.time()) - 10))


def test_tampered_signature_rejected():
    exp, _, sig = A.sign(int(time.time()) + 3600).partition(".")
    assert not A.valid(f"{exp}.{'0' * len(sig)}")


def test_verify_totp_accepts_current_code():
    current = A._totp_candidates(SECRET)[1]     # middle window = current counter
    assert A.verify_totp(current)


def test_verify_totp_rejects_garbage():
    assert not A.verify_totp("abc")
    assert not A.verify_totp("12345")           # wrong length


def test_verify_totp_closed_when_secret_unset(monkeypatch):
    monkeypatch.delenv("MEETINGS_TOTP_SECRET", raising=False)
    assert not A.verify_totp("000000")


def _app():
    app = Flask(__name__)
    A.install_gate(app)

    @app.route("/library")
    def lib():
        return "ok"

    @app.route("/run")
    def run():
        return "run"

    @app.route("/api/run/x", methods=["POST"])
    def apirun():
        return jsonify(ok=True)

    return app


def test_gate_public_open_and_gated_blocked():
    c = _app().test_client()
    assert c.get("/library").status_code == 200          # public read
    assert c.get("/run").status_code == 302              # gated page -> /unlock
    assert "/unlock" in c.get("/run").headers["Location"]
    assert c.post("/api/run/x").status_code == 401       # gated api -> 401


def test_gate_allows_with_valid_cookie():
    c = _app().test_client()
    cookie = A.sign(int(time.time()) + 3600)
    try:
        c.set_cookie(A.COOKIE, cookie)                    # Werkzeug 3 signature
    except TypeError:
        c.set_cookie("localhost", A.COOKIE, cookie)       # older signature
    assert c.post("/api/run/x").status_code == 200
