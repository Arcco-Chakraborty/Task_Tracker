"""ics.py — build a minimal RFC 5545 iCalendar string from dated events,
plus one-click "Add to Google Calendar" links."""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote


def gcal_link(summary, d, details=""):
    """Return a Google Calendar 'add event' URL for an all-day event on date d
    (the end date is exclusive, so a single all-day event). Returns None when
    there is no date."""
    if d is None:
        return None
    start = d.strftime("%Y%m%d")
    end = (d + timedelta(days=1)).strftime("%Y%m%d")
    url = ("https://calendar.google.com/calendar/render?action=TEMPLATE"
           f"&text={quote(str(summary))}&dates={start}/{end}")
    if details:
        url += f"&details={quote(str(details))}"
    return url


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
