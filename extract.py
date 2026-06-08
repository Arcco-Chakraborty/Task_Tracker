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
