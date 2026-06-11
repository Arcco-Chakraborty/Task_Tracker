"""Diagnose the Google Calendar API error using a real stored grant.
Run on the server: ./venv/bin/python scripts/gcal_diag.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

import db
from config import load_dotenv

load_dotenv()
conn = db.connect("tasktracker.db")
rows = conn.execute(
    "SELECT id, email, google_refresh_token FROM users "
    "WHERE google_refresh_token IS NOT NULL AND google_refresh_token != ''"
).fetchall()
if not rows:
    print("NO USER HAS A REFRESH TOKEN — the calendar grant never completed.")
    sys.exit(0)

user = rows[0]
print(f"testing with user {user['id']} ({user['email']})")

tok = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
    "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
    "refresh_token": user["google_refresh_token"],
    "grant_type": "refresh_token",
}, timeout=15).json()
print("refresh:", {k: (v if k != "access_token" else v[:12] + "...")
                   for k, v in tok.items()})
at = tok.get("access_token")
if not at:
    sys.exit(0)

resp = requests.post(
    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
    headers={"Authorization": f"Bearer {at}"},
    json={"summary": "BlackMoniker diag (delete me)",
          "start": {"date": "2026-06-20"}, "end": {"date": "2026-06-21"}},
    timeout=15)
print("insert status:", resp.status_code)
body = resp.json()
print(json.dumps(body, indent=2)[:1200])
if resp.ok:
    eid = body["id"]
    d = requests.delete(
        f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{eid}",
        headers={"Authorization": f"Bearer {at}"}, timeout=15)
    print("cleanup delete:", d.status_code)
