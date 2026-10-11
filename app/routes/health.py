"""
app/routes/health.py
────────────────────
Blueprint: /api/health

Endpoints
─────────
GET /api/health      — Application liveness check (no DB call).
GET /api/health/db   — Database reachability probe.

These endpoints are intentionally lightweight and must never return
stack traces or any sensitive configuration details.
"""

from __future__ import annotations

import logging

from flask import Blueprint

from app.db import ping_db
from app.utils.responses import ok, service_unavailable

logger = logging.getLogger(__name__)

health_bp = Blueprint("health", __name__, url_prefix="/api/health")


@health_bp.get("")
@health_bp.get("/")
def liveness() -> tuple:
    """
    GET /api/health

    Quick liveness check — confirms the Flask process is running.
    Does NOT touch the database.

    Response 200:
        {
            "success": true,
            "data": {"status": "ok", "service": "Hotel Management System"},
            "error": null
        }
    """
    logger.debug("Health liveness check requested.")
    return ok({"status": "ok", "service": "Hotel Management System"})


@health_bp.get("/db")
def db_health() -> tuple:
    """
    GET /api/health/db

    Verifies that the application can acquire a database connection
    and execute a simple query.

    Response 200:
        {
            "success": true,
            "data": {
                "status": "ok",
                "db": "hotel_db",
                "server_version": "8.x.x"
            },
            "error": null
        }

    Response 503:
        {
            "success": false,
            "data": null,
            "error": {"code": "DB_UNAVAILABLE", "message": "Database connection failed."}
        }
    """
    logger.debug("Database health check requested.")
    result = ping_db()

    if result["status"] == "ok":
        return ok(result)

    logger.warning("Database health check failed: %s", result.get("message"))
    return service_unavailable(
        message=result.get("message", "Database connection failed."),
        code="DB_UNAVAILABLE",
    )
