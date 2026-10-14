"""
Hommy Cottage - Authentication & Password Security Tests
Tests Werkzeug hashing, session helpers, role-based access utilities,
date parsing, file validation, transaction context manager, and auth routes.
"""
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash
from auth_utils import login_user, logout_user, parse_date, allowed_file, role_required


def test_werkzeug_password_hashing():
    """Verify password hashing generates strong one-way hashes and validates correctly."""
    raw_password = "SecretPassword123"
    hashed = generate_password_hash(raw_password)

    assert hashed != raw_password
    assert check_password_hash(hashed, raw_password) is True
    assert check_password_hash(hashed, "WrongPassword") is False


def test_session_login_and_logout(app):
    """Verify login_user and logout_user accurately set and clear session state."""
    with app.test_request_context():
        from flask import session

        dummy_user = {
            "user_id": 42,
            "email": "host@example.com",
            "name": "Test Host",
            "role": "host"
        }

        # Simulate login
        login_user(dummy_user)
        assert session.get("user_id") == 42
        assert session.get("user_role") == "host"
        assert session.get("user_name") == "Test Host"

        # Simulate logout
        logout_user()
        assert session.get("user_id") is None
        assert session.get("user_role") is None
        assert session.get("user_name") is None


def test_auth_utils_helpers():
    """Verify parse_date and allowed_file utilities."""
    # parse_date tests
    assert parse_date("2026-10-15") == date(2026, 10, 15)
    assert parse_date("invalid-date") is None
    assert parse_date("") is None
    assert parse_date(None) is None
    assert parse_date(date(2026, 12, 1)) == date(2026, 12, 1)

    # allowed_file tests
    assert allowed_file("cottage.jpg") is True
    assert allowed_file("villa.png") is True
    assert allowed_file("room.webp") is True
    assert allowed_file("document.pdf") is False
    assert allowed_file("script.py") is False
    assert allowed_file("no_extension") is False
    assert allowed_file("") is False


def test_db_transaction_context_manager(app):
    """Verify db.transaction context manager commits and rolls back properly."""
    from db import transaction, fetch_one, execute

    with app.app_context():
        # Clean test key
        test_email = "tx_test_user@example.com"
        execute("DELETE FROM users WHERE email = %s", (test_email,))

        # 1. Successful transaction commits
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (name, email, phone, password_hash, role) VALUES (%s, %s, %s, %s, %s)",
                    ("Tx User", test_email, "+91 9999988888", "hash123", "guest")
                )

        u = fetch_one("SELECT user_id, email FROM users WHERE email = %s", (test_email,))
        assert u is not None
        assert u["email"] == test_email

        # 2. Failed transaction rolls back
        try:
            with transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET name = 'Rollback Name' WHERE email = %s", (test_email,))
                    raise RuntimeError("Simulated transaction error")
        except RuntimeError:
            pass

        u_after = fetch_one("SELECT name FROM users WHERE email = %s", (test_email,))
        assert u_after["name"] == "Tx User"  # Unchanged due to rollback

        # Cleanup
        execute("DELETE FROM users WHERE email = %s", (test_email,))


def test_register_disallows_admin(client):
    """Verify public registration restricts role to guest or host, never admin."""
    import uuid
    random_email = f"attacker_{uuid.uuid4().hex[:6]}@example.com"

    # Attempt to self-register as admin
    response = client.post("/auth/register", data={
        "full_name": "Wannabe Admin",
        "email": random_email,
        "phone": "+91 9000000000",
        "password": "password123",
        "confirm_password": "password123",
        "role": "admin"
    }, follow_redirects=True)

    assert response.status_code == 200

    from db import fetch_one, execute
    user = fetch_one("SELECT role FROM users WHERE email = %s", (random_email,))
    assert user is not None
    assert user["role"] == "guest"  # Disallowed admin forced to guest

    # Clean up test user
    execute("DELETE FROM users WHERE email = %s", (random_email,))


def test_register_duplicate_email_handling(client):
    """Verify duplicate email registration is caught via MySQL UNIQUE constraint."""
    # admin@hommycottage.com already exists in seed data
    response = client.post("/auth/register", data={
        "full_name": "Imposter Admin",
        "email": "admin@hommycottage.com",
        "phone": "+91 9111111111",
        "password": "password123",
        "confirm_password": "password123",
        "role": "guest"
    })

    assert response.status_code == 200
    assert b"An account with this email address already exists" in response.data


def test_login_session_fixation_and_role_redirects(client):
    """Verify session.clear() on login and role-based redirects."""
    # 1. Admin login redirects to admin dashboard
    with client.session_transaction() as sess:
        sess["old_secret"] = "fixation_token_123"

    response = client.post("/auth/login", data={
        "email": "admin@hommycottage.com",
        "password": "password123"
    }, follow_redirects=False)

    assert response.status_code == 302
    assert "/admin" in response.headers["Location"]

    with client.session_transaction() as sess:
        assert "old_secret" not in sess  # Cleared by session fixation protection
        assert sess.get("user_role") == "admin"

    # Logout
    client.get("/auth/logout")

    # 2. Host login redirects to host dashboard
    response = client.post("/auth/login", data={
        "email": "host@hommycottage.com",
        "password": "password123"
    }, follow_redirects=False)

    assert response.status_code == 302
    assert "/host" in response.headers["Location"]

    with client.session_transaction() as sess:
        assert sess.get("user_role") == "host"

    # Logout
    client.get("/auth/logout")

    # 3. Guest login redirects to homepage/search
    response = client.post("/auth/login", data={
        "email": "guest@hommycottage.com",
        "password": "password123"
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] in ("/", "http://localhost/")
