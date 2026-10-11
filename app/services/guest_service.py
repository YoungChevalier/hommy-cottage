"""
app/services/guest_service.py
──────────────────────────────
Business logic for the guest management module.

All SQL is parameterized. Raw DB errors are never surfaced to callers;
instead, friendly messages are returned. password_hash and sensitive
id_proof fields are handled carefully.

Schema reference (guest table):
    guest_id      INT AUTO_INCREMENT PRIMARY KEY
    name          VARCHAR(80)  NOT NULL
    phone         VARCHAR(15)  NOT NULL UNIQUE
    email         VARCHAR(100) UNIQUE
    id_proof_type VARCHAR(30)
    id_proof_no   VARCHAR(40)
    UNIQUE KEY uq_guest_proof (id_proof_type, id_proof_no)

Design decisions
────────────────
* guest_id is NEVER accepted from the client (auto-increment only).
* Deletion is refused if the guest has active reservations (enforced by
  the DB trigger trg_guest_before_delete + FK; we surface the message).
* id_proof fields are optional; if one is supplied, both must be supplied.
* Empty strings for optional fields are normalised to None/NULL.
* Sorting is against an explicit allowlist to prevent SQL injection.
* All SEARCH values go through parameterized %s — never interpolated.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.db import db_cursor, get_db, release_db

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

ALLOWED_SORT_COLUMNS = frozenset({"guest_id", "name", "phone", "email"})
DEFAULT_SORT = "guest_id"
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# Schema-defined field lengths
_MAX_NAME = 80
_MAX_PHONE = 15
_MAX_EMAIL = 100
_MAX_ID_PROOF_TYPE = 30
_MAX_ID_PROOF_NO = 40

# Fields returned to callers (id_proof excluded from list endpoint for brevity)
_GUEST_FIELDS = "guest_id, name, phone, email, id_proof_type, id_proof_no"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _norm(value) -> Optional[str]:
    """Return stripped string or None for empty/None values."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _classify_db_error(exc) -> str:
    """Return a user-safe message for known MySQL duplicate-key errors."""
    msg = str(exc)
    if "Duplicate entry" in msg:
        if "phone" in msg:
            return "A guest with this phone number already exists."
        if "email" in msg:
            return "A guest with this email address already exists."
        if "uq_guest_proof" in msg or "id_proof" in msg:
            return "A guest with this ID proof already exists."
    return "A database error occurred. Please try again."


# ── Validation ─────────────────────────────────────────────────────────────────

def validate_guest_payload(
    data: dict,
    *,
    require_name: bool = True,
) -> tuple[dict | None, list[str]]:
    """
    Validate and normalise a guest creation/update payload.

    Returns:
        (clean_dict, [])           on success
        (None, ["error", ...])     on failure

    The caller decides what to do with errors (usually return 400).
    """
    errors = []
    clean: dict = {}

    # ── name ──────────────────────────────────────────────────────────────────
    name = _norm(data.get("name"))
    if require_name and not name:
        errors.append("'name' is required.")
    elif name is not None:
        if len(name) > _MAX_NAME:
            errors.append(f"'name' must not exceed {_MAX_NAME} characters.")
        else:
            clean["name"] = name

    # ── phone ─────────────────────────────────────────────────────────────────
    phone = _norm(data.get("phone"))
    if require_name and not phone:   # require_name doubles as "is this a create?"
        errors.append("'phone' is required.")
    elif phone is not None:
        if len(phone) > _MAX_PHONE:
            errors.append(f"'phone' must not exceed {_MAX_PHONE} characters.")
        else:
            import re
            if not re.fullmatch(r"^\+?[0-9]{7,15}$", phone):
                errors.append("Phone number must be 7–15 digits (optional leading +).")
            else:
                clean["phone"] = phone

    # ── email (optional) ──────────────────────────────────────────────────────
    if "email" in data:
        email = _norm(data["email"])
        if email is not None:
            if len(email) > _MAX_EMAIL:
                errors.append(f"'email' must not exceed {_MAX_EMAIL} characters.")
            else:
                import re
                pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
                if not re.fullmatch(pattern, email):
                    errors.append("Invalid email address format.")
                else:
                    clean["email"] = email
        else:
            clean["email"] = None   # explicitly clearing

    # ── id_proof_type and id_proof_no (both or neither) ───────────────────────
    has_type = "id_proof_type" in data
    has_no = "id_proof_no" in data

    id_proof_type = _norm(data.get("id_proof_type")) if has_type else "NOTPROVIDED"
    id_proof_no = _norm(data.get("id_proof_no")) if has_no else "NOTPROVIDED"

    if has_type or has_no:
        # If either is present in the payload, treat as an explicit update
        id_proof_type = _norm(data.get("id_proof_type"))
        id_proof_no = _norm(data.get("id_proof_no"))

        # Both null → clear both (allowed)
        if id_proof_type is None and id_proof_no is None:
            clean["id_proof_type"] = None
            clean["id_proof_no"] = None
        elif id_proof_type is None or id_proof_no is None:
            errors.append(
                "'id_proof_type' and 'id_proof_no' must both be provided or both be absent."
            )
        else:
            if len(id_proof_type) > _MAX_ID_PROOF_TYPE:
                errors.append(
                    f"'id_proof_type' must not exceed {_MAX_ID_PROOF_TYPE} characters."
                )
            if len(id_proof_no) > _MAX_ID_PROOF_NO:
                errors.append(
                    f"'id_proof_no' must not exceed {_MAX_ID_PROOF_NO} characters."
                )
            if not errors:
                clean["id_proof_type"] = id_proof_type
                clean["id_proof_no"] = id_proof_no

    if errors:
        return None, errors
    return clean, []


# ── Query helpers ─────────────────────────────────────────────────────────────

def list_guests(
    *,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
    sort_by: str = DEFAULT_SORT,
    sort_dir: str = "asc",
) -> dict:
    """
    Return a paginated list of guests with optional search.

    Sorting column is validated against ALLOWED_SORT_COLUMNS.
    Search value is always parameterized.
    """
    # Sanitise pagination
    page = max(1, int(page))
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = (page - 1) * limit

    # Sanitise sort (allowlist — never interpolated from user input)
    sort_by = sort_by if sort_by in ALLOWED_SORT_COLUMNS else DEFAULT_SORT
    sort_dir = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

    params: list = []
    where_clause = ""

    if search:
        s = f"%{search}%"
        where_clause = "WHERE name LIKE %s OR phone LIKE %s OR email LIKE %s"
        params = [s, s, s]

    count_sql = f"SELECT COUNT(*) AS total FROM guest {where_clause}"
    data_sql = (
        f"SELECT {_GUEST_FIELDS} FROM guest {where_clause} "
        f"ORDER BY {sort_by} {sort_dir} "
        f"LIMIT %s OFFSET %s"
    )

    try:
        with db_cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()["total"]

            cur.execute(data_sql, params + [limit, offset])
            rows = cur.fetchall()

        return {
            "guests": rows,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": max(1, -(-total // limit)),  # ceiling division
            },
        }
    except Exception as exc:
        logger.error("list_guests DB error: %s", type(exc).__name__)
        raise


def get_guest(guest_id: int) -> Optional[dict]:
    """Return one guest row by PK, or None if not found."""
    try:
        with db_cursor() as cur:
            cur.execute(
                f"SELECT {_GUEST_FIELDS} FROM guest WHERE guest_id = %s",
                (guest_id,),
            )
            return cur.fetchone()
    except Exception as exc:
        logger.error("get_guest DB error: %s", type(exc).__name__)
        raise


def create_guest(clean: dict) -> tuple[Optional[dict], Optional[str]]:
    """
    Insert a new guest row and return the created record.

    `clean` must come from validate_guest_payload().
    guest_id is always auto-assigned — never from the client.
    """
    conn = None
    try:
        conn = get_db()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "INSERT INTO guest (name, phone, email, id_proof_type, id_proof_no) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    clean["name"],
                    clean["phone"],
                    clean.get("email"),
                    clean.get("id_proof_type"),
                    clean.get("id_proof_no"),
                ),
            )
            new_id = cur.lastrowid
            conn.commit()

            cur.execute(
                f"SELECT {_GUEST_FIELDS} FROM guest WHERE guest_id = %s", (new_id,)
            )
            return cur.fetchone(), None
        except Exception as exc:
            conn.rollback()
            return None, _classify_db_error(exc)
        finally:
            cur.close()
    except Exception as exc:
        logger.error("create_guest connection error: %s", type(exc).__name__)
        return None, "A server error occurred."
    finally:
        release_db(conn)


def update_guest(guest_id: int, clean: dict) -> tuple[Optional[dict], Optional[str]]:
    """
    Update mutable fields on an existing guest.

    Only fields present in `clean` are updated (PATCH semantics even
    though the route is PUT). At minimum name and phone must be present
    for a full update; partial updates come from the route logic.

    NOTE: We SELECT the guest first to distinguish "not found" from
    "found but nothing changed" (e.g. setting email to its current value).
    MySQL rowcount=0 alone cannot distinguish these two cases.
    """
    if not clean:
        return None, "No valid fields provided for update."

    # Build SET clause from only the supplied keys
    set_parts = ", ".join(f"{col} = %s" for col in clean)
    values = list(clean.values()) + [guest_id]

    conn = None
    try:
        conn = get_db()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        try:
            # Check existence first (so we can return 404 vs "no change")
            cur.execute(
                "SELECT guest_id FROM guest WHERE guest_id = %s FOR UPDATE",
                (guest_id,),
            )
            if cur.fetchone() is None:
                conn.rollback()
                return None, "Guest not found."

            cur.execute(
                f"UPDATE guest SET {set_parts} WHERE guest_id = %s",
                values,
            )
            conn.commit()

            cur.execute(
                f"SELECT {_GUEST_FIELDS} FROM guest WHERE guest_id = %s", (guest_id,)
            )
            return cur.fetchone(), None
        except Exception as exc:
            conn.rollback()
            return None, _classify_db_error(exc)
        finally:
            cur.close()
    except Exception as exc:
        logger.error("update_guest connection error: %s", type(exc).__name__)
        return None, "A server error occurred."
    finally:
        release_db(conn)


def delete_guest(guest_id: int) -> Optional[str]:
    """
    Delete a guest by PK.

    Returns None on success, or an error string on failure.
    The DB trigger trg_guest_before_delete fires SIGNAL for active reservations.
    FK fk_user_guest CASCADE-deletes the app_user row automatically.
    """
    conn = None
    try:
        conn = get_db()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        try:
            # Check existence first for a clean 404 message
            cur.execute(
                "SELECT guest_id FROM guest WHERE guest_id = %s", (guest_id,)
            )
            if cur.fetchone() is None:
                conn.rollback()
                return "Guest not found."

            cur.execute("DELETE FROM guest WHERE guest_id = %s", (guest_id,))
            conn.commit()
            return None
        except Exception as exc:
            conn.rollback()
            err = str(exc)
            if "active reservations" in err:
                return "Cannot delete guest: they have active reservations."
            if "foreign key constraint" in err.lower() or "1451" in err:
                return "Cannot delete guest: related records exist."
            logger.error("delete_guest DB error: %s", type(exc).__name__)
            return "A database error occurred. Please try again."
        finally:
            cur.close()
    except Exception as exc:
        logger.error("delete_guest connection error: %s", type(exc).__name__)
        return "A server error occurred."
    finally:
        release_db(conn)
