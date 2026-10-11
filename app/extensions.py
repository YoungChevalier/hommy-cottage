"""
app/extensions.py
─────────────────
Flask extension singletons shared across the application.

Extensions are initialised here without a Flask app context so they can
be imported anywhere.  The actual ``init_app(app)`` calls happen in the
application factory (app/__init__.py).

Phase 2 extensions:
    csrf    — Flask-WTF CSRFProtect (CSRF protection for state-changing requests)
    limiter — Flask-Limiter      (IP-rate-limiting for login and sensitive endpoints)
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect

# ── CSRF Protection ────────────────────────────────────────────────────────────
# Applied globally. API clients must send X-CSRFToken header (obtained via
# GET /api/auth/csrf-token) on POST / PUT / DELETE / PATCH requests.
csrf = CSRFProtect()

# ── Rate Limiter ───────────────────────────────────────────────────────────────
# Uses the client's IP address as the key.
# Default limits apply to all routes; per-route overrides are set with
# @limiter.limit("N/period") on individual view functions.
# Storage: in-memory (suitable for single-process; swap to Redis for multi-worker).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],                 # no global limit — set per-route only
    storage_uri="memory://",
)
