#!/usr/bin/env python3
"""
Shared-SSO TOTP gate for the Flask app (joaovpl.uk pattern).

Mirrors the Avionics `api/meetings.py` model, translated to Flask:
  - read routes are open; mutating / crawler-control routes require a session
  - a 6-digit Authenticator (TOTP) code unlocks a 12h HMAC-signed cookie
  - the cookie is scoped to `.joaovpl.uk` so unlocking one app unlocks all (SSO)

Env:
  MEETINGS_TOTP_SECRET     base32 secret shared across joaovpl.uk apps.
                           UNSET => gate is closed (every gated route 503s).
  MEETINGS_SESSION_SECRET  HMAC key for the cookie; derived from the TOTP
                           secret if unset (same as Avionics).
  MEETINGS_COOKIE_DOMAIN   e.g. ".joaovpl.uk" (omit for host-only, e.g. tests).
  MEETINGS_COOKIE_SECURE   "0" to drop the Secure flag for http:// testing.

No third-party deps: TOTP (RFC 6238, HMAC-SHA1) is computed from stdlib.
"""
import base64
import hashlib
import hmac
import os
import struct
import time

from flask import request, redirect, Response, jsonify

COOKIE = "m_session"
SESSION_TTL = 12 * 3600

# --- Favourites area: a lighter PIN gate, independent of the owner TOTP gate ---
FAV_COOKIE = "fav_session"
FAV_TTL = 30 * 24 * 3600          # 30 days — it only guards a personal shortlist


def fav_pin():
    return os.environ.get("FAV_PIN", "125433").strip()


def _fav_key():
    return ("fav-session:" + fav_pin()).encode()


def verify_pin(pin):
    if not pin:
        return False
    return hmac.compare_digest(str(pin).strip(), fav_pin())


def sign_fav(exp):
    sig = hmac.new(_fav_key(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_fav(cookie):
    if not cookie or "." not in cookie:
        return False
    exp_str, _, sig = cookie.partition(".")
    expected = hmac.new(_fav_key(), exp_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(exp_str) > int(time.time())
    except ValueError:
        return False


def fav_cookie_kwargs():
    kw = cookie_kwargs()
    kw["max_age"] = FAV_TTL
    return kw

# Routes reachable with no session. Everything else is default-deny.
PUBLIC_PAGES = {"/", "/library", "/salaries", "/dashboard", "/unlock", "/healthz"}
PUBLIC_GET_APIS = {
    "/api/stats", "/api/salaries", "/api/jobs", "/api/analysis.json",
    "/api/export.csv",
}
PUBLIC_PREFIXES = ("/static/", "/api/job/")   # /api/job/<id> is a read


def _totp_secret():
    return os.environ.get("MEETINGS_TOTP_SECRET", "").strip()


def _session_key():
    return (os.environ.get("MEETINGS_SESSION_SECRET")
            or ("m-session:" + _totp_secret())).encode()


def _totp_candidates(secret_b32, now=None, step=30, window=1):
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad)
    counter = int((now or time.time()) // step)
    out = []
    for c in range(counter - window, counter + window + 1):
        h = hmac.new(key, struct.pack(">Q", c), hashlib.sha1).digest()
        o = h[-1] & 0x0F
        v = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000
        out.append(f"{v:06d}")
    return out


def verify_totp(code):
    secret = _totp_secret()
    if not secret or not code:
        return False
    code = str(code).strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return False
    return code in _totp_candidates(secret)


def sign(exp):
    sig = hmac.new(_session_key(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid(cookie):
    if not cookie or "." not in cookie:
        return False
    exp_str, _, sig = cookie.partition(".")
    expected = hmac.new(_session_key(), exp_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        return int(exp_str) > int(time.time())
    except ValueError:
        return False


def cookie_kwargs():
    kw = {
        "httponly": True, "samesite": "Strict", "path": "/",
        "secure": os.environ.get("MEETINGS_COOKIE_SECURE", "1") != "0",
        "max_age": SESSION_TTL,
    }
    dom = os.environ.get("MEETINGS_COOKIE_DOMAIN")
    if dom:
        kw["domain"] = dom
    return kw


def _is_public(path, method):
    # The favourites area has its OWN PIN gate (enforced per-route), so it must
    # bypass the owner TOTP gate — otherwise it'd need both.
    if path == "/favourites" or path.startswith("/api/fav"):
        return True
    if method == "GET" and (path in PUBLIC_PAGES or path in PUBLIC_GET_APIS
                            or path.startswith(PUBLIC_PREFIXES)):
        return True
    if path == "/api/unlock":            # POST unlock must be reachable
        return True
    return False


def install_gate(app):
    """Register the before_request gate. Default-deny for anything not public."""
    @app.before_request
    def _gate():
        if _is_public(request.path, request.method):
            return None
        if valid(request.cookies.get(COOKIE)):
            return None
        if request.path.startswith("/api/"):
            return jsonify(detail="authentication required"), 401
        nxt = request.full_path if request.query_string else request.path
        return redirect("/unlock?next=" + nxt)
