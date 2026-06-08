"""db.py — SQLite persistence for projects, phases and items."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    start_date  TEXT,
    due_date    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS phases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phase_id      INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'todo',
    deadline      TEXT,
    duration_days INTEGER,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --- projects --------------------------------------------------------------

def create_project(conn, title, summary, source_type, source_name,
                   start_date=None, due_date=None) -> int:
    cur = conn.execute(
        "INSERT INTO projects (title, summary, source_type, source_name, "
        "start_date, due_date) VALUES (?, ?, ?, ?, ?, ?)",
        (title, summary, source_type, source_name, start_date, due_date),
    )
    conn.commit()
    return cur.lastrowid


def get_project(conn, project_id) -> dict | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?",
                       (project_id,)).fetchone()
    return dict(row) if row else None


def list_projects(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM projects ORDER BY created_at DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def update_project_dates(conn, project_id, start_date, due_date) -> None:
    conn.execute(
        "UPDATE projects SET start_date = ?, due_date = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (start_date, due_date, project_id),
    )
    conn.commit()


def delete_project(conn, project_id) -> None:
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


# --- phases ----------------------------------------------------------------

def create_phase(conn, project_id, name, position) -> int:
    cur = conn.execute(
        "INSERT INTO phases (project_id, name, position) VALUES (?, ?, ?)",
        (project_id, name, position),
    )
    conn.commit()
    return cur.lastrowid


def list_phases(conn, project_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM phases WHERE project_id = ? ORDER BY position, id",
        (project_id,)).fetchall()
    return [dict(r) for r in rows]


def delete_phase(conn, phase_id) -> None:
    conn.execute("DELETE FROM phases WHERE id = ?", (phase_id,))
    conn.commit()


# --- items -----------------------------------------------------------------

def create_item(conn, phase_id, title, description="", deadline=None,
                duration_days=None, position=0, status="todo") -> int:
    cur = conn.execute(
        "INSERT INTO items (phase_id, title, description, status, deadline, "
        "duration_days, position) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (phase_id, title, description, status, deadline, duration_days, position),
    )
    conn.commit()
    return cur.lastrowid


def list_items(conn, phase_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM items WHERE phase_id = ? ORDER BY position, id",
        (phase_id,)).fetchall()
    return [dict(r) for r in rows]


def list_all_items(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT items.*, projects.id AS project_id, projects.title AS "
        "project_title, projects.start_date AS project_start_date "
        "FROM items "
        "JOIN phases ON items.phase_id = phases.id "
        "JOIN projects ON phases.project_id = projects.id "
        "ORDER BY items.deadline IS NULL, items.deadline").fetchall()
    return [dict(r) for r in rows]


_ITEM_FIELDS = {"title", "description", "status", "deadline",
                "duration_days", "position"}


def update_item(conn, item_id, **fields) -> None:
    cols = {k: v for k, v in fields.items() if k in _ITEM_FIELDS}
    if not cols:
        return
    assignments = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(
        f"UPDATE items SET {assignments}, updated_at = datetime('now') "
        "WHERE id = ?",
        (*cols.values(), item_id),
    )
    conn.commit()


def set_item_status(conn, item_id, status) -> None:
    update_item(conn, item_id, status=status)


def delete_item(conn, item_id) -> None:
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()


# --- composite -------------------------------------------------------------

def create_project_from_extraction(conn, extraction, source_type, source_name,
                                   start_date=None, due_date=None) -> int:
    """Insert a project + its phases + items from a normalized extraction dict.
    start_date/due_date override the model's suggested_* when provided."""
    pid = create_project(
        conn,
        extraction.get("title") or "Untitled",
        extraction.get("summary") or "",
        source_type, source_name,
        start_date or extraction.get("suggested_start"),
        due_date or extraction.get("suggested_due"),
    )
    for p_pos, phase in enumerate(extraction.get("phases", [])):
        ph = create_phase(conn, pid, phase.get("name") or "Phase", p_pos)
        for i_pos, item in enumerate(phase.get("items", [])):
            create_item(
                conn, ph,
                item.get("title") or "Item",
                item.get("description") or "",
                deadline=item.get("deadline"),
                duration_days=item.get("duration_days"),
                position=i_pos,
            )
    return pid
