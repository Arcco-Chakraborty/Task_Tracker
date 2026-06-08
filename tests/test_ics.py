from datetime import date

import ics


def test_build_ics_has_envelope_and_event():
    out = ics.build_ics([
        {"uid": "item-1", "summary": "Do thing", "date": date(2026, 6, 20)},
    ])
    assert "BEGIN:VCALENDAR" in out
    assert "END:VCALENDAR" in out
    assert "BEGIN:VEVENT" in out
    assert "SUMMARY:Do thing" in out
    assert "DTSTART;VALUE=DATE:20260620" in out
    assert "UID:item-1" in out


def test_build_ics_skips_dateless_events():
    out = ics.build_ics([{"uid": "x", "summary": "no date", "date": None}])
    assert "BEGIN:VEVENT" not in out


def test_build_ics_escapes_commas():
    out = ics.build_ics([
        {"uid": "1", "summary": "a, b; c", "date": date(2026, 1, 2)},
    ])
    assert "SUMMARY:a\\, b\\; c" in out
