"""
Hommy Cottage - Reviews Blueprint Adapter
========================================
Bridges /reviews/add/<booking_id> to routes.booking.add_review.
"""
from flask import Blueprint
from routes.booking import add_review

reviews_bp = Blueprint("reviews", __name__, url_prefix="/reviews")


@reviews_bp.route("/add/<int:booking_id>", methods=["POST"])
def add_review_bridge(booking_id):
    """Bridge for /reviews/add/<id> -> routes.booking.add_review."""
    return add_review(booking_id)
