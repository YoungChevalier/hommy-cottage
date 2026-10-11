"""
app/services/reservation_service.py
──────────────────────────────────
Reservation business logic.

Initial implementation supports one room per reservation via the existing
book_room stored procedure. The procedure owns its transaction and commits
internally, so this module does not wrap multiple procedure calls to simulate
atomic multi-room booking.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import mysql.connector

from app.db import db_cursor, get_db, release_db

logger = logging.getLogger(__name__)

RESERVATION_STATUSES = frozenset({"Booked", "Checked-in", "Checked-out", "Cancelled"})
ACTIVE_STATUSES = frozenset({"Booked", "Checked-in"})
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
DEFAULT_SORT = "reservation_id"
ALLOWED_SORT_COLUMNS = frozenset({"reservation_id", "guest_id", "check_in", "check_out", "status", "created_at"})


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


def parse_date_range(check_in_value, check_out_value) -> tuple[Optional[date], Optional[date], Optional[str]]:
    if not check_in_value:
        return None, None, "'check_in' is required in YYYY-MM-DD format."
    if not check_out_value:
        return None, None, "'check_out' is required in YYYY-MM-DD format."

    try:
        check_in = date.fromisoformat(str(check_in_value).strip())
        check_out = date.fromisoformat(str(check_out_value).strip())
    except ValueError:
        return None, None, "'check_in' and 'check_out' must be valid dates in YYYY-MM-DD format."

    if check_out <= check_in:
        return None, None, "Check-out must be later than check-in."
    return check_in, check_out, None


def validate_booking_payload(data: dict, *, role: str, session_guest_id=None) -> tuple[Optional[dict], list[str]]:
    errors: list[str] = []

    if "rooms" in data:
        errors.append("Multi-room booking is not supported by this endpoint yet; use a single 'room_no'.")
    if "rate_charged" in data or "price" in data or "base_price" in data:
        errors.append("Room prices are calculated by the database and must not be supplied.")

    try:
        room_no = int(data.get("room_no"))
    except (TypeError, ValueError):
        errors.append("'room_no' must be a positive integer.")
        room_no = None
    else:
        if room_no <= 0:
            errors.append("'room_no' must be a positive integer.")

    if role == "Guest":
        if session_guest_id is None:
            errors.append("Guest account is not linked to a guest record.")
        guest_id = session_guest_id
        supplied_guest = data.get("guest_id")
        if supplied_guest not in (None, "", session_guest_id, str(session_guest_id)):
            errors.append("Guests may only create reservations for their own account.")
    else:
        try:
            guest_id = int(data.get("guest_id"))
        except (TypeError, ValueError):
            errors.append("'guest_id' must be a positive integer.")
            guest_id = None
        else:
            if guest_id <= 0:
                errors.append("'guest_id' must be a positive integer.")

    check_in, check_out, err = parse_date_range(data.get("check_in"), data.get("check_out"))
    if err:
        errors.append(err)

    if errors:
        return None, errors
    return {"guest_id": int(guest_id), "room_no": room_no, "check_in": check_in, "check_out": check_out}, []


def _reservation_summary_where(role: str, guest_id: Optional[int]) -> tuple[str, list]:
    if role == "Guest":
        return "WHERE r.guest_id = %s", [guest_id]
    return "", []


def list_reservations(*, role: str, guest_id: Optional[int], page=1, limit=DEFAULT_LIMIT,
                      status: Optional[str] = None, sort_by=DEFAULT_SORT, sort_dir="asc") -> dict:
    page = _parse_positive_int(page, 1, 1_000_000)
    limit = _parse_positive_int(limit, DEFAULT_LIMIT)
    offset = (page - 1) * limit
    sort_by = sort_by if sort_by in ALLOWED_SORT_COLUMNS else DEFAULT_SORT
    sort_dir = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

    where_sql, params = _reservation_summary_where(role, guest_id)
    clauses = []
    if where_sql:
        clauses.append(where_sql.removeprefix("WHERE "))
    if status:
        clauses.append("r.status = %s")
        params.append(status)
    final_where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with db_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total FROM reservation r {final_where}", params)
        total = cur.fetchone()["total"]
        cur.execute(
            "SELECT r.reservation_id, r.guest_id, g.name AS guest_name, "
            "r.check_in, r.check_out, r.status, r.coupon_id, r.created_at, "
            "COUNT(rr.room_no) AS room_count "
            "FROM reservation r "
            "JOIN guest g ON g.guest_id = r.guest_id "
            "LEFT JOIN reservation_room rr ON rr.reservation_id = r.reservation_id "
            f"{final_where} "
            "GROUP BY r.reservation_id, r.guest_id, g.name, r.check_in, r.check_out, "
            "r.status, r.coupon_id, r.created_at "
            f"ORDER BY r.{sort_by} {sort_dir} LIMIT %s OFFSET %s",
            params + [limit, offset],
        )
        rows = [_serialise_row(row) for row in cur.fetchall()]

    return {
        "reservations": rows,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": max(1, -(-total // limit)),
        },
    }


def get_reservation(reservation_id: int, *, role: str, guest_id: Optional[int]) -> Optional[dict]:
    with db_cursor() as cur:
        owner_filter = "AND r.guest_id = %s" if role == "Guest" else ""
        params = [reservation_id]
        if role == "Guest":
            params.append(guest_id)

        cur.execute(
            "SELECT r.reservation_id, r.guest_id, g.name AS guest_name, "
            "r.check_in, r.check_out, r.status, r.coupon_id, r.created_at "
            "FROM reservation r JOIN guest g ON g.guest_id = r.guest_id "
            f"WHERE r.reservation_id = %s {owner_filter}",
            params,
        )
        row = cur.fetchone()
        if row is None:
            return None
        reservation = _serialise_row(row)
        cur.execute(
            "SELECT rr.room_no, rr.rate_charged, ro.floor, ro.status AS room_status, "
            "rt.type_id, rt.type_name, rt.capacity, rt.base_price "
            "FROM reservation_room rr "
            "JOIN room ro ON ro.room_no = rr.room_no "
            "JOIN room_type rt ON rt.type_id = ro.type_id "
            "WHERE rr.reservation_id = %s ORDER BY rr.room_no",
            (reservation_id,),
        )
        reservation["rooms"] = [_serialise_row(room) for room in cur.fetchall()]
        return reservation


def guest_exists(guest_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM guest WHERE guest_id = %s", (guest_id,))
        return cur.fetchone() is not None


def room_exists(room_no: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM room WHERE room_no = %s", (room_no,))
        return cur.fetchone() is not None


def _classify_booking_db_error(exc) -> str:
    msg = str(exc)
    lowered = msg.lower()
    if "check-out must be after check-in" in lowered:
        return "Check-out must be later than check-in."
    if "room does not exist" in lowered:
        return "Room does not exist."
    if "room is under maintenance" in lowered:
        return "Room is under maintenance."
    if "room already booked" in lowered:
        return "Room already booked for these dates."
    if "foreign key constraint" in lowered or "1452" in msg:
        return "Guest or room does not exist."
    if "check constraint" in lowered or "3819" in msg:
        return "Database constraint rejected the supplied values."
    logger.error("Reservation booking DB error: %s", type(exc).__name__)
    return "A database error occurred. Please try again."


def _latest_created_reservation_id(guest_id: int, room_no: int, check_in: date, check_out: date) -> Optional[int]:
    with db_cursor() as cur:
        cur.execute(
            "SELECT r.reservation_id "
            "FROM reservation r JOIN reservation_room rr ON rr.reservation_id = r.reservation_id "
            "WHERE r.guest_id = %s AND rr.room_no = %s AND r.check_in = %s AND r.check_out = %s "
            "ORDER BY r.reservation_id DESC LIMIT 1",
            (guest_id, room_no, check_in, check_out),
        )
        row = cur.fetchone()
        return row["reservation_id"] if row else None


def create_reservation(clean: dict) -> tuple[Optional[dict], Optional[str]]:
    guest_id = clean["guest_id"]
    room_no = clean["room_no"]
    check_in = clean["check_in"]
    check_out = clean["check_out"]

    if not guest_exists(guest_id):
        return None, "Guest does not exist."
    if not room_exists(room_no):
        return None, "Room does not exist."

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            cur.callproc("book_room", (guest_id, room_no, check_in, check_out))
        except Exception as exc:
            return None, _classify_booking_db_error(exc)
    finally:
        if cur:
            cur.close()
        release_db(conn)

    reservation_id = _latest_created_reservation_id(guest_id, room_no, check_in, check_out)
    if reservation_id is None:
        return None, "Reservation was created but could not be loaded."
    return get_reservation(reservation_id, role="Admin", guest_id=None), None


def _transition_error(current: str, target: str) -> Optional[str]:
    if target == "Checked-in" and current != "Booked":
        return "Only booked reservations can be checked in."
    if target == "Checked-out" and current != "Checked-in":
        return "Only checked-in reservations can be checked out."
    if target == "Cancelled" and current != "Booked":
        return "Only booked reservations can be cancelled."
    return None


def transition_reservation(reservation_id: int, *, target_status: str, role: str,
                           guest_id: Optional[int]) -> tuple[Optional[dict], Optional[str]]:
    if target_status in {"Checked-in", "Checked-out"} and role == "Guest":
        return None, "Guests cannot perform this reservation transition."

    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=True)
        try:
            conn.start_transaction()
            owner_filter = "AND guest_id = %s" if role == "Guest" else ""
            params = [reservation_id]
            if role == "Guest":
                params.append(guest_id)
            cur.execute(
                f"SELECT reservation_id, guest_id, status FROM reservation "
                f"WHERE reservation_id = %s {owner_filter} FOR UPDATE",
                params,
            )
            row = cur.fetchone()
            if row is None:
                conn.rollback()
                return None, "Reservation not found."

            err = _transition_error(row["status"], target_status)
            if err:
                conn.rollback()
                return None, err

            cur.execute(
                "UPDATE reservation SET status = %s WHERE reservation_id = %s",
                (target_status, reservation_id),
            )
            conn.commit()
        except mysql.connector.Error as exc:
            conn.rollback()
            msg = str(exc)
            if "closed reservation cannot change status" in msg.lower():
                return None, "A closed reservation cannot change status."
            logger.error("Reservation transition DB error: %s", type(exc).__name__)
            return None, "A database error occurred. Please try again."
        finally:
            cur.close()
    finally:
        release_db(conn)

    return get_reservation(reservation_id, role=role, guest_id=guest_id), None
