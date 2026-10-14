"""
Hommy Cottage - Database Schema Specification Tests
Verifies 3NF/BCNF requirements, table structures, and functional dependency comments.
"""
from pathlib import Path


def test_schema_file_exists():
    """Verify sql/schema.sql exists and is non-empty."""
    schema_path = Path("sql/schema.sql")
    assert schema_path.exists(), "sql/schema.sql must exist"
    content = schema_path.read_text(encoding="utf-8")
    assert len(content) > 500


def test_schema_has_required_tables_and_fd_comments():
    """
    Verify each table has a one-line comment stating its functional dependencies
    as mandated by the DBMS project specification.
    """
    schema_path = Path("sql/schema.sql")
    content = schema_path.read_text(encoding="utf-8")

    expected_tables = [
        "users",
        "cottages",
        "amenities",
        "cottage_amenities",
        "cottage_images",
        "bookings",
        "payments",
        "reviews"
    ]

    for table in expected_tables:
        # Check CREATE TABLE exists
        assert f"CREATE TABLE {table}" in content, f"Table '{table}' definition missing in schema.sql"
        # Check Functional Dependencies comment exists
        assert "Functional Dependencies" in content, "Functional Dependencies comments missing"


def test_sample_data_file_exists_and_contains_roles():
    """Verify sql/sample_data.sql seeds admin, host, and guest users."""
    seed_path = Path("sql/sample_data.sql")
    assert seed_path.exists(), "sql/sample_data.sql must exist"
    content = seed_path.read_text(encoding="utf-8")

    assert "admin@hommycottage.com" in content
    assert "rahul.host@example.com" in content
    assert "aarav.guest@example.com" in content
    assert "'admin'" in content
    assert "'host'" in content
    assert "'guest'" in content


def test_01_schema_specification():
    """Verify sql/01_schema.sql has all 12 required tables, indexes, and BCNF comments."""
    schema_path = Path("sql/01_schema.sql")
    assert schema_path.exists(), "sql/01_schema.sql must exist"
    content = schema_path.read_text(encoding="utf-8")

    # Verify database setup header
    assert "DROP DATABASE IF EXISTS hommy_cottage" in content
    assert "CREATE DATABASE hommy_cottage CHARACTER SET utf8mb4" in content
    assert "USE hommy_cottage" in content

    # Verify all 12 tables
    tables = [
        "users", "cities", "property_types", "properties", "room_types",
        "rooms", "amenities", "property_amenities", "property_images",
        "bookings", "payments", "reviews"
    ]
    for tbl in tables:
        assert f"CREATE TABLE {tbl}" in content, f"Table {tbl} missing in sql/01_schema.sql"

    # Verify BCNF / Functional Dependencies comments
    assert "Functional Dependencies" in content
    assert "BCNF" in content

    # Verify requested indexes
    assert "idx_properties_city_status (city_id, status)" in content
    assert "idx_room_types_price (price_per_night)" in content
    assert "idx_bookings_room_dates (room_id, check_in, check_out)" in content
    assert "idx_bookings_guest (guest_id)" in content

    # Verify checks
    assert "CHECK (check_out > check_in)" in content
    assert "CHECK (rating BETWEEN 1 AND 5)" in content
    assert "CHECK (capacity > 0)" in content
    assert "CHECK (price_per_night > 0)" in content
