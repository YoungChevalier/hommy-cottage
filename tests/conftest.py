"""
tests/conftest.py
─────────────────
Pytest fixtures shared across the test suite.

The testing config points at the real hotel_db but uses a tiny pool
(size=2) and never runs schema.sql — the DB must already be set up.

If DB credentials are not available (e.g. in CI without MySQL), tests
that require a live DB are automatically skipped via the `require_db`
fixture.

CSRF notes
──────────
WTF_CSRF_ENABLED is False in TestingConfig so the test suite can
exercise endpoints normally.  Tests that specifically verify CSRF
rejection temporarily enable it with:

    app.config["WTF_CSRF_ENABLED"] = True
    csrf.init_app(app)
"""

from __future__ import annotations

import os
import pytest
from dotenv import load_dotenv

# Load .env so that DB credentials are available in tests.
# This is a no-op if variables are already set in the environment (CI).
load_dotenv(override=False)


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """
    Create a Flask application instance configured for testing.
    Scope=session means a single app is shared for the entire test run.
    CSRF is disabled in TestingConfig so normal tests run without tokens.
    """
    from app import create_app
    application = create_app("testing")
    application.config.update({"TESTING": True})
    yield application


@pytest.fixture(scope="session")
def client(app):
    """Test client for the session-scoped app."""
    return app.test_client()


# ── Per-function isolated client (for auth tests that mutate session) ─────────

@pytest.fixture()
def fresh_client(app):
    """
    A test client with a clean session for each test function.
    Use this instead of `client` for auth tests that login/logout.
    """
    with app.test_client() as c:
        yield c


# ── CSRF fixture ──────────────────────────────────────────────────────────────

@pytest.fixture()
def csrf_client(app):
    """
    A test client with CSRF protection enabled.
    Used exclusively in CSRF rejection tests.
    Restores original setting after the test.
    """
    original = app.config.get("WTF_CSRF_ENABLED", False)
    app.config["WTF_CSRF_ENABLED"] = True
    with app.test_client() as c:
        # Get a CSRF token from the token endpoint
        resp = c.get("/api/auth/csrf-token")
        token = resp.get_json()["data"]["csrf_token"]
        yield c, token
    app.config["WTF_CSRF_ENABLED"] = original


# ── DB availability fixture ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def db_available(app) -> bool:
    """
    Returns True if the database is reachable.
    Used by tests that need a live DB to skip gracefully when MySQL is absent.
    """
    from app.db import ping_db
    with app.app_context():
        result = ping_db()
    return result["status"] == "ok"


@pytest.fixture(scope="session")
def require_db(db_available):
    """
    Skip the test if the database is not reachable.
    Use as a fixture parameter in any test that needs a live connection:

        def test_something(fresh_client, require_db):
            ...
    """
    if not db_available:
        pytest.skip("MySQL not reachable — skipping DB-dependent test.")


# ── Admin account fixture ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_admin_credentials(app, require_db):
    """
    Creates a temporary Admin account for the test session.
    Cleans it up (deletes) after all tests complete.
    Returns {"username": ..., "password": ...}.
    """
    from app.services.auth_service import create_user
    from app.db import db_cursor

    username = "_pytest_admin_"
    password = "TestAdmin#9001"

    with app.app_context():
        # Clean up any leftover from a previous failed run
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))

        user, err = create_user(username, password, "Admin")
        assert err is None, f"Failed to create test admin: {err}"

    yield {"username": username, "password": password, "user_id": user["user_id"]}

    with app.app_context():
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute("DELETE FROM app_user WHERE username = %s", (username,))
