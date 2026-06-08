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
