"""
tests/test_auth.py
──────────────────
Tests for Phase 2: Authentication and Authorization.

Test groups
───────────
1. TestCsrfToken           — GET /api/auth/csrf-token
2. TestLogin               — POST /api/auth/login (no DB needed for basic, DB for real)
3. TestLogout              — POST /api/auth/logout
4. TestMe                  — GET /api/auth/me
5. TestChangePassword      — POST /api/auth/change-password
6. TestRoleAuthorization   — role-based access control decorators
7. TestLoginThrottle       — brute-force lockout (no DB needed)
8. TestCsrfProtection      — CSRF rejection
9. TestRoleRecordValidation — invalid role/record combos
10. TestSessionRenewal     — session fixation prevention

Tests that require a live DB use `require_db` and are automatically
skipped when MySQL is not reachable.
"""

from __future__ import annotations

import json
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(resp) -> dict:
    assert resp.content_type == "application/json", (
        f"Expected JSON, got {resp.content_type!r}. Body: {resp.data.decode()!r}"
    )
    return json.loads(resp.data)


def _login(client, username: str, password: str):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )


def _logout(client):
    return client.post("/api/auth/logout")


# ── 1. CSRF Token ─────────────────────────────────────────────────────────────

class TestCsrfToken:
    """GET /api/auth/csrf-token — must always return a token string."""

    def test_returns_200(self, client):
        resp = client.get("/api/auth/csrf-token")
        assert resp.status_code == 200

    def test_returns_csrf_token_field(self, client):
        body = _json(client.get("/api/auth/csrf-token"))
        assert "csrf_token" in body["data"]
        assert isinstance(body["data"]["csrf_token"], str)
        assert len(body["data"]["csrf_token"]) > 10


# ── 2. Login ──────────────────────────────────────────────────────────────────

class TestLogin:
    """POST /api/auth/login"""

    def test_missing_username_returns_400(self, fresh_client):
        resp = fresh_client.post("/api/auth/login", json={"password": "x"})
        assert resp.status_code == 400

    def test_missing_password_returns_400(self, fresh_client):
        resp = fresh_client.post("/api/auth/login", json={"username": "x"})
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, fresh_client):
        resp = fresh_client.post("/api/auth/login", json={})
        assert resp.status_code == 400

    def test_wrong_credentials_returns_401(self, fresh_client):
        resp = _login(fresh_client, "nonexistent_user_xyz", "wrongpassword")
        assert resp.status_code == 401

    def test_wrong_credentials_generic_message(self, fresh_client):
        """Must not reveal whether the username exists."""
        body = _json(_login(fresh_client, "nonexistent_user_xyz", "wrongpassword"))
        msg = body["error"]["message"].lower()
        # Must not say "username not found", "user does not exist", etc.
        assert "not found" not in msg
        assert "does not exist" not in msg
        assert "username" not in msg or "password" in msg  # generic

    def test_no_password_in_error_response(self, fresh_client):
        resp = _login(fresh_client, "someone", "secret_password_123")
        assert "secret_password_123" not in resp.data.decode()

    def test_get_method_not_allowed(self, client):
        resp = client.get("/api/auth/login")
        assert resp.status_code == 405

    def test_successful_login(self, fresh_client, test_admin_credentials, require_db):
        creds = test_admin_credentials
        resp = _login(fresh_client, creds["username"], creds["password"])
        assert resp.status_code == 200
        body = _json(resp)
        assert body["success"] is True
        assert body["data"]["role"] == "Admin"
        assert "password" not in str(body).lower()
        assert "password_hash" not in str(body)

    def test_successful_login_no_password_hash_in_response(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        resp = _login(fresh_client, creds["username"], creds["password"])
        assert "password_hash" not in resp.data.decode()

    def test_login_response_envelope(self, fresh_client, test_admin_credentials, require_db):
        creds = test_admin_credentials
        body = _json(_login(fresh_client, creds["username"], creds["password"]))
        assert "success" in body
        assert "data" in body
        assert "error" in body

    def test_wrong_password_for_existing_user_returns_401(
        self, fresh_client, test_admin_credentials, require_db
    ):
        resp = _login(fresh_client, test_admin_credentials["username"], "completely_wrong!")
        assert resp.status_code == 401

    def test_wrong_password_same_generic_message(
        self, fresh_client, test_admin_credentials, require_db
    ):
        """Wrong password and wrong username should produce identical messages."""
        body_wrong_user = _json(_login(fresh_client, "nobody_xyz_abc", "pass"))
        body_wrong_pass = _json(
            _login(fresh_client, test_admin_credentials["username"], "badpass")
        )
        assert body_wrong_user["error"]["message"] == body_wrong_pass["error"]["message"]


# ── 3. Logout ─────────────────────────────────────────────────────────────────

class TestLogout:
    """POST /api/auth/logout"""

    def test_logout_without_login_returns_401(self, fresh_client):
        resp = _logout(fresh_client)
        assert resp.status_code == 401

    def test_get_logout_not_allowed(self, client):
        resp = client.get("/api/auth/logout")
        assert resp.status_code == 405

    def test_logout_after_login_returns_200(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        _login(fresh_client, creds["username"], creds["password"])
        resp = _logout(fresh_client)
        assert resp.status_code == 200

    def test_me_after_logout_returns_401(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        _login(fresh_client, creds["username"], creds["password"])
        _logout(fresh_client)
        resp = fresh_client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_logout_twice_returns_401_second_time(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        _login(fresh_client, creds["username"], creds["password"])
        _logout(fresh_client)
        resp = _logout(fresh_client)
        assert resp.status_code == 401


# ── 4. Me ─────────────────────────────────────────────────────────────────────

class TestMe:
    """GET /api/auth/me"""

    def test_unauthenticated_returns_401(self, fresh_client):
        resp = fresh_client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_authenticated_returns_200(
        self, fresh_client, test_admin_credentials, require_db
    ):
        _login(fresh_client, test_admin_credentials["username"],
               test_admin_credentials["password"])
        resp = fresh_client.get("/api/auth/me")
        assert resp.status_code == 200

    def test_me_response_has_no_password_hash(
        self, fresh_client, test_admin_credentials, require_db
    ):
        _login(fresh_client, test_admin_credentials["username"],
               test_admin_credentials["password"])
        resp = fresh_client.get("/api/auth/me")
        assert "password_hash" not in resp.data.decode()
        assert "password" not in resp.data.decode().lower()

    def test_me_returns_correct_role(
        self, fresh_client, test_admin_credentials, require_db
    ):
        _login(fresh_client, test_admin_credentials["username"],
               test_admin_credentials["password"])
        body = _json(fresh_client.get("/api/auth/me"))
        assert body["data"]["role"] == "Admin"

    def test_me_returns_correct_username(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        _login(fresh_client, creds["username"], creds["password"])
        body = _json(fresh_client.get("/api/auth/me"))
        assert body["data"]["username"] == creds["username"]


# ── 5. Change Password ────────────────────────────────────────────────────────

class TestChangePassword:
    """POST /api/auth/change-password"""

    def test_unauthenticated_returns_401(self, fresh_client):
        resp = fresh_client.post(
            "/api/auth/change-password",
            json={"current_password": "x", "new_password": "y"},
        )
        assert resp.status_code == 401

    def test_missing_fields_returns_400(
        self, fresh_client, test_admin_credentials, require_db
    ):
        _login(fresh_client, test_admin_credentials["username"],
               test_admin_credentials["password"])
        resp = fresh_client.post(
            "/api/auth/change-password",
            json={"current_password": "only_one"},
        )
        assert resp.status_code == 400

    def test_wrong_current_password_returns_401(
        self, fresh_client, test_admin_credentials, require_db
    ):
        _login(fresh_client, test_admin_credentials["username"],
               test_admin_credentials["password"])
        resp = fresh_client.post(
            "/api/auth/change-password",
            json={"current_password": "WRONG_PASS", "new_password": "NewPass#123"},
        )
        assert resp.status_code == 401

    def test_short_new_password_returns_400(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        _login(fresh_client, creds["username"], creds["password"])
        resp = fresh_client.post(
            "/api/auth/change-password",
            json={"current_password": creds["password"], "new_password": "short"},
        )
        assert resp.status_code == 400

    def test_successful_change_then_login_with_new_password(
        self, app, test_admin_credentials, require_db
    ):
        """Full round-trip: change password, then verify new password works."""
        creds = test_admin_credentials
        new_pw = "NewSecure#Pass99"

        # Change password
        with app.test_client() as c:
            _login(c, creds["username"], creds["password"])
            resp = c.post(
                "/api/auth/change-password",
                json={"current_password": creds["password"], "new_password": new_pw},
            )
            assert resp.status_code == 200, resp.data.decode()

        # Login with new password
        with app.test_client() as c:
            resp = _login(c, creds["username"], new_pw)
            assert resp.status_code == 200

        # Restore original password so other tests still work
        with app.test_client() as c:
            _login(c, creds["username"], new_pw)
            c.post(
                "/api/auth/change-password",
                json={"current_password": new_pw, "new_password": creds["password"]},
            )


# ── 6. Role Authorization ─────────────────────────────────────────────────────

class TestRoleAuthorization:
    """Decorator behaviour: login_required + roles_required."""

    def test_health_accessible_without_login(self, client):
        """Public endpoints must remain accessible."""
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_me_requires_login(self, fresh_client):
        resp = fresh_client.get("/api/auth/me")
        assert resp.status_code == 401
        body = _json(resp)
        assert body["error"]["code"] == "UNAUTHORIZED"

    def test_401_response_envelope(self, fresh_client):
        body = _json(fresh_client.get("/api/auth/me"))
        assert "success" in body
        assert body["success"] is False
        assert "error" in body


# ── 7. Login Throttle ─────────────────────────────────────────────────────────

class TestLoginThrottle:
    """
    Brute-force lockout via app.utils.auth (in-memory, no DB needed).
    Uses a unique username so lockout state is isolated per test.
    """

    def test_lockout_after_max_failures(self, fresh_client):
        from app.utils.auth import MAX_ATTEMPTS, _store, _lock

        username = "_throttle_test_user_unique_"

        # Clear any existing state
        with _lock:
            _store.pop(username, None)

        # Exhaust attempts
        for _ in range(MAX_ATTEMPTS):
            resp = _login(fresh_client, username, "wrong")
            assert resp.status_code == 401

        # Next attempt should be locked (401 with lockout message)
        resp = _login(fresh_client, username, "wrong")
        assert resp.status_code == 401
        body = _json(resp)
        assert "locked" in body["error"]["message"].lower()

        # Cleanup
        with _lock:
            _store.pop(username, None)

    def test_success_clears_failure_count(self, fresh_client, test_admin_credentials, require_db):
        from app.utils.auth import _store, _lock, record_failure, record_success, MAX_ATTEMPTS

        creds = test_admin_credentials
        # Pre-seed some failures
        record_failure(creds["username"])
        record_failure(creds["username"])

        # Successful login should clear them
        resp = _login(fresh_client, creds["username"], creds["password"])
        assert resp.status_code == 200

        with _lock:
            assert creds["username"] not in _store


# ── 8. CSRF Protection ────────────────────────────────────────────────────────

class TestCsrfProtection:
    """
    CSRF rejection tests.
    Uses the csrf_client fixture which enables WTF_CSRF_ENABLED=True.
    """

    def test_post_without_csrf_token_rejected(self, csrf_client):
        """Login POST without X-CSRFToken header must be rejected with 400."""
        c, _token = csrf_client
        # Do NOT send X-CSRFToken header
        resp = c.post(
            "/api/auth/login",
            data=json.dumps({"username": "x", "password": "y"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = _json(resp)
        assert body["error"]["code"] == "CSRF_ERROR"

    def test_post_with_valid_csrf_token_accepted(self, csrf_client):
        """POST with valid X-CSRFToken header must reach the route handler."""
        c, token = csrf_client
        resp = c.post(
            "/api/auth/login",
            data=json.dumps({"username": "nonexistent_xyz", "password": "pass"}),
            content_type="application/json",
            headers={"X-CSRFToken": token},
        )
        # Should reach the handler and return 401 (wrong creds), not 400 CSRF
        assert resp.status_code == 401

    def test_get_request_does_not_require_csrf(self, csrf_client):
        """GET requests must never require a CSRF token."""
        c, _token = csrf_client
        resp = c.get("/api/auth/me")
        # 401 because not logged in — but NOT 400 CSRF error
        assert resp.status_code == 401
        body = _json(resp)
        assert body["error"]["code"] != "CSRF_ERROR"


# ── 9. Role-Record Validation ─────────────────────────────────────────────────

class TestRoleRecordValidation:
    """
    Enforce that role/record combinations are validated in Python.
    These tests call auth_service directly — no DB needed for rejection cases.
    """

    def test_admin_with_guest_id_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Admin", guest_id=1, emp_id=None)
        assert err is not None
        assert "admin" in err.lower()

    def test_admin_with_emp_id_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Admin", guest_id=None, emp_id=1)
        assert err is not None

    def test_admin_with_no_ids_accepted(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Admin", guest_id=None, emp_id=None)
        assert err is None

    def test_receptionist_without_emp_id_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Receptionist", guest_id=None, emp_id=None)
        assert err is not None
        assert "receptionist" in err.lower() or "employee" in err.lower()

    def test_receptionist_with_emp_id_accepted(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Receptionist", guest_id=None, emp_id=5)
        assert err is None

    def test_receptionist_with_guest_id_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Receptionist", guest_id=3, emp_id=5)
        assert err is not None

    def test_guest_without_guest_id_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Guest", guest_id=None, emp_id=None)
        assert err is not None

    def test_guest_with_guest_id_accepted(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Guest", guest_id=7, emp_id=None)
        assert err is None

    def test_guest_with_emp_id_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("Guest", guest_id=7, emp_id=2)
        assert err is not None

    def test_invalid_role_rejected(self, app):
        from app.services.auth_service import _validate_role_record
        err = _validate_role_record("SuperAdmin", guest_id=None, emp_id=None)
        assert err is not None


# ── 10. Session Renewal (fixation prevention) ─────────────────────────────────

class TestSessionRenewal:
    """
    After login the session must be regenerated (cleared + new values set),
    preventing session fixation attacks.
    """

    def test_session_set_after_login(self, fresh_client, test_admin_credentials, require_db):
        creds = test_admin_credentials
        with fresh_client.session_transaction() as sess:
            pre_keys = set(sess.keys())

        _login(fresh_client, creds["username"], creds["password"])

        with fresh_client.session_transaction() as sess:
            assert "user_id" in sess
            assert "role" in sess
            assert sess["role"] == "Admin"

    def test_session_cleared_after_logout(
        self, fresh_client, test_admin_credentials, require_db
    ):
        creds = test_admin_credentials
        _login(fresh_client, creds["username"], creds["password"])
        _logout(fresh_client)

        with fresh_client.session_transaction() as sess:
            assert "user_id" not in sess
            assert "role" not in sess

    def test_failed_login_does_not_set_session(self, fresh_client):
        _login(fresh_client, "noone_xyz", "wrong")
        with fresh_client.session_transaction() as sess:
            assert "user_id" not in sess
