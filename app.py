"""app.py — Flask app for the task tracker."""
from __future__ import annotations

import os
import secrets
import threading
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

from flask import (Flask, abort, g, has_app_context, jsonify, redirect,
                   render_template, request, url_for, Response)

import db
import extract
import ics
import llm
import schedule
from auth import auth_bp, current_user, current_user_id, login_required
from config import load_config, load_dotenv


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


def _everyday_view(conn, project_id, today, days_back=14):
    """Attach a per-day completion grid (last `days_back` days up to today,
    oldest->today; no future days) to each everyday item, and compute today's
    completion summary. Only today is editable; past days are read-only."""
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
            "editable": d == today,
        } for d in window]
        if (item["id"], today_iso) in completed:
            done_today += 1
        rows.append({**item, "days": grid})
    total = len(rows)
    today_summary = {"done": done_today, "total": total,
                     "percent": round(done_today / total * 100) if total else 0}
    return rows, today_summary


def _all_dated_items(conn, due_soon_days, today=None, user_id=None):
    """Return every item across the user's projects with resolved date +
    urgency, grouped per project so durations accumulate correctly."""
    today = today or date.today()
    out = []
    for project in db.list_projects(conn, user_id):
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


def _run_extract_job(db_path, cfg, job_id, text, source_type, source_name,
                     start_date, due_date, user_id):
    """Run one extraction in a background thread with its own DB connection.
    The request that spawned this has already returned; the browser polls the
    job row, so neither gunicorn nor nginx timeouts apply to the AI call."""
    conn = db.connect(db_path)
    try:
        backend = llm.get_backend(cfg)
        max_chars = cfg.get("ai", {}).get("max_input_chars", 20000)
        data = extract.extract_project(text, backend, start_date=start_date,
                                       due_date=due_date,
                                       max_input_chars=max_chars)
        pid = db.create_project_from_extraction(
            conn, data, source_type, source_name, start_date, due_date,
            user_id=user_id)
        db.finish_job(conn, job_id, project_id=pid)
    except llm.LLMError as e:
        db.finish_job(conn, job_id, error=f"AI extraction failed: {e}")
    except Exception as e:  # noqa: BLE001 - surface anything to the poller
        db.finish_job(conn, job_id, error=f"Unexpected failure: {e}")
    finally:
        conn.close()


def _streak(days: set, today) -> int:
    """Consecutive days (ending today, or yesterday if today isn't done yet)
    that have at least one everyday completion."""
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    count = 0
    while cursor.isoformat() in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def create_app(cfg=None) -> Flask:
    load_dotenv()
    cfg = cfg or load_config()
    flask_app = Flask(__name__)
    db_path = cfg.get("app", {}).get("db_path", "tasktracker.db")
    flask_app.config["DB_PATH"] = db_path
    flask_app.config["CONN"] = None
    flask_app.config["CFG"] = cfg
    flask_app.config["DUE_SOON_DAYS"] = cfg.get("tracking", {}).get(
        "due_soon_days", 3)

    # --- sessions & auth (Google OAuth, ported from arctronas) ---
    flask_app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    https_enabled = os.environ.get("HTTPS_ENABLED", "").lower() == "true"
    flask_app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=https_enabled,
        PERMANENT_SESSION_LIFETIME=86400,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # cap uploads at 10 MB
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        GOOGLE_REDIRECT_URI=os.environ.get(
            "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:5000/auth/callback"),
        ALLOWED_EMAILS=os.environ.get("ALLOWED_EMAILS", ""),
        ADMIN_EMAILS=os.environ.get("ADMIN_EMAILS", ""),
        GET_CONN=lambda: get_conn(flask_app),
    )
    flask_app.register_blueprint(auth_bp)

    def _is_admin(user) -> bool:
        """Admin = email listed in ADMIN_EMAILS; if unset, the first account
        (id 1 — the instance owner) is the admin."""
        if not user:
            return False
        raw = flask_app.config.get("ADMIN_EMAILS", "")
        allow = [e.strip().lower() for e in raw.split(",") if e.strip()]
        if allow:
            return user["email"].lower() in allow
        return user["id"] == 1

    def admin_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not _is_admin(current_user()):
                abort(404)  # don't reveal the admin surface exists
            return view(*args, **kwargs)
        return login_required(wrapper)

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

    @flask_app.before_request
    def _reject_cross_origin_posts():
        """Belt-and-braces CSRF guard: state-changing requests must come from
        our own origin (SameSite=Lax cookies already block most CSRF)."""
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc not in ("", request.host):
                abort(403)

    @flask_app.after_request
    def _security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()")
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
            "https://api.fontshare.com; "
            "font-src https://fonts.gstatic.com https://api.fontshare.com "
            "https://cdn.fontshare.com data:; "
            "img-src 'self' data: https://*.googleusercontent.com; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
            "form-action 'self'")
        if https_enabled:
            resp.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains")
        return resp

    @flask_app.context_processor
    def _inject_globals():
        """`now`, `user`, and per-user `stats` for the chrome."""
        uid = current_user_id()
        user = current_user()
        base = {"now": datetime.now(), "user": user,
                "is_admin": _is_admin(user),
                "stats": {"streak": 0, "week_done": 0}}
        if uid is None:
            return base
        conn = get_conn(flask_app)
        today = date.today()
        days = db.all_completion_days(conn, uid)
        week_ago = (today - timedelta(days=7)).isoformat()
        week_done = (db.count_done_items_since(conn, week_ago, uid)
                     + sum(1 for d in days if d >= week_ago))
        base["stats"] = {"streak": _streak(days, today), "week_done": week_done}
        return base

    def _projects_with_progress(conn, user_id):
        projects = []
        for p in db.list_projects(conn, user_id):
            items = []
            for ph in db.list_phases(conn, p["id"]):
                items.extend(db.list_items(conn, ph["id"]))
            projects.append({**p, "progress": schedule.progress(items),
                             "item_count": len(items)})
        return projects

    @flask_app.route("/")
    def index():
        # Logged-out visitors get the marketing landing page; signed-in users
        # get their dashboard.
        uid = current_user_id()
        if uid is None:
            return render_template("landing.html",
                                   sent=request.args.get("sent"))
        conn = get_conn(flask_app)
        today = date.today()
        due_soon = flask_app.config["DUE_SOON_DAYS"]
        projects = _projects_with_progress(conn, uid)
        items = _all_dated_items(conn, due_soon, today, uid)
        done = sum(1 for i in items if i["status"] == "done")
        total = len(items)
        overdue = [i for i in items if i["urgency"] == "overdue"]
        upcoming = sorted(
            (i for i in items if i["status"] != "done" and i["resolved_date"]
             and i["resolved_date"] >= today),
            key=lambda i: i["resolved_date"])[:5]
        ev_total = db.count_everyday_items(conn, uid)
        ev_done = db.count_everyday_done_on(conn, today.isoformat(), uid)
        overall = round(done / total * 100) if total else 0
        focus = max(0, min(100, overall - len(overdue) * 8))
        hero = {
            "overall": overall, "done": done, "total": total,
            "overdue": len(overdue), "focus": focus,
            "everyday_done": ev_done, "everyday_total": ev_total,
            "everyday_pct": round(ev_done / ev_total * 100) if ev_total else 0,
        }
        return render_template("index.html", active="dashboard",
                               projects=projects, hero=hero, upcoming=upcoming)

    @flask_app.route("/projects")
    @login_required
    def projects_page():
        conn = get_conn(flask_app)
        return render_template("projects.html", active="projects",
                               projects=_projects_with_progress(conn, current_user_id()))

    @flask_app.route("/today")
    @login_required
    def today_page():
        conn = get_conn(flask_app)
        uid = current_user_id()
        today = date.today()
        due_soon = flask_app.config["DUE_SOON_DAYS"]
        items = _all_dated_items(conn, due_soon, today, uid)
        focus = sorted(
            (i for i in items if i["status"] != "done"
             and i["urgency"] in ("overdue", "due-soon")),
            key=lambda i: (i["urgency"] != "overdue", i["resolved_date"] or date.max))
        # everyday items across all projects, with today's done state
        everyday = []
        for p in db.list_projects(conn, uid):
            rows, _ = _everyday_view(conn, p["id"], today)
            for r in rows:
                everyday.append({**r, "project_title": p["title"],
                                 "project_id": p["id"]})
        return render_template("today.html", active="today",
                               focus=focus, everyday=everyday)

    @flask_app.route("/planner")
    @login_required
    def planner_page():
        conn = get_conn(flask_app)
        today = date.today()
        items = _all_dated_items(conn, flask_app.config["DUE_SOON_DAYS"], today,
                                 current_user_id())
        groups = {}  # date-iso -> list (None bucket for unscheduled)
        for i in items:
            key = i["resolved_date"].isoformat() if i["resolved_date"] else None
            groups.setdefault(key, []).append(i)
        dated = sorted((k, v) for k, v in groups.items() if k is not None)
        undated = groups.get(None, [])
        return render_template("planner.html", active="planner",
                               dated=dated, undated=undated)

    @flask_app.route("/analytics")
    @login_required
    def analytics_page():
        conn = get_conn(flask_app)
        uid = current_user_id()
        today = date.today()
        items = _all_dated_items(conn, flask_app.config["DUE_SOON_DAYS"], today, uid)
        total = len(items)
        done = sum(1 for i in items if i["status"] == "done")
        by_urgency = {k: 0 for k in ("overdue", "due-soon", "upcoming", "none", "done")}
        for i in items:
            by_urgency[i["urgency"]] += 1
        weight_dist = {w: 0 for w in range(1, 6)}
        for i in items:
            weight_dist[min(5, max(1, i.get("weight") or 3))] += 1
        # completions over the last 14 days
        trend = []
        for n in range(13, -1, -1):
            d = today - timedelta(days=n)
            trend.append({"label": d.strftime("%a")[0], "date": d.isoformat(),
                          "done": db.count_everyday_done_on(conn, d.isoformat(), uid)})
        max_trend = max((t["done"] for t in trend), default=0) or 1
        projects = _projects_with_progress(conn, uid)
        analytics = {
            "total": total, "done": done,
            "completion": round(done / total * 100) if total else 0,
            "by_urgency": by_urgency, "weight_dist": weight_dist,
            "weight_max": max(weight_dist.values()) or 1,
            "trend": trend, "trend_max": max_trend,
            "active_projects": len(projects),
        }
        return render_template("analytics.html", active="analytics",
                               analytics=analytics, projects=projects)

    @flask_app.route("/settings")
    @login_required
    def settings_page():
        return render_template("settings.html", active="settings",
                               cfg=flask_app.config["CFG"])

    @flask_app.route("/project/<int:project_id>")
    @login_required
    def project(project_id):
        conn = get_conn(flask_app)
        p = db.get_project(conn, project_id, current_user_id())
        if p is None:
            abort(404)
        ctx = _project_view(conn, p, flask_app.config["DUE_SOON_DAYS"])
        return render_template("project.html", active="projects", **ctx)

    @flask_app.route("/upload", methods=["GET", "POST"])
    @login_required
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
            if request.headers.get("X-Async") == "1":
                return jsonify({"ok": False,
                                "error": "Provide a file or some text."}), 400
            return render_template("upload.html",
                                   error="Provide a file or some text."), 400

        # Async path (the JS upload): hand the slow AI call to a background
        # thread and return a job id immediately — request/proxy/worker
        # timeouts can no longer kill a long extraction.
        if request.headers.get("X-Async") == "1":
            uid = current_user_id()
            jid = db.create_job(conn, uid)
            threading.Thread(
                target=_run_extract_job,
                args=(flask_app.config["DB_PATH"], cfg, jid, text,
                      source_type, source_name, start_date, due_date, uid),
                daemon=True).start()
            return jsonify({"ok": True, "job_id": jid})

        # Legacy synchronous path (no-JS fallback and tests).
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
                conn, data, source_type, source_name, start_date, due_date,
                user_id=current_user_id())
        except Exception as e:  # noqa: BLE001 - keep upload page alive
            flask_app.logger.exception("Project persistence failed")
            return render_template(
                "upload.html",
                error=f"Tracker was generated but could not be saved: {e}",
            ), 500
        return redirect(url_for("project", project_id=pid))

    @flask_app.route("/upload/job/<int:job_id>")
    @login_required
    def upload_job_status(job_id):
        job = db.get_job(get_conn(flask_app), job_id, current_user_id())
        if job is None:
            abort(404)
        return jsonify({"status": job["status"], "error": job["error"],
                        "project_id": job["project_id"]})

    def _require_item(conn, item_id):
        if not db.owns_item(conn, item_id, current_user_id()):
            abort(403)

    def _require_phase(conn, phase_id):
        if not db.owns_phase(conn, phase_id, current_user_id()):
            abort(403)

    def _require_everyday(conn, everyday_id):
        if not db.owns_everyday(conn, everyday_id, current_user_id()):
            abort(403)

    def _require_project(conn, project_id):
        if db.get_project(conn, project_id, current_user_id()) is None:
            abort(403)

    @flask_app.route("/item/<int:item_id>/status", methods=["POST"])
    @login_required
    def item_status(item_id):
        conn = get_conn(flask_app)
        _require_item(conn, item_id)
        status = (request.json or {}).get("status", "todo")
        db.set_item_status(conn, item_id, status)
        return jsonify({"ok": True, "status": status})

    @flask_app.route("/item/<int:item_id>/edit", methods=["POST"])
    @login_required
    def item_edit(item_id):
        conn = get_conn(flask_app)
        _require_item(conn, item_id)
        payload = request.json or {}
        fields = {k: payload[k] for k in
                  ("title", "description", "deadline", "duration_days")
                  if k in payload}
        db.update_item(conn, item_id, **fields)
        return jsonify({"ok": True})

    @flask_app.route("/item/<int:item_id>/delete", methods=["POST"])
    @login_required
    def item_delete(item_id):
        conn = get_conn(flask_app)
        _require_item(conn, item_id)
        db.delete_item(conn, item_id)
        return jsonify({"ok": True})

    @flask_app.route("/everyday/<int:everyday_id>/status", methods=["POST"])
    @login_required
    def everyday_status(everyday_id):
        conn = get_conn(flask_app)
        _require_everyday(conn, everyday_id)
        status = (request.json or {}).get("status", "todo")
        db.set_everyday_status(conn, everyday_id, status)
        return jsonify({"ok": True, "status": status})

    @flask_app.route("/everyday/<int:everyday_id>/delete", methods=["POST"])
    @login_required
    def everyday_delete(everyday_id):
        conn = get_conn(flask_app)
        _require_everyday(conn, everyday_id)
        db.delete_everyday_item(conn, everyday_id)
        return jsonify({"ok": True})

    @flask_app.route("/everyday/<int:everyday_id>/day", methods=["POST"])
    @login_required
    def everyday_day(everyday_id):
        conn = get_conn(flask_app)
        _require_everyday(conn, everyday_id)
        payload = request.json or {}
        day = payload.get("day")
        if not day:
            return jsonify({"ok": False, "error": "missing day"}), 400
        # Only today can be ticked off — no back- or future-dating.
        if day != date.today().isoformat():
            return jsonify({"ok": False,
                            "error": "only today can be updated"}), 403
        db.set_everyday_day(conn, everyday_id, day, bool(payload.get("done")))
        return jsonify({"ok": True})

    @flask_app.route("/phase/<int:phase_id>/item", methods=["POST"])
    @login_required
    def phase_add_item(phase_id):
        payload = request.json or {}
        conn = get_conn(flask_app)
        _require_phase(conn, phase_id)
        position = len(db.list_items(conn, phase_id))
        iid = db.create_item(conn, phase_id, payload.get("title", "New item"),
                             payload.get("description", ""),
                             deadline=payload.get("deadline"),
                             duration_days=payload.get("duration_days"),
                             position=position)
        return jsonify({"ok": True, "id": iid})

    @flask_app.route("/project/<int:project_id>/everyday", methods=["POST"])
    @login_required
    def project_add_everyday(project_id):
        payload = request.json or {}
        conn = get_conn(flask_app)
        _require_project(conn, project_id)
        position = len(db.list_everyday_items(conn, project_id))
        eid = db.create_everyday_item(
            conn, project_id, payload.get("title", "New everyday item"),
            payload.get("description", ""), payload.get("cadence", ""),
            position=position)
        return jsonify({"ok": True, "id": eid})

    @flask_app.route("/project/<int:project_id>/phase", methods=["POST"])
    @login_required
    def project_add_phase(project_id):
        conn = get_conn(flask_app)
        _require_project(conn, project_id)
        position = len(db.list_phases(conn, project_id))
        pid = db.create_phase(conn, project_id,
                              (request.json or {}).get("name", "New phase"),
                              position)
        return jsonify({"ok": True, "id": pid})

    @flask_app.route("/project/<int:project_id>/dates", methods=["POST"])
    @login_required
    def project_dates(project_id):
        db.update_project_dates(get_conn(flask_app), project_id,
                                request.form.get("start_date") or None,
                                request.form.get("due_date") or None,
                                current_user_id())
        return redirect(url_for("project", project_id=project_id))

    @flask_app.route("/project/<int:project_id>/delete", methods=["POST"])
    @login_required
    def project_delete(project_id):
        db.delete_project(get_conn(flask_app), project_id, current_user_id())
        return jsonify({"ok": True})

    @flask_app.route("/dashboard")
    @login_required
    def dashboard():
        conn = get_conn(flask_app)
        items = _all_dated_items(conn, flask_app.config["DUE_SOON_DAYS"],
                                 user_id=current_user_id())
        order = {"overdue": 0, "due-soon": 1, "upcoming": 2, "none": 3,
                 "done": 4}
        # Within an urgency bucket, time-sensitive items come first.
        items.sort(key=lambda i: (order[i["urgency"]],
                                  0 if i.get("time_sensitive") else 1,
                                  i["resolved_date"] or date.max))
        return render_template("dashboard.html", active="today", items=items)

    @flask_app.route("/calendar")
    @login_required
    def calendar():
        conn = get_conn(flask_app)
        items = [i for i in _all_dated_items(conn,
                 flask_app.config["DUE_SOON_DAYS"], user_id=current_user_id())
                 if i["resolved_date"]]
        by_date = {}
        for i in items:
            by_date.setdefault(i["resolved_date"].isoformat(), []).append(i)
        return render_template("calendar.html", active="calendar",
                               by_date=sorted(by_date.items()))

    def _ics_response(items):
        events = [{"uid": f"item-{i['id']}",
                   "summary": f"{i['project_title']}: {i['title']}",
                   "date": i["resolved_date"]} for i in items]
        return Response(ics.build_ics(events), mimetype="text/calendar")

    @flask_app.route("/export.ics")
    @login_required
    def export_all_ics():
        conn = get_conn(flask_app)
        return _ics_response(_all_dated_items(
            conn, flask_app.config["DUE_SOON_DAYS"], user_id=current_user_id()))

    # --- public pages -------------------------------------------------------

    site_url = os.environ.get("SITE_URL", "https://blackmoniker.com").rstrip("/")

    @flask_app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @flask_app.route("/robots.txt")
    def robots_txt():
        lines = ["User-agent: *", "Allow: /"]
        # All of these are login-gated anyway; keep crawlers off the redirects.
        for path in ("/admin", "/project/", "/projects", "/today", "/planner",
                     "/calendar", "/analytics", "/settings", "/upload",
                     "/dashboard", "/auth/", "/login", "/logout",
                     "/export.ics"):
            lines.append(f"Disallow: {path}")
        lines += ["", f"Sitemap: {site_url}/sitemap.xml"]
        return Response("\n".join(lines) + "\n", mimetype="text/plain")

    @flask_app.route("/sitemap.xml")
    def sitemap_xml():
        urls = [(f"{site_url}/", "weekly", "1.0"),
                (f"{site_url}/privacy", "yearly", "0.3")]
        body = "".join(
            f"<url><loc>{u}</loc><changefreq>{c}</changefreq>"
            f"<priority>{p}</priority></url>" for u, c, p in urls)
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               f"{body}</urlset>")
        return Response(xml, mimetype="application/xml")

    @flask_app.route("/llms.txt")
    def llms_txt():
        return Response(f"""\
# BlackMoniker

> BlackMoniker ({site_url}) turns messy notes, emails, syllabi and documents
> into structured, trackable plans. Paste unstructured text or upload a
> PDF/Markdown file; AI extracts every deadline, task, meeting and source,
> sequences them correctly (time-sensitive items first), assigns effort
> weights, and builds a tracker with phases, daily habit grids, progress
> analytics and one-click Google Calendar links.

## How it works
- Sign in with Google (identity only — no access to Gmail/Drive/Calendar).
- Paste text or upload a document; Gemini extracts and sequences the plan.
- Track tasks (todo / in progress / done), everyday habits per day, and
  progress weighted by effort. Export deadlines as .ics or add single
  events to Google Calendar via prefilled links.

## Pages
- [Landing]({site_url}/): product overview, live demo, FAQ, contact form
- [Privacy]({site_url}/privacy): plain-language privacy policy

The app itself ({site_url}/login and beyond) requires sign-in; per-user
workspaces are private and not crawlable.

Free while in beta. Built by Arctek Systems.
""", mimetype="text/plain")

    @flask_app.route("/contact", methods=["POST"])
    def contact():
        # Honeypot: bots fill the hidden "website" field; pretend success.
        if request.form.get("website"):
            return redirect("/?sent=1#contact")
        name = (request.form.get("name") or "").strip()[:120]
        email = (request.form.get("email") or "").strip()[:200]
        message = (request.form.get("message") or "").strip()[:5000]
        if not message:
            return redirect("/#contact")
        conn = get_conn(flask_app)
        ip = (request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
              or request.remote_addr or "")
        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)
                    ).strftime("%Y-%m-%d %H:%M:%S")
        if db.count_messages_from_ip_since(conn, ip, hour_ago) >= 5:
            return "Too many messages — try again later.", 429
        db.create_contact_message(conn, name, email, message, ip)
        return redirect("/?sent=1#contact")

    # --- admin --------------------------------------------------------------

    @flask_app.route("/admin")
    @admin_required
    def admin():
        conn = get_conn(flask_app)
        today = date.today()
        overview = db.admin_overview(conn)
        users = db.list_users_admin(conn)
        week_ago = (today - timedelta(days=7)).isoformat()
        overview["new_this_week"] = sum(
            1 for u in users if (u["created_at"] or "") >= week_ago)
        per_day = db.signups_per_day(conn, (today - timedelta(days=29)).isoformat())
        signup_trend = []
        for n in range(29, -1, -1):
            d = today - timedelta(days=n)
            signup_trend.append({"date": d.isoformat(),
                                 "label": d.strftime("%d"),
                                 "n": per_day.get(d.isoformat(), 0)})
        return render_template(
            "admin.html", active="admin", overview=overview, users=users,
            messages=db.list_contact_messages(conn), signup_trend=signup_trend,
            signup_max=max((t["n"] for t in signup_trend), default=0) or 1)

    @flask_app.route("/admin/messages/<int:message_id>/read", methods=["POST"])
    @admin_required
    def admin_message_read(message_id):
        db.set_message_read(get_conn(flask_app), message_id)
        return jsonify({"ok": True})

    @flask_app.route("/admin/messages/<int:message_id>/delete", methods=["POST"])
    @admin_required
    def admin_message_delete(message_id):
        db.delete_contact_message(get_conn(flask_app), message_id)
        return jsonify({"ok": True})

    @flask_app.route("/project/<int:project_id>/export.ics")
    @login_required
    def export_project_ics(project_id):
        conn = get_conn(flask_app)
        uid = current_user_id()
        if db.get_project(conn, project_id, uid) is None:
            abort(404)
        items = [i for i in _all_dated_items(conn,
                 flask_app.config["DUE_SOON_DAYS"], user_id=uid)
                 if i["project_id"] == project_id]
        return _ics_response(items)

    return flask_app


if __name__ == "__main__":
    cfg = load_config()
    application = create_app(cfg)
    application.run(host=cfg.get("app", {}).get("host", "127.0.0.1"),
                    port=cfg.get("app", {}).get("port", 5000), debug=True)
