"""
app/db.py
─────────
MySQL connection pool.

Usage inside a route or service:
    from app.db import get_db, release_db

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT 1")
        row = cur.fetchone()
    finally:
        cur.close()
        release_db(conn)

Or use the safe context manager:
    from app.db import db_cursor

    with db_cursor(dictionary=True) as cur:
        cur.execute("SELECT 1")
        row = cur.fetchone()

Safety rules
────────────
* autocommit is ALWAYS False — callers must commit() / rollback() explicitly.
* Passwords are never logged; the pool config is sanitised before logging.
* Schema is NEVER created or reset here; assume hotel_db already exists.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import mysql.connector
from mysql.connector import pooling, errors
from flask import current_app

logger = logging.getLogger(__name__)

# Module-level pool — created once in init_pool(), used for the app lifetime.
_pool: pooling.MySQLConnectionPool | None = None


# ── Pool lifecycle ────────────────────────────────────────────────────────────

def init_pool(app) -> None:
    """
    Create the MySQLConnectionPool from Flask app config.
    Call this exactly once inside the application factory (app/__init__.py).

    Raises mysql.connector.Error if the pool cannot be created (e.g. bad
    credentials).  The caller is responsible for handling the error.
    """
    global _pool

    if _pool is not None:
        logger.warning("init_pool() called more than once — ignoring.")
        return

    pool_config = {
        "pool_name":          app.config["DB_POOL_NAME"],
        "pool_size":          app.config["DB_POOL_SIZE"],
        "host":               app.config["DB_HOST"],
        "port":               app.config["DB_PORT"],
        "database":           app.config["DB_NAME"],
        "user":               app.config["DB_USER"],
        "password":           app.config["DB_PASSWORD"],   # never logged below
        "autocommit":         False,
        "charset":            "utf8mb4",
        "collation":          "utf8mb4_unicode_ci",
        "connection_timeout": 10,
        "use_unicode":        True,
    }

    # Log config WITHOUT the password.
    safe_log = {k: v for k, v in pool_config.items() if k != "password"}
    logger.info("Creating MySQL connection pool: %s", safe_log)

    _pool = pooling.MySQLConnectionPool(**pool_config)
    logger.info(
        "MySQL pool '%s' ready (size=%d, db=%s).",
        app.config["DB_POOL_NAME"],
        app.config["DB_POOL_SIZE"],
        app.config["DB_NAME"],
    )


def _get_pool() -> pooling.MySQLConnectionPool:
    """Return the pool, raising RuntimeError if init_pool() was not called."""
    if _pool is None:
        raise RuntimeError(
            "Database pool has not been initialised. "
            "Call init_pool(app) inside the application factory."
        )
    return _pool


# ── Connection helpers ────────────────────────────────────────────────────────

def get_db() -> pooling.PooledMySQLConnection:
    """
    Acquire a connection from the pool.
    The caller MUST call release_db(conn) in a finally block, or use db_cursor().
    """
    return _get_pool().get_connection()


def release_db(conn: pooling.PooledMySQLConnection) -> None:
    """
    Return a connection to the pool.
    Also rolls back any uncommitted transaction to avoid leaving dirty state.
    Safe to call even if conn is None.
    """
    if conn is None:
        return
    try:
        if conn.is_connected():
            conn.rollback()   # safety net — explicit commits should already be done
            conn.close()      # returns to pool, not truly closed
    except errors.Error as exc:
        logger.warning("Error releasing DB connection: %s", exc)


# ── Safe context manager ──────────────────────────────────────────────────────

@contextmanager
def db_cursor(
    dictionary: bool = True,
    commit_on_exit: bool = False,
) -> Generator[mysql.connector.cursor.MySQLCursor, None, None]:
    """
    Context manager that acquires a connection + cursor and guarantees cleanup.

    Args:
        dictionary: If True, rows are returned as dicts (recommended).
        commit_on_exit: If True, commits the transaction on clean exit.
                        Always rolls back on exception.

    Example:
        with db_cursor() as cur:
            cur.execute("SELECT 1 AS ping")
            row = cur.fetchone()   # {"ping": 1}

    Raises:
        mysql.connector.Error: propagated after rollback + cleanup.
    """
    conn = None
    cur = None
    try:
        conn = get_db()
        cur = conn.cursor(dictionary=dictionary)
        yield cur
        if commit_on_exit:
            conn.commit()
    except errors.Error:
        if conn and conn.is_connected():
            conn.rollback()
        raise
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        release_db(conn)


# ── Connectivity probe ────────────────────────────────────────────────────────

def ping_db() -> dict:
    """
    Execute a lightweight SELECT to verify database reachability.

    Returns:
        {"status": "ok", "db": "<db_name>", "server_version": "8.x.x"}
        {"status": "error", "message": "<safe message>"}   ← no stack trace
    """
    try:
        with db_cursor(dictionary=True) as cur:
            cur.execute("SELECT VERSION() AS ver, DATABASE() AS db_name")
            row = cur.fetchone()
            return {
                "status":         "ok",
                "db":             row["db_name"],
                "server_version": row["ver"],
            }
    except RuntimeError as exc:
        # Pool not initialised — safe to surface
        logger.error("DB ping failed (pool not ready): %s", exc)
        return {"status": "error", "message": str(exc)}
    except errors.Error as exc:
        # DB-level error — log full detail, return sanitised message
        logger.error("DB ping failed: %s", exc)
        return {"status": "error", "message": "Database connection failed."}
