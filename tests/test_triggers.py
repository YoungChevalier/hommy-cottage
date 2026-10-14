"""
Hommy Cottage - Database Triggers Verification Tests
Validates sql/04_triggers.sql:
1. trg_prevent_overlap (BEFORE INSERT ON bookings)
2. trg_prevent_overlap_update (BEFORE UPDATE ON bookings)
3. trg_review_after_checkout (BEFORE INSERT ON reviews)
4. trg_refund_on_cancel (AFTER UPDATE ON bookings)
5. trg_guest_capacity (BEFORE INSERT ON bookings)
"""
from pathlib import Path


def test_triggers_file_structure():
    """Verify sql/04_triggers.sql exists, uses DELIMITER $$ blocks, and defines all 5 triggers with docs."""
    triggers_path = Path("sql/04_triggers.sql")
    assert triggers_path.exists(), "sql/04_triggers.sql must exist"
    content = triggers_path.read_text(encoding="utf-8")

    # Delimiter blocks
    assert "DELIMITER $$" in content, "DELIMITER $$ block must be defined"
    assert "DELIMITER ;" in content, "DELIMITER ; reset must be present"

    triggers = [
        ("trg_prevent_overlap", "BEFORE INSERT ON bookings"),
        ("trg_prevent_overlap_update", "BEFORE UPDATE ON bookings"),
        ("trg_review_after_checkout", "BEFORE INSERT ON reviews"),
        ("trg_refund_on_cancel", "AFTER UPDATE ON bookings"),
        ("trg_guest_capacity", "BEFORE INSERT ON bookings"),
    ]

    for trg_name, trg_timing in triggers:
        assert f"CREATE TRIGGER {trg_name}" in content, f"CREATE TRIGGER {trg_name} missing"
        assert trg_timing in content, f"Timing/table '{trg_timing}' for {trg_name} missing"
        assert f"Trigger: {trg_name}" in content, f"Header comment for {trg_name} missing"
        assert "Business Rule:" in content, f"Business Rule explanation comment missing for {trg_name}"
        assert "Example Firing:" in content, f"Example Firing comment missing for {trg_name}"

    # Specific business logic checks
    # 1. Overlap condition
    assert "check_in < NEW.check_out" in content, "Overlap condition check_in < NEW.check_out missing"
    assert "check_out > NEW.check_in" in content, "Overlap condition check_out > NEW.check_in missing"
    assert "SIGNAL SQLSTATE '45000'" in content, "SIGNAL SQLSTATE '45000' missing"

    # 2. Update exclusion
    assert "booking_id != NEW.booking_id" in content, "Update trigger must exclude current booking_id"

    # 3. Review after checkout
    assert "CURRENT_DATE()" in content, "Review trigger must check against CURRENT_DATE()"
    assert "v_booking_status = 'cancelled'" in content, "Review trigger must check for cancelled bookings"

    # 4. Refund on cancel
    assert "NEW.status = 'cancelled' AND OLD.status != 'cancelled'" in content, "Refund trigger must detect transition to cancelled"
    assert "UPDATE payments" in content, "Refund trigger must update payments table"
    assert "SET status = 'refunded'" in content, "Refund trigger must set status to refunded"

    # 5. Guest capacity
    assert "NEW.guests > v_capacity" in content, "Capacity trigger must compare NEW.guests against room type capacity"


def test_triggers_parsed_by_sql_runner():
    """Verify sql/04_triggers.sql parses cleanly into discrete statements via the delimiter parser."""
    from init_db import SQL_DIR

    triggers_file = SQL_DIR / "04_triggers.sql"
    with open(triggers_file, "r", encoding="utf-8") as f:
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

    assert len(statements) >= 10, f"Expected at least 10 statements (DROP + CREATE per trigger), found {len(statements)}"
    create_triggers = [s for s in statements if s.upper().startswith("CREATE TRIGGER")]
    assert len(create_triggers) == 5, f"Expected 5 CREATE TRIGGER statements, found {len(create_triggers)}"
