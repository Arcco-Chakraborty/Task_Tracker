"""app.py — Flask app for the task tracker."""
from __future__ import annotations

from datetime import date

from flask import Flask, abort, render_template

import db
import schedule
from config import load_config


def get_conn(flask_app):
    """One sqlite connection per app (single-user, local)."""
    return flask_app.config["CONN"]


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


def create_app(cfg=None) -> Flask:
    cfg = cfg or load_config()
    flask_app = Flask(__name__)
    db_path = cfg.get("app", {}).get("db_path", "tasktracker.db")
    conn = db.connect(db_path)
    db.init_db(conn)
    flask_app.config["CONN"] = conn
    flask_app.config["CFG"] = cfg
    flask_app.config["DUE_SOON_DAYS"] = cfg.get("tracking", {}).get(
        "due_soon_days", 3)

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

    return flask_app


if __name__ == "__main__":
    cfg = load_config()
    application = create_app(cfg)
    application.run(host=cfg.get("app", {}).get("host", "127.0.0.1"),
                    port=cfg.get("app", {}).get("port", 5000), debug=True)
