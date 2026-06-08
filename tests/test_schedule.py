from datetime import date

import schedule


def test_resolve_explicit_deadline_wins():
    items = [{"deadline": "2026-06-20", "duration_days": None}]
    assert schedule.resolve_item_dates(date(2026, 6, 1), items) == [date(2026, 6, 20)]


def test_resolve_durations_accumulate():
    items = [
        {"deadline": None, "duration_days": 2},
        {"deadline": None, "duration_days": 3},
    ]
    out = schedule.resolve_item_dates(date(2026, 6, 1), items)
    assert out == [date(2026, 6, 3), date(2026, 6, 6)]


def test_resolve_no_anchor_returns_none():
    items = [{"deadline": None, "duration_days": 3}]
    assert schedule.resolve_item_dates(None, items) == [None]


def test_resolve_explicit_resets_cursor():
    items = [
        {"deadline": "2026-06-10", "duration_days": None},
        {"deadline": None, "duration_days": 2},
    ]
    out = schedule.resolve_item_dates(date(2026, 6, 1), items)
    assert out == [date(2026, 6, 10), date(2026, 6, 12)]


def test_progress():
    items = [{"status": "done"}, {"status": "todo"}, {"status": "done"}]
    p = schedule.progress(items)
    assert p == {"total": 3, "done": 2, "percent": 67}


def test_progress_empty():
    assert schedule.progress([]) == {"total": 0, "done": 0, "percent": 0}


def test_urgency_overdue():
    assert schedule.urgency(date(2026, 6, 1), "todo", date(2026, 6, 5), 3) == "overdue"


def test_urgency_done():
    assert schedule.urgency(date(2026, 6, 1), "done", date(2026, 6, 5), 3) == "done"


def test_urgency_due_soon():
    assert schedule.urgency(date(2026, 6, 7), "todo", date(2026, 6, 5), 3) == "due-soon"


def test_urgency_upcoming():
    assert schedule.urgency(date(2026, 6, 20), "todo", date(2026, 6, 5), 3) == "upcoming"


def test_urgency_none_when_no_date():
    assert schedule.urgency(None, "todo", date(2026, 6, 5), 3) == "none"
