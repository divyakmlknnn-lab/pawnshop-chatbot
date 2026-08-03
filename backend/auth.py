"""Trusted user/store identity for TellerIQ (Phase 2).

Identity comes only from the database and the signed Flask session.
Request JSON store_id / user_id values are never trusted.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Any

from flask import Flask, g, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_user_by_id, get_user_by_username

logger = logging.getLogger("telleriq.auth")

SESSION_USER_ID = "auth_user_id"
SESSION_STORE_ID = "auth_store_id"

# Local development only. Production/Render must set SECRET_KEY explicitly.
_DEV_SECRET_FALLBACK = "telleriq-local-dev-secret-not-for-production"

_PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/auth/login",
})


def auth_required_enabled() -> bool:
    return os.environ.get("AUTH_REQUIRED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_ALLOWED_SAMESITE = frozenset({"Lax", "Strict", "None"})


def resolve_session_cookie_samesite(raw: str | None = None) -> str:
    """Return a Flask-compatible SESSION_COOKIE_SAMESITE value.

    Allowed: Lax (default), Strict, None.
    Invalid / blank values fall back to Lax (safe local default) and log a warning.

    For cross-site HTTPS (e.g. Vercel → Render), set:
      SESSION_COOKIE_SAMESITE=None
      SESSION_COOKIE_SECURE=1
    Browsers require Secure when SameSite=None; Secure remains independently
    configured via SESSION_COOKIE_SECURE and is not forced here.
    """
    if raw is None:
        raw = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    cleaned = (raw or "").strip()
    if not cleaned:
        return "Lax"
    normalized = {
        "lax": "Lax",
        "strict": "Strict",
        "none": "None",
    }.get(cleaned.lower())
    if normalized is None or normalized not in _ALLOWED_SAMESITE:
        logger.warning(
            "Invalid SESSION_COOKIE_SAMESITE=%r; falling back to Lax. "
            "Allowed values: Lax, Strict, None.",
            cleaned,
        )
        return "Lax"
    return normalized


def configure_session(app: Flask) -> None:
    """Configure signed Flask sessions (8-hour lifetime)."""
    secret = (os.environ.get("SECRET_KEY") or "").strip()
    if not secret:
        secret = _DEV_SECRET_FALLBACK
        logger.warning(
            "SECRET_KEY is not set; using local development fallback. "
            "Set SECRET_KEY in the environment before any shared/deployed use."
        )
    app.config["SECRET_KEY"] = secret
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = resolve_session_cookie_samesite()
    # Local HTTP POC: Secure cookies would block session on http://127.0.0.1.
    # Cross-site HTTPS deployments should set SESSION_COOKIE_SECURE=1 together
    # with SESSION_COOKIE_SAMESITE=None.
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
        "SESSION_COOKIE_SECURE", "0"
    ).strip().lower() in {"1", "true", "yes", "on"}


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    if not password_hash or password is None:
        return False
    try:
        return check_password_hash(password_hash, password)
    except (ValueError, TypeError):
        return False


def public_user_profile(user_row: dict[str, Any]) -> dict[str, Any]:
    """Safe profile fields only — never includes password_hash."""
    return {
        "user_id": int(user_row["user_id"]),
        "store_id": int(user_row["store_id"]),
        "username": user_row["username"],
        "display_name": user_row.get("display_name"),
        "store_name": user_row.get("store_name"),
    }


def establish_session(user_row: dict[str, Any]) -> dict[str, Any]:
    """Bind the signed session to DB-derived identity only."""
    session.clear()
    session.permanent = True
    session[SESSION_USER_ID] = int(user_row["user_id"])
    session[SESSION_STORE_ID] = int(user_row["store_id"])
    session.modified = True
    return public_user_profile(user_row)


def clear_session() -> None:
    session.clear()
    session.modified = True


def _user_is_active(user_row: dict[str, Any] | None) -> bool:
    if not user_row:
        return False
    return bool(int(user_row.get("is_active") or 0))


def authenticate_username_password(username: str, password: str) -> dict[str, Any] | None:
    """Return public profile after successful auth, else None.

    store_id in the request body is ignored; session store_id comes from the DB row.
    """
    cleaned_username = (username or "").strip()
    if not cleaned_username or password is None or password == "":
        return None

    user_row = get_user_by_username(cleaned_username)
    if not _user_is_active(user_row):
        return None
    if not verify_password(user_row["password_hash"], password):
        return None
    return establish_session(user_row)


def load_request_identity() -> dict[str, Any] | None:
    """Populate flask.g from signed session + current DB row.

    Returns the public profile, or None if unauthenticated / inactive.
    """
    g.user_id = None
    g.store_id = None
    g.username = None
    g.display_name = None
    g.store_name = None
    g.current_user = None

    user_id = session.get(SESSION_USER_ID)
    session_store_id = session.get(SESSION_STORE_ID)
    if user_id is None or session_store_id is None:
        return None

    user_row = get_user_by_id(int(user_id))
    if not _user_is_active(user_row):
        clear_session()
        return None

    # Session store_id must continue to match the DB (detect tampering / moves).
    if int(user_row["store_id"]) != int(session_store_id):
        clear_session()
        return None

    profile = public_user_profile(user_row)
    g.user_id = profile["user_id"]
    g.store_id = profile["store_id"]
    g.username = profile["username"]
    g.display_name = profile["display_name"]
    g.store_name = profile["store_name"]
    g.current_user = profile
    return profile


def path_requires_auth(path: str) -> bool:
    if path in _PUBLIC_PATHS or path.startswith("/auth/"):
        return False
    return path in {"/chat", "/dashboard/stats"}


def auth_gate_response(path: str):
    """Return a 401 Flask response when AUTH_REQUIRED and identity is missing."""
    if not auth_required_enabled():
        return None
    if not path_requires_auth(path):
        return None
    if getattr(g, "current_user", None):
        return None
    from flask import jsonify

    return jsonify({"error": "Authentication required."}), 401
