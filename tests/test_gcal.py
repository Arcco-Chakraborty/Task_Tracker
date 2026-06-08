from datetime import date, datetime, timedelta, timezone

import gcal


class _Resp:
    def __init__(self, ok=True, status=200, payload=None):
        self.ok = ok
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_add_event_builds_allday(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["auth"] = headers["Authorization"]
        return _Resp(payload={"id": "evt1"})

    monkeypatch.setattr(gcal.requests, "post", fake_post)
    out = gcal.add_event("tok", "Proj: Task", date(2026, 6, 20), "do it")
    assert out["id"] == "evt1"
    assert captured["json"]["start"]["date"] == "2026-06-20"
    assert captured["json"]["end"]["date"] == "2026-06-21"   # end exclusive
    assert captured["auth"] == "Bearer tok"


def test_add_event_raises_on_error(monkeypatch):
    monkeypatch.setattr(gcal.requests, "post",
                        lambda *a, **k: _Resp(ok=False, status=403))
    try:
        gcal.add_event("tok", "x", date(2026, 1, 1))
        assert False, "expected CalendarError"
    except gcal.CalendarError:
        pass


def test_valid_token_returns_unexpired():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    user = {"id": 1, "google_access_token": "live", "google_token_expiry": future,
            "google_refresh_token": "r"}
    assert gcal._valid_access_token(None, user, "cid", "cs") == "live"


def test_valid_token_refreshes_when_expired(monkeypatch):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    user = {"id": 1, "google_access_token": "stale", "google_token_expiry": past,
            "google_refresh_token": "r"}
    monkeypatch.setattr(gcal.requests, "post",
                        lambda *a, **k: _Resp(payload={"access_token": "fresh",
                                                       "expires_in": 3600}))
    saved = {}
    monkeypatch.setattr(gcal.db, "set_user_google_tokens",
                        lambda conn, uid, **kw: saved.update(kw))
    tok = gcal._valid_access_token(None, user, "cid", "cs")
    assert tok == "fresh" and saved["access_token"] == "fresh"


def test_valid_token_no_refresh_raises():
    user = {"id": 1, "google_access_token": None, "google_token_expiry": None,
            "google_refresh_token": None}
    try:
        gcal._valid_access_token(None, user, "cid", "cs")
        assert False
    except gcal.CalendarError:
        pass
