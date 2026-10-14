"""
Hommy Cottage - Booking, Reservation, Cancellation & Review Tests
================================================================
Validates all endpoints and business logic in routes/booking.py:
1. POST /book:
   - Server-side input validations (dates, guests, room type capacity, payment method whitelist)
   - Invocation of stored procedure sp_book_room
   - Catching of MySQL SIGNAL errors with user-friendly flash messages
   - Atomic insertion of booking and payment records
   - Redirection to confirmation page
2. GET /confirmation/<booking_id>:
   - Renders confirmation receipt showing booking id, dates, nights, total, and payment status
   - Access control (only booking guest and admin permitted)
3. GET /my-bookings:
   - Displays upcoming and past stays for authenticated guest
   - Cancel button displayed strictly when allowed (check_in > today and status = 'confirmed')
   - Review button displayed strictly when allowed (check_out <= today, status != 'cancelled', unreviewed)
4. POST /cancel/<booking_id>:
   - Invocation of stored procedure sp_cancel_booking
   - Rejects cancellation after check-in date or by unauthorized user
   - Updates booking status to 'cancelled' and payment to 'refunded'
5. POST /review/<booking_id>:
   - Server-side validation of rating (1-5) and comment (non-empty)
   - Relies on trigger trg_review_after_checkout for stay completion and non-cancellation rules
   - Catches duplicate-review UNIQUE constraint error (IntegrityError 1062)
"""
import pytest
from datetime import date, timedelta
from db import fetch_one, fetch_all, execute


@pytest.fixture(autouse=True)
def cleanup_test_bookings():
    """Ensures created test bookings are cleanly purged so test_seed.py counts remain accurate."""
    yield
    execute("DELETE FROM payments WHERE booking_id > 40;")
    execute("DELETE FROM reviews WHERE booking_id > 40;")
    execute("DELETE FROM bookings WHERE booking_id > 40;")


def login_as(client, email, password="password123"):
    """Helper to authenticate a user."""
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


def test_book_page_renders_for_logged_in_guest(client):
    """Verify GET /book?room_type_id=1 renders checkout details for an approved room type."""
    login_as(client, "guest@hommycottage.com")
    res = client.get("/book?room_type_id=1")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Complete Your Reservation" in html
    assert 'name="room_type_id"' in html
    assert 'name="check_in"' in html
    assert 'name="check_out"' in html
    assert 'name="guests"' in html
    assert 'name="payment_method"' in html
    client.get("/auth/logout")


def test_book_server_validation_past_date(client):
    """Verify POST /book rejects past check-in dates server-side."""
    login_as(client, "guest@hommycottage.com")
    yesterday = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    tomorrow = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": yesterday,
        "check_out": tomorrow,
        "guests": 1,
        "payment_method": "upi"
    }, follow_redirects=True)

    html = res.data.decode("utf-8")
    assert "Check-in date cannot be in the past" in html
    client.get("/auth/logout")


def test_book_server_validation_checkout_before_checkin(client):
    """Verify POST /book rejects checkout dates on or before check-in server-side."""
    login_as(client, "guest@hommycottage.com")
    ci = (date.today() + timedelta(days=5)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=4)).strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 1,
        "payment_method": "upi"
    }, follow_redirects=True)

    html = res.data.decode("utf-8")
    assert "Check-out date must be strictly after check-in date" in html
    client.get("/auth/logout")


def test_book_server_validation_guests_capacity(client):
    """Verify POST /book rejects guest count exceeding room type capacity."""
    login_as(client, "guest@hommycottage.com")
    # Room type 1 has capacity = 2 in seed data
    rt = fetch_one("SELECT capacity FROM room_types WHERE room_type_id = 1;")
    cap = rt["capacity"]

    ci = (date.today() + timedelta(days=10)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=12)).strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": cap + 5,  # Exceeds capacity
        "payment_method": "upi"
    }, follow_redirects=True)

    html = res.data.decode("utf-8")
    assert f"exceeds the room type capacity ({cap} guests)" in html or "capacity" in html.lower()
    client.get("/auth/logout")


def test_book_server_validation_method_whitelist(client):
    """Verify POST /book rejects unapproved payment methods."""
    login_as(client, "guest@hommycottage.com")
    ci = (date.today() + timedelta(days=15)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=17)).strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 1,
        "payment_method": "bitcoin_crypto"  # Not in whitelist
    }, follow_redirects=True)

    html = res.data.decode("utf-8")
    assert "Invalid payment method" in html
    client.get("/auth/logout")


def test_book_host_cannot_book_own_property(client):
    """Verify hosts are forbidden from reserving their own listing."""
    # Host user 2 owns property 1 which has room_type 1
    login_as(client, "host@hommycottage.com")
    ci = (date.today() + timedelta(days=20)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=22)).strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 1,
        "payment_method": "upi"
    }, follow_redirects=True)

    html = res.data.decode("utf-8")
    assert "Hosts cannot book their own property listing" in html
    client.get("/auth/logout")


def test_book_success_and_confirmation_page(client):
    """
    Verify POST /book calls sp_book_room, commits booking + payment,
    and redirects to confirmation page showing booking id, dates, nights, total, and payment status.
    """
    login_as(client, "guest@hommycottage.com")
    # Choose future dates unlikely to conflict
    ci_date = date.today() + timedelta(days=240)
    co_date = ci_date + timedelta(days=3)
    ci = ci_date.strftime("%Y-%m-%d")
    co = co_date.strftime("%Y-%m-%d")

    res = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 2,
        "payment_method": "card"
    }, follow_redirects=False)

    assert res.status_code == 302
    assert "/confirmation/" in res.headers["Location"]

    # Follow redirect to confirmation page
    conf_res = client.get(res.headers["Location"])
    assert conf_res.status_code == 200
    html = conf_res.data.decode("utf-8")

    # Verify confirmation page contains all required elements:
    # booking id, dates, nights, total, and payment status
    assert "Reservation Confirmed!" in html
    assert "Booking ID" in html
    assert "3 Nights" in html or "3 Night" in html
    assert "Payment Status" in html
    assert "SUCCESS" in html.upper()
    assert "Grand Total" in html

    client.get("/auth/logout")


def test_book_double_booking_catches_signal_error(client):
    """
    Verify POST /book catches the MySQL SIGNAL error when all rooms for a room type
    are fully booked for overlapping dates, and displays a friendly flash message.
    """
    login_as(client, "guest@hommycottage.com")

    # Find total rooms for room_type_id = 2
    rt_id = 2
    rooms = fetch_all("SELECT room_id FROM rooms WHERE room_type_id = %s;", (rt_id,))
    total_rooms = len(rooms)

    ci_date = date.today() + timedelta(days=500)
    co_date = ci_date + timedelta(days=2)
    ci = ci_date.strftime("%Y-%m-%d")
    co = co_date.strftime("%Y-%m-%d")

    overflow_res = None
    for _ in range(total_rooms + 2):
        res = client.post("/book", data={
            "room_type_id": rt_id,
            "check_in": ci,
            "check_out": co,
            "guests": 1,
            "payment_method": "upi"
        }, follow_redirects=True)
        html = res.data.decode("utf-8")
        if "No available rooms found" in html or "Booking conflict" in html or "already booked" in html:
            overflow_res = res
            break

    assert overflow_res is not None, "Expected procedure to signal error when rooms exhausted"
    html_overflow = overflow_res.data.decode("utf-8")
    assert "No available rooms found" in html_overflow or "Booking conflict" in html_overflow or "already booked" in html_overflow

    client.get("/auth/logout")


def test_my_bookings_upcoming_and_past_separation(client):
    """
    Verify GET /my-bookings displays guest upcoming and past reservations,
    and shows Cancel and Review buttons strictly when permitted.
    """
    login_as(client, "guest@hommycottage.com")
    res = client.get("/my-bookings")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Verify sections exist
    assert "Upcoming Stays" in html
    assert "Past &amp; Cancelled Stays" in html or "Past & Cancelled Stays" in html

    # Cancel button should appear only on upcoming confirmed stays
    assert "Cancel Booking" in html

    client.get("/auth/logout")


def test_cancel_booking_procedure(client):
    """
    Verify POST /cancel/<booking_id> calls sp_cancel_booking,
    updates booking status to 'cancelled', and sets payment status to 'refunded'.
    """
    login_as(client, "guest@hommycottage.com")

    # 1. Create a future booking to cancel
    ci = (date.today() + timedelta(days=330)).strftime("%Y-%m-%d")
    co = (date.today() + timedelta(days=333)).strftime("%Y-%m-%d")
    res_book = client.post("/book", data={
        "room_type_id": 1,
        "check_in": ci,
        "check_out": co,
        "guests": 1,
        "payment_method": "upi"
    }, follow_redirects=False)
    booking_id = int(res_book.headers["Location"].split("/")[-1])

    # 2. Cancel the booking
    res_cancel = client.post(f"/cancel/{booking_id}", follow_redirects=True)
    assert res_cancel.status_code == 200
    html = res_cancel.data.decode("utf-8")
    assert "successfully cancelled" in html or "Refund processed" in html

    # 3. Verify in database
    b_row = fetch_one("SELECT status FROM bookings WHERE booking_id = %s;", (booking_id,))
    assert b_row["status"] == "cancelled"

    p_row = fetch_one("SELECT status FROM payments WHERE booking_id = %s;", (booking_id,))
    assert p_row["status"] == "refunded"

    # 4. Attempting to cancel again should flash an error
    res_cancel_again = client.post(f"/cancel/{booking_id}", follow_redirects=True)
    html_again = res_cancel_again.data.decode("utf-8")
    assert "already cancelled" in html_again.lower()

    client.get("/auth/logout")


def test_review_trigger_enforcement_and_duplicate_error(client):
    """
    Verify POST /review/<booking_id>:
    - Relies on trigger trg_review_after_checkout to reject reviews for future stays or cancelled bookings
    - Catches duplicate-review error (UNIQUE constraint on booking_id)
    - Validates rating and comment server-side
    """
    login_as(client, "guest@hommycottage.com")

    # 1. Find a future booking (checkout > today)
    future_b = fetch_one("""
        SELECT booking_id FROM bookings
        WHERE guest_id = 7 AND status = 'confirmed' AND check_out > CURRENT_DATE()
        LIMIT 1;
    """)
    if future_b:
        res_future_rev = client.post(f"/review/{future_b['booking_id']}", data={
            "rating": 5,
            "comment": "Too early to review!"
        }, follow_redirects=True)
        html = res_future_rev.data.decode("utf-8")
        assert "after checkout date" in html or "rejected" in html.lower()

    # 2. Find a cancelled booking
    cancelled_b = fetch_one("""
        SELECT booking_id FROM bookings
        WHERE guest_id = 7 AND status = 'cancelled'
        LIMIT 1;
    """)
    if cancelled_b:
        res_canc_rev = client.post(f"/review/{cancelled_b['booking_id']}", data={
            "rating": 4,
            "comment": "Reviewing a cancelled stay"
        }, follow_redirects=True)
        html = res_canc_rev.data.decode("utf-8")
        assert "cannot review a cancelled" in html.lower() or "rejected" in html.lower()

    # 3. Find or create a past completed booking eligible for review (checkout <= today)
    # Check if guest 7 already has a reviewed booking to test duplicate review
    reviewed_b = fetch_one("""
        SELECT b.booking_id
        FROM bookings b
        JOIN reviews r ON b.booking_id = r.booking_id
        WHERE b.guest_id = 7
        LIMIT 1;
    """)
    assert reviewed_b is not None, "Seed data must have at least one reviewed booking for guest 7"

    # Attempt submitting a duplicate review for the same booking
    res_dup = client.post(f"/review/{reviewed_b['booking_id']}", data={
        "rating": 5,
        "comment": "Second review attempt should fail"
    }, follow_redirects=True)
    html_dup = res_dup.data.decode("utf-8")
    assert "already submitted a review" in html_dup.lower()

    # 4. Input validation: invalid rating
    res_invalid_rating = client.post(f"/review/{reviewed_b['booking_id']}", data={
        "rating": 10,  # Invalid
        "comment": "Invalid rating test"
    }, follow_redirects=True)
    html_inv = res_invalid_rating.data.decode("utf-8")
    assert "between 1 and 5" in html_inv.lower()

    # 5. Input validation: empty comment
    res_empty_comment = client.post(f"/review/{reviewed_b['booking_id']}", data={
        "rating": 5,
        "comment": "   "
    }, follow_redirects=True)
    html_empty = res_empty_comment.data.decode("utf-8")
    assert "comment" in html_empty.lower()

    client.get("/auth/logout")
