"""
Hommy Cottage - Full Application & Business Integrity Integration Test Suite
=============================================================================
Executed against a separate 'hommy_cottage_test' MySQL database built by init_db.py.
Covers all 11 core DBMS & application specifications:
 1. Duplicate email registration rejected (UNIQUE constraint & user-friendly handling)
 2. Role-based access control (guest accessing /host and /admin returns 403 Forbidden)
 3. Pending listings hidden from public search and detail views
 4. Successful booking workflow via Flask test client and DB ledger verification
 5. Double-booking blocked by both the stored procedure and the raw trigger
 6. Same-day checkout/check-in (hotel room turnover) permitted without conflict
 7. Guest capacity limits enforced by route validation and database trigger
 8. Booking cancellation automatically triggers payment refund via trigger
 9. Review submissions blocked before stay completion and checkout date
10. Duplicate review submissions blocked by UNIQUE constraint
11. Multi-tenant property isolation (host cannot edit another host's property)

Prints a clear pass/fail summary table upon test suite completion.
"""
import os
import sys
import time
from functools import wraps
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import pytest
import pymysql

# Add project root directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Target the separate test database strictly
os.environ["DB_NAME"] = "hommy_cottage_test"

from config import Config
Config.DB_NAME = "hommy_cottage_test"

import db
import init_db
from app import create_app
from auth_utils import get_current_user


# Global execution registry for the pass/fail summary table
TEST_RESULTS = []
SUMMARY_PRINTED = False


def record_test(test_id: int, spec_title: str):
    """Decorator to measure test runtime and register outcome for the summary table."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            status = "PASS"
            err_msg = ""
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                status = "FAIL"
                err_msg = str(exc)
                raise
            finally:
                duration = time.time() - start_time
                TEST_RESULTS.append({
                    "id": test_id,
                    "name": func.__name__,
                    "spec": spec_title,
                    "status": status,
                    "duration": f"{duration:.2f}s",
                    "error": err_msg
                })
        return wrapper
    return decorator


class TestAppConfig(Config):
    """Configuration for Flask test client running against hommy_cottage_test."""
    TESTING = True
    DB_NAME = "hommy_cottage_test"
    SECRET_KEY = "test-secret-key-hommy-cottage-test-db"
    WTF_CSRF_ENABLED = False


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database_built():
    """
    Guarantees the separate 'hommy_cottage_test' database is built by init_db.py
    with complete schema, seed records, views, triggers, and stored procedures.
    """
    needs_build = False
    try:
        conn = db.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT DATABASE() AS current_db;")
            res = cur.fetchone()
            if not res or res["current_db"] != "hommy_cottage_test":
                needs_build = True
            else:
                cur.execute("SELECT COUNT(*) AS user_count FROM users;")
                if cur.fetchone()["user_count"] < 10:
                    needs_build = True
        conn.close()
    except Exception:
        needs_build = True

    if needs_build:
        print("\n[*] Initializing separate test database 'hommy_cottage_test' via init_db.py...")
        init_db.build_database(
            no_drop=False,
            skip_confirm=True,
            continue_on_error=True,
            db_name="hommy_cottage_test"
        )


@pytest.fixture(scope="module", autouse=True)
def print_summary_on_completion(request):
    """Prints the formatted pass/fail summary table when test suite completes."""
    yield
    print_summary_table()


@pytest.fixture
def app():
    """Creates a Flask application instance configured for testing."""
    application = create_app(TestAppConfig)
    return application


@pytest.fixture
def client(app):
    """Provides a Flask test client for HTTP request simulations."""
    return app.test_client()


@pytest.fixture(autouse=True)
def cleanup_transient_test_data():
    """
    Cleans up any ephemeral test bookings, payments, and reviews created
    during individual test runs to guarantee idempotency.
    """
    yield
    try:
        conn = db.get_conn()
        with conn.cursor() as cur:
            # Purge test bookings created during runs (id >= 900)
            cur.execute("DELETE FROM payments WHERE booking_id >= 900;")
            cur.execute("DELETE FROM reviews WHERE booking_id >= 900;")
            cur.execute("DELETE FROM bookings WHERE booking_id >= 900;")
            # Purge any test users created during duplicate tests
            cur.execute("DELETE FROM users WHERE email LIKE '%@test-transient.com';")
        conn.commit()
        conn.close()
    except Exception:
        pass


def login_as(client, email, password="password123"):
    """Helper to authenticate a user using Flask test client."""
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


def logout(client):
    """Helper to log out the current user session."""
    return client.get("/auth/logout", follow_redirects=True)


# =============================================================================
# 1. Duplicate Email Registration
# =============================================================================
@record_test(1, "Duplicate email registration rejected (UNIQUE constraint & form warning)")
def test_01_duplicate_email(client):
    """
    Cover 1: Duplicate email registration.
    - Flask test client rejects registration with existing email and returns 200 with flash notice.
    - Raw database insert raises pymysql.err.IntegrityError (MySQL Error 1062 - Duplicate entry).
    """
    # 1. Web layer: Attempt to register with existing guest email
    existing_email = "guest@hommycottage.com"
    response = client.post("/auth/register", data={
        "name": "Aarav Clone",
        "email": existing_email,
        "phone": "9998887776",
        "password": "newpassword123",
        "confirm_password": "newpassword123",
        "role": "guest"
    }, follow_redirects=True)

    assert response.status_code == 200, "Should re-render registration form without crashing"
    html = response.data.decode("utf-8")
    assert "already exists" in html.lower(), "Should inform the user that the email already exists"

    # 2. Database layer: Attempt direct INSERT violating UNIQUE(email) constraint
    with pytest.raises(pymysql.err.IntegrityError) as exc_info:
        conn = db.get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (name, email, phone, password_hash, role)
                VALUES (%s, %s, %s, %s, %s);
            """, ("Duplicate Tester", existing_email, "9123456789", "dummy_hash", "guest"))
        conn.commit()

    err = exc_info.value
    assert err.args[0] == 1062 or "Duplicate entry" in str(err), "MySQL must raise Error 1062 on duplicate email"


# =============================================================================
# 2. Role-Based Access Control (Guest on /host and /admin returns 403)
# =============================================================================
@record_test(2, "Role access control: guest on /host and /admin returns 403 Forbidden")
def test_02_role_access_guest_forbidden_on_host_and_admin(client):
    """
    Cover 2: Role access control.
    - An authenticated guest accessing /host and /admin routes returns HTTP 403 Forbidden.
    """
    login_as(client, "guest@hommycottage.com")

    # Host portal routes that guest must NOT access
    host_endpoints = [
        "/host",
        "/host/dashboard",
        "/host/properties/new",
        "/host/bookings"
    ]
    for endpoint in host_endpoints:
        res = client.get(endpoint, follow_redirects=True)
        assert res.status_code == 403, f"Guest accessing {endpoint} must return HTTP 403 Forbidden, got {res.status_code}"

    # Admin portal routes that guest must NOT access
    admin_endpoints = [
        "/admin",
        "/admin/dashboard",
        "/admin/users",
        "/admin/listings/pending",
        "/admin/reports"
    ]
    for endpoint in admin_endpoints:
        res = client.get(endpoint, follow_redirects=True)
        assert res.status_code == 403, f"Guest accessing {endpoint} must return HTTP 403 Forbidden, got {res.status_code}"

    logout(client)


# =============================================================================
# 3. Pending Listings Hidden From Search
# =============================================================================
@record_test(3, "Pending listings hidden from public search and detail views (404)")
def test_03_pending_listings_hidden_from_search(client):
    """
    Cover 3: Pending listings hidden from search.
    - Properties with status='pending' must never appear in public search results.
    - Direct access to GET /property/<pending_id> returns HTTP 404 for guests and unauthenticated visitors.
    """
    # Find pending property in database (Property 27: 'Tea Garden Cloud Canopy Treehouse')
    pending_property = db.fetch_one("SELECT property_id, name FROM properties WHERE status = 'pending' LIMIT 1;")
    assert pending_property is not None, "Test database must contain at least one pending property"
    pending_id = pending_property["property_id"]
    pending_name = pending_property["name"]

    # 1. Verify absence from search results
    res_search = client.get("/search")
    assert res_search.status_code == 200
    search_html = res_search.data.decode("utf-8")
    assert pending_name not in search_html, f"Pending property '{pending_name}' must not be visible in search results"

    # 2. Verify direct access returns 404 for unauthenticated guest
    res_unauth = client.get(f"/property/{pending_id}")
    assert res_unauth.status_code == 404, f"Accessing pending property {pending_id} directly must return 404 Not Found"

    # 3. Verify direct access returns 404 for standard logged-in guest
    login_as(client, "guest@hommycottage.com")
    res_guest = client.get(f"/property/{pending_id}")
    assert res_guest.status_code == 404, f"Standard guest accessing pending property {pending_id} must receive 404"
    logout(client)


# =============================================================================
# 4. Successful Booking Workflow
# =============================================================================
@record_test(4, "Successful booking creates confirmed stay and successful payment")
def test_04_successful_booking(client):
    """
    Cover 4: Successful booking.
    - Valid reservation submitted via POST /book calls sp_book_room, commits booking and payment,
      and redirects to the confirmation receipt.
    """
    login_as(client, "guest@hommycottage.com")

    # Use future dates unlikely to conflict with any existing stays
    ci_date = date.today() + timedelta(days=220)
    co_date = ci_date + timedelta(days=3)
    ci_str = ci_date.strftime("%Y-%m-%d")
    co_str = co_date.strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci_str,
        "check_out": co_str,
        "guests": 2,
        "payment_method": "upi"
    }, follow_redirects=False)

    assert res.status_code == 302, f"Expected 302 redirect to confirmation, got {res.status_code}"
    location = res.headers.get("Location", "")
    assert "/confirmation/" in location, f"Expected redirect to /confirmation/<id>, got {location}"
    booking_id = int(location.split("/")[-1])

    # Verify booking record in database
    booking = db.fetch_one("SELECT * FROM bookings WHERE booking_id = %s;", (booking_id,))
    assert booking is not None, "Booking record must exist in database"
    assert booking["status"] == "confirmed"
    assert booking["check_in"] == ci_date
    assert booking["check_out"] == co_date
    assert booking["guests"] == 2
    assert Decimal(str(booking["price_per_night_at_booking"])) > 0

    # Verify payment record in database
    payment = db.fetch_one("SELECT * FROM payments WHERE booking_id = %s;", (booking_id,))
    assert payment is not None, "Payment record must exist in database"
    assert payment["status"] == "success"
    assert payment["method"] == "upi"
    expected_amount = 3 * Decimal(str(booking["price_per_night_at_booking"]))
    assert Decimal(str(payment["amount"])) == expected_amount

    logout(client)


# =============================================================================
# 5. Double-Booking Blocked by Both Stored Procedure and Raw Trigger
# =============================================================================
@record_test(5, "Double-booking blocked by both sp_book_room and trg_prevent_overlap")
def test_05_double_booking_blocked_by_stored_procedure_and_trigger():
    """
    Cover 5: Double-booking blocked by both the stored procedure and the raw trigger.
    - 5A: Stored procedure sp_book_room raises SQLEXCEPTION (SQLSTATE 45000) when all rooms of a type are booked.
    - 5B: Raw trigger trg_prevent_overlap raises SQLSTATE 45000 on direct INSERT with overlapping dates.
    """
    conn = db.get_conn()
    cur = conn.cursor()

    # Find a room type and all of its physical rooms
    cur.execute("""
        SELECT rt.room_type_id, rm.room_id
        FROM room_types rt
        JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        WHERE rt.room_type_id = 14;
    """)
    rooms = cur.fetchall()
    assert len(rooms) >= 1, "Room type 14 must have physical rooms"

    start_date = date.today() + timedelta(days=260)
    end_date = start_date + timedelta(days=4)
    overlap_start = start_date + timedelta(days=1)
    overlap_end = start_date + timedelta(days=3)

    try:
        # Occupy all physical rooms for room type 14 for the baseline date window
        for idx, r in enumerate(rooms):
            cur.execute("""
                INSERT INTO bookings (
                    booking_id, guest_id, room_id, check_in, check_out,
                    guests, price_per_night_at_booking, status
                ) VALUES (%s, 7, %s, %s, %s, 2, 2200.00, 'confirmed');
            """, (910 + idx, r["room_id"], start_date, end_date))
        conn.commit()

        # ---------------------------------------------------------------------
        # 5A: Verify Stored Procedure sp_book_room blocks double-booking
        # ---------------------------------------------------------------------
        with pytest.raises(pymysql.err.OperationalError) as sp_exc:
            cur.execute("""
                CALL sp_book_room(7, 14, %s, %s, 2, 'upi', @new_booking_id);
            """, (overlap_start, overlap_end))
        conn.rollback()

        sp_err_msg = str(sp_exc.value)
        assert sp_exc.value.args[0] == 1644 or "45000" in sp_err_msg, "sp_book_room must signal SQLSTATE 45000"
        assert "No available rooms found" in sp_err_msg or "Booking failed" in sp_err_msg

        # ---------------------------------------------------------------------
        # 5B: Verify Raw Trigger trg_prevent_overlap blocks direct INSERT
        # ---------------------------------------------------------------------
        occupied_room_id = rooms[0]["room_id"]
        with pytest.raises(pymysql.err.OperationalError) as trg_exc:
            cur.execute("""
                INSERT INTO bookings (
                    booking_id, guest_id, room_id, check_in, check_out,
                    guests, price_per_night_at_booking, status
                ) VALUES (920, 7, %s, %s, %s, 2, 2200.00, 'confirmed');
            """, (occupied_room_id, overlap_start, overlap_end))
        conn.rollback()

        trg_err_msg = str(trg_exc.value)
        assert trg_exc.value.args[0] == 1644 or "45000" in trg_err_msg, "trg_prevent_overlap must signal SQLSTATE 45000"
        assert "Booking conflict" in trg_err_msg or "already booked" in trg_err_msg

    finally:
        cur.execute("DELETE FROM bookings WHERE booking_id >= 910;")
        conn.commit()
        conn.close()


# =============================================================================
# 6. Same-Day Checkout/Check-in Allowed (Room Turnover Rule)
# =============================================================================
@record_test(6, "Same-day checkout/check-in turnover allowed without conflict")
def test_06_same_day_checkout_checkin_allowed():
    """
    Cover 6: Same-day checkout/check-in allowed.
    - Verifies hotel turnover rule: If Booking A ends on Day X, Booking B can check in on Day X.
      Similarly, Booking C can check out on Day X when Booking A checks in on Day X.
    - Triggers allow adjacent non-overlapping bookings without false positive collision.
    """
    conn = db.get_conn()
    cur = conn.cursor()

    day_x = date.today() + timedelta(days=280)
    day_before = day_x - timedelta(days=3)
    day_after = day_x + timedelta(days=3)
    day_far_after = day_x + timedelta(days=6)

    try:
        # Booking A: From day_x to day_after on room 1
        cur.execute("""
            INSERT INTO bookings (
                booking_id, guest_id, room_id, check_in, check_out,
                guests, price_per_night_at_booking, status
            ) VALUES (930, 7, 1, %s, %s, 2, 2250.00, 'confirmed');
        """, (day_x, day_after))

        # Booking B: Check in on the EXACT day Booking A checks out (day_after)
        cur.execute("""
            INSERT INTO bookings (
                booking_id, guest_id, room_id, check_in, check_out,
                guests, price_per_night_at_booking, status
            ) VALUES (931, 7, 1, %s, %s, 2, 2250.00, 'confirmed');
        """, (day_after, day_far_after))

        # Booking C: Check out on the EXACT day Booking A checks in (day_x)
        cur.execute("""
            INSERT INTO bookings (
                booking_id, guest_id, room_id, check_in, check_out,
                guests, price_per_night_at_booking, status
            ) VALUES (932, 7, 1, %s, %s, 2, 2250.00, 'confirmed');
        """, (day_before, day_x))

        conn.commit()

        # Verify all 3 adjacent bookings exist in database
        cur.execute("SELECT COUNT(*) AS c FROM bookings WHERE booking_id IN (930, 931, 932);")
        count = cur.fetchone()["c"]
        assert count == 3, f"Expected 3 turnover bookings to be stored successfully, found {count}"

    finally:
        cur.execute("DELETE FROM bookings WHERE booking_id IN (930, 931, 932);")
        conn.commit()
        conn.close()


# =============================================================================
# 7. Capacity Limit
# =============================================================================
@record_test(7, "Capacity limit enforced by POST /book and trg_guest_capacity trigger")
def test_07_capacity_limit(client):
    """
    Cover 7: Capacity limit.
    - 7A: Web route POST /book rejects guest count exceeding room type capacity.
    - 7B: Raw database trigger trg_guest_capacity rejects direct INSERT with guests > capacity.
    """
    # 7A: Route validation
    login_as(client, "guest@hommycottage.com")
    ci = (date.today() + timedelta(days=300)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=303)).strftime("%Y-%m-%d")

    # Room type 1 has capacity = 2 in seed data
    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 25,  # Vastly exceeds capacity
        "payment_method": "upi"
    }, follow_redirects=True)

    html = res.data.decode("utf-8")
    assert "exceeds the room type capacity" in html or "capacity" in html.lower()
    logout(client)

    # 7B: Raw trigger validation (trg_guest_capacity)
    conn = db.get_conn()
    cur = conn.cursor()
    try:
        with pytest.raises(pymysql.err.OperationalError) as exc_info:
            cur.execute("""
                INSERT INTO bookings (
                    booking_id, guest_id, room_id, check_in, check_out,
                    guests, price_per_night_at_booking, status
                ) VALUES (940, 7, 1, '2027-10-01', '2027-10-04', 99, 2250.00, 'confirmed');
            """)
        conn.rollback()

        err_msg = str(exc_info.value)
        assert exc_info.value.args[0] == 1644 or "45000" in err_msg
        assert "Capacity exceeded" in err_msg or "occupancy" in err_msg.lower()

    finally:
        cur.execute("DELETE FROM bookings WHERE booking_id = 940;")
        conn.commit()
        conn.close()


# =============================================================================
# 8. Cancel Refunds Payment
# =============================================================================
@record_test(8, "Cancel booking automatically triggers payment refund via trigger")
def test_08_cancel_refunds_payment(client):
    """
    Cover 8: Cancel refunds payment.
    - Cancelling a reservation updates booking status to 'cancelled' and payment status to 'refunded'.
    - Trigger trg_refund_on_cancel maintains ledger integrity.
    """
    login_as(client, "guest@hommycottage.com")

    # 1. Create a future reservation to cancel
    ci = (date.today() + timedelta(days=320)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=323)).strftime("%Y-%m-%d")

    res_book = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 1,
        "payment_method": "card"
    }, follow_redirects=False)
    booking_id = int(res_book.headers["Location"].split("/")[-1])

    # 2. Cancel via POST /cancel/<booking_id>
    res_cancel = client.post(f"/cancel/{booking_id}", follow_redirects=True)
    assert res_cancel.status_code == 200

    # 3. Verify in database
    booking = db.fetch_one("SELECT status FROM bookings WHERE booking_id = %s;", (booking_id,))
    assert booking["status"] == "cancelled", "Booking status must be 'cancelled'"

    payment = db.fetch_one("SELECT status FROM payments WHERE booking_id = %s;", (booking_id,))
    assert payment["status"] == "refunded", "Payment status must be updated to 'refunded' by trigger"

    logout(client)


# =============================================================================
# 9. Review Blocked Before Check-Out
# =============================================================================
@record_test(9, "Review blocked before stay checkout by route and trg_review_after_checkout")
def test_09_review_blocked_before_check_out(client):
    """
    Cover 9: Review blocked before check-out.
    - 9A: Route POST /review/<booking_id> rejects review for stays with check_out > CURRENT_DATE().
    - 9B: Database trigger trg_review_after_checkout raises SQLSTATE 45000 on premature INSERT into reviews.
    """
    login_as(client, "guest@hommycottage.com")

    # Find a future booking in seed data where check_out > CURRENT_DATE()
    future_booking = db.fetch_one("""
        SELECT booking_id FROM bookings
        WHERE guest_id = 7 AND status = 'confirmed' AND check_out > CURRENT_DATE()
        LIMIT 1;
    """)
    assert future_booking is not None, "Test database must have an active future booking for guest 7"
    future_id = future_booking["booking_id"]

    # 9A: Route rejection
    res = client.post(f"/review/{future_id}", data={
        "rating": 5,
        "comment": "Attempting to review ahead of my trip!"
    }, follow_redirects=True)
    html = res.data.decode("utf-8")
    assert "after checkout date" in html.lower() or "rejected" in html.lower()
    logout(client)

    # 9B: Raw trigger rejection (trg_review_after_checkout)
    conn = db.get_conn()
    cur = conn.cursor()
    try:
        with pytest.raises(pymysql.err.OperationalError) as exc_info:
            cur.execute("""
                INSERT INTO reviews (booking_id, rating, comment)
                VALUES (%s, 5, 'Premature direct review insert');
            """, (future_id,))
        conn.rollback()

        err_msg = str(exc_info.value)
        assert exc_info.value.args[0] == 1644 or "45000" in err_msg
        assert "after checkout date" in err_msg or "Review rejected" in err_msg

    finally:
        cur.execute("DELETE FROM reviews WHERE booking_id = %s AND comment = 'Premature direct review insert';", (future_id,))
        conn.commit()
        conn.close()


# =============================================================================
# 10. Duplicate Review Blocked
# =============================================================================
@record_test(10, "Duplicate review blocked by route validation and UNIQUE(booking_id) constraint")
def test_10_duplicate_review_blocked(client):
    """
    Cover 10: Duplicate review blocked.
    - Submitting a second review for the same completed stay is blocked.
    - Database enforces UNIQUE constraint on reviews.booking_id (1 stay = 1 review).
    """
    login_as(client, "guest@hommycottage.com")

    # Find a past booking that has already been reviewed
    reviewed_booking = db.fetch_one("""
        SELECT b.booking_id
        FROM bookings b
        JOIN reviews r ON b.booking_id = r.booking_id
        WHERE b.guest_id = 7
        LIMIT 1;
    """)
    assert reviewed_booking is not None, "Test database must have a reviewed past booking for guest 7"
    b_id = reviewed_booking["booking_id"]

    # 1. Route validation
    res = client.post(f"/review/{b_id}", data={
        "rating": 5,
        "comment": "Submitting a second review attempt"
    }, follow_redirects=True)
    html = res.data.decode("utf-8")
    assert "already submitted a review" in html.lower() or "duplicate" in html.lower()
    logout(client)

    # 2. Database layer UNIQUE constraint validation
    conn = db.get_conn()
    cur = conn.cursor()
    try:
        with pytest.raises(pymysql.err.IntegrityError) as exc_info:
            cur.execute("""
                INSERT INTO reviews (booking_id, rating, comment)
                VALUES (%s, 4, 'Direct second review attempt');
            """, (b_id,))
        conn.rollback()

        err_msg = str(exc_info.value)
        assert exc_info.value.args[0] == 1062 or "Duplicate entry" in err_msg
    finally:
        conn.close()


# =============================================================================
# 11. Host Cannot Edit Another Host's Property
# =============================================================================
@record_test(11, "Multi-tenant isolation: Host cannot edit another host's property (403 Forbidden)")
def test_11_host_cannot_edit_another_host_property(client):
    """
    Cover 11: Host cannot edit another host's property.
    - Multi-tenant security: Host 2 (host@hommycottage.com) cannot view or modify Property 2
      (owned by Host 3). Both GET and POST return HTTP 403 Forbidden.
    """
    login_as(client, "host@hommycottage.com")  # User 2

    # Property 2 is owned by Host 3 (Rajesh Verma)
    prop2_before = db.fetch_one("SELECT property_id, host_id, name, address FROM properties WHERE property_id = 2;")
    assert prop2_before is not None
    assert prop2_before["host_id"] != 2, "Property 2 must belong to another host"

    # 1. GET edit form must return 403 Forbidden
    res_get = client.get("/host/property/2/edit")
    assert res_get.status_code == 403, f"Expected 403 Forbidden on GET, got {res_get.status_code}"

    # 2. POST update attempt must return 403 Forbidden
    res_post = client.post("/host/property/2/edit", data={
        "name": "Malicious Tampered Cottage Title",
        "type_id": "2",
        "city_id": "1",
        "address": "Hijacked Road 99",
        "pincode": "452001",
        "description": "Unauthorized attempt to modify another host's listing."
    })
    assert res_post.status_code == 403, f"Expected 403 Forbidden on POST, got {res_post.status_code}"

    # 3. Verify database record remained unchanged
    prop2_after = db.fetch_one("SELECT name, address FROM properties WHERE property_id = 2;")
    assert prop2_after["name"] == prop2_before["name"], "Property name must not be modified"
    assert prop2_after["address"] == prop2_before["address"], "Property address must not be modified"

    logout(client)


# =============================================================================
# Pass/Fail Summary Table Generator
# =============================================================================
def print_summary_table():
    """Formats and prints the pass/fail summary table to stdout."""
    global SUMMARY_PRINTED
    if SUMMARY_PRINTED or not TEST_RESULTS:
        return
    SUMMARY_PRINTED = True

    passed_count = sum(1 for t in TEST_RESULTS if t["status"] == "PASS")
    failed_count = sum(1 for t in TEST_RESULTS if t["status"] == "FAIL")
    total_count = len(TEST_RESULTS)
    pct = (passed_count / total_count * 100) if total_count else 0.0

    sep_double = "=" * 98
    sep_single = "-" * 98

    print("\n" + sep_double)
    print("                HOMMY COTTAGE DBMS - AUTOMATED INTEGRATION TEST RESULTS")
    print("               Target Database: hommy_cottage_test (MySQL 8.0 / InnoDB)")
    print(sep_double)
    header = f"{'#':<3} | {'Test Name':<38} | {'Status':<8} | {'Duration':<8} | {'Specification / Coverage'}"
    print(header)
    print(sep_single)

    for item in sorted(TEST_RESULTS, key=lambda x: x["id"]):
        status_display = f"[{item['status']}]"
        print(f"{item['id']:<3} | {item['name']:<38} | {status_display:<8} | {item['duration']:<8} | {item['spec'][:38]}")

    print(sep_single)
    print(f" TOTAL EXECUTED: {total_count:<3} | PASSED: {passed_count:<3} | FAILED: {failed_count:<3} | PASS RATE: {pct:.1f}%")
    print(sep_double + "\n")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Pytest hook invoked at terminal reporting phase."""
    print_summary_table()


if __name__ == "__main__":
    # Allows direct execution: python tests/test_app.py
    exit_code = pytest.main(["-s", "-v", __file__])
    print_summary_table()
    sys.exit(exit_code)
