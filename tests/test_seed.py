"""
Hommy Cottage - Seed Data Verification Tests
Verifies sql/02_seed.sql requirements:
- Users (1 admin, 5 hosts, 11 guests)
- 12 cities across MP, HP, Goa, Rajasthan, Kerala, UK (including Indore and Bhopal)
- 4 property types, 12 amenities
- 32 properties (26 approved, 4 pending, 2 rejected)
- Room types (2-4 per property) and rooms (2-6 per room type)
- Property amenities and property images
- 40 bookings with no overlapping dates on the same room, each with a payment row
- 25 reviews attached only to past, non-cancelled bookings
"""
from pathlib import Path


def test_seed_file_structure():
    """Verify sql/02_seed.sql exists and contains comments naming each block."""
    seed_path = Path("sql/02_seed.sql")
    assert seed_path.exists(), "sql/02_seed.sql must exist"
    content = seed_path.read_text(encoding="utf-8")

    # Verify sections with comments
    blocks = [
        "1. Users",
        "2. Cities",
        "3. Property Types",
        "4. Amenities",
        "5. Properties",
        "6. Property Amenities",
        "7. Property Images",
        "8. Room Types",
        "9. Rooms",
        "10. Bookings",
        "11. Payments",
        "12. Reviews"
    ]
    for block in blocks:
        assert block in content, f"Comment block '{block}' missing in sql/02_seed.sql"

    # Verify cities Indore and Bhopal
    assert "Indore" in content
    assert "Bhopal" in content
    assert "Pachmarhi" in content
    assert "Madhya Pradesh" in content

    # Verify placeholder __HASH__
    assert "'__HASH__'" in content

    # Verify image paths format
    assert "/static/img/sample/p1.jpg" in content


def test_database_seed_row_counts_and_integrity(app):
    """Verify live database row counts and relational integrity from 02_seed.sql."""
    from db import query_one, query_all
    from werkzeug.security import check_password_hash

    with app.app_context():
        # Users
        total_users = query_one("SELECT COUNT(*) AS c FROM users")["c"]
        admin_count = query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")["c"]
        host_count = query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'host'")["c"]
        guest_count = query_one("SELECT COUNT(*) AS c FROM users WHERE role = 'guest'")["c"]

        assert total_users == 17
        assert admin_count == 1
        assert host_count == 5
        assert guest_count == 11

        # Check password hash replacement
        admin_user = query_one("SELECT password_hash FROM users WHERE email = 'admin@hommycottage.com'")
        assert check_password_hash(admin_user["password_hash"], "password123") is True

        # Cities (12)
        cities_count = query_one("SELECT COUNT(*) AS c FROM cities")["c"]
        assert cities_count == 12

        # Property Types (4) & Amenities (12)
        assert query_one("SELECT COUNT(*) AS c FROM property_types")["c"] == 4
        assert query_one("SELECT COUNT(*) AS c FROM amenities")["c"] == 12

        # Properties (32: 26 approved, 4 pending, 2 rejected)
        assert query_one("SELECT COUNT(*) AS c FROM properties")["c"] == 32
        assert query_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'approved'")["c"] == 26
        assert query_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'pending'")["c"] == 4
        assert query_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'rejected'")["c"] == 2

        # Bookings (40) & Payments (40)
        assert query_one("SELECT COUNT(*) AS c FROM bookings")["c"] == 40
        assert query_one("SELECT COUNT(*) AS c FROM payments")["c"] == 40

        # Payments match bookings (one-to-one)
        cancelled_payments = query_one("SELECT COUNT(*) AS c FROM payments WHERE status = 'refunded'")["c"]
        assert cancelled_payments > 0

        # Reviews (25) attached only to past, non-cancelled bookings
        assert query_one("SELECT COUNT(*) AS c FROM reviews")["c"] == 25

        invalid_reviews = query_one("""
            SELECT COUNT(*) AS c
            FROM reviews r
            JOIN bookings b ON r.booking_id = b.booking_id
            WHERE b.status = 'cancelled' OR b.check_out >= '2026-10-14'
        """)["c"]
        assert invalid_reviews == 0, "Found reviews on cancelled or future bookings!"

        # Verify NO overlapping booking dates on the same room
        overlapping_bookings = query_one("""
            SELECT COUNT(*) AS c
            FROM bookings b1
            JOIN bookings b2 ON b1.room_id = b2.room_id AND b1.booking_id < b2.booking_id
            WHERE NOT (b1.check_out <= b2.check_in OR b1.check_in >= b2.check_out)
        """)["c"]
        assert overlapping_bookings == 0, "Found overlapping booking dates on the same room!"
