"""app.py — Flask app for the task tracker."""
from __future__ import annotations

from datetime import date, timedelta

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
    phase_items = []
    all_items = []
    for phase in phases:
        items = db.list_items(conn, phase["id"])
        phase_items.append((phase, items))
        all_items.extend(items)

    resolved_dates = schedule.resolve_item_dates(project["start_date"],
                                                 all_items)
    resolved_by_id = {
        item["id"]: rdate for item, rdate in zip(all_items, resolved_dates)
    }

    view_phases = []
    for phase, items in phase_items:
        rows = []
        for item in items:
            rdate = resolved_by_id.get(item["id"])
            rows.append({
                **item,
                "resolved_date": rdate,
                "urgency": schedule.urgency(rdate, item["status"], today,
                                            due_soon_days),
                "resources": db.list_item_resources(conn, item["id"]),
            })
        view_phases.append({**phase, "items": rows,
                            "progress": schedule.progress(items)})
    everyday_rows, everyday_today = _everyday_view(conn, project["id"], today)
    return {
        "project": project,
        "phases": view_phases,
        "progress": schedule.progress(all_items),
        "info_cards": db.list_info_cards(conn, project["id"]),
        "everyday_items": everyday_rows,
        "everyday_today": everyday_today,
        "resources": db.list_project_resources(conn, project["id"]),
    }


def _everyday_view(conn, project_id, today, days_back=7):
    """Attach a per-day completion grid (last `days_back` days, oldest->today)
    to each everyday item, and compute today's completion summary."""
    window = [today - timedelta(days=n) for n in range(days_back - 1, -1, -1)]
    today_iso = today.isoformat()
    completed = db.list_everyday_completions(conn, project_id,
                                             window[0].isoformat())
    rows = []
    done_today = 0
    for item in db.list_everyday_items(conn, project_id):
        grid = [{
            "date": d.isoformat(),
            "label": d.strftime("%a"),
            "dom": d.day,
            "done": (item["id"], d.isoformat()) in completed,
            "is_today": d == today,
        } for d in window]
        if (item["id"], today_iso) in completed:
            done_today += 1
        rows.append({**item, "days": grid})
    total = len(rows)
    today_summary = {"done": done_today, "total": total,
                     "percent": round(done_today / total * 100) if total else 0}
    return rows, today_summary


def _all_dated_items(conn, due_soon_days, today=None):
    """Return every item across projects with resolved date + urgency,
    grouped per project so durations accumulate correctly."""
    today = today or date.today()
    out = []
    for project in db.list_projects(conn):
        ordered_items = []
        for phase in db.list_phases(conn, project["id"]):
            ordered_items.extend(db.list_items(conn, phase["id"]))
        resolved = schedule.resolve_item_dates(project["start_date"],
                                               ordered_items)
        for item, rdate in zip(ordered_items, resolved):
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
    # Expose the Google Calendar link builder to templates.
    flask_app.jinja_env.globals["gcal_link"] = ics.gcal_link

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
            tmp_path = tmp.name
            tmp.close()
            try:
                file.save(tmp_path)
                source_type, source_name, text = extract.extract_text(tmp_path)
            except Exception as e:  # noqa: BLE001 - keep upload page alive
                flask_app.logger.exception("File extraction failed")
                try:
                    _os.unlink(tmp_path)
                except OSError:
                    pass
                return render_template(
                    "upload.html",
                    error=f"Could not read that file: {e}",
                ), 400
            else:
                try:
                    _os.unlink(tmp_path)
                except OSError:
                    flask_app.logger.warning("Could not delete temp upload")
                source_name = file.filename
        else:
            text = request.form.get("text", "")
            source_type, source_name = "text", "typed"
        if not text.strip():
            return render_template("upload.html",
                                   error="Provide a file or some text."), 400
        max_chars = cfg.get("ai", {}).get("max_input_chars", 20000)
        try:
            backend = llm.get_backend(cfg)
            data = extract.extract_project(
                text, backend, start_date=start_date, due_date=due_date,
                max_input_chars=max_chars)
        except llm.LLMError as e:
            return render_template("upload.html",
                                   error=f"AI extraction failed: {e}"), 502
        except Exception as e:  # noqa: BLE001 - report without a crash page
            flask_app.logger.exception("Unexpected upload failure")
            return render_template(
                "upload.html",
                error=f"Upload failed before a tracker could be created: {e}",
            ), 500
        try:
            pid = db.create_project_from_extraction(
                conn, data, source_type, source_name, start_date, due_date)
        except Exception as e:  # noqa: BLE001 - keep upload page alive
            flask_app.logger.exception("Project persistence failed")
            return render_template(
                "upload.html",
                error=f"Tracker was generated but could not be saved: {e}",
            ), 500
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

    @flask_app.route("/everyday/<int:everyday_id>/status", methods=["POST"])
    def everyday_status(everyday_id):
        status = (request.json or {}).get("status", "todo")
        db.set_everyday_status(get_conn(flask_app), everyday_id, status)
        return jsonify({"ok": True, "status": status})

    @flask_app.route("/everyday/<int:everyday_id>/delete", methods=["POST"])
    def everyday_delete(everyday_id):
        db.delete_everyday_item(get_conn(flask_app), everyday_id)
        return jsonify({"ok": True})

    @flask_app.route("/everyday/<int:everyday_id>/day", methods=["POST"])
    def everyday_day(everyday_id):
        payload = request.json or {}
        day = payload.get("day")
        if not day:
            return jsonify({"ok": False, "error": "missing day"}), 400
        db.set_everyday_day(get_conn(flask_app), everyday_id, day,
                            bool(payload.get("done")))
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

    @flask_app.route("/project/<int:project_id>/everyday", methods=["POST"])
    def project_add_everyday(project_id):
        payload = request.json or {}
        conn = get_conn(flask_app)
        position = len(db.list_everyday_items(conn, project_id))
        eid = db.create_everyday_item(
            conn, project_id, payload.get("title", "New everyday item"),
            payload.get("description", ""), payload.get("cadence", ""),
            position=position)
        return jsonify({"ok": True, "id": eid})

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
