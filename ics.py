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
