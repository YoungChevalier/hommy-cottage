"""
Hommy Cottage - Bookings Legacy Blueprint Adapter
================================================
Bridges legacy /bookings/* routes to the unified routes.booking blueprint.
"""
import uuid
from datetime import datetime
from flask import Blueprint, redirect, url_for, request
from routes.booking import booking_bp, book, book_page, confirmation, my_bookings, cancel_booking

bookings_bp = Blueprint("bookings", __name__, url_prefix="/bookings")


def generate_booking_code():
    """Generates a human-friendly unique booking reference (e.g., HC-2026-A8B9C1)."""
    random_part = uuid.uuid4().hex[:6].upper()
    return f"HC-{datetime.now().year}-{random_part}"


def generate_txn_ref():
    """Generates a unique simulated transaction reference ID."""
    return f"TXN-HC-{uuid.uuid4().hex[:8].upper()}"


@bookings_bp.route("/new/<int:cottage_id>", methods=["GET", "POST"])
def new_booking(cottage_id):
    """Bridge for /bookings/new/<cottage_id> -> /book."""
    if request.method == "POST":
        return book()
    return book_page()


@bookings_bp.route("/confirmation/<int:booking_id>")
def confirmation_bridge(booking_id):
    """Bridge for /bookings/confirmation/<id> -> /confirmation/<id>."""
    return confirmation(booking_id)


@bookings_bp.route("/my-bookings")
def my_bookings_bridge():
    """Bridge for /bookings/my-bookings -> /my-bookings."""
    return my_bookings()


@bookings_bp.route("/<int:booking_id>/cancel", methods=["POST"])
def cancel_booking_bridge(booking_id):
    """Bridge for /bookings/<id>/cancel -> /cancel/<id>."""
    return cancel_booking(booking_id)
