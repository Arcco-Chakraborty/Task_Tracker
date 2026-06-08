import db


def _conn():
    conn = db.connect(":memory:")
    db.init_db(conn)
    return conn


def test_create_and_get_project():
    conn = _conn()
    pid = db.create_project(conn, "Title", "Summary", "text", "typed")
    p = db.get_project(conn, pid)
    assert p["title"] == "Title"
    assert p["source_type"] == "text"
    assert p["start_date"] is None


def test_list_projects():
    conn = _conn()
    db.create_project(conn, "A", "", "text", "x")
    db.create_project(conn, "B", "", "text", "x")
    assert len(db.list_projects(conn)) == 2


def test_update_project_dates():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    db.update_project_dates(conn, pid, "2026-06-10", "2026-07-01")
    p = db.get_project(conn, pid)
    assert p["start_date"] == "2026-06-10"
    assert p["due_date"] == "2026-07-01"


def test_phases_and_items_crud():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    ph = db.create_phase(conn, pid, "Phase 1", 0)
    it = db.create_item(conn, ph, "Item", "desc", deadline="2026-06-20",
                        duration_days=None, position=0)
    items = db.list_items(conn, ph)
    assert items[0]["title"] == "Item"
    assert items[0]["status"] == "todo"
    db.set_item_status(conn, it, "done")
    assert db.list_items(conn, ph)[0]["status"] == "done"
    db.update_item(conn, it, title="New", duration_days=5)
    row = db.list_items(conn, ph)[0]
    assert row["title"] == "New" and row["duration_days"] == 5


def test_delete_project_cascades():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    ph = db.create_phase(conn, pid, "P", 0)
    db.create_item(conn, ph, "I", "", position=0)
    db.delete_project(conn, pid)
    assert db.get_project(conn, pid) is None
    assert db.list_phases(conn, pid) == []
    assert db.list_items(conn, ph) == []


def test_list_all_items_includes_project():
    conn = _conn()
    pid = db.create_project(conn, "Proj", "", "text", "x")
    ph = db.create_phase(conn, pid, "P", 0)
    db.create_item(conn, ph, "I", "", position=0)
    rows = db.list_all_items(conn)
    assert rows[0]["project_id"] == pid
    assert rows[0]["project_title"] == "Proj"


def test_create_project_from_extraction():
    conn = _conn()
    extraction = {
        "title": "T", "summary": "S",
        "suggested_start": "2026-06-09", "suggested_due": "2026-06-30",
        "phases": [
            {"name": "Ph1", "items": [
                {"title": "i1", "description": "d", "deadline": None, "duration_days": 2},
            ]},
        ],
    }
    pid = db.create_project_from_extraction(conn, extraction, "pdf", "spec.pdf",
                                            None, None)
    p = db.get_project(conn, pid)
    assert p["title"] == "T"
    assert p["start_date"] == "2026-06-09"   # seeded from suggested_start
    phases = db.list_phases(conn, pid)
    assert phases[0]["name"] == "Ph1"
    items = db.list_items(conn, phases[0]["id"])
    assert items[0]["duration_days"] == 2
