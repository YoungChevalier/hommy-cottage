"""
app/decorators.py
─────────────────
Authorization decorators used across all blueprints.

Usage
─────
    from app.decorators import login_required, roles_required

    @bp.get("/api/admin/something")
    @login_required
    @roles_required("Admin")
    def admin_only():
        ...

    @bp.get("/api/staff/something")
    @login_required
    @roles_required("Admin", "Receptionist")
    def staff_route():
        ...

    @bp.get("/api/guest/something")
    @login_required
    @roles_required("Guest")
    def guest_route():
        ...

Rules
─────
* login_required  → 401 if session is not authenticated.
* roles_required  → 403 if the authenticated user's role is not in the list.
* Order matters:  always apply @login_required BEFORE @roles_required.
* Stack traces are never included in 401/403 responses.
"""

from __future__ import annotations

import functools
import logging

from flask import session, jsonify

logger = logging.getLogger(__name__)

# ── Helper ────────────────────────────────────────────────────────────────────

def _error(code: str, message: str, status: int):
    return jsonify({"success": False, "data": None,
                    "error": {"code": code, "message": message}}), status


# ── Decorators ─────────────────────────────────────────────────────────────────

def login_required(f):
    """
    Reject unauthenticated requests with 401.
    Sets X-Login-Required header for SPA/browser clients.
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            resp, status = _error("UNAUTHORIZED", "Authentication required.", 401)
            resp.headers["X-Login-Required"] = "true"
            return resp, status
        return f(*args, **kwargs)
    return wrapper


def roles_required(*allowed_roles: str):
    """
    Decorator factory. Rejects requests whose session role is not in
    ``allowed_roles`` with 403.

    Must be applied AFTER @login_required so that session["role"] is set.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            role = session.get("role")
            if role not in allowed_roles:
                logger.warning(
                    "Forbidden: user_id=%s role=%s tried to access %s (needs %s)",
                    session.get("user_id"), role, f.__name__, allowed_roles,
                )
                return _error("FORBIDDEN", "You do not have permission to access this resource.", 403)
            return f(*args, **kwargs)
        return wrapper
    return decorator
