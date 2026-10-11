"""
app/utils/responses.py
──────────────────────
Standardised JSON response helpers used across all blueprints.

Every response has the envelope:
    {
        "success": true | false,
        "data":    <payload>   | null,
        "error":   null        | {"code": "...", "message": "..."}
    }

Rules
─────
* Stack traces are NEVER included in responses.
* Error messages are safe for end-users (no SQL details, no file paths).
* HTTP status codes follow REST conventions.
"""

from __future__ import annotations

from flask import jsonify, Response


# ── Success helpers ───────────────────────────────────────────────────────────

def ok(data: object = None, status: int = 200) -> tuple[Response, int]:
    """200 OK (or custom 2xx) with a payload."""
    return jsonify({"success": True, "data": data, "error": None}), status


def created(data: object = None) -> tuple[Response, int]:
    """201 Created."""
    return jsonify({"success": True, "data": data, "error": None}), 201


def no_content() -> tuple[Response, int]:
    """204 No Content — empty body."""
    return Response(status=204)


# ── Error helpers ─────────────────────────────────────────────────────────────

def _error_body(code: str, message: str) -> dict:
    return {"success": False, "data": None, "error": {"code": code, "message": message}}


def bad_request(message: str = "Invalid request.", code: str = "BAD_REQUEST") -> tuple[Response, int]:
    """400 Bad Request."""
    return jsonify(_error_body(code, message)), 400


def unauthorized(message: str = "Authentication required.", code: str = "UNAUTHORIZED") -> tuple[Response, int]:
    """401 Unauthorized."""
    return jsonify(_error_body(code, message)), 401


def forbidden(message: str = "You do not have permission.", code: str = "FORBIDDEN") -> tuple[Response, int]:
    """403 Forbidden."""
    return jsonify(_error_body(code, message)), 403


def not_found(message: str = "Resource not found.", code: str = "NOT_FOUND") -> tuple[Response, int]:
    """404 Not Found."""
    return jsonify(_error_body(code, message)), 404


def conflict(message: str = "Conflict.", code: str = "CONFLICT") -> tuple[Response, int]:
    """409 Conflict."""
    return jsonify(_error_body(code, message)), 409


def internal_error(message: str = "An internal error occurred.", code: str = "INTERNAL_ERROR") -> tuple[Response, int]:
    """
    500 Internal Server Error.
    NEVER pass raw exception messages here — sanitise before calling.
    """
    return jsonify(_error_body(code, message)), 500


def service_unavailable(message: str = "Service temporarily unavailable.", code: str = "SERVICE_UNAVAILABLE") -> tuple[Response, int]:
    """503 Service Unavailable."""
    return jsonify(_error_body(code, message)), 503
