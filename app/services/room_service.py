"""
app/services/room_service.py
────────────────────────────
Business logic for room management and availability.

The schema already defines room statuses and the find_available_rooms stored
procedure. This module does not change database design or procedure logic.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from app.db import db_cursor, get_db, release_db

logger = logging.getLogger(__name__)

ROOM_STATUSES = frozenset({"Available", "Occupied", "Cleaning", "Maintenance"})
ADMIN_SETTABLE_STATUSES = frozenset({"Available", "Cleaning", "Maintenance"})
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_SORT = "room_no"
ALLOWED_ROOM_SORT_COLUMNS = frozenset({"room_no", "floor", "status", "type_name", "base_price", "capacity"})
ALLOWED_TYPE_SORT_COLUMNS = frozenset({"type_id", "type_name", "base_price", "capacity"})

_ROOM_SELECT = (
    "ro.room_no, ro.floor, ro.status, ro.type_id, "
    "rt.type_name, rt.base_price, rt.capacity, rt.description"
)


def _norm(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _serialise(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _serialise_row(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    return {key: _serialise(value) for key, value in row.items()}


def _parse_positive_int(value, default: int, maximum: int = MAX_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, maximum))


def parse_date_range(from_value: str | None, to_value: str | None) -> tuple[Optional[date], Optional[date], Optional[str]]:
    if not from_value:
        return None, None, "'from' is required in YYYY-MM-DD format."
    if not to_value:
        return None, None, "'to' is required in YYYY-MM-DD format."

    try:
        check_in = date.fromisoformat(str(from_value).strip())
        check_out = date.fromisoformat(str(to_value).strip())
    except ValueError:
        return None, None, "'from' and 'to' must be valid dates in YYYY-MM-DD format."

    if check_out <= check_in:
        return None, None, "Check-out must be later than check-in."

    return check_in, check_out, None


def validate_room_type_payload(data: dict, *, partial: bool = False) -> tuple[Optional[dict], list[str]]:
    errors: list[str] = []
    clean: dict = {}

    if not partial or "type_name" in data:
        type_name = _norm(data.get("type_name"))
        if not type_name:
            errors.append("'type_name' is required.")
        elif len(type_name) > 40:
            errors.append("'type_name' must not exceed 40 characters.")
        else:
            clean["type_name"] = type_name

    if not partial or "base_price" in data:
        try:
            base_price = Decimal(str(data.get("base_price")))
        except Exception:
            errors.append("'base_price' must be a positive number.")
        else:
            if base_price <= 0:
                errors.append("'base_price' must be greater than zero.")
            else:
                clean["base_price"] = base_price

    if not partial or "capacity" in data:
        try:
            capacity = int(data.get("capacity"))
        except (TypeError, ValueError):
            errors.append("'capacity' must be a positive integer.")
        else:
            if capacity <= 0 or capacity > 255:
                errors.append("'capacity' must be between 1 and 255.")
            else:
                clean["capacity"] = capacity

    if "description" in data:
        description = _norm(data.get("description"))
        if description is not None and len(description) > 255:
            errors.append("'description' must not exceed 255 characters.")
        else:
            clean["description"] = description

    if partial and not clean and not errors:
        errors.append("Request body must contain at least one valid field to update.")

    return (None, errors) if errors else (clean, [])


def validate_room_payload(data: dict, *, partial: bool = False) -> tuple[Optional[dict], list[str]]:
    errors: list[str] = []
    clean: dict = {}

    if not partial or "room_no" in data:
        try:
            room_no = int(data.get("room_no"))
        except (TypeError, ValueError):
            errors.append("'room_no' must be a positive integer.")
        else:
            if room_no <= 0:
                errors.append("'room_no' must be a positive integer.")
            else:
                clean["room_no"] = room_no

    if not partial or "type_id" in data:
        try:
            type_id = int(data.get("type_id"))
        except (TypeError, ValueError):
            errors.append("'type_id' must be a positive integer.")
        else:
            if type_id <= 0:
                errors.append("'type_id' must be a positive integer.")
            else:
                clean["type_id"] = type_id

    if not partial or "floor" in data:
        try:
            floor = int(data.get("floor"))
        except (TypeError, ValueError):
            errors.append("'floor' must be a positive integer.")
        else:
            if floor <= 0 or floor > 255:
                errors.append("'floor' must be between 1 and 255.")
            else:
                clean["floor"] = floor

    if "status" in data:
        status = _norm(data.get("status"))
        if status not in ROOM_STATUSES:
            errors.append(f"'status' must be one of: {', '.join(sorted(ROOM_STATUSES))}.")
        elif status not in ADMIN_SETTABLE_STATUSES:
            errors.append("Room status 'Occupied' is managed by reservation check-in workflows.")
        else:
            clean["status"] = status

    if partial and not clean and not errors:
        errors.append("Request body must contain at least one valid field to update.")

    return (None, errors) if errors else (clean, [])


def _classify_db_error(exc) -> str:
    msg = str(exc)
    if "Duplicate entry" in msg:
        if "room_type" in msg or "type_name" in msg:
            return "A room type with this name already exists."
        return "A room with this number already exists."
    if "foreign key constraint" in msg.lower() or "1452" in msg:
        return "Referenced room type does not exist."
    if "check constraint" in msg.lower() or "3819" in msg:
        return "Database constraint rejected the supplied values."
    return "A database error occurred. Please try again."


def list_rooms(*, page=1, limit=DEFAULT_LIMIT, status: Optional[str] = None,
               type_id: Optional[int] = None, sort_by=DEFAULT_SORT, sort_dir="asc") -> dict:
    page = _parse_positive_int(page, 1, 1_000_000)
    limit = _parse_positive_int(limit, DEFAULT_LIMIT)
    offset = (page - 1) * limit
    sort_by = sort_by if sort_by in ALLOWED_ROOM_SORT_COLUMNS else DEFAULT_SORT
    sort_dir = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

    where: list[str] = []
    params: list = []
    if status:
        where.append("ro.status = %s")
        params.append(status)
    if type_id is not None:
        where.append("ro.type_id = %s")
        params.append(type_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM room ro {where_sql}", params)
        total = cur.fetchone()["total"]
        cur.execute(
            f"SELECT {_ROOM_SELECT} FROM room ro "
            f"JOIN room_type rt ON rt.type_id = ro.type_id "
            f"{where_sql} ORDER BY {sort_by} {sort_dir} LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rooms = [_serialise_row(row) for row in cur.fetchall()]

    return {
        "rooms": rooms,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": max(1, -(-total // limit)),
        },
    }


def get_room(room_no: int) -> Optional[dict]:
    with db_cursor() as cur:
        cur.execute(
            f"SELECT {_ROOM_SELECT} FROM room ro "
            f"JOIN room_type rt ON rt.type_id = ro.type_id "
            "WHERE ro.room_no = %s",
            (room_no,),
        )
        return _serialise_row(cur.fetchone())


def list_room_types(*, page=1, limit=DEFAULT_LIMIT, sort_by="type_id", sort_dir="asc") -> dict:
    page = _parse_positive_int(page, 1, 1_000_000)
    limit = _parse_positive_int(limit, DEFAULT_LIMIT)
    offset = (page - 1) * limit
    sort_by = sort_by if sort_by in ALLOWED_TYPE_SORT_COLUMNS else "type_id"
    sort_dir = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM room_type")
        total = cur.fetchone()["total"]
        cur.execute(
            "SELECT type_id, type_name, base_price, capacity, description "
            f"FROM room_type ORDER BY {sort_by} {sort_dir} LIMIT %s OFFSET %s",
            (limit, offset),
        )
        rows = [_serialise_row(row) for row in cur.fetchall()]

    return {
        "room_types": rows,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": max(1, -(-total // limit)),
        },
    }


def get_room_status() -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT status, COUNT(*) AS count FROM room GROUP BY status ORDER BY status")
        counts = {row["status"]: row["count"] for row in cur.fetchall()}
        cur.execute(
            f"SELECT {_ROOM_SELECT} FROM room ro "
            f"JOIN room_type rt ON rt.type_id = ro.type_id "
            "ORDER BY ro.floor, ro.room_no"
        )
        rooms = [_serialise_row(row) for row in cur.fetchall()]

    for status in ROOM_STATUSES:
        counts.setdefault(status, 0)
    return {"counts": counts, "rooms": rooms}


def find_available_rooms(check_in: date, check_out: date) -> dict:
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        cur.callproc("find_available_rooms", (check_in, check_out))
        rows: list[dict] = []
        for result in cur.stored_results():
            rows.extend(result.fetchall())

        available = [_serialise_row(row) for row in rows]
        room_numbers = [row["room_no"] for row in available]
        discrepancies: list[dict] = []

        if room_numbers:
            placeholders = ", ".join(["%s"] * len(room_numbers))
            cur.execute(
                f"SELECT room_no, status FROM room WHERE room_no IN ({placeholders}) "
                "AND status <> 'Available'",
                room_numbers,
            )
            discrepancies = [_serialise_row(row) for row in cur.fetchall()]

        return {
            "from": check_in.isoformat(),
            "to": check_out.isoformat(),
            "rooms": available,
            "count": len(available),
            "status_availability_discrepancies": discrepancies,
            "availability_source": "find_available_rooms",
            "notes": [
                "Availability is date-based and excludes maintenance rooms and overlapping active reservations.",
                "Current room status is reported separately from booking availability.",
            ],
        }
    finally:
        if cur:
            cur.close()
        release_db(conn)


def create_room_type(clean: dict) -> tuple[Optional[dict], Optional[str]]:
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            cur.execute(
                "INSERT INTO room_type (type_name, base_price, capacity, description) "
                "VALUES (%s, %s, %s, %s)",
                (clean["type_name"], clean["base_price"], clean["capacity"], clean.get("description")),
            )
            type_id = cur.lastrowid
            conn.commit()
            cur.execute(
                "SELECT type_id, type_name, base_price, capacity, description "
                "FROM room_type WHERE type_id = %s",
                (type_id,),
            )
            return _serialise_row(cur.fetchone()), None
        except Exception as exc:
            conn.rollback()
            return None, _classify_db_error(exc)
        finally:
            cur.close()
    finally:
        release_db(conn)


def update_room_type(type_id: int, clean: dict) -> tuple[Optional[dict], Optional[str]]:
    set_parts = ", ".join(f"{field} = %s" for field in clean)
    values = list(clean.values()) + [type_id]
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            cur.execute("SELECT type_id FROM room_type WHERE type_id = %s FOR UPDATE", (type_id,))
            if cur.fetchone() is None:
                conn.rollback()
                return None, "Room type not found."
            cur.execute(f"UPDATE room_type SET {set_parts} WHERE type_id = %s", values)
            conn.commit()
            cur.execute(
                "SELECT type_id, type_name, base_price, capacity, description "
                "FROM room_type WHERE type_id = %s",
                (type_id,),
            )
            return _serialise_row(cur.fetchone()), None
        except Exception as exc:
            conn.rollback()
            return None, _classify_db_error(exc)
        finally:
            cur.close()
    finally:
        release_db(conn)


def create_room(clean: dict) -> tuple[Optional[dict], Optional[str]]:
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            cur.execute(
                "INSERT INTO room (room_no, type_id, floor, status) VALUES (%s, %s, %s, %s)",
                (clean["room_no"], clean["type_id"], clean["floor"], clean.get("status", "Available")),
            )
            conn.commit()
            return get_room(clean["room_no"]), None
        except Exception as exc:
            conn.rollback()
            return None, _classify_db_error(exc)
        finally:
            cur.close()
    finally:
        release_db(conn)


def update_room(room_no: int, clean: dict) -> tuple[Optional[dict], Optional[str]]:
    updatable = {key: value for key, value in clean.items() if key in {"type_id", "floor", "status"}}
    if not updatable:
        return None, "No valid fields provided for update."

    set_parts = ", ".join(f"{field} = %s" for field in updatable)
    values = list(updatable.values()) + [room_no]
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            cur.execute("SELECT room_no FROM room WHERE room_no = %s FOR UPDATE", (room_no,))
            if cur.fetchone() is None:
                conn.rollback()
                return None, "Room not found."
            cur.execute(f"UPDATE room SET {set_parts} WHERE room_no = %s", values)
            conn.commit()
            return get_room(room_no), None
        except Exception as exc:
            conn.rollback()
            return None, _classify_db_error(exc)
        finally:
            cur.close()
    finally:
        release_db(conn)
