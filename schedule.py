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


def _weight(item) -> int:
    """An item's seriousness weight (>=1). Missing/invalid weights count as 1."""
    try:
        w = int(item.get("weight") or 1)
    except (ValueError, TypeError):
        w = 1
    return w if w > 0 else 1


def progress(items) -> dict:
    """Return {total, done, percent} where percent is WEIGHTED by each item's
    seriousness ('weight'). With uniform/absent weights this matches a plain
    completed-count ratio."""
    total = len(items)
    done = sum(1 for i in items if i.get("status") == "done")
    total_w = sum(_weight(i) for i in items)
    done_w = sum(_weight(i) for i in items if i.get("status") == "done")
    percent = round(done_w / total_w * 100) if total_w else 0
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
