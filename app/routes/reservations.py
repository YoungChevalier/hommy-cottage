"""
app/routes/reservations.py
──────────────────────────
Reservation API endpoints.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request, session

from app.decorators import login_required, roles_required
from app.services import reservation_service
from app.utils.responses import ok, created, bad_request, not_found, forbidden, conflict

logger = logging.getLogger(__name__)

reservations_bp = Blueprint("reservations", __name__, url_prefix="/api/reservations")


def _parse_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validation_error(message: str):
    return bad_request(message, code="VALIDATION_ERROR")


def _current_role() -> str:
    return session.get("role")


def _current_guest_id():
    return session.get("guest_id")


@reservations_bp.get("")
@reservations_bp.get("/")
@login_required
@roles_required("Admin", "Receptionist", "Guest")
def list_reservations():
    args = request.args
    status = args.get("status")
    if status and status not in reservation_service.RESERVATION_STATUSES:
        return _validation_error(
            f"Invalid status. Allowed values: {', '.join(sorted(reservation_service.RESERVATION_STATUSES))}."
        )

    sort_by = args.get("sort_by", reservation_service.DEFAULT_SORT)
    if sort_by not in reservation_service.ALLOWED_SORT_COLUMNS:
        return _validation_error(
            f"Invalid sort_by. Allowed values: {', '.join(sorted(reservation_service.ALLOWED_SORT_COLUMNS))}."
        )

    if _current_role() == "Guest" and _current_guest_id() is None:
        return forbidden("Guest account is not linked to a guest record.")

    return ok(reservation_service.list_reservations(
        role=_current_role(),
        guest_id=_current_guest_id(),
        page=_parse_int(args.get("page"), 1),
        limit=_parse_int(args.get("limit"), reservation_service.DEFAULT_LIMIT),
        status=status,
        sort_by=sort_by,
        sort_dir=args.get("sort_dir", "asc"),
    ))


@reservations_bp.get("/<int:reservation_id>")
@login_required
@roles_required("Admin", "Receptionist", "Guest")
def get_reservation(reservation_id: int):
    if _current_role() == "Guest" and _current_guest_id() is None:
        return forbidden("Guest account is not linked to a guest record.")

    reservation = reservation_service.get_reservation(
        reservation_id,
        role=_current_role(),
        guest_id=_current_guest_id(),
    )
    if reservation is None:
        return not_found(f"Reservation {reservation_id} not found.")
    return ok(reservation)


@reservations_bp.post("")
@reservations_bp.post("/")
@login_required
@roles_required("Admin", "Receptionist", "Guest")
def create_reservation():
    data = request.get_json(silent=True) or {}
    clean, errors = reservation_service.validate_booking_payload(
        data,
        role=_current_role(),
        session_guest_id=_current_guest_id(),
    )
    if errors:
        return _validation_error(" ".join(errors))

    reservation, err = reservation_service.create_reservation(clean)
    if err:
        lowered = err.lower()
        if "already booked" in lowered:
            return conflict(err)
        if "does not exist" in lowered or "not found" in lowered:
            return not_found(err)
        if "maintenance" in lowered:
            return conflict(err)
        return _validation_error(err)

    return created(reservation)


def _transition(reservation_id: int, target_status: str):
    reservation, err = reservation_service.transition_reservation(
        reservation_id,
        target_status=target_status,
        role=_current_role(),
        guest_id=_current_guest_id(),
    )
    if err:
        lowered = err.lower()
        if "not found" in lowered:
            return not_found(err)
        if "guests cannot" in lowered:
            return forbidden(err)
        if "only" in lowered or "closed" in lowered:
            return conflict(err)
        return _validation_error(err)
    return ok(reservation)


@reservations_bp.post("/<int:reservation_id>/checkin")
@login_required
@roles_required("Admin", "Receptionist")
def checkin(reservation_id: int):
    return _transition(reservation_id, "Checked-in")


@reservations_bp.post("/<int:reservation_id>/checkout")
@login_required
@roles_required("Admin", "Receptionist")
def checkout(reservation_id: int):
    return _transition(reservation_id, "Checked-out")


@reservations_bp.post("/<int:reservation_id>/cancel")
@login_required
@roles_required("Admin", "Receptionist", "Guest")
def cancel(reservation_id: int):
    return _transition(reservation_id, "Cancelled")
