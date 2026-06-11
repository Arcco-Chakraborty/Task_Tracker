import app as app_module
import db


def _client(tmp_path):
    db_path = str(tmp_path / "t.db")
    cfg = {"app": {"db_path": db_path}, "tracking": {"due_soon_days": 3}}
    flask_app = app_module.create_app(cfg)
    flask_app.config.update(TESTING=True)
    client = flask_app.test_client()
    # log in a test user so the (now auth-gated) routes are reachable
    conn = app_module.get_conn(flask_app)
    user = db.get_or_create_user(conn, "tester@example.com", "Tester", "")
    flask_app.config["TEST_UID"] = user["id"]
    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
    return flask_app, client


def _uid(flask_app):
    return flask_app.config["TEST_UID"]


def _seed(flask_app):
    conn = app_module.get_conn(flask_app)
    pid = db.create_project(conn, "My Project", "summary", "text", "typed",
                            start_date="2026-06-01", user_id=_uid(flask_app))
    ph = db.create_phase(conn, pid, "Phase 1", 0)
    db.create_item(conn, ph, "First item", "desc", duration_days=2, position=0)
    return pid


def test_index_lists_projects(tmp_path):
    flask_app, client = _client(tmp_path)
    _seed(flask_app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"My Project" in resp.data


def test_project_page_shows_items(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    resp = client.get(f"/project/{pid}")
    assert resp.status_code == 200
    assert b"First item" in resp.data
    assert b"Phase 1" in resp.data


def test_project_404(tmp_path):
    flask_app, client = _client(tmp_path)
    assert client.get("/project/999").status_code == 404


def test_upload_text_creates_project(tmp_path, monkeypatch):
    flask_app, client = _client(tmp_path)

    def fake_extract_project(text, backend, **kw):
        return {"title": "Generated", "summary": "s",
                "suggested_start": None, "suggested_due": None,
                "info_cards": [{"title": "Constraint", "body": "Keep this"}],
                "everyday_items": [{"title": "Daily review",
                                    "description": "", "cadence": "daily"}],
                "resources": [{"title": "Portal", "url": None,
                               "note": "Use for uploads",
                               "related_item_title": "task a"}],
                "phases": [{"name": "P", "items": [
                    {"title": "task a", "description": "", "deadline": None,
                     "duration_days": 1, "resources": []}]}]}

    monkeypatch.setattr(app_module.extract, "extract_project",
                        fake_extract_project)
    monkeypatch.setattr(app_module.llm, "get_backend", lambda cfg: object())
    resp = client.post("/upload", data={"text": "do some work"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b"Generated" in resp.data
    assert b"task a" in resp.data
    assert b"Constraint" in resp.data
    assert b"Daily review" in resp.data
    assert b"Portal" in resp.data


def test_upload_llm_error_stays_on_upload_page(tmp_path, monkeypatch):
    flask_app, client = _client(tmp_path)

    def fail_extract_project(text, backend, **kw):
        raise app_module.llm.LLMError("quota")

    monkeypatch.setattr(app_module.extract, "extract_project",
                        fail_extract_project)
    monkeypatch.setattr(app_module.llm, "get_backend", lambda cfg: object())
    resp = client.post("/upload", data={"text": "do some work"})
    assert resp.status_code == 502
    assert b"AI extraction failed: quota" in resp.data


def test_toggle_status(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    ph = db.list_phases(conn, pid)[0]
    item_id = db.list_items(conn, ph["id"])[0]["id"]
    resp = client.post(f"/item/{item_id}/status", json={"status": "done"})
    assert resp.status_code == 200
    assert db.list_items(conn, ph["id"])[0]["status"] == "done"


def test_add_item(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    ph = db.list_phases(conn, pid)[0]
    client.post(f"/phase/{ph['id']}/item",
                json={"title": "new one", "description": ""})
    titles = [i["title"] for i in db.list_items(conn, ph["id"])]
    assert "new one" in titles


def test_everyday_status_and_add(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    resp = client.post(f"/project/{pid}/everyday",
                       json={"title": "review inbox", "cadence": "daily"})
    assert resp.status_code == 200
    everyday = db.list_everyday_items(conn, pid)
    assert everyday[0]["title"] == "review inbox"
    resp = client.post(f"/everyday/{everyday[0]['id']}/status",
                       json={"status": "done"})
    assert resp.status_code == 200
    assert db.list_everyday_items(conn, pid)[0]["status"] == "done"


def test_delete_item(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    ph = db.list_phases(conn, pid)[0]
    item_id = db.list_items(conn, ph["id"])[0]["id"]
    client.post(f"/item/{item_id}/delete")
    assert db.list_items(conn, ph["id"]) == []


def test_set_dates(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    client.post(f"/project/{pid}/dates",
                data={"start_date": "2026-06-05", "due_date": "2026-07-01"},
                follow_redirects=True)
    conn = app_module.get_conn(flask_app)
    assert db.get_project(conn, pid)["start_date"] == "2026-06-05"


def test_dashboard_and_calendar_render(tmp_path):
    flask_app, client = _client(tmp_path)
    _seed(flask_app)
    assert client.get("/dashboard").status_code == 200
    assert client.get("/calendar").status_code == 200


def test_export_ics(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    ph = db.list_phases(conn, pid)[0]
    # give the item a real date so it appears in the calendar export
    db.update_item(conn, db.list_items(conn, ph["id"])[0]["id"],
                   deadline="2026-06-20")
    resp = client.get("/export.ics")
    assert resp.status_code == 200
    assert b"BEGIN:VCALENDAR" in resp.data
    assert resp.mimetype == "text/calendar"


def test_everyday_day_toggle(tmp_path):
    from datetime import date
    today = date.today().isoformat()
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    pid = db.create_project(conn, "P", "", "text", "x", user_id=_uid(flask_app))
    eid = db.create_everyday_item(conn, pid, "Standup", position=0)
    r = client.post(f"/everyday/{eid}/day", json={"day": today, "done": True})
    assert r.status_code == 200
    assert (eid, today) in db.list_everyday_completions(conn, pid, "2000-01-01")
    client.post(f"/everyday/{eid}/day", json={"day": today, "done": False})
    assert (eid, today) not in db.list_everyday_completions(conn, pid, "2000-01-01")


def test_everyday_day_rejects_non_today(tmp_path):
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    pid = db.create_project(conn, "P", "", "text", "x", user_id=_uid(flask_app))
    eid = db.create_everyday_item(conn, pid, "Standup", position=0)
    # yesterday / any non-today date must be refused
    r = client.post(f"/everyday/{eid}/day", json={"day": "2000-01-01", "done": True})
    assert r.status_code == 403
    assert db.list_everyday_completions(conn, pid, "1999-01-01") == set()


def test_everyday_day_requires_day(tmp_path):
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    pid = db.create_project(conn, "P", "", "text", "x", user_id=_uid(flask_app))
    eid = db.create_everyday_item(conn, pid, "Standup", position=0)
    assert client.post(f"/everyday/{eid}/day", json={"done": True}).status_code == 400


def test_project_page_has_day_grid_and_gcal(tmp_path):
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    pid = db.create_project(conn, "P", "summary", "text", "x",
                            start_date="2026-06-01", user_id=_uid(flask_app))
    db.create_everyday_item(conn, pid, "Standup", position=0)
    ph = db.create_phase(conn, pid, "Phase", 0)
    db.create_item(conn, ph, "Task", "", deadline="2026-06-20", position=0)
    resp = client.get(f"/project/{pid}")
    assert resp.status_code == 200
    assert b"js-everyday-day" in resp.data           # per-day checkbox grid
    assert b"calendar.google.com" in resp.data       # per-item prefilled gcal link
    assert b"export.ics" in resp.data                # whole-project .ics export


def test_project_delete(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    assert db.get_project(conn, pid) is not None
    r = client.post(f"/project/{pid}/delete")
    assert r.status_code == 200
    assert db.get_project(conn, pid) is None
    # cascade: phases gone too
    assert db.list_phases(conn, pid) == []


def test_anonymous_redirected_to_login(tmp_path):
    db_path = str(tmp_path / "t.db")
    cfg = {"app": {"db_path": db_path}, "tracking": {"due_soon_days": 3}}
    flask_app = app_module.create_app(cfg)
    client = flask_app.test_client()  # no session
    for path in ("/projects", "/today", "/calendar", "/analytics"):
        r = client.get(path)
        assert r.status_code == 302 and "/login" in r.headers["Location"]
    assert client.get("/login").status_code == 200


def test_anonymous_index_shows_landing(tmp_path):
    db_path = str(tmp_path / "t.db")
    cfg = {"app": {"db_path": db_path}, "tracking": {"due_soon_days": 3}}
    flask_app = app_module.create_app(cfg)
    client = flask_app.test_client()  # no session
    r = client.get("/")
    assert r.status_code == 200
    assert b"BlackMoniker" in r.data and b"Paste the" in r.data


def test_all_pages_render_logged_in(tmp_path):
    flask_app, client = _client(tmp_path)
    _seed(flask_app)
    for path in ("/", "/projects", "/today", "/planner", "/calendar",
                 "/analytics", "/settings", "/upload", "/dashboard"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        assert b"BlackMoniker" in r.data  # branded chrome everywhere


def test_users_are_isolated(tmp_path):
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    mine = _seed(flask_app)  # owned by tester
    other = db.get_or_create_user(conn, "other@example.com", "Other", "")
    theirs = db.create_project(conn, "Secret", "", "text", "x",
                               user_id=other["id"])
    # dashboard / index only show my project
    body = client.get("/").data
    assert b"My Project" in body and b"Secret" not in body
    # cannot open or delete someone else's project
    assert client.get(f"/project/{theirs}").status_code == 404
    assert client.post(f"/project/{theirs}/delete").status_code == 200  # no-op
    assert db.get_project(conn, theirs) is not None  # still there
    # cannot toggle an item in someone else's project
    tph = db.create_phase(conn, theirs, "P", 0)
    tit = db.create_item(conn, tph, "x", position=0)
    assert client.post(f"/item/{tit}/status", json={"status": "done"}).status_code == 403


def test_async_upload_job_flow(tmp_path, monkeypatch):
    import time as _time
    flask_app, client = _client(tmp_path)

    class FakeBackend:
        def complete(self, prompt):
            return {"title": "Async Plan", "phases": [
                {"name": "P1", "items": [{"title": "Task A"}]}]}

    monkeypatch.setattr(app_module.llm, "get_backend",
                        lambda cfg: FakeBackend())
    r = client.post("/upload", data={"text": "do work"},
                    headers={"X-Async": "1"})
    assert r.status_code == 200
    jid = r.get_json()["job_id"]
    # wait for the background thread to finish
    conn = app_module.get_conn(flask_app)
    for _ in range(50):
        job = db.get_job(conn, jid)
        if job["status"] != "pending":
            break
        _time.sleep(0.1)
    assert job["status"] == "done", job["error"]
    assert job["project_id"] is not None
    # the poll endpoint reports it (and enforces ownership)
    s = client.get(f"/upload/job/{jid}").get_json()
    assert s["status"] == "done" and s["project_id"] == job["project_id"]
    other = db.get_or_create_user(conn, "other@example.com", "O", "")
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
    assert client.get(f"/upload/job/{jid}").status_code == 404


def test_async_upload_empty_text_is_json_error(tmp_path):
    flask_app, client = _client(tmp_path)
    r = client.post("/upload", data={"text": "  "}, headers={"X-Async": "1"})
    assert r.status_code == 400 and r.get_json()["ok"] is False


def test_ring_class_does_not_collide_with_tailwind(tmp_path):
    # Tailwind's "ring" utility paints a square box-shadow outline; our
    # progress ring must use "pring".
    flask_app, client = _client(tmp_path)
    _seed(flask_app)
    body = client.get("/").data
    assert b'class="pring"' in body
    assert b'class="ring"' not in body


def test_task_card_has_in_progress_control(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    body = client.get(f"/project/{pid}").data
    assert b"js-progress" in body


def test_basic_scopes_only():
    """Login must not request sensitive scopes (keeps Google's consent screen
    free of the 'unverified app' warning)."""
    import auth
    assert auth.SCOPES == "openid email profile"


def test_oauth_state_in_redirect(tmp_path):
    flask_app, client = _client(tmp_path)
    with client.session_transaction() as sess:
        sess.clear()  # log out
    r = client.get("/auth/google")
    assert r.status_code == 302 and "state=" in r.headers["Location"]
    # callback with a wrong/missing state is rejected before token exchange
    r = client.get("/auth/callback?code=x&state=forged")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_privacy_page_public(tmp_path):
    flask_app, client = _client(tmp_path)
    with client.session_transaction() as sess:
        sess.clear()
    r = client.get("/privacy")
    assert r.status_code == 200 and b"Privacy" in r.data


def test_contact_form_and_rate_limit(tmp_path):
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    r = client.post("/contact", data={"name": "A", "email": "a@b.c",
                                      "message": "hello"})
    assert r.status_code == 302
    msgs = db.list_contact_messages(conn)
    assert len(msgs) == 1 and msgs[0]["message"] == "hello"
    # honeypot filled -> swallowed silently, nothing stored
    client.post("/contact", data={"message": "spam", "website": "http://x"})
    assert len(db.list_contact_messages(conn)) == 1
    # empty message -> not stored
    client.post("/contact", data={"message": "   "})
    assert len(db.list_contact_messages(conn)) == 1
    # 5 messages/hour/IP cap
    for i in range(4):
        client.post("/contact", data={"message": f"m{i}"})
    r = client.post("/contact", data={"message": "one too many"})
    assert r.status_code == 429


def test_admin_dashboard_access(tmp_path):
    flask_app, client = _client(tmp_path)  # tester is user id 1 -> admin
    _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    db.create_contact_message(conn, "Visitor", "v@x.y", "love it", "1.2.3.4")
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"Instance overview" in r.data and b"love it" in r.data
    # a non-first user without ADMIN_EMAILS is not an admin -> 404
    other = db.get_or_create_user(conn, "other@example.com", "Other", "")
    with client.session_transaction() as sess:
        sess["user_id"] = other["id"]
    assert client.get("/admin").status_code == 404
    assert client.post("/admin/messages/1/read").status_code == 404


def test_admin_message_actions(tmp_path):
    flask_app, client = _client(tmp_path)
    conn = app_module.get_conn(flask_app)
    mid = db.create_contact_message(conn, "V", "v@x.y", "hi", "ip")
    assert client.post(f"/admin/messages/{mid}/read").status_code == 200
    assert db.list_contact_messages(conn)[0]["is_read"] == 1
    assert client.post(f"/admin/messages/{mid}/delete").status_code == 200
    assert db.list_contact_messages(conn) == []


def test_cross_origin_post_blocked(tmp_path):
    flask_app, client = _client(tmp_path)
    pid = _seed(flask_app)
    conn = app_module.get_conn(flask_app)
    ph = db.list_phases(conn, pid)[0]
    iid = db.list_items(conn, ph["id"])[0]["id"]
    r = client.post(f"/item/{iid}/status", json={"status": "done"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers(tmp_path):
    flask_app, client = _client(tmp_path)
    r = client.get("/login")
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Permissions-Policy" in r.headers
