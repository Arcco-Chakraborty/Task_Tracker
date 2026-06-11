"""extract.py — turn a document/prompt into a normalized project structure."""
from __future__ import annotations

import os
from datetime import date, timedelta

from schedule import parse_date

PROMPT_TEMPLATE = """\
You are an expert project planner. Turn the document into a precise, trackable \
plan. Getting the SEQUENCE and TIMING right matters most.

SEQUENCE & TIMING (most important):
- Order phases, and items within them, by WHEN they should be done \
(chronologically / by dependency) - NOT by where they appear in the document. \
A section that appears at the END of the document but says to do something \
"in week 1", "first", "to begin", or "immediately" MUST be placed at the \
START of the plan.
- "Week N", "Day N", "by <date>", "before X", "after X", "kickoff", "ASAP", \
"immediately", "first" describe WHEN a task happens, NOT how long it takes. \
Never turn "do this in week 1" into a task that lasts one week. Set \
"duration_days" from the ACTUAL effort and use ordering/deadline for timing.
- DATE ARITHMETIC: when the start date is known, "week N" spans days \
7*(N-1) to 7*N-1 after the start (start 2026-06-15 -> week 1 = 2026-06-15 to \
2026-06-21, week 2 = 2026-06-22 to 2026-06-28). Set "deadline" to a concrete \
date inside that window. If the start date is unknown, place the task in an \
early phase with a small "duration_days" instead — never guess a date.
- WEEKDAYS: when the document names a weekday ("friday", "by sunday"), you \
MUST look that weekday up in the Calendar line below and copy its exact date \
(the next occurrence). Never compute weekday dates yourself.
- Dependencies go EARLY even if listed late or never called urgent: \
prerequisites, environment/setup, installs, accounts, registrations, \
approvals, ordering/buying materials - anything that BLOCKS later work.

EXPAND LISTS:
- Every distinct action becomes its OWN checklist item. NEVER merge a list, \
multiple bullets, or several sentences into one item. A "list of time-sensitive \
actions" must become one item per action.

TIME-SENSITIVE (set "time_sensitive": true or false on every item):
- true when an item has a hard/near deadline or is inherently urgent: \
registrations, submissions, applications, bookings, payments, RSVPs, \
approvals, anything marked urgent/ASAP/"first"/"week 1", AND any prerequisite \
that blocks other work - even if the document does not literally say "urgent".
- Also infer it: a step others depend on, or something with an external \
deadline, is time-sensitive. Otherwise false.
- Place every time-sensitive item as early as its timing requires.

OTHER FIELDS:
- "weight" 1-5 = EFFORT/TIME: 1 = minutes/trivial (e.g. "create a repo"), \
2 = under an hour, 3 = a few hours, 4 = ~a full day, 5 = multiple days / major \
(e.g. "study a 4-hour lecture"). Use the FULL range; differentiate.
- "duration_days" = calendar days to allot to the task before the next one \
starts (1 for anything doable in a day). It paces the schedule when there is \
no explicit deadline.
- Group items into 2-6 phases named for stages of the work (e.g. "Setup", \
"Build", "Polish & submit") — not document section headings.
- "summary": 1-2 concrete sentences — what is being built/done and the end \
goal or final deadline.
- Put recurring/background/ongoing work in "everyday_items" with a "cadence" \
(e.g. "daily", "weekly"), NOT in phases. Never list the same work in both.
- Preserve specifics (names, numbers, constraints, decisions, deliverables, \
tools, files, contacts, references) in "info_cards" and "resources". Attach a \
resource to its closest item when possible, else the top-level "resources" — \
never both.
- URLs: only ones that appear VERBATIM in the document. Never invent, guess \
or "fix" a link.
- "deadline" is a real date (YYYY-MM-DD) only when stated or clearly implied \
(directly, or via "week N"/"by <date>" relative to the start). Never invent \
dates; use "duration_days" otherwise. Keep titles short; detail in \
"description".
{anchor}
Respond with raw JSON only (no markdown, no code fences) in EXACTLY this shape:
{{
  "title": "string",
  "summary": "string",
  "suggested_start": "YYYY-MM-DD or null",
  "suggested_due": "YYYY-MM-DD or null",
  "info_cards": [
    {{"title": "string", "body": "string"}}
  ],
  "phases": [
    {{"name": "string", "items": [
      {{"title": "string", "description": "string",
        "deadline": "YYYY-MM-DD or null", "duration_days": integer or null,
        "weight": integer 1-5, "time_sensitive": true or false,
        "resources": [
          {{"title": "string", "url": "string or null", "note": "string"}}
        ]}}
    ]}}
  ],
  "everyday_items": [
    {{"title": "string", "description": "string", "cadence": "string"}}
  ],
  "resources": [
    {{"title": "string", "url": "string or null", "note": "string",
      "related_item_title": "string or null"}}
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
    # Models are unreliable at weekday->date arithmetic; hand them a calendar
    # so "friday"/"next sunday" resolve to the right date.
    cal = ", ".join((today + timedelta(days=n)).strftime("%a=%Y-%m-%d")
                    for n in range(14))
    anchor_lines.append(f"- Calendar (next 14 days): {cal}.")
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
    if parse_date(value) is not None:
        return value
    # tolerate ISO datetime strings like "2026-06-19T00:00:00"
    if isinstance(value, str) and parse_date(value[:10]) is not None:
        return value[:10]
    return None


def _coerce_weight(value, default=3):
    """Clamp the model's seriousness weight into 1..5 (default 3)."""
    try:
        w = int(value)
    except (ValueError, TypeError):
        return default
    return min(5, max(1, w))


def _clean_text(value, fallback=""):
    text = str(value or "").strip()
    return text or fallback


def _normalize_resource(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = _clean_text(raw.get("title"))
    url = _clean_text(raw.get("url")) or None
    note = _clean_text(raw.get("note"))
    if not title and url:
        title = url
    if not title and note:
        title = "Resource"
    if not title:
        return None
    related = _clean_text(raw.get("related_item_title")) or None
    return {
        "title": title,
        "url": url,
        "note": note,
        "related_item_title": related,
    }


def normalize_extraction(raw: dict) -> dict:
    """Validate/coerce the model output into the canonical structure."""
    info_cards_out = []
    for card in raw.get("info_cards") or []:
        if not isinstance(card, dict):
            continue
        title = _clean_text(card.get("title"), "Important info")
        body = _clean_text(card.get("body"))
        if title or body:
            info_cards_out.append({"title": title, "body": body})

    phases_out = []
    for phase in raw.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        items_out = []
        for item in phase.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue
            resources = []
            for res in item.get("resources") or []:
                normalized = _normalize_resource(res)
                if normalized:
                    normalized.pop("related_item_title", None)
                    resources.append(normalized)
            duration = _coerce_int(item.get("duration_days"))
            if duration is not None:
                duration = min(duration, 90)  # cap runaway durations
            items_out.append({
                "title": title,
                "description": (item.get("description") or "").strip(),
                "deadline": _norm_date(item.get("deadline")),
                "duration_days": duration,
                "weight": _coerce_weight(item.get("weight")),
                "time_sensitive": bool(item.get("time_sensitive")),
                "resources": resources,
            })
        if not items_out:
            continue  # an empty phase is just clutter
        # Safeguard: keep time-sensitive actions at the front of their phase
        # (stable, so the model's order is otherwise preserved).
        items_out.sort(key=lambda i: 0 if i["time_sensitive"] else 1)
        phases_out.append({
            "name": (phase.get("name") or "Phase").strip(),
            "items": items_out,
        })

    everyday_out = []
    seen_everyday = set()
    everyday_raw = (raw.get("everyday_items") or raw.get("everyday") or
                    raw.get("background_items") or [])
    for item in everyday_raw:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        if not title or title.lower() in seen_everyday:
            continue
        seen_everyday.add(title.lower())
        everyday_out.append({
            "title": title,
            "description": _clean_text(item.get("description")),
            "cadence": _clean_text(item.get("cadence")),
        })

    # Resources already attached to an item shouldn't repeat at the top level.
    attached = set()
    for phase in phases_out:
        for item in phase["items"]:
            for res in item["resources"]:
                attached.add((res["url"] or "").lower() or res["title"].lower())
    resources_out = []
    seen_res = set()
    for res in raw.get("resources") or []:
        normalized = _normalize_resource(res)
        if not normalized:
            continue
        key = (normalized["url"] or "").lower() or normalized["title"].lower()
        if key in attached or key in seen_res:
            continue
        seen_res.add(key)
        resources_out.append(normalized)

    return {
        "title": (raw.get("title") or "Untitled").strip() or "Untitled",
        "summary": (raw.get("summary") or "").strip(),
        "suggested_start": _norm_date(raw.get("suggested_start")),
        "suggested_due": _norm_date(raw.get("suggested_due")),
        "info_cards": info_cards_out,
        "phases": phases_out,
        "everyday_items": everyday_out,
        "resources": resources_out,
    }


def clip_document(doc: str, max_chars: int) -> str:
    """Clip an over-long document keeping the head AND the tail.

    Important instructions (deadlines, "do this first" lists) often live at
    the END of a document, so plain tail-chopping loses exactly the content
    that matters most. 70% head + 30% tail preserves both framing and
    late-breaking instructions."""
    if len(doc) <= max_chars:
        return doc
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return (doc[:head]
            + "\n[... middle of document omitted for length ...]\n"
            + doc[-tail:])


def extract_project(text, backend, today=None, start_date=None, due_date=None,
                    max_input_chars=20000) -> dict:
    """Build the prompt, call the backend, and normalize the result."""
    doc = clip_document(text or "", max_input_chars)
    prompt = build_prompt(doc, today=today, start_date=start_date,
                          due_date=due_date)
    raw = backend.complete(prompt)   # may raise LLMError
    return normalize_extraction(raw)
