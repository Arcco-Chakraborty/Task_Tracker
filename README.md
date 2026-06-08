# Task Tracker

Local web app that turns a PDF / Markdown / typed description into an
AI-generated, trackable project: phases, checklist items, deadlines,
recommended timelines, progress, a due-soon dashboard, calendar, and `.ics`
export.

The project detail page also preserves extracted context as info cards,
separates recurring/background work into an Everyday checklist, and collects
resources both on related task cards and in a Resources section.

## Setup

1. `python -m venv .venv && .venv\Scripts\activate` (Windows) or
   `source .venv/bin/activate` (Unix)
2. `pip install -r requirements.txt`
3. Put your Gemini keys in `.env` (git-ignored) as a comma-separated list:
   `GEMINI_API_KEYS=key1,key2,key3`
4. `python app.py` and open http://127.0.0.1:5000

## Configuration

Edit `config.yaml`: model, temperature, input truncation, and the
`due_soon_days` urgency window.

## Tests

`python -m pytest`

## Current Extraction Shape

Besides `title`, `summary`, `suggested_start`, `suggested_due`, and `phases`,
the normalized extraction may include:

- `info_cards`: important facts, constraints, names, decisions, or context.
- `everyday_items`: recurring/background checklist work with optional cadence.
- `resources`: project-level or task-linked links/references.
- Item-level `resources`: resources displayed directly on the task card.

## Architecture

- `extract.py`: ingest (pypdf/text) + Gemini call + normalize.
- `db.py`: SQLite persistence.
- `schedule.py`: resolved dates, progress, urgency (pure).
- `ics.py`: calendar export.
- `llm.py`: Gemini backend with `.env` (`GEMINI_API_KEYS`) round-robin rotation.
- `app.py`: Flask routes + Jinja templates (`templates/`, `static/`).
