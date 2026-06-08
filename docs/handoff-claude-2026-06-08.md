# Claude Handoff - 2026-06-08

## User Request

The user reported that uploads/Gemini loading were causing website errors, and
asked for:

- Better handling while the backend is working.
- A separate checklist for background/everyday activities.
- Better preservation of specific document information via info cards.
- Resources shown with their related task card and also in a separate resources
  area/tab.
- Clear documentation of the work for handoff.

## What Changed

### Upload and Gemini UX

- `templates/upload.html`
  - Added a loading overlay that appears on submit.
  - The submit button disables and changes text while the backend works.
  - Error messages still render on the upload page.

- `static/app.js`
  - Added upload submit handling for the loading overlay.

- `app.py`
  - Wrapped file extraction errors and Gemini/LLM errors so they render the
    upload page instead of a raw Flask error page.
  - Added an extra guard around project persistence after extraction.
  - Temp uploaded files are now closed before saving, which is safer on
    Windows, and are removed after extraction.

### New Extraction Buckets

- `extract.py`
  - Prompt now asks Gemini to preserve:
    - `info_cards`
    - `everyday_items`
    - top-level `resources`
    - item-level `resources`
  - Normalization now accepts and cleans those fields.
  - Normalization skips malformed cards/resources/items instead of crashing.
  - Backward-compatible defaults are still returned when older/simple model
    output is provided.

Current normalized shape additions:

```python
{
    "info_cards": [{"title": str, "body": str}],
    "everyday_items": [
        {"title": str, "description": str, "cadence": str}
    ],
    "resources": [
        {
            "title": str,
            "url": str | None,
            "note": str,
            "related_item_title": str | None,
        }
    ],
    "phases": [
        {"items": [
            {"resources": [
                {"title": str, "url": str | None, "note": str}
            ]}
        ]}
    ],
}
```

### SQLite Persistence

- `db.py`
  - Added new tables:
    - `info_cards`
    - `everyday_items`
    - `resources`
  - Added CRUD/list helpers for those tables.
  - `create_project_from_extraction()` now persists info cards, everyday
    checklist items, top-level resources, and item-level resources.
  - Project-level resources can be linked to an item by matching
    `related_item_title` to the extracted item title.

Migration note: this uses `CREATE TABLE IF NOT EXISTS`, so existing local DBs
will get the new tables when the app starts. Existing rows are not modified.

### Project Detail UI

- `templates/project.html`
  - Reworked the project detail page into sections:
    - Plan
    - Everyday
    - Resources
  - Added top info cards.
  - Added separate everyday checklist with its own progress bar.
  - Added item-attached resource chips on task cards.
  - Added a separate Resources section that lists all project resources and
    shows the related task title when linked.

- `static/app.js`
  - Added everyday checklist status toggle.
  - Added add/delete everyday item controls.

- `app.py`
  - Added endpoints:
    - `POST /everyday/<id>/status`
    - `POST /everyday/<id>/delete`
    - `POST /project/<id>/everyday`

### Scheduling Fix

- `app.py`
  - `_project_view()` and `_all_dated_items()` now resolve duration-based dates
    across all phases/items in project order.
  - Before this change, duration resolution restarted inside each phase.

### Docs Cleanup

- `README.md`
  - Rewritten in ASCII to avoid mojibake.
  - Documents the current `.env`/`GEMINI_API_KEYS` setup.
  - Documents the new extraction buckets.

- `llm.py`
  - Corrected stale docstring that still said keys were loaded from `keys.txt`.

## Tests

Ran:

```powershell
python -m pytest -q
```

Result:

```text
51 passed in 1.28s
```

New/updated coverage:

- `tests/test_extract.py`
  - Verifies info cards, everyday items, project resources, and item resources
    are normalized.

- `tests/test_db.py`
  - Verifies `create_project_from_extraction()` persists the new tables.
  - Verifies everyday item status updates.

- `tests/test_app.py`
  - Verifies upload renders extracted cards/everyday/resources.
  - Verifies LLM errors stay on the upload page.
  - Verifies everyday add/status endpoints.

## Known Notes For Claude

- The older `docs/superpowers/specs` and `docs/superpowers/plans` still discuss
  `keys.txt`; the actual current code/config/README use `.env` with
  `GEMINI_API_KEYS`.
- `git` was not available in the PowerShell environment, so no git status or
  commit was created.
- The UI now has tab-like section links, not a separate full route for
  resources.
- Inline editing exists as a JSON endpoint for items, but the browser UI still
  mainly supports status, add, and delete actions.
