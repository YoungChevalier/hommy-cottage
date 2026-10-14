"""
Hommy Cottage - Database Initialization Script (MySQL CLI Subprocess Runner)
=============================================================================
Builds the relational database from SQL scripts in strict order 01 to 06
using the official 'mysql' CLI client via subprocess. Piped execution natively
supports MySQL DELIMITER $$ blocks without splitting SQL strings in Python.

Files Executed in Order:
    1. sql/01_schema.sql      (3NF/BCNF Table Definitions & Constraints)
    2. sql/02_seed.sql        (Realistic Indian Seed Data & Password Hashes)
    3. sql/03_views.sql       (Search, Analytics & Dashboard Views)
    4. sql/04_triggers.sql    (Integrity, Turnover & Refund Triggers with DELIMITER $$)
    5. sql/05_procedures.sql  (Transactional Booking & Availability Routines)
    6. sql/06_security.sql    (RBAC, Least-Privilege Grants & Service Account)

Usage:
    python init_db.py                  # Drop & rebuild database (prompts for confirmation)
    python init_db.py --no-drop        # Build/update without dropping existing database
    python init_db.py -y               # Non-interactive mode (skips confirmation prompt)
    python init_db.py --continue-on-error  # Tolerates non-standard engine limitations
"""
import sys
import os
import shutil
import subprocess
import argparse
from pathlib import Path
from werkzeug.security import generate_password_hash
from config import Config

BASE_DIR = Path(__file__).resolve().parent
SQL_DIR = BASE_DIR / "sql"

# Strict sequence of execution
SQL_FILES = [
    "01_schema.sql",
    "02_seed.sql",
    "03_views.sql",
    "04_triggers.sql",
    "05_procedures.sql",
    "06_security.sql"
]


def get_mysql_cmd():
    """
    Locates the MySQL client CLI binary and constructs the base connection command.
    """
    mysql_bin = shutil.which("mysql")
    if not mysql_bin:
        print("\n[!] FATAL ERROR: 'mysql' CLI executable not found on system PATH.")
        print("    Please ensure MySQL Server or MySQL Client tools are installed and in PATH.")
        sys.exit(1)

    cmd = [
        mysql_bin,
        f"--host={Config.DB_HOST}",
        f"--port={Config.DB_PORT}",
        f"--user={Config.DB_USER}",
        "--default-character-set=utf8mb4"
    ]
    if Config.DB_SSL:
        cmd.append("--ssl-mode=REQUIRED")

    return cmd


def get_mysql_env():
    """
    Configures environment variables for MySQL subprocess execution.
    Injects MYSQL_PWD to prevent CLI plain-text password warnings.
    """
    env = os.environ.copy()
    if Config.DB_PASSWORD:
        env["MYSQL_PWD"] = str(Config.DB_PASSWORD)
    return env


def prepare_sql_content(file_name: str, raw_content: str, no_drop: bool, db_name: str = None) -> str:
    """
    Applies in-memory parameter substitutions to SQL file contents before execution.
    Keeps on-disk repository files clean and free of committed secrets.
    Supports targeting alternate databases (e.g. hommy_cottage_test).
    """
    content = raw_content
    target_db = db_name or Config.DB_NAME

    # 1. 01_schema.sql: Honor --no-drop flag
    if file_name == "01_schema.sql" and no_drop:
        content = content.replace("DROP DATABASE IF EXISTS hommy_cottage;", f"-- DROP DATABASE IF EXISTS {target_db};")
        content = content.replace("CREATE DATABASE hommy_cottage", f"CREATE DATABASE IF NOT EXISTS {target_db}")
        # In --no-drop mode, cleanly reset existing tables within the database without dropping the database itself
        table_cleanup = (
            f"USE {target_db};\n"
            "SET FOREIGN_KEY_CHECKS = 0;\n"
            "DROP TABLE IF EXISTS reviews, payments, bookings, property_images, "
            "property_amenities, amenities, rooms, room_types, properties, "
            "property_types, cities, users;\n"
            "SET FOREIGN_KEY_CHECKS = 1;\n"
        )
        content = content.replace("USE hommy_cottage;", table_cleanup, 1)

    # Substitute default database name with target_db if different
    if target_db != "hommy_cottage":
        content = content.replace("hommy_cottage", target_db)

    # 2. 02_seed.sql: Replace '__HASH__' with a real Werkzeug password hash of 'password123'
    if file_name == "02_seed.sql" and "__HASH__" in content:
        real_hash = generate_password_hash("password123")
        content = content.replace("__HASH__", real_hash)

    # 3. 06_security.sql: Replace '__APP_PASSWORD__' from the environment
    if file_name == "06_security.sql" and "__APP_PASSWORD__" in content:
        app_password = os.environ.get("APP_DB_PASSWORD") or os.environ.get("DB_PASSWORD", "HommyAppSecurePass2026!")
        content = content.replace("__APP_PASSWORD__", app_password)

    return content


def print_demo_logins(db_name: str = None):
    """
    Prints demo credentials for all user roles upon successful database construction.
    """
    target_db = db_name or Config.DB_NAME
    print("\n" + "=" * 70)
    print(" [SUCCESS] Hommy Cottage Database Built Successfully!")
    print("=" * 70)
    print("\nDemo User Credentials (Universal Password: 'password123'):")
    print("-" * 70)
    print(" [1] Administrator Account:")
    print("     Name:     System Administrator")
    print("     Email:    admin@hommycottage.com")
    print("     Role:     admin")
    print("     Access:   Platform analytics, cottage approval, city management")
    print()
    print(" [2] Host Account:")
    print("     Name:     Rahul Sharma")
    print("     Email:    host@hommycottage.com")
    print("     Role:     host")
    print("     Access:   Property listings, room inventory, booking calendar")
    print()
    print(" [3] Guest Account:")
    print("     Name:     Aarav Patel")
    print("     Email:    guest@hommycottage.com")
    print("     Role:     guest")
    print("     Access:   Cottage search, room booking, reviews, cancellation")
    print("-" * 70)
    print(f"Database Target: {target_db} at {Config.DB_HOST}:{Config.DB_PORT}")
    print("=" * 70 + "\n")


def build_database(no_drop: bool = False, skip_confirm: bool = False, continue_on_error: bool = False, db_name: str = None):
    """
    Executes database build workflow from sql/01 through sql/06 using mysql CLI.
    Supports targeting alternate databases like hommy_cottage_test.
    """
    target_db = db_name or Config.DB_NAME
    print(f"[*] Target MySQL Server: {Config.DB_HOST}:{Config.DB_PORT}")
    print(f"[*] Target Database:     {target_db}")
    print(f"[*] Database User:       {Config.DB_USER}")

    # Confirm before dropping database unless --no-drop or -y is provided
    if not no_drop and not skip_confirm:
        print("\n" + "!" * 70)
        print(f" WARNING: This operation will DROP and RECREATE database '{target_db}'.")
        print(" All existing tables, data, views, triggers, and routines will be LOST.")
        print("!" * 70)
        try:
            choice = input(f"Are you sure you want to drop and rebuild '{target_db}'? [y/N]: ").strip().lower()
            if choice not in ("y", "yes"):
                print("[*] Database initialization aborted by user.")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Database initialization aborted by user.")
            return False

    mysql_cmd = get_mysql_cmd()
    mysql_env = get_mysql_env()

    print("\n[*] Beginning database build from /sql files in order (01 to 06)...")
    print("-" * 70)

    for fname in SQL_FILES:
        fpath = SQL_DIR / fname
        if not fpath.exists():
            print(f"[ERROR] Required SQL file '{fname}' not found in {SQL_DIR}.")
            sys.exit(1)

        print(f"[*] Executing {fname}...")
        raw_sql = fpath.read_text(encoding="utf-8")
        prepared_sql = prepare_sql_content(fname, raw_sql, no_drop=no_drop, db_name=target_db)

        # Execute via mysql CLI subprocess with raw prepared content piped to stdin
        proc = subprocess.run(
            mysql_cmd,
            input=prepared_sql,
            text=True,
            encoding="utf-8",
            capture_output=True,
            env=mysql_env
        )

        if proc.returncode == 0:
            print(f"    [SUCCESS] {fname} executed successfully.")
        else:
            print(f"\n    [FAILED] MySQL ERROR executing {fname} (Exit Code: {proc.returncode}):")
            err_msg = (proc.stderr or proc.stdout or "").strip()
            for line in err_msg.splitlines():
                print(f"        {line}")

            if not continue_on_error:
                print(f"\n[!] Build ABORTED: Failed at {fname}.")
                print("    Fix the MySQL error above or run with --continue-on-error for engine limitations.")
                sys.exit(proc.returncode)
            else:
                print(f"    [!] --continue-on-error enabled: Proceeding to next file...")

    print("-" * 70)
    print_demo_logins(db_name=target_db)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Hommy Cottage Database Initialization Script (MySQL CLI Subprocess Runner)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Database name to initialize (defaults to DB_NAME from config/env or hommy_cottage)."
    )
    parser.add_argument(
        "--no-drop",
        action="store_true",
        help="Do not drop the database before creating tables/views."
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip the drop-database confirmation prompt."
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue to next file if a non-critical feature fails (e.g. TiDB Serverless trigger support)."
    )

    args = parser.parse_args()
    success = build_database(
        no_drop=args.no_drop,
        skip_confirm=args.yes,
        continue_on_error=args.continue_on_error,
        db_name=args.db
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
