# Task Tracker — Design Spec

**Date:** 2026-06-08
**Status:** Approved design, pre-implementation

## Summary

A local single-user Flask web app. The user provides a PDF, `.md`, `.txt`, or
typed text describing work to be done. Gemini extracts a structured project —
phases (milestones) each containing checklist items with deadlines and/or
recommended durations. The user then tracks progress, sees what is due soon,
edits everything freely, and exports deadlines to a calendar.

## Goals

- Turn an unstructured document/prompt into a structured, trackable project.
- Extract explicit deadlines when present; otherwise produce a recommended
  timeline (durations) that resolves to real dates once anchored.
- Provide day-to-day tracking: status, progress, due-soon/overdue view, manual
  editing, calendar view and export.

## Non-Goals (YAGNI)

- Push / email reminders (calendar export covers external reminders).
- Multi-user accounts or authentication.
- Cloud hosting (designed local; not precluded later).

## Stack & Reuse

- **Backend:** Python + Flask. Jinja2 templates. Light vanilla JS for in-page
  actions (toggle status, inline edit, add/delete). No React/Vite/Node build.
- **Styling:** Tailwind via CDN — no build step, keeps the project Python-only.
- **AI:** Port `Mailbox/llm.py` almost verbatim: `GeminiBackend` with
  round-robin key rotation and 429 retry, `parse_json_object`, `get_backend()`
  factory. The only change is key loading (see below).
- **Config:** `config.yaml` (mirrors Mailbox) — model, temperature, endpoint,
  max output tokens, timeout, and urgency thresholds. Default model
  `gemini-2.5-flash-lite`; swappable.

### Key loading (changed from Mailbox)

Keys are read from **`keys.txt` in the project root**, not `.env`.

- Format: one API key per line. Blank lines and lines starting with `#` are
  ignored. A comma-separated list on a single line is also tolerated (split on
  both newlines and commas).
- `keys.txt` is git-ignored.
- Replaces Mailbox's `load_env_keys`; `GeminiBackend` consumes the resulting
  list unchanged.

## Data Model (SQLite, single local `.db` file)

**projects**
- `id` (PK), `title`, `summary`, `source_type` (`pdf`|`md`|`txt`|`text`),
  `source_name`, `start_date` (DATE, nullable), `due_date` (DATE, nullable),
  `created_at`, `updated_at`

**phases**
- `id` (PK), `project_id` (FK), `name`, `position` (INT, ordering)

**items**
- `id` (PK), `phase_id` (FK), `title`, `description`,
  `status` (`todo`|`in_progress`|`done`), `deadline` (DATE, nullable),
  `duration_days` (INT, nullable), `position` (INT, ordering),
  `created_at`, `updated_at`

Cascading deletes: deleting a project deletes its phases and items; deleting a
phase deletes its items.

## AI Extraction (`extract.py`)

1. **Ingest → text.** PDF via `pypdf`; `.md`/`.txt`/typed text read directly.
   Text over a configured token/char budget is truncated (with a note appended
   so the model knows it was cut).
2. **Prompt.** Instruct Gemini to return strict JSON only:

   ```json
   {
     "title": "string",
     "summary": "string",
     "suggested_start": "YYYY-MM-DD | null",
     "suggested_due": "YYYY-MM-DD | null",
     "phases": [
       {
         "name": "string",
         "items": [
           {
             "title": "string",
             "description": "string",
             "deadline": "YYYY-MM-DD | null",
             "duration_days": "integer | null"
           }
         ]
       }
     ]
   }
   ```

   The prompt tells the model: use explicit dates found in the document for
   `deadline`; otherwise estimate `duration_days` for a recommended timeline;
   set fields to `null` when unknown rather than inventing dates.
3. **Validate & normalize.** Reuse `parse_json_object`. Coerce/validate types,
   drop malformed items, ensure positions, clamp negative/absurd durations.
   `suggested_start`/`suggested_due` seed the project's `start_date`/`due_date`
   if the user did not supply them at upload.

## Scheduling (`schedule.py`) — flexible timeline

A **resolved date** for each item is computed at read time (never stored), so
changing the project anchor re-flows the whole schedule:

1. If the item has an explicit `deadline` → use it.
2. Else if it has `duration_days` and the project has a `start_date` →
   accumulate durations sequentially in `position` order across phases/items to
   assign each a real date.
3. Else → no calendar date; shown as relative (e.g. "~3 days") until anchored.

If `due_date` is set and resolved dates overrun it, the view flags the overrun
(no silent compression in v1).

Also provides:
- **Progress:** % of items `done` per phase and per project.
- **Urgency badges** from `config.yaml` thresholds: `overdue` (resolved date
  < today and not done), `due-soon`, `upcoming`.

## Pages & Routes (`app.py`)

- `GET /` — projects list with progress bars.
- `GET /upload`, `POST /upload` — file upload or pasted text + optional
  start/due dates → `extract.py` → create project → redirect to detail.
- `GET /project/<id>` — phases & items; check off, inline edit, add/delete
  items & phases, set/override dates.
- `GET /dashboard` — all items across all projects sorted by resolved deadline,
  with urgency badges.
- `GET /calendar` — month view of resolved deadlines.
- `GET /export.ics`, `GET /project/<id>/export.ics` — iCalendar export.
- Small POST/JSON endpoints: item status toggle, item edit, add item, add
  phase, delete item/phase, set project dates.

## Module Layout

```
app.py          # Flask routes
db.py           # SQLite schema + CRUD
extract.py      # ingest (pypdf/text) + prompt + AI call + normalize
schedule.py     # resolved dates, progress, urgency
llm.py          # ported from Mailbox (keys.txt loader)
config.yaml     # model/engine/endpoint/temperature/thresholds
keys.txt        # API keys (git-ignored)
templates/      # Jinja2
static/         # vanilla JS, any local assets
tests/          # pytest
requirements.txt
.gitignore
```

## Testing (pytest, mirrors Mailbox)

- `schedule.py` — date resolution across the three branches, sequential
  accumulation, urgency edge cases (overdue/due-soon boundaries), progress math.
- `db.py` — CRUD and cascade deletes.
- `extract.py` — JSON normalization with a **stubbed** LLM backend (no network):
  malformed items dropped, durations clamped, dates seeded.
- key loader — parses `keys.txt` (per-line, comments, comma-separated tolerance).
- Reused `parse_json_object` behavior (fence stripping, non-JSON → error).

## Open Questions

None at design time.
