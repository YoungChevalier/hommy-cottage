"""
Hommy Cottage - Main Blueprint
Handles Landing Page and About Us brand story.
"""
from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Delegates home route to search blueprint index."""
    from routes.search import index as search_index
    return search_index()


@main_bp.route("/about")
def about():
    """
    About Us page presenting the brand story, core pillars,
    and nature getaway standards.
    """
    return render_template("main/about.html")
