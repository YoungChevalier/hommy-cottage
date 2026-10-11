"""
app/utils/validators.py
───────────────────────
Reusable input validation helpers for use in routes and service layers.

All validators return (is_valid: bool, error_message: str | None).
They never raise exceptions — callers decide how to handle failures.
"""

from __future__ import annotations

import re
from datetime import date


# ── Generic ───────────────────────────────────────────────────────────────────

def require_fields(data: dict, *fields: str) -> tuple[bool, str | None]:
    """
    Check that all required field names are present and non-empty in `data`.

    Returns:
        (True, None) if all fields are present.
        (False, "<field> is required.") on first missing/blank field.
    """
    for field in fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False, f"'{field}' is required."
    return True, None


# ── String ────────────────────────────────────────────────────────────────────

def validate_max_length(value: str, max_len: int, field: str = "field") -> tuple[bool, str | None]:
    if len(value) > max_len:
        return False, f"'{field}' must not exceed {max_len} characters."
    return True, None


def validate_phone(phone: str) -> tuple[bool, str | None]:
    """Accepts E.164-style and common local formats (7–15 digits, optional +)."""
    pattern = r"^\+?[0-9]{7,15}$"
    if not re.fullmatch(pattern, phone.strip()):
        return False, "Phone number must be 7–15 digits (optional leading +)."
    return True, None


def validate_email(email: str) -> tuple[bool, str | None]:
    """Basic RFC-5322 subset check."""
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    if not re.fullmatch(pattern, email.strip()):
        return False, "Invalid email address format."
    return True, None


# ── Numeric ───────────────────────────────────────────────────────────────────

def validate_positive_decimal(value: str | float | int, field: str = "amount") -> tuple[bool, str | None]:
    """Ensure value can be parsed as a positive decimal."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False, f"'{field}' must be a number."
    if parsed <= 0:
        return False, f"'{field}' must be greater than zero."
    return True, None


# ── Date ──────────────────────────────────────────────────────────────────────

def validate_date_string(value: str, field: str = "date") -> tuple[bool, str | None]:
    """Validate ISO-8601 date string (YYYY-MM-DD)."""
    try:
        date.fromisoformat(value.strip())
        return True, None
    except (ValueError, AttributeError):
        return False, f"'{field}' must be a valid date in YYYY-MM-DD format."


def validate_date_range(check_in: str, check_out: str) -> tuple[bool, str | None]:
    """Ensure check_out is strictly after check_in (mirrors the schema CHECK)."""
    try:
        d_in = date.fromisoformat(check_in.strip())
        d_out = date.fromisoformat(check_out.strip())
    except (ValueError, AttributeError):
        return False, "check_in and check_out must be valid dates (YYYY-MM-DD)."
    if d_out <= d_in:
        return False, "check_out must be after check_in."
    return True, None
