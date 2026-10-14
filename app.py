"""
Hommy Cottage - Vacation Stays & Cottage Booking Application
=============================================================
Application Factory, Blueprint Registration, Context Processors,
and Centralized Error Handlers (403, 404, 413, 500).
"""
from datetime import datetime, date
from flask import Flask, render_template
from config import Config
from db import init_app_db
from auth_utils import get_current_user

from werkzeug.middleware.proxy_fix import ProxyFix

# Import Blueprints
from routes.search import search_bp
from routes.main import main_bp
from routes.auth import auth_bp
from routes.cottages import cottages_bp
from routes.booking import booking_bp
from routes.bookings import bookings_bp
from routes.host import host_bp
from routes.admin import admin_bp
from routes.reviews import reviews_bp


def create_app(config_class=Config):
    """Application factory for Hommy Cottage."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Reverse proxy support for custom domains and HTTPS behind Render/Cloudflare
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Initialize Database teardown handler
    init_app_db(app)

    # Global context processor to make current_user available across all Jinja2 templates
    @app.context_processor
    def inject_globals():
        return {
            "current_user": get_current_user(),
            "current_year": datetime.now().year
        }

    # Template Filters for Indian Currency and Date Formatting
    @app.template_filter("currency_inr")
    def currency_inr(val):
        """Formats numbers into standard Indian Rupee format (e.g. ₹3,800.00)."""
        try:
            return f"₹{float(val):,.2f}"
        except (ValueError, TypeError):
            return "₹0.00"

    @app.template_filter("format_date")
    def format_date(val):
        """Formats dates to human-friendly strings (e.g. 15 Oct 2026)."""
        if not val:
            return ""
        if isinstance(val, (date, datetime)):
            return val.strftime("%d %b %Y")
        if isinstance(val, str):
            try:
                parsed = datetime.strptime(val, "%Y-%m-%d").date()
                return parsed.strftime("%d %b %Y")
            except ValueError:
                return val
        return str(val)

    # Register Blueprints
    app.register_blueprint(search_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(cottages_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(host_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(reviews_bp)

    # Centralized HTTP Error Handlers (Rendering templates/error.html)
    @app.errorhandler(403)
    def forbidden_error(e):
        return render_template(
            "error.html",
            code=403,
            title="Access Forbidden",
            message="You do not have permission to view or access this section of Hommy Cottage."
        ), 403

    @app.errorhandler(404)
    def not_found_error(e):
        return render_template(
            "error.html",
            code=404,
            title="Page Not Found",
            message="The cottage, page, or resource you are looking for does not exist or has been relocated."
        ), 404

    @app.errorhandler(413)
    def request_entity_too_large(e):
        return render_template(
            "error.html",
            code=413,
            title="File Too Large",
            message="The uploaded photo exceeds the allowed file upload limit (maximum 16 MB)."
        ), 413

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template(
            "error.html",
            code=500,
            title="Internal Server Error",
            message="An unexpected server error occurred while processing your request. Please try again later."
        ), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
