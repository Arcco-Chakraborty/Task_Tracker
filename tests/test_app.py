import app as app_module
import db


def _client(tmp_path):
    db_path = str(tmp_path / "t.db")
    cfg = {"app": {"db_path": db_path}, "tracking": {"due_soon_days": 3}}
    flask_app = app_module.create_app(cfg)
    flask_app.config.update(TESTING=True)
    return flask_app, flask_app.test_client()


def _seed(flask_app):
    conn = app_module.get_conn(flask_app)
    pid = db.create_project(conn, "My Project", "summary", "text", "typed",
                            start_date="2026-06-01")
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
