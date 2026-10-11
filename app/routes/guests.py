"""
app/routes/guests.py
─────────────────────
Blueprint: /api/guests

Endpoints
─────────
  GET    /api/guests              — List / search guests (Admin, Receptionist)
  GET    /api/guests/<guest_id>   — Get one guest (Admin, Receptionist, or own Guest)
  POST   /api/guests              — Create guest (Admin, Receptionist)
  PUT    /api/guests/<guest_id>   — Update guest (Admin, Receptionist)
  DELETE /api/guests/<guest_id>   — Delete guest (Admin only)

Authorization policy
─────────────────────
  Admin        → full CRUD on all guests
  Receptionist → list, get, create, update  (no delete)
  Guest        → GET /api/guests/<own_guest_id> ONLY

CSRF
────
All state-changing routes (POST, PUT, DELETE) require a valid X-CSRFToken
header.  Handled globally by Flask-WTF CSRFProtect.

Error codes
───────────
  400 VALIDATION_ERROR   — invalid / missing fields
  401 UNAUTHORIZED       — not authenticated
  403 FORBIDDEN          — authenticated but wrong role / wrong guest_id
  404 NOT_FOUND          — guest_id does not exist
  409 CONFLICT           — unique constraint violated (phone / email)
  422 UNPROCESSABLE      — deletion blocked by FK / active reservations
"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Blueprint, request, session

from app.decorators import login_required, roles_required
from app.services import guest_service
from app.utils.responses import ok, created, bad_request, not_found, conflict, forbidden

logger = logging.getLogger(__name__)

guests_bp = Blueprint("guests", __name__, url_prefix="/api/guests")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _guest_error(status: int, message: str):
    from flask import jsonify
    code_map = {
        400: "VALIDATION_ERROR",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "UNPROCESSABLE",
    }
    code = code_map.get(status, "ERROR")
    return jsonify({"success": False, "data": None,
                    "error": {"code": code, "message": message}}), status


# ── GET /api/guests ────────────────────────────────────────────────────────────

@guests_bp.get("/")
@guests_bp.get("")
@login_required
@roles_required("Admin", "Receptionist")
def list_guests():
    """
    GET /api/guests?search=&page=1&limit=20&sort_by=guest_id&sort_dir=asc

    Query parameters:
        search   — substring match on name, phone, email
        page     — 1-based page number (default 1)
        limit    — records per page (default 20, max 100)
        sort_by  — guest_id | name | phone | email  (default guest_id)
        sort_dir — asc | desc (default asc)
    """
    args = request.args
    search = args.get("search", "").strip() or None
    page = _parse_int(args.get("page"), 1)
    limit = _parse_int(args.get("limit"), guest_service.DEFAULT_LIMIT)
    sort_by = args.get("sort_by", guest_service.DEFAULT_SORT)
    sort_dir = args.get("sort_dir", "asc")

    # Validate sort_by against allowlist (service layer also enforces this,
    # but we surface a clear 400 instead of silently falling back)
    if sort_by not in guest_service.ALLOWED_SORT_COLUMNS:
        return _guest_error(
            400,
            f"Invalid sort_by. Allowed values: "
            f"{', '.join(sorted(guest_service.ALLOWED_SORT_COLUMNS))}.",
        )

    try:
        result = guest_service.list_guests(
            search=search,
            page=page,
            limit=limit,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
    except Exception:
        return _guest_error(500, "A server error occurred.")

    return ok(result)


# ── GET /api/guests/<guest_id> ────────────────────────────────────────────────

@guests_bp.get("/<int:guest_id>")
@login_required
def get_guest(guest_id: int):
    """
    GET /api/guests/<guest_id>

    Authorization:
    - Admin / Receptionist: any guest_id
    - Guest role: only their own linked guest_id (session["guest_id"])
    """
    role = session.get("role")

    # Guest role: enforce ownership
    if role == "Guest":
        own_id = session.get("guest_id")
        if own_id is None or int(own_id) != guest_id:
            return forbidden("You may only access your own guest record.")
    elif role not in ("Admin", "Receptionist"):
        return forbidden("You do not have permission to access this resource.")

    try:
        guest = guest_service.get_guest(guest_id)
    except Exception:
        return _guest_error(500, "A server error occurred.")

    if guest is None:
        return not_found(f"Guest {guest_id} not found.")

    return ok(guest)


# ── POST /api/guests ──────────────────────────────────────────────────────────

@guests_bp.post("/")
@guests_bp.post("")
@login_required
@roles_required("Admin", "Receptionist")
def create_guest():
    """
    POST /api/guests

    Body (JSON):
        {
            "name":          "Full Name",          (required)
            "phone":         "+1234567890",        (required)
            "email":         "email@example.com",  (optional)
            "id_proof_type": "Passport",           (optional; both or neither)
            "id_proof_no":   "AB1234567"           (optional; both or neither)
        }

    guest_id is NEVER accepted from the client.
    """
    data = request.get_json(silent=True) or {}

    # Reject any attempt to supply guest_id
    if "guest_id" in data:
        return _guest_error(400, "'guest_id' must not be supplied by the client.")

    clean, errors = guest_service.validate_guest_payload(data, require_name=True)
    if errors:
        return _guest_error(400, " ".join(errors))

    guest, err = guest_service.create_guest(clean)
    if err:
        # Duplicate phone/email → 409 Conflict
        if "already exists" in err:
            return conflict(err)
        return _guest_error(400, err)

    return created(guest)


# ── PUT /api/guests/<guest_id> ────────────────────────────────────────────────

@guests_bp.put("/<int:guest_id>")
@login_required
@roles_required("Admin", "Receptionist")
def update_guest(guest_id: int):
    """
    PUT /api/guests/<guest_id>

    Accepts a full or partial update. Only provided fields are changed.
    guest_id in the body is silently ignored to prevent accidental moves.
    """
    data = request.get_json(silent=True) or {}

    # Drop client-supplied guest_id silently
    data.pop("guest_id", None)

    if not data:
        return _guest_error(400, "Request body must contain at least one field to update.")

    # For PUT we do NOT require name/phone if this is a partial update;
    # only validate what's provided (require_name=False)
    clean, errors = guest_service.validate_guest_payload(data, require_name=False)
    if errors:
        return _guest_error(400, " ".join(errors))

    if not clean:
        return _guest_error(400, "No valid fields provided for update.")

    guest, err = guest_service.update_guest(guest_id, clean)
    if err:
        if "not found" in err.lower():
            return not_found(err)
        if "already exists" in err:
            return conflict(err)
        return _guest_error(400, err)

    return ok(guest)


# ── DELETE /api/guests/<guest_id> ─────────────────────────────────────────────

@guests_bp.delete("/<int:guest_id>")
@login_required
@roles_required("Admin")
def delete_guest(guest_id: int):
    """
    DELETE /api/guests/<guest_id>

    Admin only. Refused if the guest has active reservations (trigger).
    The linked app_user row is CASCADE-deleted by the FK automatically.
    """
    err = guest_service.delete_guest(guest_id)
    if err:
        if "not found" in err.lower():
            return not_found(err)
        if "active reservations" in err or "related records" in err:
            return _guest_error(422, err)
        return _guest_error(400, err)

    return ok({"message": f"Guest {guest_id} deleted successfully."})
