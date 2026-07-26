#!/usr/bin/env python3
"""
Web interface for the Postgres job library.

Features:
  - Full-text search across company/title/description
  - Filter by source (Workday/LinkedIn), competitor-only, new-since-last-ingest,
    open/closed status, and company
  - Read full descriptions inline
  - Export the current filtered view to CSV

Run:
    python -m jobsdb.app          # serves http://localhost:5000
"""
import csv
import io
from pathlib import Path
from flask import Flask, request, jsonify, Response, render_template, send_file
from sqlalchemy import text

from .db import get_engine
from . import actions

app = Flask(__name__)
engine = get_engine(create_db_if_missing=False)

UI_DIR = Path(__file__).parent.parent / "ui"


def _where(args):
    """Build a WHERE clause + params from query args."""
    clauses, params = [], {}
    q = (args.get("q") or "").strip()
    if q:
        clauses.append("search @@ plainto_tsquery('english', :q)")
        params["q"] = q
    if args.get("source"):
        clauses.append("source = :source")
        params["source"] = args["source"]
    if args.get("company"):
        clauses.append("company = :company")
        params["company"] = args["company"]
    if args.get("competitor") == "1":
        clauses.append("is_competitor = true")
    if args.get("new") == "1":
        clauses.append("is_new = true")
    if args.get("min_score"):
        clauses.append("ai_score >= :min_score")
        params["min_score"] = int(args["min_score"])
    if args.get("scored") == "1":
        clauses.append("ai_score IS NOT NULL")
    status = args.get("status") or "open"
    if status in ("open", "closed"):
        clauses.append("status = :status")
        params["status"] = status
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/library")
def library():
    return render_template("index.html")


@app.route("/run")
def run_center():
    return render_template("run.html")


@app.route("/dashboard")
def dashboard():
    """Serve the analytics dashboard (loads live DB data via ?file=/api/analysis.json)."""
    return send_file(UI_DIR / "dashboard.html")


@app.route("/builder")
def builder():
    """Serve the command builder GUI."""
    return send_file(UI_DIR / "command_builder.html")


@app.route("/api/analysis.json")
def analysis_json():
    """Return AI-scored jobs in the shape the dashboard expects (results[])."""
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT company, title, location, url, ai_score, ai_match, ai_reasons "
            "FROM jobs WHERE ai_score IS NOT NULL ORDER BY ai_score DESC")).mappings().all()
    results = [{
        "company": r["company"], "title": r["title"], "location": r["location"],
        "url": r["url"], "score": r["ai_score"],
        "decision": "MATCHED" if r["ai_match"] else "REJECTED",
        "reasons": (r["ai_reasons"] or "").split("; ") if r["ai_reasons"] else [],
    } for r in rows]
    return jsonify({"model": "jobsdb", "analysis_model": "jobsdb", "results": results})


@app.route("/api/stats")
def stats():
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT count(*) total, "
            "count(*) FILTER (WHERE is_competitor) competitor, "
            "count(*) FILTER (WHERE is_new) new, "
            "count(*) FILTER (WHERE ai_score IS NOT NULL) scored, "
            "count(*) FILTER (WHERE ai_match) matched, "
            "count(*) FILTER (WHERE status='open') open, "
            "count(DISTINCT company) companies FROM jobs")).mappings().first()
        companies = c.execute(text(
            "SELECT company, count(*) n, bool_or(is_competitor) comp "
            "FROM jobs WHERE status='open' GROUP BY company ORDER BY n DESC")).mappings().all()
    return jsonify({"summary": dict(row),
                    "companies": [dict(x) for x in companies]})


@app.route("/api/jobs")
def api_jobs():
    where, params = _where(request.args)
    params["limit"] = min(int(request.args.get("limit", 100)), 500)
    params["offset"] = int(request.args.get("offset", 0))
    order = request.args.get("sort")
    order_sql = ("ai_score DESC NULLS LAST, is_competitor DESC"
                 if order == "score"
                 else "is_new DESC, is_competitor DESC, company, title")
    sql = (
        "SELECT id, source, company, title, location, url, competitor, "
        "is_competitor, is_new, status, first_seen, ai_score, ai_match, "
        "left(description, 320) AS snippet, length(description) AS desc_len "
        f"FROM jobs {where} "
        f"ORDER BY {order_sql} "
        "LIMIT :limit OFFSET :offset"
    )
    cnt_sql = f"SELECT count(*) FROM jobs {where}"
    with engine.connect() as c:
        total = c.execute(text(cnt_sql), params).scalar()
        rows = c.execute(text(sql), params).mappings().all()
    return jsonify({"total": total, "rows": [dict(r) for r in rows]})


@app.route("/api/job/<int:job_id>")
def api_job(job_id):
    with engine.connect() as c:
        r = c.execute(text("SELECT * FROM jobs WHERE id=:i"), {"i": job_id}).mappings().first()
    if not r:
        return jsonify({"error": "not found"}), 404
    d = dict(r)
    d.pop("search", None)
    d.pop("raw", None)
    for k in ("first_seen", "last_seen"):
        if d.get(k):
            d[k] = str(d[k])
    return jsonify(d)


@app.route("/api/run/<kind>", methods=["POST"])
def run_task(kind):
    if kind not in ("refresh", "ai", "scrape", "analyze", "pipeline"):
        return jsonify({"error": "unknown task"}), 400
    opts = request.get_json(silent=True) or {}
    tid = actions.start(kind, **opts)
    if tid is None:
        return jsonify({"error": f"a '{kind}' task is already running"}), 409
    return jsonify(actions.TASKS[tid])


@app.route("/api/task/<tid>")
def task_status(tid):
    t = actions.TASKS.get(tid)
    if not t:
        return jsonify({"error": "no such task"}), 404
    return jsonify(t)


@app.route("/api/tasks")
def tasks_all():
    return jsonify(list(actions.TASKS.values())[-10:])


@app.route("/api/export.csv")
def export_csv():
    where, params = _where(request.args)
    sql = ("SELECT company, title, location, source, competitor, status, "
           "first_seen, url FROM jobs " + where +
           " ORDER BY company, title")
    with engine.connect() as c:
        rows = c.execute(text(sql), params).mappings().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "title", "location", "source", "competitor",
                "status", "first_seen", "url"])
    for r in rows:
        w.writerow([r["company"], r["title"], r["location"], r["source"],
                    r["competitor"], r["status"], r["first_seen"], r["url"]])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=jobs_export.csv"})


if __name__ == "__main__":
    import os
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
