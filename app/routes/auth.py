"""
app/routes/auth.py
──────────────────
Blueprint: /api/auth

Endpoints
─────────
  POST /api/auth/login          — Authenticate and start a session.
  POST /api/auth/logout         — Destroy the session (POST to prevent CSRF logout).
  GET  /api/auth/me             — Return the authenticated user's profile.
  POST /api/auth/change-password — Change the current user's password.

Security decisions
──────────────────
* CSRF:     Flask-WTF CSRFProtect is initialised globally. API clients
            must send X-CSRFToken header (or csrf_token form field) on
            POST/PUT/DELETE/PATCH requests.
            The GET /api/auth/csrf-token endpoint provides a token to
            SPA / browser clients.

* Rate-limiting: flask-limiter applies IP-level request rate limits
            on the login endpoint; plus per-username lockout via
            app.utils.auth (in-memory, server-side).

* Session fixation: session.clear() + new data on every successful login.

* Generic errors: login never reveals whether a username exists.

* Logging: Usernames are logged at INFO; passwords are NEVER logged.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request, session, jsonify, current_app
from flask_wtf.csrf import generate_csrf

from app.decorators import login_required, roles_required
from app.services import auth_service
from app.utils.auth import is_locked, record_failure, record_success
from app.utils.responses import ok, bad_request, unauthorized, forbidden
from app.utils.validators import require_fields

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# ── CSRF token provider (GET — safe, no mutation) ─────────────────────────────

@auth_bp.get("/csrf-token")
def csrf_token():
    """
    GET /api/auth/csrf-token

    Returns a CSRF token for SPA / browser clients.
    The token must be sent as X-CSRFToken header or csrf_token field
    on all state-changing requests (POST / PUT / DELETE / PATCH).

    Response 200:
        {"success": true, "data": {"csrf_token": "<token>"}, "error": null}
    """
    return ok({"csrf_token": generate_csrf()})


# ── Login ──────────────────────────────────────────────────────────────────────

@auth_bp.post("/login")
def login():
    """
    POST /api/auth/login

    Body (JSON):
        {"username": "...", "password": "..."}

    Response 200:
        {"success": true, "data": {"user_id": ..., "username": "...", "role": "..."}, ...}

    Response 400:  missing fields
    Response 401:  invalid credentials or account locked (same generic message)
    Response 429:  IP rate limit exceeded
    """
    data = request.get_json(silent=True) or {}
    valid, err = require_fields(data, "username", "password")
    if not valid:
        return bad_request(err)

    username = str(data["username"]).strip()
    password = str(data["password"])          # do NOT strip passwords

    # ── Check lockout BEFORE touching the DB ──────────────────────────────────
    if is_locked(username):
        logger.warning("Login attempt on locked account: %s", username)
        return unauthorized(
            "Account temporarily locked due to multiple failed attempts. "
            "Please try again later."
        )

    # ── Verify credentials ────────────────────────────────────────────────────
    user, err = auth_service.authenticate_user(username, password)

    if user is None:
        failures = record_failure(username)
        logger.info("Failed login for username=%s (attempt %d)", username, failures)
        return unauthorized("Invalid username or password.")

    # ── Success: regenerate session (prevent fixation) ────────────────────────
    record_success(username)
    session.clear()
    session["user_id"] = user["user_id"]
    session["username"] = user["username"]
    session["role"] = user["role"]
    session["guest_id"] = user.get("guest_id")
    session["emp_id"] = user.get("emp_id")
    session.permanent = True

    logger.info("User logged in: user_id=%s role=%s", user["user_id"], user["role"])
    return ok({"user_id": user["user_id"],
               "username": user["username"],
               "role": user["role"]})


# ── Logout ─────────────────────────────────────────────────────────────────────

@auth_bp.post("/logout")
@login_required
def logout():
    """
    POST /api/auth/logout

    Destroys the current session.  Must be POST (GET logout is a CSRF risk).
    Requires a valid CSRF token.

    Response 200:
        {"success": true, "data": {"message": "Logged out."}, "error": null}
    """
    user_id = session.get("user_id")
    session.clear()
    logger.info("User logged out: user_id=%s", user_id)
    return ok({"message": "Logged out successfully."})


# ── Me ─────────────────────────────────────────────────────────────────────────

@auth_bp.get("/me")
@login_required
def me():
    """
    GET /api/auth/me

    Returns the current authenticated user's profile.
    password_hash is never included.

    Response 200:
        {"success": true, "data": {"user_id": ..., "username": ..., "role": ...}, ...}
    """
    user_id = session["user_id"]
    user = auth_service.get_user_by_id(user_id)
    if user is None:
        # Session references a deleted user — clear and 401
        session.clear()
        return unauthorized("Session is no longer valid.")
    return ok(user)


# ── Change password ────────────────────────────────────────────────────────────

@auth_bp.post("/change-password")
@login_required
def change_password():
    """
    POST /api/auth/change-password

    Body (JSON):
        {
            "current_password": "...",
            "new_password":     "..."
        }

    Security:
    - Requires re-authentication (current_password).
    - Role cannot be changed here.
    - Requires a valid CSRF token.

    Response 200:
        {"success": true, "data": {"message": "Password changed."}, "error": null}
    Response 400:  validation error
    Response 401:  current password wrong
    """
    data = request.get_json(silent=True) or {}
    valid, err = require_fields(data, "current_password", "new_password")
    if not valid:
        return bad_request(err)

    user_id = session["user_id"]
    current_pw = str(data["current_password"])
    new_pw = str(data["new_password"])

    err = auth_service.change_password(user_id, current_pw, new_pw)
    if err:
        # "Current password is incorrect" → 401; validation errors → 400
        if "incorrect" in err.lower():
            return unauthorized(err)
        return bad_request(err)

    logger.info("Password changed: user_id=%s", user_id)
    return ok({"message": "Password changed successfully."})
