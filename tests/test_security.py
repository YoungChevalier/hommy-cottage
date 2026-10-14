"""
Hommy Cottage - Database Security & RBAC Verification Tests
Validates sql/06_security.sql:
1. Role creation (role_guest, role_host, role_admin)
2. Least privilege grants on views, tables, and stored routines
3. Service account 'hommy_app'@'localhost' creation and default role assignment
4. Security guidance comments for Flask application integration
"""
from pathlib import Path


def test_security_file_structure():
    """Verify sql/06_security.sql contains required roles, permissions, user creation, and docs."""
    sec_path = Path("sql/06_security.sql")
    assert sec_path.exists(), "sql/06_security.sql must exist"
    content = sec_path.read_text(encoding="utf-8")

    # 1. Role definitions
    assert "CREATE ROLE IF NOT EXISTS 'role_guest'" in content, "role_guest creation missing"
    assert "CREATE ROLE IF NOT EXISTS 'role_host'" in content, "role_host creation missing"
    assert "CREATE ROLE IF NOT EXISTS 'role_admin'" in content, "role_admin creation missing"

    # 2. Permissions for role_guest
    assert "GRANT SELECT ON hommy_cottage.property_search_view TO 'role_guest'" in content
    assert "GRANT SELECT ON hommy_cottage.property_rating_view TO 'role_guest'" in content
    assert "GRANT EXECUTE ON PROCEDURE hommy_cottage.sp_book_room TO 'role_guest'" in content
    assert "GRANT EXECUTE ON PROCEDURE hommy_cottage.sp_cancel_booking TO 'role_guest'" in content
    assert "GRANT EXECUTE ON FUNCTION hommy_cottage.fn_available_rooms TO 'role_guest'" in content

    # 3. Permissions for role_host
    assert "GRANT INSERT, UPDATE ON hommy_cottage.properties TO 'role_host'" in content
    assert "GRANT INSERT, UPDATE, DELETE ON hommy_cottage.room_types TO 'role_host'" in content
    assert "GRANT INSERT, UPDATE, DELETE ON hommy_cottage.rooms TO 'role_host'" in content
    assert "GRANT SELECT ON hommy_cottage.host_revenue_view TO 'role_host'" in content

    # 4. Permissions for role_admin
    assert "GRANT ALL PRIVILEGES ON hommy_cottage.* TO 'role_admin'" in content

    # 5. Service account creation and role assignment
    assert "CREATE USER IF NOT EXISTS 'hommy_app'@'localhost'" in content
    assert "__APP_PASSWORD__" in content, "Placeholder __APP_PASSWORD__ must be present"
    assert "GRANT 'role_guest', 'role_host', 'role_admin' TO 'hommy_app'@'localhost'" in content
    assert "SET DEFAULT ROLE ALL TO 'hommy_app'@'localhost'" in content
    assert "FLUSH PRIVILEGES" in content

    # 6. Documentation / Architecture comments
    assert "Principle of Least Privilege" in content
    assert "root" in content
    assert "Flask" in content
    assert "DB_USER=hommy_app" in content


def test_security_parsed_by_sql_runner():
    """Verify sql/06_security.sql parses cleanly into individual statements."""
    from init_db import SQL_DIR

    sec_file = SQL_DIR / "06_security.sql"
    with open(sec_file, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines()
    delimiter = ";"
    buffer = []
    statements = []

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER"):
            parts = stripped.split()
            if len(parts) >= 2:
                delimiter = parts[1]
            continue
        if stripped.startswith("--") or stripped.startswith("#"):
            continue

        buffer.append(line)
        current_text = "\n".join(buffer).strip()

        if current_text.endswith(delimiter):
            stmt = current_text[:-len(delimiter)].strip()
            buffer = []
            if stmt:
                statements.append(stmt)

    assert len(statements) >= 15, f"Expected at least 15 security statements, found {len(statements)}"
