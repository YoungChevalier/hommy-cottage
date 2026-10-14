"""
Hommy Cottage - Booking & Reservation Blueprint
==============================================
DBMS College Project (MySQL 8.0, 3NF/BCNF, PyMySQL raw parameterized queries)

Routes:
- POST /book: Calls stored procedure sp_book_room, catches MySQL SIGNAL errors
  and displays friendly flash messages, and redirects to confirmation page.
- GET /book: Renders reservation checkout page with room type and property breakdown.
- GET /confirmation/<booking_id>: Displays booking confirmation receipt (dates, nights, total, payment).
- GET /my-bookings: Guest booking history split into upcoming and past stays,
  with Cancel and Review buttons shown strictly when permitted.
- POST /cancel/<booking_id>: Calls sp_cancel_booking to cancel an upcoming stay.
- POST /review/<booking_id>: Relies on trg_review_after_checkout for stay completion rule
  and catches duplicate-review UNIQUE constraint errors.
"""
from datetime import date, datetime
from decimal import Decimal
import pymysql.err
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from config import Config
from db import get_conn, fetch_one, fetch_all, execute, transaction
from auth_utils import login_required, get_current_user, parse_date

booking_bp = Blueprint("booking", __name__)

# Allowed payment methods whitelist (matches payments.method ENUM)
ALLOWED_METHODS = {"upi", "card", "netbanking", "cash"}


def _call_sp_book_room(guest_id, room_type_id, check_in, check_out, guests, method, room_type):
    """
    Invokes MySQL stored procedure sp_book_room.
    On TiDB Cloud Serverless (which returns errno 8108 for complex procedures),
    executes the identical ACID transaction logic directly via PyMySQL.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SET @new_booking_id = 0;")
            cur.execute(
                "CALL sp_book_room(%s, %s, %s, %s, %s, %s, @new_booking_id);",
                (guest_id, room_type_id, check_in, check_out, guests, method)
            )
            cur.execute("SELECT @new_booking_id AS booking_id;")
            row = cur.fetchone()
            booking_id = row.get("booking_id") if row else None
        conn.commit()
        return booking_id
    except pymysql.err.OperationalError as exc:
        # Check for TiDB unsupported multi-statement procedure compiler error (8108)
        if exc.args and exc.args[0] == 8108:
            return _execute_sp_book_room_acid(guest_id, room_type_id, check_in, check_out, guests, method, room_type)
        raise


def _execute_sp_book_room_acid(guest_id, room_type_id, check_in, check_out, guests, method, room_type):
    """
    ACID transaction fallback implementing the exact business logic of sp_book_room:
    1. Locks room inventory with SELECT ... FOR UPDATE
    2. Finds first available room (no overlapping active bookings)
    3. Inserts booking snapshot with current price_per_night
    4. Inserts payment ledger record with status 'success'
    5. Commits atomically or rolls back on exception
    """
    with transaction() as conn:
        with conn.cursor() as cur:
            # 1. Lock room inventory for this room type
            cur.execute(
                "SELECT COUNT(*) AS total_rooms FROM rooms WHERE room_type_id = %s FOR UPDATE;",
                (room_type_id,)
            )

            # 2. Pick the first free room for requested dates
            cur.execute("""
                SELECT rm.room_id
                FROM rooms rm
                WHERE rm.room_type_id = %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM bookings b
                      WHERE b.room_id = rm.room_id
                        AND b.status != 'cancelled'
                        AND b.check_in < %s
                        AND b.check_out > %s
                  )
                ORDER BY rm.room_id ASC
                LIMIT 1
                FOR UPDATE;
            """, (room_type_id, check_out, check_in))
            room = cur.fetchone()
            if not room or not room.get("room_id"):
                raise pymysql.err.OperationalError(
                    1644,
                    "Booking failed: No available rooms found for the selected dates and room type."
                )

            room_id = room["room_id"]
            nights = (check_out - check_in).days
            price_per_night = Decimal(str(room_type["price_per_night"]))
            total_amount = Decimal(str(nights)) * price_per_night

            # 3. Insert booking
            cur.execute("""
                INSERT INTO bookings (
                    guest_id, room_id, check_in, check_out, guests,
                    price_per_night_at_booking, status
                ) VALUES (%s, %s, %s, %s, %s, %s, 'confirmed');
            """, (guest_id, room_id, check_in, check_out, guests, price_per_night))
            booking_id = cur.lastrowid

            # 4. Insert payment
            cur.execute("""
                INSERT INTO payments (
                    booking_id, amount, method, status, paid_at
                ) VALUES (%s, %s, %s, 'success', CURRENT_TIMESTAMP);
            """, (booking_id, total_amount, method))

            return booking_id


def _call_sp_cancel_booking(booking_id, guest_id):
    """
    Invokes MySQL stored procedure sp_cancel_booking.
    On TiDB Cloud Serverless (errno 8108), executes the identical ACID transaction logic.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("CALL sp_cancel_booking(%s, %s);", (booking_id, guest_id))
        conn.commit()
    except pymysql.err.OperationalError as exc:
        if exc.args and exc.args[0] == 8108:
            _execute_sp_cancel_booking_acid(booking_id, guest_id)
        else:
            raise


def _execute_sp_cancel_booking_acid(booking_id, guest_id):
    """
    ACID transaction fallback implementing the exact business logic of sp_cancel_booking:
    - Verifies booking exists and belongs to guest_id
    - Rejects if already cancelled
    - Rejects if check_in <= CURRENT_DATE() (allowed ONLY before check-in)
    - Updates booking status to 'cancelled' and payment to 'refunded'
    """
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT guest_id, check_in, status
                FROM bookings
                WHERE booking_id = %s
                FOR UPDATE;
            """, (booking_id,))
            b = cur.fetchone()
            if not b:
                raise pymysql.err.OperationalError(1644, "Cancellation failed: Booking not found.")
            if b["guest_id"] != guest_id:
                raise pymysql.err.OperationalError(1644, "Cancellation failed: You can only cancel your own bookings.")
            if b["status"] == "cancelled":
                raise pymysql.err.OperationalError(1644, "Cancellation failed: Booking is already cancelled.")
            if b["check_in"] <= date.today():
                raise pymysql.err.OperationalError(
                    1644,
                    "Cancellation failed: Cancellations are only permitted prior to the check-in date."
                )

            cur.execute("UPDATE bookings SET status = 'cancelled' WHERE booking_id = %s;", (booking_id,))
            cur.execute("UPDATE payments SET status = 'refunded' WHERE booking_id = %s;", (booking_id,))


# =====================================================================
# Route 1: Checkout Form (GET /book)
# =====================================================================
@booking_bp.route("/book", methods=["GET"])
@login_required
def book_page():
    """Renders booking checkout page with room type details and bill calculation."""
    user = get_current_user()
    room_type_id = request.args.get("room_type_id", type=int)
    property_id = request.args.get("property_id") or request.args.get("cottage_id")

    if not room_type_id and property_id:
        # Default to first room type of this property
        rt_row = fetch_one(
            "SELECT room_type_id FROM room_types WHERE property_id = %s ORDER BY price_per_night ASC LIMIT 1;",
            (property_id,)
        )
        if rt_row:
            room_type_id = rt_row["room_type_id"]

    if not room_type_id:
        flash("Please select a valid cottage and room type to reserve.", "warning")
        return redirect(url_for("search.search"))

    sql = """
        SELECT 
            rt.room_type_id, rt.type_name, rt.capacity, rt.price_per_night,
            p.property_id, p.name AS property_name, p.name AS title,
            p.description, p.address, p.pincode, p.status, p.host_id,
            pt.type_name AS property_type,
            c.city_name, c.state, c.city_name AS city,
            COALESCE(img.image_url, '/static/img/sample/p1.jpg') AS primary_image
        FROM room_types rt
        JOIN properties p ON rt.property_id = p.property_id
        JOIN property_types pt ON p.type_id = pt.type_id
        JOIN cities c ON p.city_id = c.city_id
        LEFT JOIN property_images img ON p.property_id = img.property_id AND img.is_primary = TRUE
        WHERE rt.room_type_id = %s AND p.status = 'approved';
    """
    room_type = fetch_one(sql, (room_type_id,))
    if not room_type:
        flash("The selected room type is currently unavailable.", "danger")
        return redirect(url_for("search.search"))

    # Host cannot book their own listing
    if room_type["host_id"] == user["user_id"]:
        flash("Hosts cannot book their own property listing.", "warning")
        return redirect(url_for("search.property_detail", property_id=room_type["property_id"]))

    # Read pre-filled query parameters
    check_in_str = request.args.get("check_in") or request.args.get("check_in_date") or ""
    check_out_str = request.args.get("check_out") or request.args.get("check_out_date") or ""
    guests = request.args.get("guests") or request.args.get("num_guests") or "1"

    # Cottage compatibility alias dictionary for templates
    cottage_dict = dict(room_type)
    cottage_dict["cottage_id"] = room_type["property_id"]
    cottage_dict["base_price_per_night"] = room_type["price_per_night"]
    cottage_dict["max_guests"] = room_type["capacity"]

    return render_template(
        "bookings/book.html",
        room_type=room_type,
        cottage=cottage_dict,
        check_in=check_in_str,
        check_out=check_out_str,
        guests=guests,
        gst_rate=Config.GST_TAX_RATE
    )


# =====================================================================
# Route 2: Execute Booking (POST /book)
# =====================================================================
@booking_bp.route("/book", methods=["POST"])
@login_required
def book():
    """
    Processes room reservation:
    - Server-side validates dates, guests, room type capacity, and payment method whitelist.
    - Calls stored procedure sp_book_room.
    - Catches MySQL SIGNAL errors and flashes user-friendly messages.
    - Redirects to confirmation page on success.
    """
    user = get_current_user()

    # 1. Parse room_type_id
    raw_rt_id = request.form.get("room_type_id") or request.args.get("room_type_id")
    try:
        room_type_id = int(raw_rt_id)
    except (ValueError, TypeError):
        flash("Invalid room type selected.", "danger")
        return redirect(url_for("search.search"))

    # Fetch room type and property details
    sql_rt = """
        SELECT rt.*, p.property_id, p.name AS property_name, p.status, p.host_id
        FROM room_types rt
        JOIN properties p ON rt.property_id = p.property_id
        WHERE rt.room_type_id = %s;
    """
    room_type = fetch_one(sql_rt, (room_type_id,))
    if not room_type or room_type["status"] != "approved":
        flash("Selected room type is invalid or belongs to an unapproved listing.", "danger")
        return redirect(url_for("search.search"))

    # Host cannot book own property
    if room_type["host_id"] == user["user_id"]:
        flash("Hosts cannot book their own property listing.", "warning")
        return redirect(url_for("search.property_detail", property_id=room_type["property_id"]))

    # 2. Server-side Date Validation
    check_in_raw = request.form.get("check_in") or request.form.get("check_in_date", "").strip()
    check_out_raw = request.form.get("check_out") or request.form.get("check_out_date", "").strip()

    check_in = parse_date(check_in_raw)
    check_out = parse_date(check_out_raw)

    if not check_in or not check_out:
        flash("Please provide valid check-in and check-out dates (format: YYYY-MM-DD).", "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw))

    today = date.today()
    if check_in < today:
        flash("Check-in date cannot be in the past.", "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw))

    if check_out <= check_in:
        flash("Check-out date must be strictly after check-in date.", "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw))

    # 3. Server-side Guest Count & Capacity Validation
    guests_raw = request.form.get("guests") or request.form.get("num_guests", "1")
    try:
        guests = int(guests_raw)
        if guests < 1:
            raise ValueError()
    except (ValueError, TypeError):
        flash("Number of guests must be at least 1.", "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw))

    if guests > room_type["capacity"]:
        flash(f"Guest count ({guests}) exceeds the room type capacity ({room_type['capacity']} guests).", "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw))

    # 4. Server-side Payment Method Whitelist Validation
    raw_method = request.form.get("payment_method") or request.form.get("method") or "upi"
    method = raw_method.strip().lower()
    if method not in ALLOWED_METHODS:
        flash(f"Invalid payment method '{method}'. Allowed methods: {', '.join(sorted(ALLOWED_METHODS))}.", "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw))

    # 5. Call Stored Procedure sp_book_room & Catch MySQL SIGNAL errors
    try:
        booking_id = _call_sp_book_room(
            guest_id=user["user_id"],
            room_type_id=room_type_id,
            check_in=check_in,
            check_out=check_out,
            guests=guests,
            method=method,
            room_type=room_type
        )
    except pymysql.err.MySQLError as exc:
        # Extract MySQL SIGNAL error message
        err_msg = exc.args[1] if len(exc.args) > 1 else str(exc)
        if "45000: " in err_msg:
            err_msg = err_msg.split("45000: ", 1)[-1]
        flash(err_msg, "danger")
        return redirect(url_for("booking.book_page", room_type_id=room_type_id, check_in=check_in_raw, check_out=check_out_raw, guests=guests))

    flash(f"Reservation confirmed! Booking reference #{booking_id} created.", "success")
    return redirect(url_for("booking.confirmation", booking_id=booking_id))


# =====================================================================
# Route 3: Booking Confirmation Receipt (GET /confirmation/<booking_id>)
# =====================================================================
@booking_bp.route("/confirmation/<int:booking_id>")
@login_required
def confirmation(booking_id):
    """
    Displays reservation confirmation page showing:
    - booking id
    - check-in and check-out dates
    - total nights
    - total amount
    - payment status and ledger details
    """
    user = get_current_user()

    sql = """
        SELECT 
            b.booking_id, b.guest_id, b.room_id, b.check_in, b.check_out,
            b.guests, b.price_per_night_at_booking, b.status AS booking_status,
            DATEDIFF(b.check_out, b.check_in) AS nights,
            (DATEDIFF(b.check_out, b.check_in) * b.price_per_night_at_booking) AS total_amount,
            p.payment_id, p.amount AS payment_amount, p.method AS payment_method,
            p.status AS payment_status, p.paid_at,
            rm.room_number,
            rt.room_type_id, rt.type_name AS room_type_name,
            prop.property_id, prop.name AS property_name, prop.name AS cottage_title,
            prop.address AS address_line, prop.pincode,
            c.city_name AS city, c.state,
            u_host.name AS host_name, u_host.phone AS host_phone, u_host.email AS host_email,
            u_guest.name AS guest_name, u_guest.email AS guest_email, u_guest.phone AS guest_phone
        FROM bookings b
        JOIN rooms rm ON b.room_id = rm.room_id
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN properties prop ON rt.property_id = prop.property_id
        JOIN cities c ON prop.city_id = c.city_id
        JOIN users u_host ON prop.host_id = u_host.user_id
        JOIN users u_guest ON b.guest_id = u_guest.user_id
        LEFT JOIN payments p ON b.booking_id = p.booking_id
        WHERE b.booking_id = %s;
    """
    booking = fetch_one(sql, (booking_id,))
    if not booking:
        abort(404)

    # Access control: only the booking guest or an admin can view receipt
    if booking["guest_id"] != user["user_id"] and user["role"] != "admin":
        abort(403)

    # Aliases for template compatibility
    booking["booking_code"] = f"HC-B{booking['booking_id']:04d}"
    booking["check_in_date"] = booking["check_in"]
    booking["check_out_date"] = booking["check_out"]
    booking["total_nights"] = booking["nights"]
    booking["num_guests"] = booking["guests"]
    booking["transaction_ref"] = f"TXN-HC-{booking.get('payment_id') or booking_id:06d}"

    return render_template("bookings/confirmation.html", booking=booking)


# =====================================================================
# Route 4: Guest Booking History (GET /my-bookings)
# =====================================================================
@booking_bp.route("/my-bookings")
@login_required
def my_bookings():
    """
    Displays guest reservations split into upcoming and past stays.
    Calculates permissions:
    - Cancel button: Allowed ONLY before check-in on confirmed bookings.
    - Review button: Allowed ONLY after check-out on non-cancelled bookings without existing review.
    """
    user = get_current_user()
    today = date.today()

    sql = """
        SELECT 
            b.booking_id, b.guest_id, b.room_id, b.check_in, b.check_out,
            b.guests, b.price_per_night_at_booking, b.status AS booking_status,
            DATEDIFF(b.check_out, b.check_in) AS nights,
            (DATEDIFF(b.check_out, b.check_in) * b.price_per_night_at_booking) AS total_amount,
            p.payment_id, p.amount AS payment_amount, p.method AS payment_method,
            p.status AS payment_status, p.paid_at,
            rm.room_number,
            rt.room_type_id, rt.type_name AS room_type_name,
            prop.property_id, prop.name AS property_name, prop.name AS cottage_title,
            prop.address,
            c.city_name AS city, c.state,
            COALESCE(img.image_url, '/static/img/sample/p1.jpg') AS primary_image,
            rev.review_id, rev.rating AS review_rating, rev.rating AS given_rating, rev.comment AS review_comment
        FROM bookings b
        JOIN rooms rm ON b.room_id = rm.room_id
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN properties prop ON rt.property_id = prop.property_id
        JOIN cities c ON prop.city_id = c.city_id
        LEFT JOIN property_images img ON prop.property_id = img.property_id AND img.is_primary = TRUE
        LEFT JOIN payments p ON b.booking_id = p.booking_id
        LEFT JOIN reviews rev ON b.booking_id = rev.booking_id
        WHERE b.guest_id = %s
        ORDER BY b.check_in DESC, b.booking_id DESC;
    """
    all_bookings = fetch_all(sql, (user["user_id"],))

    upcoming_bookings = []
    past_bookings = []

    for b in all_bookings:
        # Populate template helper fields
        b["booking_code"] = f"HC-B{b['booking_id']:04d}"
        b["check_in_date"] = b["check_in"]
        b["check_out_date"] = b["check_out"]
        b["total_nights"] = b["nights"]
        b["num_guests"] = b["guests"]
        b["cottage_id"] = b["property_id"]

        # Permission checks
        # Cancel allowed ONLY if confirmed and strictly before check-in date
        b["can_cancel"] = (b["booking_status"] == "confirmed" and b["check_in"] > today)

        # Review allowed ONLY if not cancelled, check_out <= today, and not yet reviewed
        b["can_review"] = (
            b["booking_status"] != "cancelled" and
            b["check_out"] <= today and
            b.get("review_id") is None
        )

        if b["check_in"] >= today and b["booking_status"] != "cancelled":
            upcoming_bookings.append(b)
        else:
            past_bookings.append(b)

    return render_template(
        "bookings/my_bookings.html",
        bookings=all_bookings,
        upcoming_bookings=upcoming_bookings,
        past_bookings=past_bookings,
        today=today
    )


# =====================================================================
# Route 5: Cancel Booking (POST /cancel/<booking_id>)
# =====================================================================
@booking_bp.route("/cancel/<int:booking_id>", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    """
    Cancels an upcoming reservation:
    - Calls stored procedure sp_cancel_booking.
    - Catches MySQL SIGNAL error and shows friendly message.
    - Redirects to my_bookings.
    """
    user = get_current_user()

    try:
        _call_sp_cancel_booking(booking_id, user["user_id"])
        flash(f"Booking #{booking_id} was successfully cancelled. Refund processed.", "info")
    except pymysql.err.MySQLError as exc:
        err_msg = exc.args[1] if len(exc.args) > 1 else str(exc)
        if "45000: " in err_msg:
            err_msg = err_msg.split("45000: ", 1)[-1]
        flash(err_msg, "danger")

    return redirect(url_for("booking.my_bookings"))


# =====================================================================
# Route 6: Submit Review (POST /review/<booking_id>)
# =====================================================================
@booking_bp.route("/review/<int:booking_id>", methods=["POST"])
@login_required
def add_review(booking_id):
    """
    Submits guest review and star rating:
    - Server-side validates rating (1-5) and comment (non-empty).
    - Relies on trigger trg_review_after_checkout for checkout date and cancellation rules.
    - Catches MySQL duplicate-review error (UNIQUE constraint on booking_id).
    """
    user = get_current_user()

    # 1. Fetch booking to check ownership
    booking = fetch_one(
        "SELECT booking_id, guest_id, status, check_out FROM bookings WHERE booking_id = %s;",
        (booking_id,)
    )
    if not booking:
        abort(404)

    if booking["guest_id"] != user["user_id"] and user["role"] != "admin":
        abort(403)

    # 2. Server-side validation for rating and comment
    rating_raw = request.form.get("rating", "5").strip()
    comment = request.form.get("comment", "").strip()

    try:
        rating = int(rating_raw)
        if rating < 1 or rating > 5:
            raise ValueError()
    except (ValueError, TypeError):
        flash("Rating must be an integer between 1 and 5.", "danger")
        return redirect(url_for("booking.my_bookings"))

    if not comment:
        flash("Please provide a review comment describing your stay.", "danger")
        return redirect(url_for("booking.my_bookings"))

    # 3. Attempt Review Insertion
    # Trigger trg_review_after_checkout enforces:
    # - Cannot review cancelled reservation
    # - Cannot review before checkout date
    # On engines without active triggers (e.g. TiDB), emulate the trigger's SIGNAL
    try:
        if booking["status"] == "cancelled":
            raise pymysql.err.OperationalError(
                1644,
                "Review rejected: Cannot review a cancelled reservation."
            )
        if booking["check_out"] > date.today():
            raise pymysql.err.OperationalError(
                1644,
                "Review rejected: Reviews can only be submitted after checkout date."
            )

        sql_insert = "INSERT INTO reviews (booking_id, rating, comment) VALUES (%s, %s, %s);"
        execute(sql_insert, (booking_id, rating, comment))
        flash("Thank you! Your stay review has been submitted successfully.", "success")
    except pymysql.err.IntegrityError as exc:
        # Catches duplicate-review error (UNIQUE key on reviews.booking_id, MySQL error 1062)
        flash("You have already submitted a review for this booking.", "warning")
    except pymysql.err.MySQLError as exc:
        # Catches MySQL SIGNAL error from trigger trg_review_after_checkout
        err_msg = exc.args[1] if len(exc.args) > 1 else str(exc)
        if "45000: " in err_msg:
            err_msg = err_msg.split("45000: ", 1)[-1]
        flash(err_msg, "danger")

    return redirect(url_for("booking.my_bookings"))


# Backward-compatibility alias for blueprints
bookings_bp = booking_bp
