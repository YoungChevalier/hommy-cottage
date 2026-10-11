"""
tests/test_guests.py
─────────────────────
Tests for Phase 3: Guest Management module.

Test groups
───────────
1.  TestGuestList           — GET /api/guests
2.  TestGuestSearch         — GET /api/guests?search=...
3.  TestGuestPagination     — GET /api/guests?page=&limit=
4.  TestGuestSorting        — sort_by / sort_dir validation
5.  TestGuestGet            — GET /api/guests/<id>
6.  TestGuestOwnership      — Guest-role can only see own record
7.  TestGuestCreate         — POST /api/guests
8.  TestGuestDuplicates     — duplicate phone / email / id_proof
9.  TestGuestUpdate         — PUT /api/guests/<id>
10. TestGuestDelete         — DELETE /api/guests/<id>
11. TestGuestUnauthorized   — unauthenticated / wrong role
12. TestGuestIdProof        — id_proof_type / id_proof_no rules

All tests that need a live DB depend on `require_db` and skip automatically
when MySQL is unreachable.

Fixture strategy
────────────────
- Credentials are stored session-wide (create user once).
- Clients are created fresh per test via `as_admin`, `as_receptionist`,
  `as_guest_role` fixtures (function-scoped helpers that log in).
- Transient data (guest rows created per-test) is cleaned up in the
  fixture teardown.
"""

from __future__ import annotations

import json
import uuid
import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json(resp) -> dict:
    assert resp.content_type == "application/json", (
        f"Expected JSON, got {resp.content_type!r}. Body: {resp.data.decode()!r}"
    )
    return json.loads(resp.data)


def _unique() -> str:
    """6-digit unique suffix (decimal only) to avoid test phone regex failures."""
    import random
    return str(random.randint(100000, 999999))



def _login(client, username, password):
    return client.post("/api/auth/login",
                       json={"username": username, "password": password})


def _db_exec(app, sql, params=(), *, commit=True):
    """Run a raw SQL statement in an app context."""
    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=commit) as cur:
            cur.execute(sql, params)
            try:
                return cur.fetchall()
            except Exception:
                return None


def _db_one(app, sql, params=()):
    with app.app_context():
        from app.db import db_cursor
        with db_cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


# ── Session-scoped credential fixtures (no client, just creds) ─────────────────

@pytest.fixture(scope="session")
def test_receptionist_credentials(app, require_db):
    """
    Creates a real employee + Receptionist app_user for the session.
    Cleans up after all tests complete.
    """
    from app.services.auth_service import create_user

    username = f"_r_{_unique()}_"
    password = "TestRecept#9002"
    phone_suffix = _unique()

    with app.app_context():
        from app.db import db_cursor

        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "INSERT INTO department (dept_name) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE dept_id=LAST_INSERT_ID(dept_id)",
                ("_test_dept_",),
            )
        with db_cursor() as cur:
            cur.execute(
                "SELECT dept_id FROM department WHERE dept_name = %s", ("_test_dept_",)
            )
            dept_id = cur.fetchone()["dept_id"]

        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "INSERT INTO employee "
                "(name, phone, role, salary, dept_id, hire_date) "
                "VALUES (%s, %s, %s, %s, %s, '2024-01-01')",
                ("Test Receptionist", f"+999{phone_suffix}", "Receptionist",
                 30000, dept_id),
            )
            emp_id = cur.lastrowid

        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))

        user, err = create_user(username, password, "Receptionist", emp_id=emp_id)
        assert err is None, f"Failed to create receptionist: {err}"

    yield {"username": username, "password": password,
           "user_id": user["user_id"], "emp_id": emp_id}

    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))
            cur.execute("DELETE FROM employee WHERE emp_id = %s", (emp_id,))


@pytest.fixture(scope="session")
def test_guest_user(app, require_db):
    """
    Creates a guest record + linked Guest app_user for ownership tests.
    """
    from app.services.auth_service import create_user

    username = f"_g_{_unique()}_"
    password = "TestGuest#9003"
    phone = f"+888{_unique()}"

    with app.app_context():
        from app.db import db_cursor

        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "INSERT INTO guest (name, phone, email) VALUES (%s, %s, %s)",
                ("Test Guest User", phone, f"g_{_unique()}@test.com"),
            )
            guest_id = cur.lastrowid

        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))

        user, err = create_user(username, password, "Guest", guest_id=guest_id)
        assert err is None, f"Failed to create guest user: {err}"

    yield {
        "username": username, "password": password,
        "user_id": user["user_id"], "guest_id": guest_id,
    }

    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))
            cur.execute("DELETE FROM guest WHERE guest_id = %s", (guest_id,))


# ── Per-test logged-in client helpers ──────────────────────────────────────────

@pytest.fixture()
def as_admin(app, test_admin_credentials):
    """Fresh client logged in as Admin."""
    with app.test_client() as c:
        r = _login(c, test_admin_credentials["username"],
                   test_admin_credentials["password"])
        assert r.status_code == 200, f"Admin login failed: {r.data}"
        yield c


@pytest.fixture()
def as_receptionist(app, test_receptionist_credentials):
    """Fresh client logged in as Receptionist."""
    with app.test_client() as c:
        creds = test_receptionist_credentials
        r = _login(c, creds["username"], creds["password"])
        assert r.status_code == 200, f"Receptionist login failed: {r.data}"
        yield c


@pytest.fixture()
def as_guest_role(app, test_guest_user):
    """Fresh client logged in as Guest role."""
    with app.test_client() as c:
        guu = test_guest_user
        r = _login(c, guu["username"], guu["password"])
        assert r.status_code == 200, f"Guest login failed: {r.data}"
        yield c


# ── Transient guest (created + cleaned per test) ──────────────────────────────

@pytest.fixture()
def transient_guest(app, require_db):
    """Creates a guest row for one test, deletes it afterwards."""
    phone = f"+777{_unique()}"

    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "INSERT INTO guest (name, phone) VALUES (%s, %s)",
                ("Transient Guest", phone),
            )
            guest_id = cur.lastrowid

        with db_cursor() as cur:
            cur.execute("SELECT * FROM guest WHERE guest_id = %s", (guest_id,))
            row = cur.fetchone()

    yield row

    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE guest_id = %s", (guest_id,))
            cur.execute("DELETE FROM guest WHERE guest_id = %s", (guest_id,))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestGuestList
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestList:
    def test_requires_auth(self, fresh_client):
        resp = fresh_client.get("/api/guests")
        assert resp.status_code == 401

    def test_guest_role_forbidden(self, as_guest_role):
        resp = as_guest_role.get("/api/guests")
        assert resp.status_code == 403

    def test_admin_can_list(self, as_admin, require_db):
        resp = as_admin.get("/api/guests")
        assert resp.status_code == 200
        body = _json(resp)
        assert body["success"] is True
        assert "guests" in body["data"]
        assert "pagination" in body["data"]

    def test_receptionist_can_list(self, as_receptionist, require_db):
        resp = as_receptionist.get("/api/guests")
        assert resp.status_code == 200

    def test_pagination_keys_present(self, as_admin, require_db):
        body = _json(as_admin.get("/api/guests"))
        p = body["data"]["pagination"]
        for key in ("page", "limit", "total", "pages"):
            assert key in p, f"Missing pagination key: {key}"

    def test_response_envelope(self, as_admin, require_db):
        body = _json(as_admin.get("/api/guests"))
        assert body["success"] is True
        assert body["error"] is None

    def test_no_password_hash_in_list(self, as_admin, require_db):
        resp = as_admin.get("/api/guests")
        assert "password_hash" not in resp.data.decode()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestGuestSearch
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestSearch:
    def test_search_by_name(self, as_admin, transient_guest, require_db):
        name_frag = transient_guest["name"][:7]
        resp = as_admin.get(f"/api/guests?search={name_frag}")
        assert resp.status_code == 200
        ids = [g["guest_id"] for g in _json(resp)["data"]["guests"]]
        assert transient_guest["guest_id"] in ids

    def test_search_by_phone(self, as_admin, transient_guest, require_db):
        phone_frag = transient_guest["phone"][2:7]
        resp = as_admin.get(f"/api/guests?search={phone_frag}")
        assert resp.status_code == 200
        assert any(
            g["guest_id"] == transient_guest["guest_id"]
            for g in _json(resp)["data"]["guests"]
        )

    def test_search_no_results(self, as_admin, require_db):
        resp = as_admin.get("/api/guests?search=ZZZNOMATCH_xyz_impossible_9999")
        assert resp.status_code == 200
        body = _json(resp)
        assert body["data"]["guests"] == []
        assert body["data"]["pagination"]["total"] == 0

    def test_search_sql_injection_safe(self, as_admin, require_db):
        """SQL injection attempt must return 200 (not 500)."""
        resp = as_admin.get("/api/guests?search=' OR 1=1 --")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestGuestPagination
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestPagination:
    def test_default_page_is_1(self, as_admin, require_db):
        body = _json(as_admin.get("/api/guests"))
        assert body["data"]["pagination"]["page"] == 1

    def test_custom_limit(self, as_admin, require_db):
        body = _json(as_admin.get("/api/guests?limit=3"))
        assert body["data"]["pagination"]["limit"] == 3
        assert len(body["data"]["guests"]) <= 3

    def test_limit_capped_at_max(self, as_admin, require_db):
        body = _json(as_admin.get("/api/guests?limit=9999"))
        assert body["data"]["pagination"]["limit"] <= 100

    def test_page_2_with_limit_1(self, as_admin, transient_guest, require_db):
        resp = as_admin.get("/api/guests?page=2&limit=1")
        assert resp.status_code == 200
        assert _json(resp)["data"]["pagination"]["page"] == 2

    def test_invalid_page_defaults_gracefully(self, as_admin, require_db):
        resp = as_admin.get("/api/guests?page=abc")
        assert resp.status_code == 200

    def test_invalid_limit_defaults_gracefully(self, as_admin, require_db):
        resp = as_admin.get("/api/guests?limit=xyz")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestGuestSorting
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestSorting:
    @pytest.mark.parametrize("col", ["guest_id", "name", "phone", "email"])
    def test_valid_sort_columns(self, as_admin, require_db, col):
        resp = as_admin.get(f"/api/guests?sort_by={col}")
        assert resp.status_code == 200

    def test_invalid_sort_column_returns_400(self, as_admin, require_db):
        resp = as_admin.get("/api/guests?sort_by=password_hash")
        assert resp.status_code == 400

    def test_sort_desc(self, as_admin, require_db):
        resp = as_admin.get("/api/guests?sort_by=guest_id&sort_dir=desc")
        assert resp.status_code == 200

    def test_sql_injection_in_sort_rejected(self, as_admin, require_db):
        resp = as_admin.get("/api/guests?sort_by=guest_id;DROP TABLE guest--")
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestGuestGet
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestGet:
    def test_requires_auth(self, fresh_client):
        resp = fresh_client.get("/api/guests/1")
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, as_admin, require_db):
        resp = as_admin.get("/api/guests/9999999")
        assert resp.status_code == 404
        assert _json(resp)["error"]["code"] == "NOT_FOUND"

    def test_get_returns_correct_guest(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.get(f"/api/guests/{gid}")
        assert resp.status_code == 200
        body = _json(resp)
        assert body["data"]["guest_id"] == gid
        assert body["data"]["name"] == transient_guest["name"]

    def test_no_password_hash_in_get(self, as_admin, transient_guest, require_db):
        resp = as_admin.get(f"/api/guests/{transient_guest['guest_id']}")
        assert "password_hash" not in resp.data.decode()

    def test_receptionist_can_get(self, as_receptionist, transient_guest, require_db):
        resp = as_receptionist.get(f"/api/guests/{transient_guest['guest_id']}")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# 6. TestGuestOwnership
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestOwnership:
    def test_guest_role_can_access_own_record(self, as_guest_role, test_guest_user,
                                               require_db):
        gid = test_guest_user["guest_id"]
        resp = as_guest_role.get(f"/api/guests/{gid}")
        assert resp.status_code == 200
        assert _json(resp)["data"]["guest_id"] == gid

    def test_guest_role_cannot_access_other_record(self, as_guest_role,
                                                    transient_guest, require_db):
        other_gid = transient_guest["guest_id"]
        resp = as_guest_role.get(f"/api/guests/{other_gid}")
        assert resp.status_code == 403
        assert _json(resp)["error"]["code"] == "FORBIDDEN"

    def test_guest_role_cannot_create(self, as_guest_role):
        resp = as_guest_role.post(
            "/api/guests", json={"name": "Hijack", "phone": "+9990001111"}
        )
        assert resp.status_code == 403

    def test_guest_role_cannot_update(self, as_guest_role, transient_guest, require_db):
        resp = as_guest_role.put(
            f"/api/guests/{transient_guest['guest_id']}", json={"name": "Evil"}
        )
        assert resp.status_code == 403

    def test_guest_role_cannot_delete(self, as_guest_role, transient_guest, require_db):
        resp = as_guest_role.delete(f"/api/guests/{transient_guest['guest_id']}")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 7. TestGuestCreate
# ═══════════════════════════════════════════════════════════════════════════════

def _cleanup_guest(app, guest_id):
    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM guest WHERE guest_id = %s", (guest_id,))


class TestGuestCreate:
    def test_requires_auth(self, fresh_client):
        resp = fresh_client.post("/api/guests", json={"name": "x", "phone": "+12345678901"})
        assert resp.status_code == 401

    def test_missing_name_returns_400(self, as_admin, require_db):
        resp = as_admin.post("/api/guests", json={"phone": f"+999{_unique()}"})
        assert resp.status_code == 400

    def test_missing_phone_returns_400(self, as_admin, require_db):
        resp = as_admin.post("/api/guests", json={"name": "Test"})
        assert resp.status_code == 400

    def test_invalid_phone_format_returns_400(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests", json={"name": "Test", "phone": "not-a-phone"}
        )
        assert resp.status_code == 400
        assert "phone" in _json(resp)["error"]["message"].lower()

    def test_invalid_email_format_returns_400(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests",
            json={"name": "Test", "phone": f"+997{_unique()}", "email": "not-an-email"},
        )
        assert resp.status_code == 400

    def test_guest_id_in_body_rejected(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests",
            json={"guest_id": 999, "name": "Test", "phone": f"+996{_unique()}"},
        )
        assert resp.status_code == 400
        assert "guest_id" in _json(resp)["error"]["message"].lower()

    def test_successful_create_returns_201(self, app, as_admin, require_db):
        phone = f"+995{_unique()}"
        resp = as_admin.post("/api/guests", json={"name": "New Guest", "phone": phone})
        assert resp.status_code == 201
        body = _json(resp)
        assert body["success"] is True
        gid = body["data"]["guest_id"]
        assert gid is not None
        _cleanup_guest(app, gid)

    def test_create_assigns_auto_id(self, app, as_admin, require_db):
        phone = f"+994{_unique()}"
        resp = as_admin.post("/api/guests", json={"name": "Auto ID Guest", "phone": phone})
        assert resp.status_code == 201
        gid = _json(resp)["data"]["guest_id"]
        assert isinstance(gid, int) and gid > 0
        _cleanup_guest(app, gid)

    def test_create_with_email(self, app, as_admin, require_db):
        phone = f"+993{_unique()}"
        email = f"test_{_unique()}@example.com"
        resp = as_admin.post(
            "/api/guests",
            json={"name": "Email Guest", "phone": phone, "email": email},
        )
        assert resp.status_code == 201
        body = _json(resp)
        assert body["data"]["email"] == email
        _cleanup_guest(app, body["data"]["guest_id"])

    def test_name_too_long_returns_400(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests", json={"name": "A" * 81, "phone": "+9991234567"}
        )
        assert resp.status_code == 400

    def test_receptionist_can_create(self, app, as_receptionist, require_db):
        phone = f"+992{_unique()}"
        resp = as_receptionist.post(
            "/api/guests", json={"name": "Recept Created", "phone": phone}
        )
        assert resp.status_code == 201
        _cleanup_guest(app, _json(resp)["data"]["guest_id"])


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TestGuestDuplicates
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestDuplicates:
    def test_duplicate_phone_returns_409(self, as_admin, transient_guest, require_db):
        resp = as_admin.post(
            "/api/guests",
            json={"name": "Dup Phone", "phone": transient_guest["phone"]},
        )
        assert resp.status_code == 409
        body = _json(resp)
        assert body["error"]["code"] == "CONFLICT"
        assert "phone" in body["error"]["message"].lower()

    def test_duplicate_email_returns_409(self, app, as_admin, require_db):
        email = f"dup_{_unique()}@example.com"
        phone1, phone2 = f"+911{_unique()}", f"+912{_unique()}"

        r1 = as_admin.post("/api/guests",
                           json={"name": "G1", "phone": phone1, "email": email})
        assert r1.status_code == 201
        gid1 = _json(r1)["data"]["guest_id"]

        try:
            r2 = as_admin.post("/api/guests",
                               json={"name": "G2", "phone": phone2, "email": email})
            assert r2.status_code == 409
            assert "email" in _json(r2)["error"]["message"].lower()
        finally:
            _cleanup_guest(app, gid1)

    def test_update_to_existing_phone_returns_409(self, app, as_admin,
                                                   transient_guest, require_db):
        phone2 = f"+913{_unique()}"
        r = as_admin.post("/api/guests", json={"name": "Second", "phone": phone2})
        assert r.status_code == 201
        gid2 = _json(r)["data"]["guest_id"]

        try:
            resp = as_admin.put(
                f"/api/guests/{gid2}",
                json={"phone": transient_guest["phone"]},
            )
            assert resp.status_code == 409
        finally:
            _cleanup_guest(app, gid2)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. TestGuestUpdate
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestUpdate:
    def test_requires_auth(self, fresh_client):
        resp = fresh_client.put("/api/guests/1", json={"name": "X"})
        assert resp.status_code == 401

    def test_nonexistent_returns_404(self, as_admin, require_db):
        resp = as_admin.put("/api/guests/9999999", json={"name": "Ghost"})
        assert resp.status_code == 404

    def test_update_name(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.put(f"/api/guests/{gid}", json={"name": "Updated Name"})
        assert resp.status_code == 200
        assert _json(resp)["data"]["name"] == "Updated Name"

    def test_update_returns_full_record(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        body = _json(as_admin.put(f"/api/guests/{gid}", json={"name": "Full Record"}))
        for key in ("guest_id", "name", "phone"):
            assert key in body["data"]

    def test_update_invalid_email_returns_400(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.put(f"/api/guests/{gid}", json={"email": "bad-email"})
        assert resp.status_code == 400

    def test_update_clears_email_with_null(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.put(f"/api/guests/{gid}", json={"email": None})
        assert resp.status_code == 200
        assert _json(resp)["data"]["email"] is None

    def test_empty_body_returns_400(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.put(f"/api/guests/{gid}", json={})
        assert resp.status_code == 400

    def test_guest_id_in_body_is_ignored(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.put(
            f"/api/guests/{gid}",
            json={"guest_id": 9999, "name": "Ignored ID"},
        )
        assert resp.status_code == 200
        assert _json(resp)["data"]["guest_id"] == gid  # unchanged

    def test_receptionist_can_update(self, as_receptionist, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_receptionist.put(f"/api/guests/{gid}", json={"name": "Recept Updated"})
        assert resp.status_code == 200

    def test_receptionist_cannot_delete(self, as_receptionist, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_receptionist.delete(f"/api/guests/{gid}")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# 10. TestGuestDelete
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestDelete:
    def test_requires_auth(self, fresh_client):
        resp = fresh_client.delete("/api/guests/1")
        assert resp.status_code == 401

    def test_receptionist_cannot_delete(self, as_receptionist, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_receptionist.delete(f"/api/guests/{gid}")
        assert resp.status_code == 403

    def test_nonexistent_returns_404(self, as_admin, require_db):
        resp = as_admin.delete("/api/guests/9999999")
        assert resp.status_code == 404

    def test_successful_delete_returns_200(self, as_admin, require_db):
        phone = f"+914{_unique()}"
        r = as_admin.post("/api/guests", json={"name": "To Delete", "phone": phone})
        assert r.status_code == 201
        gid = _json(r)["data"]["guest_id"]

        resp = as_admin.delete(f"/api/guests/{gid}")
        assert resp.status_code == 200
        assert _json(resp)["success"] is True

    def test_deleted_guest_returns_404_on_get(self, as_admin, require_db):
        phone = f"+915{_unique()}"
        r = as_admin.post("/api/guests", json={"name": "Gone", "phone": phone})
        assert r.status_code == 201
        gid = _json(r)["data"]["guest_id"]

        as_admin.delete(f"/api/guests/{gid}")
        assert as_admin.get(f"/api/guests/{gid}").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 11. TestGuestUnauthorized
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestUnauthorized:
    def test_list_unauthenticated_401(self, fresh_client):
        assert fresh_client.get("/api/guests").status_code == 401

    def test_get_unauthenticated_401(self, fresh_client):
        assert fresh_client.get("/api/guests/1").status_code == 401

    def test_post_unauthenticated_401(self, fresh_client):
        assert fresh_client.post("/api/guests", json={}).status_code == 401

    def test_put_unauthenticated_401(self, fresh_client):
        assert fresh_client.put("/api/guests/1", json={}).status_code == 401

    def test_delete_unauthenticated_401(self, fresh_client):
        assert fresh_client.delete("/api/guests/1").status_code == 401

    def test_401_response_has_envelope(self, fresh_client):
        body = _json(fresh_client.get("/api/guests"))
        assert body["success"] is False
        assert "error" in body


# ═══════════════════════════════════════════════════════════════════════════════
# 12. TestGuestIdProof
# ═══════════════════════════════════════════════════════════════════════════════

class TestGuestIdProof:
    def test_create_with_both_proof_fields(self, app, as_admin, require_db):
        phone = f"+916{_unique()}"
        resp = as_admin.post(
            "/api/guests",
            json={
                "name": "Proof Guest", "phone": phone,
                "id_proof_type": "Passport", "id_proof_no": f"PP{_unique()}",
            },
        )
        assert resp.status_code == 201
        body = _json(resp)
        assert body["data"]["id_proof_type"] == "Passport"
        assert body["data"]["id_proof_no"] is not None
        _cleanup_guest(app, body["data"]["guest_id"])

    def test_create_with_only_proof_type_rejected(self, as_admin, require_db):
        phone = f"+917{_unique()}"
        resp = as_admin.post(
            "/api/guests",
            json={"name": "Half Proof", "phone": phone, "id_proof_type": "Passport"},
        )
        assert resp.status_code == 400
        assert "id_proof" in _json(resp)["error"]["message"].lower()

    def test_create_with_only_proof_no_rejected(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests",
            json={"name": "Half Proof 2", "phone": f"+918{_unique()}", "id_proof_no": "12345"},
        )
        assert resp.status_code == 400

    def test_proof_type_too_long_returns_400(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests",
            json={
                "name": "Long Proof", "phone": f"+919{_unique()}",
                "id_proof_type": "X" * 31, "id_proof_no": "ABC123",
            },
        )
        assert resp.status_code == 400

    def test_proof_no_too_long_returns_400(self, as_admin, require_db):
        resp = as_admin.post(
            "/api/guests",
            json={
                "name": "Long Proof No", "phone": f"+920{_unique()}",
                "id_proof_type": "Passport", "id_proof_no": "Y" * 41,
            },
        )
        assert resp.status_code == 400

    def test_clear_proof_fields_with_nulls(self, as_admin, transient_guest, require_db):
        gid = transient_guest["guest_id"]
        resp = as_admin.put(
            f"/api/guests/{gid}",
            json={"id_proof_type": None, "id_proof_no": None},
        )
        assert resp.status_code == 200
        body = _json(resp)
        assert body["data"]["id_proof_type"] is None
        assert body["data"]["id_proof_no"] is None
