"""
app/services/auth_service.py
─────────────────────────────
Business logic for authentication and account management.

All DB access goes through app.db helpers so connection lifecycle is
handled uniformly.  No raw SQL is in the route handlers.

Security decisions
──────────────────
1.  Passwords are hashed with Werkzeug's generate_password_hash
    (pbkdf2:sha256 by default).  Plaintext is never stored or logged.
2.  Parameterized queries throughout — no f-string SQL.
3.  password_hash is never returned from any function.
4.  Generic "invalid credentials" message for all login failures
    (wrong username, wrong password, locked account).
5.  Session is regenerated after successful login to prevent fixation.
6.  Account-role / linked-record consistency is validated in Python,
    not relying solely on MySQL FK constraints (which cannot enforce
    that role matches the linked record type).
7.  Transaction rollback if account creation fails mid-way.

Role-to-record rules (enforced here, not only in the DB)
─────────────────────────────────────────────────────────
  Admin         → guest_id IS NULL  AND emp_id IS NULL
  Receptionist  → emp_id IS NOT NULL (must reference a valid employee)
                  AND guest_id IS NULL
  Guest         → guest_id IS NOT NULL (must reference a valid guest)
                  AND emp_id IS NULL
"""

from __future__ import annotations

import logging
from typing import Optional

from werkzeug.security import generate_password_hash, check_password_hash

from app.db import db_cursor, get_db, release_db

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

VALID_ROLES = frozenset({"Admin", "Receptionist", "Guest"})

# Fields we are allowed to return from app_user (never password_hash)
_SAFE_USER_FIELDS = ("user_id", "username", "role", "guest_id", "emp_id", "created_at")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _safe_user(row: dict) -> dict:
    """Strip password_hash from a row dict."""
    return {k: (str(v) if hasattr(v, 'isoformat') else v)
            for k, v in row.items()
            if k in _SAFE_USER_FIELDS}


def _validate_role_record(role: str,
                           guest_id: Optional[int],
                           emp_id: Optional[int]) -> Optional[str]:
    """
    Return an error message string if the role/record combo is invalid,
    otherwise None.
    """
    if role == "Admin":
        if guest_id is not None or emp_id is not None:
            return "Admin accounts must not be linked to a guest or employee record."
    elif role == "Receptionist":
        if emp_id is None:
            return "Receptionist accounts must be linked to an employee record (emp_id)."
        if guest_id is not None:
            return "Receptionist accounts must not be linked to a guest record."
    elif role == "Guest":
        if guest_id is None:
            return "Guest accounts must be linked to a guest record (guest_id)."
        if emp_id is not None:
            return "Guest accounts must not be linked to an employee record."
    else:
        return f"Invalid role '{role}'."
    return None


def _employee_exists(emp_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM employee WHERE emp_id = %s", (emp_id,))
        return cur.fetchone() is not None


def _guest_record_exists(guest_id: int) -> bool:
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM guest WHERE guest_id = %s", (guest_id,))
        return cur.fetchone() is not None


# ── Public API ────────────────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Verify credentials and return a safe user dict.

    Returns:
        (user_dict, None)       on success
        (None, error_message)   on failure

    The error_message is always generic — never reveals whether the
    username exists.
    """
    GENERIC_MSG = "Invalid username or password."

    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT user_id, username, password_hash, role, guest_id, emp_id, created_at "
                "FROM app_user WHERE username = %s",
                (username,)
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("DB error during authentication lookup: %s", type(exc).__name__)
        return None, "A server error occurred. Please try again."

    if row is None:
        # Perform a dummy hash-check to keep timing constant
        check_password_hash(
            "pbkdf2:sha256:260000$dummy$" + "0" * 64, password
        )
        return None, GENERIC_MSG

    if not check_password_hash(row["password_hash"], password):
        return None, GENERIC_MSG

    # Validate role-record relationship at login time too
    err = _validate_role_record(row["role"], row["guest_id"], row["emp_id"])
    if err:
        logger.error(
            "User %s has inconsistent role/record: %s", row["username"], err
        )
        return None, GENERIC_MSG

    return _safe_user(row), None


def get_user_by_id(user_id: int) -> Optional[dict]:
    """Fetch a safe user dict by PK (for GET /api/auth/me)."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT user_id, username, role, guest_id, emp_id, created_at "
                "FROM app_user WHERE user_id = %s",
                (user_id,)
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("DB error fetching user %s: %s", user_id, type(exc).__name__)
        return None

    if row is None:
        return None
    return _safe_user(row)


def change_password(user_id: int, current_password: str, new_password: str) -> Optional[str]:
    """
    Change the password for an authenticated user.

    Returns None on success, or an error string on failure.

    Security:
    - Requires the current password (re-authentication).
    - Role cannot be changed here.
    - New password is hashed before storage; plaintext is never stored.
    """
    if len(new_password) < 8:
        return "New password must be at least 8 characters."
    if len(new_password) > 128:
        return "New password must not exceed 128 characters."

    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT password_hash FROM app_user WHERE user_id = %s",
                (user_id,)
            )
            row = cur.fetchone()
    except Exception as exc:
        logger.error("DB error fetching user for password change: %s", type(exc).__name__)
        return "A server error occurred."

    if row is None:
        return "User not found."

    if not check_password_hash(row["password_hash"], current_password):
        return "Current password is incorrect."

    new_hash = generate_password_hash(new_password)
    try:
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "UPDATE app_user SET password_hash = %s WHERE user_id = %s",
                (new_hash, user_id)
            )
    except Exception as exc:
        logger.error("DB error updating password: %s", type(exc).__name__)
        return "A server error occurred."

    return None


def create_user(
    username: str,
    password: str,
    role: str,
    guest_id: Optional[int] = None,
    emp_id: Optional[int] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """
    Create a new app_user with role/record validation.

    This function is used by the CLI bootstrap command and any internal
    account-creation logic. It is NOT exposed as a public registration
    endpoint — callers must enforce access control.

    Returns:
        (user_dict, None)       on success
        (None, error_message)   on failure

    Transaction safety:
        All INSERTs happen in one Python-managed transaction.
        On any error, the entire operation rolls back.
    """
    # ── Validate role ─────────────────────────────────────────────────────────
    if role not in VALID_ROLES:
        return None, f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}."

    # ── Validate role-record consistency ──────────────────────────────────────
    err = _validate_role_record(role, guest_id, emp_id)
    if err:
        return None, err

    # ── Validate referenced records exist ─────────────────────────────────────
    if emp_id is not None and not _employee_exists(emp_id):
        return None, f"No employee found with emp_id={emp_id}."
    if guest_id is not None and not _guest_record_exists(guest_id):
        return None, f"No guest found with guest_id={guest_id}."

    # ── Password validation ───────────────────────────────────────────────────
    if len(password) < 8:
        return None, "Password must be at least 8 characters."
    if len(password) > 128:
        return None, "Password must not exceed 128 characters."

    password_hash = generate_password_hash(password)

    # ── Insert (single transaction managed in Python) ─────────────────────────
    conn = None
    try:
        conn = get_db()
        conn.start_transaction()
        cur = conn.cursor(dictionary=True)
        try:
            cur.execute(
                "INSERT INTO app_user (username, password_hash, role, guest_id, emp_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (username, password_hash, role, guest_id, emp_id),
            )
            user_id = cur.lastrowid
            conn.commit()

            cur.execute(
                "SELECT user_id, username, role, guest_id, emp_id, created_at "
                "FROM app_user WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return _safe_user(row), None
        except Exception as exc:
            conn.rollback()
            err_str = str(exc)
            if "Duplicate entry" in err_str and "username" in err_str:
                return None, f"Username '{username}' is already taken."
            if "Duplicate entry" in err_str and "guest_id" in err_str:
                return None, f"A user account already exists for guest_id={guest_id}."
            if "Duplicate entry" in err_str and "emp_id" in err_str:
                return None, f"A user account already exists for emp_id={emp_id}."
            logger.error("DB error creating user: %s", type(exc).__name__)
            return None, "Failed to create account. Please try again."
        finally:
            cur.close()
    except Exception as exc:
        logger.error("Connection error during user creation: %s", type(exc).__name__)
        return None, "A server error occurred."
    finally:
        release_db(conn)
