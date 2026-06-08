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
        "info_cards": [{"title": "Constraint", "body": "Use the client portal"}],
        "everyday_items": [
            {"title": "Check inbox", "description": "Look for blockers",
             "cadence": "daily"},
        ],
        "resources": [
            {"title": "Portal", "url": "https://example.test",
             "note": "Client upload area", "related_item_title": "i1"},
        ],
        "phases": [
            {"name": "Ph1", "items": [
                {"title": "i1", "description": "d", "deadline": None,
                 "duration_days": 2,
                 "resources": [{"title": "Spec", "url": None,
                                "note": "Pinned details"}]},
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
    assert db.list_info_cards(conn, pid)[0]["title"] == "Constraint"
    assert db.list_everyday_items(conn, pid)[0]["cadence"] == "daily"
    resources = db.list_project_resources(conn, pid)
    assert [r["title"] for r in resources] == ["Spec", "Portal"]
    assert resources[1]["item_title"] == "i1"


def test_everyday_status_update():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    eid = db.create_everyday_item(conn, pid, "Review", cadence="daily")
    db.set_everyday_status(conn, eid, "done")
    assert db.list_everyday_items(conn, pid)[0]["status"] == "done"


def test_item_weight_persists():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    ph = db.create_phase(conn, pid, "P", 0)
    it = db.create_item(conn, ph, "I", "", weight=5, position=0)
    assert db.list_items(conn, ph)[0]["weight"] == 5
    db.update_item(conn, it, weight=2)
    assert db.list_items(conn, ph)[0]["weight"] == 2


def test_item_weight_defaults_to_three():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    ph = db.create_phase(conn, pid, "P", 0)
    db.create_item(conn, ph, "I", "", position=0)
    assert db.list_items(conn, ph)[0]["weight"] == 3


def test_weight_migration_adds_column(tmp_path):
    # simulate an older DB whose items table lacks the weight column
    import sqlite3
    p = str(tmp_path / "old.db")
    raw = sqlite3.connect(p)
    raw.executescript(
        "CREATE TABLE projects (id INTEGER PRIMARY KEY, title TEXT, summary TEXT,"
        " source_type TEXT, source_name TEXT, start_date TEXT, due_date TEXT,"
        " created_at TEXT, updated_at TEXT);"
        "CREATE TABLE phases (id INTEGER PRIMARY KEY, project_id INTEGER,"
        " name TEXT, position INTEGER);"
        "CREATE TABLE items (id INTEGER PRIMARY KEY, phase_id INTEGER, title TEXT,"
        " description TEXT, status TEXT, deadline TEXT, duration_days INTEGER,"
        " position INTEGER, created_at TEXT, updated_at TEXT);")
    raw.commit(); raw.close()
    conn = db.connect(p)
    db.init_db(conn)  # should add items.weight without error
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
    assert "weight" in cols


def test_everyday_per_day_completions():
    conn = _conn()
    pid = db.create_project(conn, "A", "", "text", "x")
    eid = db.create_everyday_item(conn, pid, "Water plants", position=0)
    db.set_everyday_day(conn, eid, "2026-06-07", True)
    db.set_everyday_day(conn, eid, "2026-06-08", True)
    comp = db.list_everyday_completions(conn, pid, "2026-06-06")
    assert (eid, "2026-06-07") in comp and (eid, "2026-06-08") in comp
    # clearing removes it
    db.set_everyday_day(conn, eid, "2026-06-07", False)
    comp = db.list_everyday_completions(conn, pid, "2026-06-06")
    assert (eid, "2026-06-07") not in comp
    # since_day filter excludes older days
    assert db.list_everyday_completions(conn, pid, "2026-06-08") == {(eid, "2026-06-08")}
