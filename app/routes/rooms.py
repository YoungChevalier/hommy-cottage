"""
app/routes/rooms.py
──────────────────
Blueprints for room management, room types, status, and availability.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request

from app.decorators import login_required, roles_required
from app.services import room_service
from app.utils.responses import ok, created, bad_request, not_found, conflict

logger = logging.getLogger(__name__)

rooms_bp = Blueprint("rooms", __name__, url_prefix="/api/rooms")
room_types_bp = Blueprint("room_types", __name__, url_prefix="/api/room-types")


def _parse_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _validation_error(message: str):
    return bad_request(message, code="VALIDATION_ERROR")


@rooms_bp.get("")
@rooms_bp.get("/")
@login_required
@roles_required("Admin", "Receptionist")
def list_rooms():
    args = request.args
    status = args.get("status")
    if status and status not in room_service.ROOM_STATUSES:
        return _validation_error(
            f"Invalid status. Allowed values: {', '.join(sorted(room_service.ROOM_STATUSES))}."
        )

    type_id = args.get("type_id")
    if type_id not in (None, ""):
        try:
            type_id = int(type_id)
        except ValueError:
            return _validation_error("'type_id' must be an integer.")
    else:
        type_id = None

    sort_by = args.get("sort_by", room_service.DEFAULT_SORT)
    if sort_by not in room_service.ALLOWED_ROOM_SORT_COLUMNS:
        return _validation_error(
            f"Invalid sort_by. Allowed values: {', '.join(sorted(room_service.ALLOWED_ROOM_SORT_COLUMNS))}."
        )

    try:
        result = room_service.list_rooms(
            page=_parse_int(args.get("page"), 1),
            limit=_parse_int(args.get("limit"), room_service.DEFAULT_LIMIT),
            status=status,
            type_id=type_id,
            sort_by=sort_by,
            sort_dir=args.get("sort_dir", "asc"),
        )
    except Exception:
        logger.exception("Unable to list rooms.")
        return bad_request("Unable to list rooms.")

    return ok(result)


@rooms_bp.post("")
@rooms_bp.post("/")
@login_required
@roles_required("Admin")
def create_room():
    data = request.get_json(silent=True) or {}
    clean, errors = room_service.validate_room_payload(data, partial=False)
    if errors:
        return _validation_error(" ".join(errors))

    room, err = room_service.create_room(clean)
    if err:
        if "already exists" in err:
            return conflict(err)
        return _validation_error(err)
    return created(room)


@rooms_bp.get("/status")
@login_required
@roles_required("Admin", "Receptionist")
def room_status():
    return ok(room_service.get_room_status())


@rooms_bp.get("/available")
@login_required
@roles_required("Admin", "Receptionist", "Guest")
def available_rooms():
    check_in, check_out, err = room_service.parse_date_range(
        request.args.get("from"),
        request.args.get("to"),
    )
    if err:
        return _validation_error(err)
    return ok(room_service.find_available_rooms(check_in, check_out))


@rooms_bp.get("/<int:room_no>")
@login_required
@roles_required("Admin", "Receptionist")
def get_room(room_no: int):
    room = room_service.get_room(room_no)
    if room is None:
        return not_found(f"Room {room_no} not found.")
    return ok(room)


@rooms_bp.put("/<int:room_no>")
@login_required
@roles_required("Admin")
def update_room(room_no: int):
    data = request.get_json(silent=True) or {}
    data.pop("room_no", None)
    clean, errors = room_service.validate_room_payload(data, partial=True)
    if errors:
        return _validation_error(" ".join(errors))

    room, err = room_service.update_room(room_no, clean)
    if err:
        if "not found" in err.lower():
            return not_found(err)
        return _validation_error(err)
    return ok(room)


@room_types_bp.get("")
@room_types_bp.get("/")
@login_required
@roles_required("Admin", "Receptionist", "Guest")
def list_room_types():
    args = request.args
    sort_by = args.get("sort_by", "type_id")
    if sort_by not in room_service.ALLOWED_TYPE_SORT_COLUMNS:
        return _validation_error(
            f"Invalid sort_by. Allowed values: {', '.join(sorted(room_service.ALLOWED_TYPE_SORT_COLUMNS))}."
        )
    return ok(room_service.list_room_types(
        page=_parse_int(args.get("page"), 1),
        limit=_parse_int(args.get("limit"), room_service.DEFAULT_LIMIT),
        sort_by=sort_by,
        sort_dir=args.get("sort_dir", "asc"),
    ))


@room_types_bp.post("")
@room_types_bp.post("/")
@login_required
@roles_required("Admin")
def create_room_type():
    data = request.get_json(silent=True) or {}
    if "type_id" in data:
        return _validation_error("'type_id' must not be supplied by the client.")

    clean, errors = room_service.validate_room_type_payload(data, partial=False)
    if errors:
        return _validation_error(" ".join(errors))

    room_type, err = room_service.create_room_type(clean)
    if err:
        if "already exists" in err:
            return conflict(err)
        return _validation_error(err)
    return created(room_type)


@room_types_bp.put("/<int:type_id>")
@login_required
@roles_required("Admin")
def update_room_type(type_id: int):
    data = request.get_json(silent=True) or {}
    data.pop("type_id", None)

    clean, errors = room_service.validate_room_type_payload(data, partial=True)
    if errors:
        return _validation_error(" ".join(errors))

    room_type, err = room_service.update_room_type(type_id, clean)
    if err:
        if "not found" in err.lower():
            return not_found(err)
        if "already exists" in err:
            return conflict(err)
        return _validation_error(err)
    return ok(room_type)
