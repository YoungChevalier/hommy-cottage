"""
app/config.py
─────────────
Loads all application configuration from environment variables.
Never hardcode credentials here; populate .env from .env.example.
"""

import os
from datetime import timedelta


class Config:
    """Base configuration — values read from environment at import time."""

    # ── Flask ────────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    FLASK_ENV: str = os.environ.get("FLASK_ENV", "production")

    # ── Session / Cookie security ─────────────────────────────────────────────
    # SESSION_COOKIE_HTTPONLY: browser JS cannot read the session cookie.
    SESSION_COOKIE_HTTPONLY: bool = True
    # SESSION_COOKIE_SAMESITE: "Lax" blocks cross-site POST (CSRF protection).
    SESSION_COOKIE_SAMESITE: str = "Lax"
    # SESSION_COOKIE_SECURE: True in production (HTTPS only). Overridden below.
    SESSION_COOKIE_SECURE: bool = True
    # Sessions expire after 8 hours of inactivity.
    PERMANENT_SESSION_LIFETIME: timedelta = timedelta(hours=8)

    # ── CSRF (Flask-WTF) ─────────────────────────────────────────────────────
    WTF_CSRF_ENABLED: bool = True
    WTF_CSRF_TIME_LIMIT: int = 3600   # token valid for 1 hour
    # Allow X-CSRFToken header from SPA / JSON clients
    WTF_CSRF_HEADERS: list = ["X-CSRFToken", "X-CSRF-Token"]

    # ── Database ─────────────────────────────────────────────────────────────
    DB_HOST: str = os.environ.get("DB_HOST", "localhost")
    DB_PORT: int = int(os.environ.get("DB_PORT", "3306"))
    DB_NAME: str = os.environ.get("DB_NAME", "hotel_db")       # matches schema.sql
    DB_USER: str = os.environ.get("DB_USER", "")
    DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")       # never logged / exposed
    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "5"))
    DB_POOL_NAME: str = os.environ.get("DB_POOL_NAME", "hotel_pool")

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    FLASK_ENV = "development"
    LOG_LEVEL = "DEBUG"
    # Allow session cookies over plain HTTP during local development
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    FLASK_ENV = "production"
    LOG_LEVEL = "WARNING"
    SESSION_COOKIE_SECURE = True   # enforce HTTPS in production


class TestingConfig(Config):
    """
    Used by pytest.  Points at the same hotel_db schema but lets you
    override credentials via environment if a separate test DB is available.
    Connection pool size is kept small to avoid exhausting the test server.
    """
    TESTING: bool = True
    DB_POOL_SIZE: int = 2
    DB_POOL_NAME: str = "hotel_test_pool"
    LOG_LEVEL: str = "WARNING"
    # Disable secure cookie so tests work over plain HTTP test client
    SESSION_COOKIE_SECURE = False
    # Disable CSRF in tests — tests that explicitly test CSRF will
    # temporarily re-enable it via app.config update.
    WTF_CSRF_ENABLED = False


# ── Config selector ──────────────────────────────────────────────────────────
_config_map: dict[str, type[Config]] = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config() -> Config:
    """Return the correct Config class based on FLASK_ENV."""
    env = os.environ.get("FLASK_ENV", "production").lower()
    return _config_map.get(env, ProductionConfig)()
