"""gcal.py — add events to the signed-in user's Google Calendar via the REST API.

Uses the OAuth tokens stored on the user (auth.py). Access tokens are refreshed
with the stored refresh token when they expire.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

import db

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class CalendarError(Exception):
    """Raised when an event cannot be added to Google Calendar."""


def _valid_access_token(conn, user, client_id, client_secret) -> str:
    """Return a non-expired access token, refreshing via the refresh token
    when needed (and persisting the new one)."""
    token = user.get("google_access_token")
    expiry = user.get("google_token_expiry")
    now = datetime.now(timezone.utc)
    if token and expiry:
        try:
            if datetime.fromisoformat(expiry) > now + timedelta(seconds=60):
                return token
        except ValueError:
            pass
    refresh = user.get("google_refresh_token")
    if not refresh:
        raise CalendarError(
            "Google Calendar isn't connected — sign out and back in to grant access.")
    resp = requests.post(TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=15)
    if not resp.ok:
        raise CalendarError("Google access expired — sign out and back in.")
    data = resp.json()
    new_token = data.get("access_token")
    if not new_token:
        raise CalendarError("Google did not return an access token.")
    expiry = (now + timedelta(seconds=int(data.get("expires_in", 3600)))).isoformat()
    db.set_user_google_tokens(conn, user["id"], access_token=new_token,
                              expiry=expiry)
    return new_token


def add_event(access_token, summary, day, description="") -> dict:
    """Insert a single all-day event on `day` (a date). Returns event JSON."""
    body = {
        "summary": summary,
        "description": description or "",
        "start": {"date": day.isoformat()},
        "end": {"date": (day + timedelta(days=1)).isoformat()},
    }
    resp = requests.post(EVENTS_URL, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"}, json=body, timeout=15)
    if not resp.ok:
        raise CalendarError(f"Calendar API error ({resp.status_code})")
    return resp.json()


def sync_items(conn, user, client_id, client_secret, items) -> int:
    """Add an all-day event for every item with a resolved_date.
    Each item: {summary, resolved_date(date), description}. Returns count added."""
    token = _valid_access_token(conn, user, client_id, client_secret)
    added = 0
    for it in items:
        day = it.get("resolved_date")
        if not day:
            continue
        add_event(token, it.get("summary") or it.get("title", "Task"), day,
                  it.get("description", ""))
        added += 1
    return added
