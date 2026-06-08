"""db.py — SQLite persistence for projects, phases and items."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL DEFAULT '',
    picture    TEXT NOT NULL DEFAULT '',
    google_access_token  TEXT,
    google_refresh_token TEXT,
    google_token_expiry  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
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
    weight        INTEGER NOT NULL DEFAULT 3,
    time_sensitive INTEGER NOT NULL DEFAULT 0,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS info_cards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS everyday_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    cadence     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'todo',
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS resources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    item_id     INTEGER REFERENCES items(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    url         TEXT,
    note        TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS everyday_completions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    everyday_id INTEGER NOT NULL REFERENCES everyday_items(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    UNIQUE(everyday_id, day)
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Migrate older DBs created before the items.weight column existed.
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()]
    if "weight" not in cols:
        conn.execute(
            "ALTER TABLE items ADD COLUMN weight INTEGER NOT NULL DEFAULT 3")
    if "time_sensitive" not in cols:
        conn.execute(
            "ALTER TABLE items ADD COLUMN time_sensitive INTEGER NOT NULL "
            "DEFAULT 0")
    pcols = [r["name"] for r in
             conn.execute("PRAGMA table_info(projects)").fetchall()]
    if "user_id" not in pcols:
        conn.execute("ALTER TABLE projects ADD COLUMN user_id INTEGER")
    ucols = [r["name"] for r in
             conn.execute("PRAGMA table_info(users)").fetchall()]
    for col in ("google_access_token", "google_refresh_token",
                "google_token_expiry"):
        if col not in ucols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
    conn.commit()


# --- users -----------------------------------------------------------------

def get_or_create_user(conn, email, name="", picture="") -> dict:
    """Return the user row for an email, creating/refreshing it on login."""
    row = conn.execute("SELECT * FROM users WHERE email = ?",
                       (email,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO users (email, name, picture) VALUES (?, ?, ?)",
            (email, name, picture))
        conn.commit()
        return get_user(conn, cur.lastrowid)
    # keep name/picture fresh
    conn.execute("UPDATE users SET name = ?, picture = ? WHERE id = ?",
                 (name or row["name"], picture or row["picture"], row["id"]))
    conn.commit()
    return dict(conn.execute("SELECT * FROM users WHERE id = ?",
                             (row["id"],)).fetchone())


def get_user(conn, user_id) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    return dict(row) if row else None


def set_user_google_tokens(conn, user_id, access_token=None,
                           refresh_token=None, expiry=None) -> None:
    """Persist Google tokens on a user. refresh_token is only sent by Google on
    first consent, so we keep the existing one when a later login omits it."""
    sets, vals = [], []
    if access_token is not None:
        sets.append("google_access_token = ?"); vals.append(access_token)
    if refresh_token:
        sets.append("google_refresh_token = ?"); vals.append(refresh_token)
    if expiry is not None:
        sets.append("google_token_expiry = ?"); vals.append(expiry)
    if not sets:
        return
    vals.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def owns_item(conn, item_id, user_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM items i JOIN phases ph ON i.phase_id = ph.id "
        "JOIN projects p ON ph.project_id = p.id "
        "WHERE i.id = ? AND p.user_id = ?", (item_id, user_id)).fetchone()
    return row is not None


def owns_phase(conn, phase_id, user_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM phases ph JOIN projects p ON ph.project_id = p.id "
        "WHERE ph.id = ? AND p.user_id = ?", (phase_id, user_id)).fetchone()
    return row is not None


def owns_everyday(conn, everyday_id, user_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM everyday_items e JOIN projects p ON e.project_id = p.id "
        "WHERE e.id = ? AND p.user_id = ?", (everyday_id, user_id)).fetchone()
    return row is not None


# --- projects --------------------------------------------------------------

def create_project(conn, title, summary, source_type, source_name,
                   start_date=None, due_date=None, user_id=None) -> int:
    cur = conn.execute(
        "INSERT INTO projects (user_id, title, summary, source_type, "
        "source_name, start_date, due_date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, title, summary, source_type, source_name, start_date, due_date),
    )
    conn.commit()
    return cur.lastrowid


def get_project(conn, project_id, user_id=None) -> dict | None:
    """Fetch a project. When user_id is given, only return it if owned."""
    if user_id is not None:
        row = conn.execute("SELECT * FROM projects WHERE id = ? AND user_id = ?",
                           (project_id, user_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM projects WHERE id = ?",
                           (project_id,)).fetchone()
    return dict(row) if row else None


def list_projects(conn, user_id=None) -> list[dict]:
    if user_id is not None:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC", (user_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def update_project_dates(conn, project_id, start_date, due_date,
                         user_id=None) -> None:
    if user_id is not None:
        conn.execute(
            "UPDATE projects SET start_date = ?, due_date = ?, "
            "updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (start_date, due_date, project_id, user_id))
    else:
        conn.execute(
            "UPDATE projects SET start_date = ?, due_date = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (start_date, due_date, project_id))
    conn.commit()


def delete_project(conn, project_id, user_id=None) -> None:
    if user_id is not None:
        conn.execute("DELETE FROM projects WHERE id = ? AND user_id = ?",
                     (project_id, user_id))
    else:
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
                duration_days=None, position=0, status="todo", weight=3,
                time_sensitive=0) -> int:
    cur = conn.execute(
        "INSERT INTO items (phase_id, title, description, status, deadline, "
        "duration_days, weight, time_sensitive, position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (phase_id, title, description, status, deadline, duration_days,
         weight, int(bool(time_sensitive)), position),
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
                "duration_days", "weight", "time_sensitive", "position"}


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


# --- info cards ------------------------------------------------------------

def create_info_card(conn, project_id, title, body="", position=0) -> int:
    cur = conn.execute(
        "INSERT INTO info_cards (project_id, title, body, position) "
        "VALUES (?, ?, ?, ?)",
        (project_id, title, body, position),
    )
    conn.commit()
    return cur.lastrowid


def list_info_cards(conn, project_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM info_cards WHERE project_id = ? ORDER BY position, id",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- everyday checklist ----------------------------------------------------

def create_everyday_item(conn, project_id, title, description="", cadence="",
                         position=0, status="todo") -> int:
    cur = conn.execute(
        "INSERT INTO everyday_items (project_id, title, description, cadence, "
        "status, position) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, title, description, cadence, status, position),
    )
    conn.commit()
    return cur.lastrowid


def list_everyday_items(conn, project_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM everyday_items WHERE project_id = ? "
        "ORDER BY position, id",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def set_everyday_status(conn, everyday_id, status) -> None:
    conn.execute(
        "UPDATE everyday_items SET status = ?, updated_at = datetime('now') "
        "WHERE id = ?",
        (status, everyday_id),
    )
    conn.commit()


def delete_everyday_item(conn, everyday_id) -> None:
    conn.execute("DELETE FROM everyday_items WHERE id = ?", (everyday_id,))
    conn.commit()


def set_everyday_day(conn, everyday_id, day, done) -> None:
    """Record or clear a per-day completion for an everyday item."""
    if done:
        conn.execute(
            "INSERT OR IGNORE INTO everyday_completions (everyday_id, day) "
            "VALUES (?, ?)", (everyday_id, day))
    else:
        conn.execute(
            "DELETE FROM everyday_completions WHERE everyday_id = ? AND day = ?",
            (everyday_id, day))
    conn.commit()


def all_completion_days(conn, user_id=None) -> set:
    """All distinct days (YYYY-MM-DD) with any everyday completion (scoped)."""
    if user_id is not None:
        rows = conn.execute(
            "SELECT DISTINCT c.day AS day FROM everyday_completions c "
            "JOIN everyday_items e ON c.everyday_id = e.id "
            "JOIN projects p ON e.project_id = p.id WHERE p.user_id = ?",
            (user_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT day FROM everyday_completions").fetchall()
    return {r["day"] for r in rows}


def count_everyday_items(conn, user_id=None) -> int:
    if user_id is not None:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM everyday_items e "
            "JOIN projects p ON e.project_id = p.id WHERE p.user_id = ?",
            (user_id,)).fetchone()["c"]
    return conn.execute("SELECT COUNT(*) AS c FROM everyday_items").fetchone()["c"]


def count_everyday_done_on(conn, day, user_id=None) -> int:
    if user_id is not None:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM everyday_completions c "
            "JOIN everyday_items e ON c.everyday_id = e.id "
            "JOIN projects p ON e.project_id = p.id "
            "WHERE c.day = ? AND p.user_id = ?", (day, user_id)).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) AS c FROM everyday_completions WHERE day = ?",
        (day,)).fetchone()["c"]


def count_done_items_since(conn, since, user_id=None) -> int:
    """Plan items marked done with updated_at on/after `since` (a date string)."""
    if user_id is not None:
        return conn.execute(
            "SELECT COUNT(*) AS c FROM items i "
            "JOIN phases ph ON i.phase_id = ph.id "
            "JOIN projects p ON ph.project_id = p.id "
            "WHERE i.status = 'done' AND i.updated_at >= ? AND p.user_id = ?",
            (since, user_id)).fetchone()["c"]
    return conn.execute(
        "SELECT COUNT(*) AS c FROM items WHERE status = 'done' "
        "AND updated_at >= ?", (since,)).fetchone()["c"]


def list_everyday_completions(conn, project_id, since_day) -> set:
    """Return {(everyday_id, day)} completions for a project's everyday items
    on or after since_day (inclusive)."""
    rows = conn.execute(
        "SELECT c.everyday_id AS eid, c.day AS day FROM everyday_completions c "
        "JOIN everyday_items e ON c.everyday_id = e.id "
        "WHERE e.project_id = ? AND c.day >= ?",
        (project_id, since_day)).fetchall()
    return {(r["eid"], r["day"]) for r in rows}


# --- resources -------------------------------------------------------------

def create_resource(conn, project_id, title, url=None, note="", item_id=None,
                    position=0) -> int:
    cur = conn.execute(
        "INSERT INTO resources (project_id, item_id, title, url, note, "
        "position) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, item_id, title, url, note, position),
    )
    conn.commit()
    return cur.lastrowid


def list_project_resources(conn, project_id) -> list[dict]:
    rows = conn.execute(
        "SELECT resources.*, items.title AS item_title "
        "FROM resources "
        "LEFT JOIN items ON resources.item_id = items.id "
        "WHERE resources.project_id = ? "
        "ORDER BY resources.position, resources.id",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_item_resources(conn, item_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM resources WHERE item_id = ? ORDER BY position, id",
        (item_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# --- composite -------------------------------------------------------------

def create_project_from_extraction(conn, extraction, source_type, source_name,
                                   start_date=None, due_date=None,
                                   user_id=None) -> int:
    """Insert a project + its phases + items from a normalized extraction dict.
    start_date/due_date override the model's suggested_* when provided."""
    pid = create_project(
        conn,
        extraction.get("title") or "Untitled",
        extraction.get("summary") or "",
        source_type, source_name,
        start_date or extraction.get("suggested_start"),
        due_date or extraction.get("suggested_due"),
        user_id=user_id,
    )
    for c_pos, card in enumerate(extraction.get("info_cards", [])):
        create_info_card(
            conn, pid, card.get("title") or "Important info",
            card.get("body") or "", c_pos)

    item_ids_by_title = {}
    resource_pos = 0
    for p_pos, phase in enumerate(extraction.get("phases", [])):
        ph = create_phase(conn, pid, phase.get("name") or "Phase", p_pos)
        for i_pos, item in enumerate(phase.get("items", [])):
            item_id = create_item(
                conn, ph,
                item.get("title") or "Item",
                item.get("description") or "",
                deadline=item.get("deadline"),
                duration_days=item.get("duration_days"),
                weight=item.get("weight", 3),
                time_sensitive=item.get("time_sensitive", False),
                position=i_pos,
            )
            key = (item.get("title") or "").strip().lower()
            if key:
                item_ids_by_title.setdefault(key, item_id)
            for res in item.get("resources", []):
                create_resource(
                    conn, pid, res.get("title") or "Resource",
                    url=res.get("url"), note=res.get("note") or "",
                    item_id=item_id, position=resource_pos)
                resource_pos += 1

    for e_pos, item in enumerate(extraction.get("everyday_items", [])):
        create_everyday_item(
            conn, pid, item.get("title") or "Everyday item",
            item.get("description") or "", item.get("cadence") or "", e_pos)

    for res in extraction.get("resources", []):
        related = (res.get("related_item_title") or "").strip().lower()
        create_resource(
            conn, pid, res.get("title") or "Resource",
            url=res.get("url"), note=res.get("note") or "",
            item_id=item_ids_by_title.get(related), position=resource_pos)
        resource_pos += 1
    return pid
