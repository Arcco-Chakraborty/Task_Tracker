"""extract.py — turn a document/prompt into a normalized project structure."""
from __future__ import annotations

import os
from datetime import date

from schedule import parse_date

PROMPT_TEMPLATE = """\
You are a project planner. Read the document below and preserve all specific \
project details while turning the work into a tracker.

Rules:
- Use a real date for "deadline" (format YYYY-MM-DD) ONLY if the document \
states or clearly implies one.
- Otherwise estimate "duration_days" (an integer) for a recommended timeline, \
and set "deadline" to null. Do not invent calendar dates.
- If you know neither, set both to null.
- Set "weight" to an integer 1-5 for how serious/important each item is \
(5 = critical/high-stakes, 3 = normal, 1 = trivial). Default to 3 if unsure.
- Put recurring/background/everyday work in "everyday_items", not in phases.
- Preserve names, constraints, decisions, deliverables, tools, links, files, \
contacts, references, and other specifics in "info_cards" and "resources".
- Attach resources to the closest checklist item when possible; otherwise put \
them in the top-level "resources" list.
- Keep titles short; put detail in "description".
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
        "weight": integer 1-5,
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
            items_out.append({
                "title": title,
                "description": (item.get("description") or "").strip(),
                "deadline": _norm_date(item.get("deadline")),
                "duration_days": _coerce_int(item.get("duration_days")),
                "weight": _coerce_weight(item.get("weight")),
                "resources": resources,
            })
        phases_out.append({
            "name": (phase.get("name") or "Phase").strip(),
            "items": items_out,
        })

    everyday_out = []
    everyday_raw = (raw.get("everyday_items") or raw.get("everyday") or
                    raw.get("background_items") or [])
    for item in everyday_raw:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        if not title:
            continue
        everyday_out.append({
            "title": title,
            "description": _clean_text(item.get("description")),
            "cadence": _clean_text(item.get("cadence")),
        })

    resources_out = []
    for res in raw.get("resources") or []:
        normalized = _normalize_resource(res)
        if normalized:
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
