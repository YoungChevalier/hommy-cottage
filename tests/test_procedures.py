"""
Hommy Cottage - Stored Procedures & Functions Verification Tests
Validates sql/05_procedures.sql:
1. sp_book_room (IN p_guest_id, IN p_room_type_id, IN p_check_in, IN p_check_out, IN p_guests, IN p_method, OUT p_booking_id)
2. sp_cancel_booking (IN p_booking_id, IN p_guest_id)
3. fn_available_rooms (IN p_room_type_id, IN p_check_in, IN p_check_out) RETURNS INT
"""
from pathlib import Path


def test_procedures_file_structure():
    """Verify sql/05_procedures.sql exists, uses DELIMITER $$ blocks, and defines all procedures and functions."""
    proc_path = Path("sql/05_procedures.sql")
    assert proc_path.exists(), "sql/05_procedures.sql must exist"
    content = proc_path.read_text(encoding="utf-8")

    # Delimiter blocks
    assert "DELIMITER $$" in content, "DELIMITER $$ block must be defined"
    assert "DELIMITER ;" in content, "DELIMITER ; reset must be present"

    # Routine existence
    assert "CREATE PROCEDURE sp_book_room" in content, "CREATE PROCEDURE sp_book_room missing"
    assert "CREATE PROCEDURE sp_cancel_booking" in content, "CREATE PROCEDURE sp_cancel_booking missing"
    assert "CREATE FUNCTION fn_available_rooms" in content, "CREATE FUNCTION fn_available_rooms missing"

    # Call / invocation comment examples
    assert "CALL sp_book_room" in content, "CALL sp_book_room example comment missing"
    assert "CALL sp_cancel_booking" in content, "CALL sp_cancel_booking example comment missing"
    assert "fn_available_rooms" in content and "SELECT fn_available_rooms" in content, "SELECT fn_available_rooms example comment missing"

    # Transaction, Locking, and Exception handling in sp_book_room
    assert "START TRANSACTION" in content, "START TRANSACTION missing"
    assert "FOR UPDATE" in content, "FOR UPDATE locking missing"
    assert "DECLARE EXIT HANDLER FOR SQLEXCEPTION" in content, "DECLARE EXIT HANDLER FOR SQLEXCEPTION missing"
    assert "ROLLBACK;" in content, "ROLLBACK missing"
    assert "RESIGNAL;" in content, "RESIGNAL missing"
    assert "COMMIT;" in content, "COMMIT missing"
    assert "SIGNAL SQLSTATE '45000'" in content, "SIGNAL SQLSTATE '45000' missing"
    assert "LAST_INSERT_ID()" in content, "LAST_INSERT_ID() missing"

    # Pricing snapshot and payment
    assert "price_per_night_at_booking" in content, "Price copy into price_per_night_at_booking missing"
    assert "INSERT INTO payments" in content, "INSERT INTO payments missing"
    assert "'success'" in content, "Payment status 'success' missing"

    # sp_cancel_booking business checks
    assert "check_in <= CURRENT_DATE()" in content or "check_in > CURRENT_DATE()" in content, "Check-in date validation in sp_cancel_booking missing"
    assert "UPDATE bookings" in content and "SET status = 'cancelled'" in content, "Booking cancellation update missing"

    # fn_available_rooms function specifics
    assert "RETURNS INT" in content, "RETURNS INT missing in fn_available_rooms"
    assert "READS SQL DATA" in content, "READS SQL DATA missing in fn_available_rooms"


def test_procedures_parsed_by_sql_runner():
    """Verify sql/05_procedures.sql parses cleanly into discrete statements via the delimiter parser."""
    from init_db import SQL_DIR

    proc_file = SQL_DIR / "05_procedures.sql"
    with open(proc_file, "r", encoding="utf-8") as f:
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

    assert len(statements) >= 6, f"Expected at least 6 statements, found {len(statements)}"
    creates = [s for s in statements if s.upper().startswith("CREATE ")]
    assert len(creates) == 3, f"Expected 3 CREATE statements, found {len(creates)}"
