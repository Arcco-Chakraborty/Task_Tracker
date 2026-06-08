# Task Tracker

Local web app that turns a PDF / Markdown / typed description into an
AI-generated, trackable project (phases → checklist items with deadlines and
recommended timelines), with progress, a due-soon dashboard, a calendar, and
`.ics` export.

## Setup

1. `python -m venv .venv && .venv\Scripts\activate` (Windows) or
   `source .venv/bin/activate` (Unix)
2. `pip install -r requirements.txt`
3. Put your Gemini keys in `.env` (git-ignored) as a comma-separated list:
   `GEMINI_API_KEYS=key1,key2,key3`
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
- `llm.py` — Gemini backend with `.env` (GEMINI_API_KEYS) round-robin rotation
- `app.py` — Flask routes + Jinja templates (`templates/`, `static/`)
