"""
tests/test_health.py
────────────────────
Tests for GET /api/health and GET /api/health/db.

Tests are split into two groups:
  1. Tests that work without a live MySQL connection (always run).
  2. Tests that require a live DB (skipped automatically via `require_db`).
"""

from __future__ import annotations

import json
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(response) -> dict:
    """Parse response JSON; raise clear error on failure."""
    assert response.content_type == "application/json", (
        f"Expected JSON, got {response.content_type!r}. "
        f"Body: {response.data.decode()!r}"
    )
    return json.loads(response.data)


# ── /api/health (liveness — no DB required) ───────────────────────────────────

class TestLiveness:
    """GET /api/health — should always succeed regardless of DB state."""

    def test_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_returns_json(self, client):
        resp = client.get("/api/health")
        body = _json(resp)
        assert isinstance(body, dict)

    def test_success_true(self, client):
        resp = client.get("/api/health")
        body = _json(resp)
        assert body["success"] is True

    def test_error_null(self, client):
        resp = client.get("/api/health")
        body = _json(resp)
        assert body["error"] is None

    def test_data_contains_status_ok(self, client):
        resp = client.get("/api/health")
        body = _json(resp)
        assert body["data"]["status"] == "ok"

    def test_data_contains_service_name(self, client):
        resp = client.get("/api/health")
        body = _json(resp)
        assert "service" in body["data"]
        assert body["data"]["service"] == "Hotel Management System"

    def test_trailing_slash_also_works(self, client):
        resp = client.get("/api/health/")
        assert resp.status_code == 200

    def test_post_returns_405(self, client):
        resp = client.post("/api/health")
        assert resp.status_code == 405

    def test_no_password_in_response(self, client):
        resp = client.get("/api/health")
        body = resp.data.decode()
        assert "password" not in body.lower()
        assert "DB_PASSWORD" not in body


# ── /api/health/db (DB probe — skipped if MySQL absent) ───────────────────────

class TestDbHealth:
    """GET /api/health/db — exercises the actual database connection."""

    def test_returns_200_when_db_available(self, client, require_db):
        resp = client.get("/api/health/db")
        assert resp.status_code == 200

    def test_success_true_when_db_available(self, client, require_db):
        resp = client.get("/api/health/db")
        body = _json(resp)
        assert body["success"] is True

    def test_data_status_ok_when_db_available(self, client, require_db):
        resp = client.get("/api/health/db")
        body = _json(resp)
        assert body["data"]["status"] == "ok"

    def test_data_contains_db_name(self, client, require_db):
        resp = client.get("/api/health/db")
        body = _json(resp)
        assert "db" in body["data"]
        assert body["data"]["db"] == "hotel_db"

    def test_data_contains_server_version(self, client, require_db):
        resp = client.get("/api/health/db")
        body = _json(resp)
        assert "server_version" in body["data"]
        # Should start with a supported MySQL major version (e.g., 8.x, 9.x)
        assert any(body["data"]["server_version"].startswith(prefix) for prefix in ("8.", "9."))

    def test_no_password_in_db_response(self, client, require_db):
        resp = client.get("/api/health/db")
        body = resp.data.decode()
        assert "password" not in body.lower()

    def test_no_stack_trace_in_response(self, client, require_db):
        resp = client.get("/api/health/db")
        body = resp.data.decode()
        assert "Traceback" not in body
        assert "traceback" not in body

    def test_post_returns_405(self, client):
        resp = client.post("/api/health/db")
        assert resp.status_code == 405


# ── Response envelope contract (no DB needed) ─────────────────────────────────

class TestResponseEnvelope:
    """Verify the standard JSON envelope is present on all responses."""

    @pytest.mark.parametrize("url", ["/api/health", "/api/health/"])
    def test_envelope_keys_present(self, client, url):
        resp = client.get(url)
        body = _json(resp)
        assert "success" in body
        assert "data"    in body
        assert "error"   in body

    def test_404_has_envelope(self, client):
        resp = client.get("/api/does-not-exist")
        body = _json(resp)
        assert "success" in body
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"

    def test_405_has_envelope(self, client):
        resp = client.post("/api/health")
        body = _json(resp)
        assert body["success"] is False


# ── Validator unit tests (no Flask or DB needed) ──────────────────────────────

class TestValidators:
    """Unit tests for app/utils/validators.py — pure Python, no I/O."""

    def test_require_fields_all_present(self):
        from app.utils.validators import require_fields
        ok, msg = require_fields({"a": "x", "b": "y"}, "a", "b")
        assert ok is True
        assert msg is None

    def test_require_fields_missing(self):
        from app.utils.validators import require_fields
        ok, msg = require_fields({"a": "x"}, "a", "b")
        assert ok is False
        assert "b" in msg

    def test_require_fields_blank_string(self):
        from app.utils.validators import require_fields
        ok, msg = require_fields({"a": "  "}, "a")
        assert ok is False

    def test_validate_phone_valid(self):
        from app.utils.validators import validate_phone
        ok, _ = validate_phone("+911234567890")
        assert ok is True

    def test_validate_phone_invalid(self):
        from app.utils.validators import validate_phone
        ok, msg = validate_phone("abc")
        assert ok is False
        assert msg is not None

    def test_validate_email_valid(self):
        from app.utils.validators import validate_email
        ok, _ = validate_email("user@example.com")
        assert ok is True

    def test_validate_email_invalid(self):
        from app.utils.validators import validate_email
        ok, msg = validate_email("not-an-email")
        assert ok is False

    def test_validate_date_string_valid(self):
        from app.utils.validators import validate_date_string
        ok, _ = validate_date_string("2025-12-31")
        assert ok is True

    def test_validate_date_string_invalid(self):
        from app.utils.validators import validate_date_string
        ok, msg = validate_date_string("31-12-2025")
        assert ok is False

    def test_validate_date_range_valid(self):
        from app.utils.validators import validate_date_range
        ok, _ = validate_date_range("2025-01-01", "2025-01-05")
        assert ok is True

    def test_validate_date_range_checkout_before_checkin(self):
        from app.utils.validators import validate_date_range
        ok, msg = validate_date_range("2025-01-05", "2025-01-01")
        assert ok is False

    def test_validate_date_range_same_day(self):
        from app.utils.validators import validate_date_range
        ok, msg = validate_date_range("2025-01-01", "2025-01-01")
        assert ok is False

    def test_validate_positive_decimal_valid(self):
        from app.utils.validators import validate_positive_decimal
        ok, _ = validate_positive_decimal(99.99)
        assert ok is True

    def test_validate_positive_decimal_zero(self):
        from app.utils.validators import validate_positive_decimal
        ok, msg = validate_positive_decimal(0)
        assert ok is False

    def test_validate_positive_decimal_negative(self):
        from app.utils.validators import validate_positive_decimal
        ok, msg = validate_positive_decimal(-5)
        assert ok is False

    def test_validate_max_length_within(self):
        from app.utils.validators import validate_max_length
        ok, _ = validate_max_length("hello", 10, "name")
        assert ok is True

    def test_validate_max_length_exceeded(self):
        from app.utils.validators import validate_max_length
        ok, msg = validate_max_length("hello world", 5, "name")
        assert ok is False
        assert "name" in msg
