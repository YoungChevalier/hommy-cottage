"""
app/__init__.py
───────────────
Flask application factory.

Usage:
    from app import create_app
    app = create_app()          # uses FLASK_ENV from environment
    app = create_app("testing") # for pytest

The factory:
  1. Loads environment variables from .env (via python-dotenv, called in run.py).
  2. Selects the correct Config class.
  3. Configures structured logging.
  4. Initialises the MySQL connection pool.
  5. Initialises Flask extensions (CSRFProtect, Limiter).
  6. Registers all blueprints.
  7. Registers CLI commands.
  8. Registers global error handlers.

IMPORTANT: The database schema is NEVER created or modified here.
           Assume hotel_db already exists and was loaded via schema.sql.
"""

from __future__ import annotations

import logging
import logging.config
import sys

from flask import Flask, jsonify

from app.config import Config, TestingConfig, DevelopmentConfig, ProductionConfig


def _configure_logging(log_level: str) -> None:
    """Set up structured console logging for the application."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                }
            },
            "root": {
                "level": log_level,
                "handlers": ["console"],
            },
        }
    )


def create_app(env: str | None = None) -> Flask:
    """
    Flask application factory.

    Args:
        env: Override the config environment ("development", "production",
             "testing"). If None, FLASK_ENV from the environment is used.

    Returns:
        A fully configured Flask application instance.
    """
    app = Flask(__name__, instance_relative_config=False)

    # ── 1. Select and load configuration ─────────────────────────────────────
    config_map: dict[str, type[Config]] = {
        "development": DevelopmentConfig,
        "production":  ProductionConfig,
        "testing":     TestingConfig,
    }

    import os
    chosen_env = (env or os.environ.get("FLASK_ENV", "production")).lower()
    cfg = config_map.get(chosen_env, ProductionConfig)()
    app.config.from_object(cfg)

    # ── 2. Logging ────────────────────────────────────────────────────────────
    _configure_logging(app.config.get("LOG_LEVEL", "INFO"))
    logger = logging.getLogger(__name__)
    logger.info("Starting Hotel Management System [env=%s]", chosen_env)

    # ── 3. Database pool ──────────────────────────────────────────────────────
    # Pool initialisation is deferred so the app can still start (for import
    # checks) even if the DB is temporarily unavailable.  The /api/health/db
    # endpoint will report the failure gracefully.
    from app.db import init_pool
    try:
        init_pool(app)
    except Exception as exc:  # noqa: BLE001
        # Log the error type but NOT the message (may contain credentials).
        logger.error(
            "MySQL pool could not be created (%s). "
            "Check DB_HOST, DB_USER, DB_PASSWORD, DB_NAME in .env. "
            "GET /api/health/db will report status.",
            type(exc).__name__,
        )

    # ── 4. Extensions (CSRF, Rate-limiter) ───────────────────────────────────
    from app.extensions import csrf, limiter
    csrf.init_app(app)
    limiter.init_app(app)

    # ── 5. Register blueprints ────────────────────────────────────────────────
    _register_blueprints(app)

    # ── 6. Register CLI commands ──────────────────────────────────────────────
    from app.commands import register_commands
    register_commands(app)

    # ── 7. Register global error handlers ────────────────────────────────────
    _register_error_handlers(app)

    logger.info("Application factory complete.")
    return app


# ── Blueprint registration ────────────────────────────────────────────────────

def _register_blueprints(app: Flask) -> None:
    from app.routes.health import health_bp
    from app.routes.auth import auth_bp
    from app.routes.guests import guests_bp
    from app.routes.rooms import rooms_bp, room_types_bp
    from app.routes.reservations import reservations_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(guests_bp)
    app.register_blueprint(rooms_bp)
    app.register_blueprint(room_types_bp)
    app.register_blueprint(reservations_bp)

    # Future blueprints will be registered here in later phases:
    # … etc.


# ── Global error handlers ─────────────────────────────────────────────────────

def _register_error_handlers(app: Flask) -> None:
    """
    Convert common HTTP and MySQL errors into the standard JSON envelope.
    Stack traces are NEVER included in responses.
    """
    import mysql.connector
    from flask_wtf.csrf import CSRFError

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "BAD_REQUEST", "message": str(e.description)}}), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "UNAUTHORIZED", "message": "Authentication required."}}), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "FORBIDDEN", "message": "You do not have permission."}}), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "NOT_FOUND", "message": "The requested resource was not found."}}), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "METHOD_NOT_ALLOWED", "message": "Method not allowed."}}), 405

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "RATE_LIMITED",
                                  "message": "Too many requests. Please slow down."}}), 429

    @app.errorhandler(500)
    def internal_error(e):
        logging.getLogger(__name__).exception("Unhandled 500 error.")
        return jsonify({"success": False, "data": None,
                        "error": {"code": "INTERNAL_ERROR",
                                  "message": "An internal error occurred."}}), 500

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return jsonify({"success": False, "data": None,
                        "error": {"code": "CSRF_ERROR",
                                  "message": "CSRF token missing or invalid."}}), 400

    @app.errorhandler(mysql.connector.Error)
    def mysql_error(e):
        logging.getLogger(__name__).error("Unhandled MySQL error: %s", type(e).__name__)
        return jsonify({"success": False, "data": None,
                        "error": {"code": "DB_ERROR",
                                  "message": "A database error occurred."}}), 500
