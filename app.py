"""app.py — Flask app for the task tracker."""
from __future__ import annotations

from datetime import date

from flask import (Flask, abort, g, has_app_context, jsonify, redirect,
                   render_template, request, url_for, Response)

import db
import extract
import ics
import llm
import schedule
from config import load_config


def get_conn(flask_app):
    """Return a SQLite connection.

    SQLite forbids using a connection from a thread other than the one that
    created it, and Flask's dev server serves each request on its own thread.
    So inside a request/app context we use a per-request connection cached on
    `g` (and closed on teardown). Outside any app context — e.g. tests that
    seed/assert by calling get_conn directly — we fall back to a persistent
    connection stored on the app config (only ever touched on that thread).
    """
    db_path = flask_app.config["DB_PATH"]
    if has_app_context():
        if "conn" not in g:
            g.conn = db.connect(db_path)
        return g.conn
    conn = flask_app.config.get("CONN")
    if conn is None:
        conn = flask_app.config["CONN"] = db.connect(db_path)
    return conn


def _project_view(conn, project, due_soon_days, today=None):
    """Build the render context for one project: phases with resolved dates,
    urgency and progress."""
    today = today or date.today()
    phases = db.list_phases(conn, project["id"])
    all_items = []
    view_phases = []
    for phase in phases:
        items = db.list_items(conn, phase["id"])
        resolved = schedule.resolve_item_dates(project["start_date"], items)
        rows = []
        for item, rdate in zip(items, resolved):
            rows.append({
                **item,
                "resolved_date": rdate,
                "urgency": schedule.urgency(rdate, item["status"], today,
                                            due_soon_days),
            })
        all_items.extend(rows)
        view_phases.append({**phase, "items": rows,
                            "progress": schedule.progress(items)})
    return {
        "project": project,
        "phases": view_phases,
        "progress": schedule.progress(all_items),
    }


def _all_dated_items(conn, due_soon_days, today=None):
    """Return every item across projects with resolved date + urgency,
    grouped per project so durations accumulate correctly."""
    today = today or date.today()
    out = []
    for project in db.list_projects(conn):
        for phase in db.list_phases(conn, project["id"]):
            items = db.list_items(conn, phase["id"])
            resolved = schedule.resolve_item_dates(project["start_date"], items)
            for item, rdate in zip(items, resolved):
                out.append({
                    **item,
                    "project_id": project["id"],
                    "project_title": project["title"],
                    "resolved_date": rdate,
                    "urgency": schedule.urgency(rdate, item["status"], today,
                                                due_soon_days),
                })
    return out


def create_app(cfg=None) -> Flask:
    cfg = cfg or load_config()
    flask_app = Flask(__name__)
    db_path = cfg.get("app", {}).get("db_path", "tasktracker.db")
    flask_app.config["DB_PATH"] = db_path
    flask_app.config["CONN"] = None
    flask_app.config["CFG"] = cfg
    flask_app.config["DUE_SOON_DAYS"] = cfg.get("tracking", {}).get(
        "due_soon_days", 3)

    # Create the schema once at startup (separate short-lived connection).
    init_conn = db.connect(db_path)
    db.init_db(init_conn)
    init_conn.close()

    @flask_app.teardown_appcontext
    def _close_conn(exc):  # noqa: ARG001 - Flask passes the exception
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @flask_app.route("/")
    def index():
        conn = get_conn(flask_app)
        projects = []
        for p in db.list_projects(conn):
            items = []
            for ph in db.list_phases(conn, p["id"]):
                items.extend(db.list_items(conn, ph["id"]))
            projects.append({**p, "progress": schedule.progress(items)})
        return render_template("index.html", projects=projects)

    @flask_app.route("/project/<int:project_id>")
    def project(project_id):
        conn = get_conn(flask_app)
        p = db.get_project(conn, project_id)
        if p is None:
            abort(404)
        ctx = _project_view(conn, p, flask_app.config["DUE_SOON_DAYS"])
        return render_template("project.html", **ctx)

    @flask_app.route("/upload", methods=["GET", "POST"])
    def upload():
        conn = get_conn(flask_app)
        if request.method == "GET":
            return render_template("upload.html")
        cfg = flask_app.config["CFG"]
        start_date = request.form.get("start_date") or None
        due_date = request.form.get("due_date") or None
        file = request.files.get("file")
        if file and file.filename:
            import tempfile, os as _os
            ext = _os.path.splitext(file.filename)[1]
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
            file.save(tmp.name)
            tmp.close()
            try:
                source_type, source_name, text = extract.extract_text(tmp.name)
            finally:
                _os.unlink(tmp.name)
            source_name = file.filename
        else:
            text = request.form.get("text", "")
            source_type, source_name = "text", "typed"
        if not text.strip():
            return render_template("upload.html",
                                   error="Provide a file or some text."), 400
        backend = llm.get_backend(cfg)
        max_chars = cfg.get("ai", {}).get("max_input_chars", 20000)
        try:
            data = extract.extract_project(
                text, backend, start_date=start_date, due_date=due_date,
                max_input_chars=max_chars)
        except llm.LLMError as e:
            return render_template("upload.html",
                                   error=f"AI extraction failed: {e}"), 502
        pid = db.create_project_from_extraction(
            conn, data, source_type, source_name, start_date, due_date)
        return redirect(url_for("project", project_id=pid))

    @flask_app.route("/item/<int:item_id>/status", methods=["POST"])
    def item_status(item_id):
        status = (request.json or {}).get("status", "todo")
        db.set_item_status(get_conn(flask_app), item_id, status)
        return jsonify({"ok": True, "status": status})

    @flask_app.route("/item/<int:item_id>/edit", methods=["POST"])
    def item_edit(item_id):
        payload = request.json or {}
        fields = {k: payload[k] for k in
                  ("title", "description", "deadline", "duration_days")
                  if k in payload}
        db.update_item(get_conn(flask_app), item_id, **fields)
        return jsonify({"ok": True})

    @flask_app.route("/item/<int:item_id>/delete", methods=["POST"])
    def item_delete(item_id):
        db.delete_item(get_conn(flask_app), item_id)
        return jsonify({"ok": True})

    @flask_app.route("/phase/<int:phase_id>/item", methods=["POST"])
    def phase_add_item(phase_id):
        payload = request.json or {}
        conn = get_conn(flask_app)
        position = len(db.list_items(conn, phase_id))
        iid = db.create_item(conn, phase_id, payload.get("title", "New item"),
                             payload.get("description", ""),
                             deadline=payload.get("deadline"),
                             duration_days=payload.get("duration_days"),
                             position=position)
        return jsonify({"ok": True, "id": iid})

    @flask_app.route("/project/<int:project_id>/phase", methods=["POST"])
    def project_add_phase(project_id):
        conn = get_conn(flask_app)
        position = len(db.list_phases(conn, project_id))
        pid = db.create_phase(conn, project_id,
                              (request.json or {}).get("name", "New phase"),
                              position)
        return jsonify({"ok": True, "id": pid})

    @flask_app.route("/project/<int:project_id>/dates", methods=["POST"])
    def project_dates(project_id):
        db.update_project_dates(get_conn(flask_app), project_id,
                                request.form.get("start_date") or None,
                                request.form.get("due_date") or None)
        return redirect(url_for("project", project_id=project_id))

    @flask_app.route("/dashboard")
    def dashboard():
        conn = get_conn(flask_app)
        items = _all_dated_items(conn, flask_app.config["DUE_SOON_DAYS"])
        order = {"overdue": 0, "due-soon": 1, "upcoming": 2, "none": 3,
                 "done": 4}
        items.sort(key=lambda i: (order[i["urgency"]],
                                  i["resolved_date"] or date.max))
        return render_template("dashboard.html", items=items)

    @flask_app.route("/calendar")
    def calendar():
        conn = get_conn(flask_app)
        items = [i for i in _all_dated_items(conn,
                 flask_app.config["DUE_SOON_DAYS"]) if i["resolved_date"]]
        by_date = {}
        for i in items:
            by_date.setdefault(i["resolved_date"].isoformat(), []).append(i)
        return render_template("calendar.html",
                               by_date=sorted(by_date.items()))

    def _ics_response(items):
        events = [{"uid": f"item-{i['id']}",
                   "summary": f"{i['project_title']}: {i['title']}",
                   "date": i["resolved_date"]} for i in items]
        return Response(ics.build_ics(events), mimetype="text/calendar")

    @flask_app.route("/export.ics")
    def export_all_ics():
        return _ics_response(_all_dated_items(conn := get_conn(flask_app),
                             flask_app.config["DUE_SOON_DAYS"]))

    @flask_app.route("/project/<int:project_id>/export.ics")
    def export_project_ics(project_id):
        conn = get_conn(flask_app)
        if db.get_project(conn, project_id) is None:
            abort(404)
        items = [i for i in _all_dated_items(conn,
                 flask_app.config["DUE_SOON_DAYS"])
                 if i["project_id"] == project_id]
        return _ics_response(items)

    return flask_app


if __name__ == "__main__":
    cfg = load_config()
    application = create_app(cfg)
    application.run(host=cfg.get("app", {}).get("host", "127.0.0.1"),
                    port=cfg.get("app", {}).get("port", 5000), debug=True)
