# Task Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local Flask web app that turns an uploaded PDF/`.md`/typed task into an AI-generated, trackable project (phases → checklist items with deadlines/durations), with progress, a due-soon dashboard, a calendar, and `.ics` export.

**Architecture:** A small Flask server backed by SQLite. `extract.py` ingests a document, calls Gemini (key rotation ported from `Mailbox/llm.py`) and normalizes the result into a canonical project structure. `db.py` persists projects/phases/items. `schedule.py` computes resolved dates, progress and urgency at read time (pure functions). `app.py` wires routes to Jinja templates with light vanilla JS. No JS build step (Tailwind via CDN).

**Tech Stack:** Python 3, Flask, sqlite3 (stdlib), PyYAML, requests, pypdf, pytest.

---

## File Structure

```
app.py            # Flask routes + app factory
config.py         # load_config(path) -> dict
db.py             # sqlite schema + CRUD + create_project_from_extraction
schedule.py       # resolve_item_dates, progress, urgency (pure functions)
extract.py        # extract_text, build_prompt, normalize_extraction, extract_project
ics.py            # build_ics (pure)
llm.py            # ported from Mailbox; keys.txt loader; GeminiBackend reads cfg["ai"]
config.yaml       # app/ai/tracking config
keys.txt          # API keys, one per line (git-ignored)
requirements.txt
.gitignore
templates/        # base, index, upload, project, dashboard, calendar
static/app.js     # toggle status, inline edit via fetch
tests/            # pytest: test_llm, test_db, test_schedule, test_extract, test_ics, test_app
```

Canonical extraction dict (produced by `extract.normalize_extraction`, consumed by `db.create_project_from_extraction`):

```python
{
  "title": str,
  "summary": str,
  "suggested_start": "YYYY-MM-DD" | None,
  "suggested_due": "YYYY-MM-DD" | None,
  "phases": [
    {"name": str, "items": [
      {"title": str, "description": str,
       "deadline": "YYYY-MM-DD" | None, "duration_days": int | None}
    ]}
  ],
}
```

---

## Task 1: Project scaffolding

**Files:**
- Create: `D:\Projects\Task_Tracker\.gitignore`
- Create: `D:\Projects\Task_Tracker\requirements.txt`
- Create: `D:\Projects\Task_Tracker\config.yaml`
- Create: `D:\Projects\Task_Tracker\keys.txt`
- Create: `D:\Projects\Task_Tracker\config.py`
- Create: `D:\Projects\Task_Tracker\tests\test_config.py`

- [ ] **Step 1: Initialize git and create `.gitignore`**

```bash
cd /d/Projects/Task_Tracker
git init
```

`.gitignore`:

```
__pycache__/
*.pyc
.venv/
venv/
*.db
keys.txt
.pytest_cache/
```

- [ ] **Step 2: Create `requirements.txt`**

```
Flask>=3.0
PyYAML>=6.0
requests>=2.31
pypdf>=4.0
pytest>=8.0
```

- [ ] **Step 3: Create `keys.txt` placeholder**

```
# One Gemini API key per line. Lines starting with # are ignored.
# Paste your real keys here (this file is git-ignored).
```

- [ ] **Step 4: Create `config.yaml`**

```yaml
app:
  db_path: tasktracker.db
  host: 127.0.0.1
  port: 5000

ai:
  engine: gemini                 # gemini | local
  model: gemini-2.5-flash-lite
  endpoint: https://generativelanguage.googleapis.com/v1beta
  temperature: 0.2
  max_output_tokens: 4096
  timeout_seconds: 60
  max_input_chars: 20000         # documents longer than this are truncated
  keys_path: keys.txt

tracking:
  due_soon_days: 3
```

- [ ] **Step 5: Write the failing test for config loading**

`tests/test_config.py`:

```python
import config


def test_load_config_reads_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("app:\n  db_path: x.db\nai:\n  model: m\n", encoding="utf-8")
    cfg = config.load_config(str(p))
    assert cfg["app"]["db_path"] == "x.db"
    assert cfg["ai"]["model"] == "m"


def test_load_config_missing_returns_empty(tmp_path):
    cfg = config.load_config(str(tmp_path / "nope.yaml"))
    assert cfg == {}
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 7: Implement `config.py`**

```python
"""config.py — load config.yaml into a dict."""
from __future__ import annotations

import os

import yaml


def load_config(path: str = "config.yaml") -> dict:
    """Return the parsed YAML config, or {} if the file is absent."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 9: Commit**

```bash
git add .gitignore requirements.txt config.yaml keys.txt config.py tests/test_config.py
git commit -m "chore: scaffold task tracker project + config loader"
```

---

## Task 2: Port `llm.py` with `keys.txt` loader

**Files:**
- Create: `D:\Projects\Task_Tracker\llm.py`
- Create: `D:\Projects\Task_Tracker\tests\test_llm.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_llm.py`:

```python
import pytest
import llm


def test_parse_json_object_strips_fences():
    assert llm.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_object_rejects_non_json():
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("not json")


def test_parse_json_object_rejects_non_object():
    with pytest.raises(llm.LLMError):
        llm.parse_json_object("[1, 2, 3]")


def test_load_keys_one_per_line(tmp_path):
    p = tmp_path / "keys.txt"
    p.write_text("# comment\nkey1\n\n  key2  \n", encoding="utf-8")
    assert llm.load_keys(str(p)) == ["key1", "key2"]


def test_load_keys_comma_tolerated(tmp_path):
    p = tmp_path / "keys.txt"
    p.write_text("a, b ,c\n", encoding="utf-8")
    assert llm.load_keys(str(p)) == ["a", "b", "c"]


def test_load_keys_missing_file(tmp_path):
    assert llm.load_keys(str(tmp_path / "none.txt")) == []


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}

    def json(self):
        return self._payload


def _payload(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def _cfg(tmp_path):
    keys = tmp_path / "keys.txt"
    keys.write_text("k1\nk2\n", encoding="utf-8")
    return {"ai": {"engine": "gemini", "model": "m", "keys_path": str(keys)}}


def test_gemini_rotates_past_429(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path))
    seq = [_Resp(429), _Resp(200, _payload('{"ok": true}'))]
    used = []
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: (used.append(url), seq.pop(0))[1])
    assert backend.complete("p") == {"ok": True}
    assert len(used) == 2


def test_gemini_all_keys_exhausted_raises(monkeypatch, tmp_path):
    backend = llm.GeminiBackend(_cfg(tmp_path))
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: _Resp(429))
    with pytest.raises(llm.LLMError):
        backend.complete("p")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm'`

- [ ] **Step 3: Implement `llm.py`**

```python
"""llm.py — Gemini backend with round-robin key rotation.

Ported from Mailbox/llm.py. Differences:
  - keys are loaded from keys.txt (one per line; commas tolerated), not .env
  - config is read from cfg["ai"] instead of cfg["summarize"]
"""
from __future__ import annotations

import json
import os
import re

import requests


class LLMError(Exception):
    """Raised when a backend cannot return a parsed JSON object."""


_FENCE = re.compile(r"```(?:json)?\s*|\s*```", re.IGNORECASE)


def parse_json_object(text: str) -> dict:
    """Strip code fences and parse a JSON object. Raises LLMError on failure."""
    cleaned = _FENCE.sub("", text or "").strip()
    try:
        obj = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as e:
        raise LLMError(f"non-JSON model output: {e}") from e
    if not isinstance(obj, dict):
        raise LLMError("model output was not a JSON object")
    return obj


def load_keys(path: str = "keys.txt") -> list[str]:
    """Read API keys from keys.txt. One key per line; '#' lines and blanks
    ignored; a comma-separated line is split too."""
    if not os.path.exists(path):
        return []
    keys: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            keys.extend(k.strip() for k in line.split(",") if k.strip())
    return keys


class GeminiBackend:
    """Gemini generateContent with round-robin key rotation.

    On 429 / non-OK, advances to the next key; tries each key at most once per
    call. A JSON parse failure does NOT rotate (model-output issue, not quota)."""

    def __init__(self, cfg: dict):
        s = cfg.get("ai", {})
        self.model = s.get("model", "gemini-2.5-flash-lite")
        self.endpoint = s.get(
            "endpoint", "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        self.temperature = float(s.get("temperature", 0.2))
        self.max_output_tokens = int(s.get("max_output_tokens", 4096))
        self.timeout = int(s.get("timeout_seconds", 60))
        self.keys = load_keys(s.get("keys_path", "keys.txt"))
        self._i = 0

    def _next_key(self) -> str:
        key = self.keys[self._i % len(self.keys)]
        self._i += 1
        return key

    def complete(self, prompt: str) -> dict:
        if not self.keys:
            raise LLMError("no keys configured (keys.txt empty or missing)")
        last = "all keys exhausted"
        for _ in range(len(self.keys)):
            key = self._next_key()
            url = f"{self.endpoint}/models/{self.model}:generateContent?key={key}"
            try:
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": self.temperature,
                            "maxOutputTokens": self.max_output_tokens,
                        },
                    },
                    timeout=self.timeout,
                )
            except requests.RequestException as e:
                last = f"request failed: {e}"
                continue
            if resp.status_code == 429:
                last = "rate-limited (429)"
                continue
            if not resp.ok:
                last = f"gemini error ({resp.status_code})"
                continue
            try:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
            except (ValueError, KeyError, IndexError) as e:
                last = f"unexpected response shape: {e}"
                continue
            return parse_json_object(text)  # LLMError propagates (no rotate)
        raise LLMError(last)


def get_backend(cfg: dict):
    """Return the configured backend. Only 'gemini' is implemented here."""
    engine = cfg.get("ai", {}).get("engine", "gemini").lower()
    if engine == "gemini":
        return GeminiBackend(cfg)
    raise LLMError(f"unknown ai.engine: {engine}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_llm.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add llm.py tests/test_llm.py
git commit -m "feat: port Gemini backend with keys.txt rotation"
```

---

## Task 3: `db.py` — schema + CRUD

**Files:**
- Create: `D:\Projects\Task_Tracker\db.py`
- Create: `D:\Projects\Task_Tracker\tests\test_db.py`

- [ ] **Step 1: Write failing tests**

`tests/test_db.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Implement `db.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: sqlite schema and CRUD for projects/phases/items"
```

---

## Task 4: `schedule.py` — resolved dates, progress, urgency

**Files:**
- Create: `D:\Projects\Task_Tracker\schedule.py`
- Create: `D:\Projects\Task_Tracker\tests\test_schedule.py`

- [ ] **Step 1: Write failing tests**

`tests/test_schedule.py`:

```python
from datetime import date

import schedule


def test_resolve_explicit_deadline_wins():
    items = [{"deadline": "2026-06-20", "duration_days": None}]
    assert schedule.resolve_item_dates(date(2026, 6, 1), items) == [date(2026, 6, 20)]


def test_resolve_durations_accumulate():
    items = [
        {"deadline": None, "duration_days": 2},
        {"deadline": None, "duration_days": 3},
    ]
    out = schedule.resolve_item_dates(date(2026, 6, 1), items)
    assert out == [date(2026, 6, 3), date(2026, 6, 6)]


def test_resolve_no_anchor_returns_none():
    items = [{"deadline": None, "duration_days": 3}]
    assert schedule.resolve_item_dates(None, items) == [None]


def test_resolve_explicit_resets_cursor():
    items = [
        {"deadline": "2026-06-10", "duration_days": None},
        {"deadline": None, "duration_days": 2},
    ]
    out = schedule.resolve_item_dates(date(2026, 6, 1), items)
    assert out == [date(2026, 6, 10), date(2026, 6, 12)]


def test_progress():
    items = [{"status": "done"}, {"status": "todo"}, {"status": "done"}]
    p = schedule.progress(items)
    assert p == {"total": 3, "done": 2, "percent": 67}


def test_progress_empty():
    assert schedule.progress([]) == {"total": 0, "done": 0, "percent": 0}


def test_urgency_overdue():
    assert schedule.urgency(date(2026, 6, 1), "todo", date(2026, 6, 5), 3) == "overdue"


def test_urgency_done():
    assert schedule.urgency(date(2026, 6, 1), "done", date(2026, 6, 5), 3) == "done"


def test_urgency_due_soon():
    assert schedule.urgency(date(2026, 6, 7), "todo", date(2026, 6, 5), 3) == "due-soon"


def test_urgency_upcoming():
    assert schedule.urgency(date(2026, 6, 20), "todo", date(2026, 6, 5), 3) == "upcoming"


def test_urgency_none_when_no_date():
    assert schedule.urgency(None, "todo", date(2026, 6, 5), 3) == "none"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_schedule.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schedule'`

> Note: this module is named `schedule` and lives at the project root; it shadows nothing here because there is no PyPI `schedule` dependency in `requirements.txt`.

- [ ] **Step 3: Implement `schedule.py`**

```python
"""schedule.py — pure functions for resolved dates, progress and urgency."""
from __future__ import annotations

from datetime import date, datetime, timedelta


def parse_date(value) -> date | None:
    """Parse 'YYYY-MM-DD' to a date, or return None."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def resolve_item_dates(start_date, items) -> list:
    """Resolve a real date for each item, in order.

    Rules per item:
      1. explicit 'deadline' -> use it; cursor advances to that date
      2. else 'duration_days' + a live cursor -> cursor += duration; use cursor
      3. else -> None (cursor unchanged)
    `start_date` and item deadlines may be date or 'YYYY-MM-DD' strings.
    """
    cursor = parse_date(start_date)
    out = []
    for item in items:
        dl = parse_date(item.get("deadline"))
        if dl is not None:
            out.append(dl)
            cursor = dl
            continue
        dur = item.get("duration_days")
        if dur is not None and cursor is not None:
            cursor = cursor + timedelta(days=int(dur))
            out.append(cursor)
        else:
            out.append(None)
    return out


def progress(items) -> dict:
    """Return {total, done, percent} from a list of items with a 'status'."""
    total = len(items)
    done = sum(1 for i in items if i.get("status") == "done")
    percent = round(done / total * 100) if total else 0
    return {"total": total, "done": done, "percent": percent}


def urgency(resolved_date, status, today, due_soon_days) -> str:
    """Classify an item: done | none | overdue | due-soon | upcoming."""
    if status == "done":
        return "done"
    d = parse_date(resolved_date)
    if d is None:
        return "none"
    delta = (d - today).days
    if delta < 0:
        return "overdue"
    if delta <= due_soon_days:
        return "due-soon"
    return "upcoming"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_schedule.py -v`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add schedule.py tests/test_schedule.py
git commit -m "feat: scheduling (resolved dates, progress, urgency)"
```

---

## Task 5: `extract.py` — ingest, prompt, normalize

**Files:**
- Create: `D:\Projects\Task_Tracker\extract.py`
- Create: `D:\Projects\Task_Tracker\tests\test_extract.py`

- [ ] **Step 1: Write failing tests**

`tests/test_extract.py`:

```python
import extract


def test_normalize_drops_items_without_title():
    raw = {"title": "T", "summary": "S", "phases": [
        {"name": "P", "items": [
            {"title": "keep", "description": "d", "deadline": "2026-06-10",
             "duration_days": 2},
            {"title": "", "description": "drop me"},
        ]},
    ]}
    out = extract.normalize_extraction(raw)
    items = out["phases"][0]["items"]
    assert len(items) == 1
    assert items[0]["title"] == "keep"


def test_normalize_coerces_and_clamps():
    raw = {"phases": [{"name": "P", "items": [
        {"title": "x", "duration_days": "5"},
        {"title": "y", "duration_days": -3},
        {"title": "z", "deadline": "not-a-date"},
    ]}]}
    items = extract.normalize_extraction(raw)["phases"][0]["items"]
    assert items[0]["duration_days"] == 5
    assert items[1]["duration_days"] is None   # negative -> None
    assert items[2]["deadline"] is None        # invalid date -> None


def test_normalize_defaults_title_and_phases():
    out = extract.normalize_extraction({})
    assert out["title"] == "Untitled"
    assert out["phases"] == []
    assert out["suggested_start"] is None


def test_normalize_validates_suggested_dates():
    out = extract.normalize_extraction(
        {"suggested_start": "2026-06-09", "suggested_due": "bad"})
    assert out["suggested_start"] == "2026-06-09"
    assert out["suggested_due"] is None


def test_extract_text_reads_markdown(tmp_path):
    p = tmp_path / "spec.md"
    p.write_text("# Title\nbody", encoding="utf-8")
    kind, name, text = extract.extract_text(str(p))
    assert kind == "md"
    assert "body" in text


def test_extract_project_uses_backend():
    class StubBackend:
        def complete(self, prompt):
            return {"title": "T", "summary": "S", "phases": [
                {"name": "P", "items": [{"title": "i", "duration_days": 1}]}]}

    out = extract.extract_project("some doc text", StubBackend(),
                                  max_input_chars=1000)
    assert out["title"] == "T"
    assert out["phases"][0]["items"][0]["title"] == "i"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'extract'`

- [ ] **Step 3: Implement `extract.py`**

```python
"""extract.py — turn a document/prompt into a normalized project structure."""
from __future__ import annotations

import os
from datetime import date

from schedule import parse_date

PROMPT_TEMPLATE = """\
You are a project planner. Read the document below and break the work into a \
checklist organized as phases (milestones), each containing concrete items.

Rules:
- Use a real date for "deadline" (format YYYY-MM-DD) ONLY if the document \
states or clearly implies one.
- Otherwise estimate "duration_days" (an integer) for a recommended timeline, \
and set "deadline" to null. Do not invent calendar dates.
- If you know neither, set both to null.
- Keep titles short; put detail in "description".
{anchor}
Respond with raw JSON only (no markdown, no code fences) in EXACTLY this shape:
{{
  "title": "string",
  "summary": "string",
  "suggested_start": "YYYY-MM-DD or null",
  "suggested_due": "YYYY-MM-DD or null",
  "phases": [
    {{"name": "string", "items": [
      {{"title": "string", "description": "string",
        "deadline": "YYYY-MM-DD or null", "duration_days": integer or null}}
    ]}}
  ]
}}

DOCUMENT:
{document}
"""


def extract_text(path: str) -> tuple[str, str, str]:
    """Return (source_type, source_name, text) for a file path.
    source_type is one of: pdf, md, txt."""
    name = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return "pdf", name, text
    kind = "md" if ext == ".md" else "txt"
    with open(path, encoding="utf-8", errors="replace") as f:
        return kind, name, f.read()


def build_prompt(text, today=None, start_date=None, due_date=None) -> str:
    today = today or date.today()
    anchor_lines = [f"- Today's date is {today.isoformat()}."]
    if start_date:
        anchor_lines.append(f"- The work starts on {start_date}.")
    if due_date:
        anchor_lines.append(f"- Everything must be finished by {due_date}.")
    anchor = "\n".join(anchor_lines) + "\n"
    return PROMPT_TEMPLATE.format(anchor=anchor, document=text)


def _coerce_int(value):
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n >= 0 else None


def _norm_date(value):
    return value if parse_date(value) is not None else None


def normalize_extraction(raw: dict) -> dict:
    """Validate/coerce the model output into the canonical structure."""
    phases_out = []
    for phase in raw.get("phases") or []:
        items_out = []
        for item in phase.get("items") or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            items_out.append({
                "title": title,
                "description": (item.get("description") or "").strip(),
                "deadline": _norm_date(item.get("deadline")),
                "duration_days": _coerce_int(item.get("duration_days")),
            })
        phases_out.append({
            "name": (phase.get("name") or "Phase").strip(),
            "items": items_out,
        })
    return {
        "title": (raw.get("title") or "Untitled").strip() or "Untitled",
        "summary": (raw.get("summary") or "").strip(),
        "suggested_start": _norm_date(raw.get("suggested_start")),
        "suggested_due": _norm_date(raw.get("suggested_due")),
        "phases": phases_out,
    }


def extract_project(text, backend, today=None, start_date=None, due_date=None,
                    max_input_chars=20000) -> dict:
    """Build the prompt, call the backend, and normalize the result."""
    doc = text or ""
    if len(doc) > max_input_chars:
        doc = doc[:max_input_chars] + "\n[...document truncated...]"
    prompt = build_prompt(doc, today=today, start_date=start_date,
                          due_date=due_date)
    raw = backend.complete(prompt)   # may raise LLMError
    return normalize_extraction(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extract.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add extract.py tests/test_extract.py
git commit -m "feat: document ingest, prompt building and extraction normalize"
```

---

## Task 6: `ics.py` — calendar export

**Files:**
- Create: `D:\Projects\Task_Tracker\ics.py`
- Create: `D:\Projects\Task_Tracker\tests\test_ics.py`

- [ ] **Step 1: Write failing tests**

`tests/test_ics.py`:

```python
from datetime import date

import ics


def test_build_ics_has_envelope_and_event():
    out = ics.build_ics([
        {"uid": "item-1", "summary": "Do thing", "date": date(2026, 6, 20)},
    ])
    assert "BEGIN:VCALENDAR" in out
    assert "END:VCALENDAR" in out
    assert "BEGIN:VEVENT" in out
    assert "SUMMARY:Do thing" in out
    assert "DTSTART;VALUE=DATE:20260620" in out
    assert "UID:item-1" in out


def test_build_ics_skips_dateless_events():
    out = ics.build_ics([{"uid": "x", "summary": "no date", "date": None}])
    assert "BEGIN:VEVENT" not in out


def test_build_ics_escapes_commas():
    out = ics.build_ics([
        {"uid": "1", "summary": "a, b; c", "date": date(2026, 1, 2)},
    ])
    assert "SUMMARY:a\\, b\\; c" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ics'`

- [ ] **Step 3: Implement `ics.py`**

```python
"""ics.py — build a minimal RFC 5545 iCalendar string from dated events."""
from __future__ import annotations


def _escape(text: str) -> str:
    return (str(text).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def build_ics(events: list[dict]) -> str:
    """events: list of {uid, summary, date(date|None)}. Dateless ones skipped.
    All-day VEVENTs (VALUE=DATE)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Task Tracker//EN",
        "CALSCALE:GREGORIAN",
    ]
    for ev in events:
        d = ev.get("date")
        if d is None:
            continue
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_escape(ev.get('uid', ''))}",
            f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(ev.get('summary', ''))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ics.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ics.py tests/test_ics.py
git commit -m "feat: minimal iCalendar export"
```

---

## Task 7: `app.py` — Flask app factory + read routes

**Files:**
- Create: `D:\Projects\Task_Tracker\app.py`
- Create: `D:\Projects\Task_Tracker\templates\base.html`
- Create: `D:\Projects\Task_Tracker\templates\index.html`
- Create: `D:\Projects\Task_Tracker\templates\project.html`
- Create: `D:\Projects\Task_Tracker\tests\test_app.py`

This task builds the app factory, the projects list, and the project detail page (read-only rendering). Mutations and other pages come in Tasks 8–9.

- [ ] **Step 1: Write failing tests**

`tests/test_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Implement `app.py` (factory + read routes)**

```python
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
```

- [ ] **Step 4: Create `templates/base.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}Task Tracker{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-50 text-slate-800">
  <nav class="bg-slate-900 text-white px-6 py-3 flex gap-6 items-center">
    <a href="/" class="font-semibold">Task Tracker</a>
    <a href="/upload" class="hover:underline">New</a>
    <a href="/dashboard" class="hover:underline">Dashboard</a>
    <a href="/calendar" class="hover:underline">Calendar</a>
    <a href="/export.ics" class="hover:underline ml-auto text-sm">Export .ics</a>
  </nav>
  <main class="max-w-4xl mx-auto p-6">
    {% block body %}{% endblock %}
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 5: Create `templates/index.html`**

```html
{% extends "base.html" %}
{% block body %}
<h1 class="text-2xl font-bold mb-4">Projects</h1>
{% if not projects %}
  <p class="text-slate-500">No projects yet. <a class="text-blue-600 underline" href="/upload">Create one</a>.</p>
{% endif %}
<ul class="space-y-3">
  {% for p in projects %}
  <li class="bg-white rounded-lg shadow p-4">
    <a class="text-lg font-semibold text-blue-700 hover:underline" href="/project/{{ p.id }}">{{ p.title }}</a>
    <p class="text-sm text-slate-500">{{ p.summary }}</p>
    <div class="mt-2 h-2 bg-slate-200 rounded">
      <div class="h-2 bg-green-500 rounded" style="width: {{ p.progress.percent }}%"></div>
    </div>
    <p class="text-xs text-slate-500 mt-1">{{ p.progress.done }}/{{ p.progress.total }} done ({{ p.progress.percent }}%)</p>
  </li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 6: Create `templates/project.html`**

```html
{% extends "base.html" %}
{% block title %}{{ project.title }}{% endblock %}
{% block body %}
{% set badge = {"overdue":"bg-red-100 text-red-700","due-soon":"bg-amber-100 text-amber-700","upcoming":"bg-slate-100 text-slate-600","done":"bg-green-100 text-green-700","none":"bg-slate-100 text-slate-400"} %}
<div class="flex items-center justify-between">
  <h1 class="text-2xl font-bold">{{ project.title }}</h1>
  <a class="text-sm text-blue-600 underline" href="/project/{{ project.id }}/export.ics">Export .ics</a>
</div>
<p class="text-slate-500">{{ project.summary }}</p>

<form method="post" action="/project/{{ project.id }}/dates" class="mt-3 flex gap-3 items-end text-sm">
  <label>Start <input type="date" name="start_date" value="{{ project.start_date or '' }}" class="border rounded px-2 py-1"></label>
  <label>Due <input type="date" name="due_date" value="{{ project.due_date or '' }}" class="border rounded px-2 py-1"></label>
  <button class="bg-slate-800 text-white px-3 py-1 rounded">Save dates</button>
</form>

<div class="mt-2 h-2 bg-slate-200 rounded">
  <div class="h-2 bg-green-500 rounded" style="width: {{ progress.percent }}%"></div>
</div>
<p class="text-xs text-slate-500 mt-1">{{ progress.done }}/{{ progress.total }} done ({{ progress.percent }}%)</p>

{% for phase in phases %}
<section class="mt-6">
  <div class="flex items-center justify-between">
    <h2 class="text-lg font-semibold">{{ phase.name }}</h2>
    <span class="text-xs text-slate-500">{{ phase.progress.done }}/{{ phase.progress.total }}</span>
  </div>
  <ul class="mt-2 space-y-2">
    {% for item in phase["items"] %}
    <li class="bg-white rounded shadow p-3 flex items-start gap-3" data-item-id="{{ item.id }}">
      <input type="checkbox" class="mt-1 js-status" {% if item.status == 'done' %}checked{% endif %}>
      <div class="flex-1">
        <p class="font-medium {% if item.status == 'done' %}line-through text-slate-400{% endif %}">{{ item.title }}</p>
        {% if item.description %}<p class="text-sm text-slate-500">{{ item.description }}</p>{% endif %}
      </div>
      <span class="text-xs px-2 py-1 rounded {{ badge[item.urgency] }}">
        {% if item.resolved_date %}{{ item.resolved_date }}{% elif item.duration_days %}~{{ item.duration_days }}d{% else %}—{% endif %}
      </span>
      <button class="js-delete text-slate-400 hover:text-red-600 text-sm">✕</button>
    </li>
    {% endfor %}
  </ul>
</section>
{% endfor %}
{% endblock %}
```

- [ ] **Step 7: Create a minimal `static/app.js` (filled in Task 9)**

```javascript
// Interactions are wired in Task 9 (status toggle, delete, inline add).
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Commit**

```bash
git add app.py templates/base.html templates/index.html templates/project.html static/app.js tests/test_app.py
git commit -m "feat: flask app factory, projects list and project detail"
```

---

## Task 8: Upload + mutation + dashboard + calendar + ics routes

**Files:**
- Modify: `D:\Projects\Task_Tracker\app.py` (add routes inside `create_app`)
- Create: `D:\Projects\Task_Tracker\templates\upload.html`
- Create: `D:\Projects\Task_Tracker\templates\dashboard.html`
- Create: `D:\Projects\Task_Tracker\templates\calendar.html`
- Modify: `D:\Projects\Task_Tracker\tests\test_app.py` (append tests)

- [ ] **Step 1: Append failing tests to `tests/test_app.py`**

```python
def test_upload_text_creates_project(tmp_path, monkeypatch):
    flask_app, client = _client(tmp_path)

    def fake_extract_project(text, backend, **kw):
        return {"title": "Generated", "summary": "s",
                "suggested_start": None, "suggested_due": None,
                "phases": [{"name": "P", "items": [
                    {"title": "task a", "description": "", "deadline": None,
                     "duration_days": 1}]}]}

    monkeypatch.setattr(app_module.extract, "extract_project",
                        fake_extract_project)
    monkeypatch.setattr(app_module.llm, "get_backend", lambda cfg: object())
    resp = client.post("/upload", data={"text": "do some work"},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b"Generated" in resp.data
    assert b"task a" in resp.data


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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'extract'` and 404s for the not-yet-added routes.

- [ ] **Step 3: Add imports and a dated-items helper to `app.py`**

Add these imports near the top of `app.py` (below the existing imports):

```python
import extract
import ics
import llm
from flask import jsonify, redirect, request, url_for, Response
```

Add this helper at module level (after `_project_view`):

```python
def _all_dated_items(conn, due_soon_days, today=None):
    """Return every item across projects with resolved date + urgency,
    grouped per project so durations accumulate correctly."""
    today = today or date.today()
    out = []
    for project in db.list_projects(conn):
        for phase in db.list_phases(conn, project["id"]):
            items = db.list_items(conn, phase["id"])
            resolved = schedule.resolve_item_dates(project["start_date"], items)
            for item, rdate in zip(items, resolved):
                out.append({
                    **item,
                    "project_id": project["id"],
                    "project_title": project["title"],
                    "resolved_date": rdate,
                    "urgency": schedule.urgency(rdate, item["status"], today,
                                                due_soon_days),
                })
    return out
```

- [ ] **Step 4: Add the routes inside `create_app` (before `return flask_app`)**

```python
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
            file.save(tmp.name)
            tmp.close()
            try:
                source_type, source_name, text = extract.extract_text(tmp.name)
            finally:
                _os.unlink(tmp.name)
            source_name = file.filename
        else:
            text = request.form.get("text", "")
            source_type, source_name = "text", "typed"
        if not text.strip():
            return render_template("upload.html",
                                   error="Provide a file or some text."), 400
        backend = llm.get_backend(cfg)
        max_chars = cfg.get("ai", {}).get("max_input_chars", 20000)
        try:
            data = extract.extract_project(
                text, backend, start_date=start_date, due_date=due_date,
                max_input_chars=max_chars)
        except llm.LLMError as e:
            return render_template("upload.html",
                                   error=f"AI extraction failed: {e}"), 502
        pid = db.create_project_from_extraction(
            conn, data, source_type, source_name, start_date, due_date)
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
```

- [ ] **Step 5: Create `templates/upload.html`**

```html
{% extends "base.html" %}
{% block body %}
<h1 class="text-2xl font-bold mb-4">New project</h1>
{% if error %}<p class="bg-red-100 text-red-700 p-2 rounded mb-3">{{ error }}</p>{% endif %}
<form method="post" enctype="multipart/form-data" class="space-y-4 bg-white p-5 rounded-lg shadow">
  <div>
    <label class="block text-sm font-medium mb-1">Upload a PDF / .md / .txt</label>
    <input type="file" name="file" accept=".pdf,.md,.txt" class="block">
  </div>
  <p class="text-center text-slate-400 text-sm">— or —</p>
  <div>
    <label class="block text-sm font-medium mb-1">Describe the task</label>
    <textarea name="text" rows="6" class="w-full border rounded p-2" placeholder="Paste or write what needs to be done..."></textarea>
  </div>
  <div class="flex gap-4 text-sm">
    <label>Start date <input type="date" name="start_date" class="border rounded px-2 py-1"></label>
    <label>Target due date <input type="date" name="due_date" class="border rounded px-2 py-1"></label>
  </div>
  <button class="bg-blue-600 text-white px-4 py-2 rounded">Generate tracker</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Create `templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block body %}
{% set badge = {"overdue":"bg-red-100 text-red-700","due-soon":"bg-amber-100 text-amber-700","upcoming":"bg-slate-100 text-slate-600","done":"bg-green-100 text-green-700","none":"bg-slate-100 text-slate-400"} %}
<h1 class="text-2xl font-bold mb-4">Due soon</h1>
<ul class="space-y-2">
  {% for i in items %}
  <li class="bg-white rounded shadow p-3 flex items-center gap-3">
    <span class="text-xs px-2 py-1 rounded {{ badge[i.urgency] }}">{{ i.urgency }}</span>
    <a href="/project/{{ i.project_id }}" class="text-blue-700 hover:underline">{{ i.project_title }}</a>
    <span class="{% if i.status == 'done' %}line-through text-slate-400{% endif %}">{{ i.title }}</span>
    <span class="ml-auto text-sm text-slate-500">{{ i.resolved_date or '—' }}</span>
  </li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 7: Create `templates/calendar.html`**

```html
{% extends "base.html" %}
{% block body %}
<h1 class="text-2xl font-bold mb-4">Calendar</h1>
{% if not by_date %}<p class="text-slate-500">No dated items yet.</p>{% endif %}
<div class="space-y-4">
  {% for day, items in by_date %}
  <div class="bg-white rounded shadow p-3">
    <h2 class="font-semibold text-slate-700">{{ day }}</h2>
    <ul class="mt-1 space-y-1">
      {% for i in items %}
      <li class="text-sm"><a href="/project/{{ i.project_id }}" class="text-blue-700 hover:underline">{{ i.project_title }}</a> — {{ i.title }}</li>
      {% endfor %}
    </ul>
  </div>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS (all tests in the file pass)

- [ ] **Step 9: Commit**

```bash
git add app.py templates/upload.html templates/dashboard.html templates/calendar.html tests/test_app.py
git commit -m "feat: upload, mutations, dashboard, calendar and ics routes"
```

---

## Task 9: Frontend interactions (`static/app.js`)

**Files:**
- Modify: `D:\Projects\Task_Tracker\static\app.js`
- Modify: `D:\Projects\Task_Tracker\templates\project.html` (add-item / add-phase controls)

This is browser-only glue. Tested manually (Step 4) since the server endpoints it calls are already covered by `tests/test_app.py`.

- [ ] **Step 1: Implement `static/app.js`**

```javascript
// Wires project-page interactions to the JSON endpoints from app.py.
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

document.addEventListener("change", (e) => {
  if (e.target.classList.contains("js-status")) {
    const li = e.target.closest("[data-item-id]");
    const status = e.target.checked ? "done" : "todo";
    postJSON(`/item/${li.dataset.itemId}/status`, { status }).then(() =>
      window.location.reload()
    );
  }
});

document.addEventListener("click", (e) => {
  if (e.target.classList.contains("js-delete")) {
    const li = e.target.closest("[data-item-id]");
    if (confirm("Delete this item?")) {
      postJSON(`/item/${li.dataset.itemId}/delete`).then(() =>
        window.location.reload()
      );
    }
  }
  if (e.target.classList.contains("js-add-item")) {
    const phaseId = e.target.dataset.phaseId;
    const title = prompt("New item title?");
    if (title) {
      postJSON(`/phase/${phaseId}/item`, { title }).then(() =>
        window.location.reload()
      );
    }
  }
  if (e.target.classList.contains("js-add-phase")) {
    const projectId = e.target.dataset.projectId;
    const name = prompt("New phase name?");
    if (name) {
      postJSON(`/project/${projectId}/phase`, { name }).then(() =>
        window.location.reload()
      );
    }
  }
});
```

- [ ] **Step 2: Add "add item" / "add phase" controls to `templates/project.html`**

Inside each `<section>` for a phase, just before its closing `</section>`, add:

```html
  <button class="js-add-item text-sm text-blue-600 mt-2" data-phase-id="{{ phase.id }}">+ Add item</button>
```

After the final `{% endfor %}` of the phases loop (before `{% endblock %}`), add:

```html
<button class="js-add-phase mt-6 text-blue-600" data-project-id="{{ project.id }}">+ Add phase</button>
```

- [ ] **Step 3: Run the full test suite (no regressions)**

Run: `python -m pytest -v`
Expected: PASS (all tests across all files)

- [ ] **Step 4: Manual smoke test**

```bash
# put at least one real key in keys.txt first
python app.py
```
Then in a browser at `http://127.0.0.1:5000`:
- Go to **New**, paste a few sentences describing a project, click **Generate tracker** → a project page appears with phases/items.
- Toggle a checkbox → progress bar updates after reload.
- **+ Add item** / **+ Add phase** → new rows appear.
- Set **Start date**, **Save dates** → items with durations show resolved dates.
- Visit **Dashboard**, **Calendar**, and **Export .ics** → all load.

- [ ] **Step 5: Commit**

```bash
git add static/app.js templates/project.html
git commit -m "feat: frontend interactions (status, add/delete, add phase)"
```

---

## Task 10: README

**Files:**
- Create: `D:\Projects\Task_Tracker\README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Task Tracker

Local web app that turns a PDF / Markdown / typed description into an
AI-generated, trackable project (phases → checklist items with deadlines and
recommended timelines), with progress, a due-soon dashboard, a calendar, and
`.ics` export.

## Setup

1. `python -m venv .venv && .venv\Scripts\activate` (Windows) or
   `source .venv/bin/activate` (Unix)
2. `pip install -r requirements.txt`
3. Put one Gemini API key per line in `keys.txt` (git-ignored).
4. `python app.py` and open http://127.0.0.1:5000

## Configuration

Edit `config.yaml` — model, temperature, input truncation, and the
`due_soon_days` urgency window.

## Tests

`python -m pytest`

## Architecture

- `extract.py` — ingest (pypdf/text) + Gemini call + normalize
- `db.py` — SQLite persistence
- `schedule.py` — resolved dates, progress, urgency (pure)
- `ics.py` — calendar export
- `llm.py` — Gemini backend with `keys.txt` round-robin rotation
- `app.py` — Flask routes + Jinja templates (`templates/`, `static/`)
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** form factor (Flask local app, Task 7) · Gemini + keys.txt rotation (Task 2) · SQLite phases/items model (Task 3) · flexible timeline = explicit date / duration accumulation / relative fallback (Task 4) · extraction normalize (Task 5) · status+progress, dashboard, manual edit/add, calendar+ics (Tasks 6–9). All spec sections map to a task.
- **`schedule` module name:** root-level `schedule.py` is intentional; no PyPI `schedule` package is installed, so there is no shadow conflict. If one is ever added, rename to `scheduling.py` and update imports in `app.py`/`extract.py`/tests.
- **Single connection:** the app uses one sqlite connection (single-user, local). If you later run with threads, switch to a per-request connection or `check_same_thread=False` with a lock.
- **Type consistency:** `normalize_extraction` output keys match `create_project_from_extraction` reads; `resolve_item_dates` consumes `deadline`/`duration_days` exactly as stored; `_all_dated_items`/`_project_view` attach `resolved_date` + `urgency` consumed identically by templates.
```
