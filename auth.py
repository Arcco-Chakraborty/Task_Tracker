"""auth.py — Google OAuth login + per-user sessions.

Ported and simplified from arctronas/routes/auth.py: raw OAuth via `requests`,
Flask sessions, no extra deps. Any Google account signs in and gets its own
scoped workspace; an optional ALLOWED_EMAILS allowlist can restrict access.
"""
from __future__ import annotations

import secrets
from functools import wraps
from urllib.parse import urlencode

import requests
from flask import (Blueprint, current_app, g, redirect, render_template,
                   request, session, url_for)

import db

auth_bp = Blueprint("auth", __name__)

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v2/userinfo"
# Identity only — no sensitive scopes, so Google shows no "unverified app"
# warning. Calendar adds use permissionless prefilled links instead.
SCOPES = "openid email profile"


def _conn():
    return current_app.config["GET_CONN"]()


def current_user_id():
    return session.get("user_id")


def current_user():
    """The logged-in user's row (cached per request), or None."""
    uid = session.get("user_id")
    if uid is None:
        return None
    if not hasattr(g, "_cached_user"):
        g._cached_user = db.get_user(_conn(), uid)
    return g._cached_user


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def _allowed(email: str) -> bool:
    raw = current_app.config.get("ALLOWED_EMAILS", "")
    allow = [e.strip().lower() for e in raw.split(",") if e.strip()]
    return (not allow) or (email.lower() in allow)


@auth_bp.route("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))
    configured = bool(current_app.config.get("GOOGLE_CLIENT_ID"))
    return render_template("login.html", error=request.args.get("error"),
                           configured=configured)


@auth_bp.route("/auth/google")
def google_start():
    # `state` ties the callback to this browser session (blocks login CSRF).
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {
        "client_id": current_app.config.get("GOOGLE_CLIENT_ID", ""),
        "redirect_uri": current_app.config.get("GOOGLE_REDIRECT_URI", ""),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
    }
    return redirect(GOOGLE_AUTH + "?" + urlencode(params))


@auth_bp.route("/auth/callback")
def google_callback():
    expected_state = session.pop("oauth_state", None)
    if not expected_state or request.args.get("state") != expected_state:
        return redirect(url_for("auth.login", error="Sign-in expired, try again"))
    code = request.args.get("code")
    if not code:
        return redirect(url_for("auth.login", error="Authentication failed"))
    try:
        token = requests.post(GOOGLE_TOKEN, data={
            "code": code,
            "client_id": current_app.config.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": current_app.config.get("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": current_app.config.get("GOOGLE_REDIRECT_URI", ""),
            "grant_type": "authorization_code",
        }, timeout=15).json()
        access_token = token.get("access_token")
        if not access_token:
            return redirect(url_for("auth.login", error="Could not sign in"))
        info = requests.get(GOOGLE_USERINFO, headers={
            "Authorization": f"Bearer {access_token}"}, timeout=15).json()
    except requests.RequestException:
        return redirect(url_for("auth.login", error="Network error, try again"))

    email = info.get("email", "")
    if not email:
        return redirect(url_for("auth.login", error="No email from Google"))
    if not _allowed(email):
        return redirect(url_for("auth.login", error=f"{email} is not allowed here"))

    conn = _conn()
    user = db.get_or_create_user(conn, email, info.get("name", ""),
                                 info.get("picture", ""))
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    return redirect(url_for("index"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
