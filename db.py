"""
Hommy Cottage - Database Connection & Raw SQL Execution Layer
=============================================================
Uses PyMySQL with parameterized SQL (%s placeholders) to prevent SQL Injection.
No ORM is used, strictly adhering to the DBMS project specifications.

Provides:
- get_conn(): Retrieves or creates a raw MySQL database connection.
- fetch_all(sql, params): Executes query and returns all records as dicts.
- fetch_one(sql, params): Executes query and returns single record or None.
- execute(sql, params): Executes INSERT/UPDATE/DELETE query and commits.
- transaction(): Context manager providing ACID-compliant transaction rollback/commit.
"""
from contextlib import contextmanager
import pymysql
import pymysql.cursors
from flask import g, current_app
from config import Config


def resolve_db_host(host):
    """
    Resolves hostname to IP address. If local system DNS encounters resolution
    issues (e.g. ISP DNS caching delay), falls back to resolving via public DNS (8.8.8.8).
    """
    import socket
    try:
        socket.gethostbyname(host)
        return host
    except socket.gaierror:
        import subprocess
        try:
            res = subprocess.run(
                ["nslookup", host, "8.8.8.8"],
                capture_output=True, text=True, timeout=4
            )
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("Address:") and not line.endswith("8.8.8.8"):
                    ip = line.split(":")[-1].strip()
                    if ip:
                        return ip
        except Exception:
            pass
        return host


def get_ssl_kwargs():
    """
    Builds SSL connection kwargs for PyMySQL.
    Automatically enables TLS if connecting to remote cloud databases (Aiven, TiDB)
    or if DB_SSL is set.
    """
    ssl_setting = str(Config.DB_SSL).lower()
    is_remote = any(x in Config.DB_HOST.lower() for x in ("aivencloud", "tidb", "aws", "cloud")) or Config.DB_PORT not in (3306, 0)
    if ssl_setting in ("true", "1", "yes", "required") or (ssl_setting == "auto" and is_remote):
        import ssl
        import os
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if Config.DB_SSL_CA and os.path.exists(Config.DB_SSL_CA):
            ctx.load_verify_locations(cafile=Config.DB_SSL_CA)
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.check_hostname = True
        return {"ssl": ctx}
    return {}


def get_active_db_name():
    """
    Retrieves active database name from Flask current_app config if inside an application context;
    otherwise falls back to Config.DB_NAME.
    """
    try:
        from flask import current_app, has_app_context
        if has_app_context() and current_app and current_app.config.get("DB_NAME"):
            return current_app.config["DB_NAME"]
    except Exception:
        pass
    return Config.DB_NAME


def get_conn(use_database=True):
    """
    Retrieves or establishes a database connection.
    Reuses Flask request context (g._database) if inside a web request;
    otherwise creates and returns a standalone connection.
    """
    resolved_host = resolve_db_host(Config.DB_HOST)
    active_db = get_active_db_name() if use_database else None
    try:
        from flask import has_request_context
        if has_request_context():
            if "_database" not in g:
                conn_kwargs = {
                    "host": resolved_host,
                    "port": Config.DB_PORT,
                    "user": Config.DB_USER,
                    "password": Config.DB_PASSWORD,
                    "database": active_db,
                    "cursorclass": pymysql.cursors.DictCursor,
                    "autocommit": False,
                    "charset": "utf8mb4"
                }
                conn_kwargs.update(get_ssl_kwargs())
                g._database = pymysql.connect(**conn_kwargs)
            return g._database
    except (ImportError, RuntimeError):
        pass

    # Standalone connection (CLI/scripts/background tasks)
    conn_kwargs = {
        "host": resolved_host,
        "port": Config.DB_PORT,
        "user": Config.DB_USER,
        "password": Config.DB_PASSWORD,
        "database": active_db,
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "charset": "utf8mb4"
    }
    conn_kwargs.update(get_ssl_kwargs())
    return pymysql.connect(**conn_kwargs)


# Backward-compatibility alias
get_db_connection = get_conn
get_db = get_conn


def close_db(e=None):
    """Flask teardown hook to automatically close the request database connection."""
    try:
        db = g.pop("_database", None)
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
    except (AttributeError, RuntimeError):
        pass


@contextmanager
def transaction():
    """
    Context manager for atomic database transactions.
    Yields the active connection. Automatically commits upon successful
    completion of the block, or rolls back and re-raises on any exception.

    Example:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ...", (...))
                cur.execute("UPDATE ...", (...))
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def fetch_all(sql, params=None):
    """
    Executes a SELECT query with parameterized values and returns ALL matching rows as a list of dicts.
    Parameters are bound safely via PyMySQL to prevent SQL injection.
    """
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute(sql, params or ())
        return cursor.fetchall()


def fetch_one(sql, params=None):
    """
    Executes a SELECT query with parameterized values and returns ONE matching row as a dict, or None.
    """
    conn = get_conn()
    with conn.cursor() as cursor:
        cursor.execute(sql, params or ())
        return cursor.fetchone()


def execute(sql, params=None):
    """
    Executes an INSERT, UPDATE, or DELETE query with parameterized values, commits the transaction,
    and returns:
    - cursor.lastrowid if the query is an INSERT
    - cursor.rowcount otherwise
    Rolls back automatically if an error occurs.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            affected = cursor.execute(sql, params or ())
            is_insert = sql.strip().upper().startswith("INSERT")
            res = cursor.lastrowid if is_insert else affected
        conn.commit()
        return res
    except Exception as exc:
        conn.rollback()
        raise exc


# Backward compatibility aliases for existing blueprints and tests
query_all = fetch_all
query_one = fetch_one
execute_insert = execute
execute_modify = execute


def init_app_db(app):
    """Registers database teardown hook with the Flask application instance."""
    app.teardown_appcontext(close_db)
