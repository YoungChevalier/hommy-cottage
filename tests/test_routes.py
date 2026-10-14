"""
Hommy Cottage - Application Routing & Filters Tests
Validates blueprint endpoint availability, template filters, and HTTP error handlers.
"""
from datetime import date


def test_about_page_renders(client):
    """Verify /about page serves About Us brand story."""
    response = client.get("/about")
    assert response.status_code == 200
    assert b"Where Mountain Serenity Meets Cozy Hospitality" in response.data
    assert b"Handcrafted Nature Escapes" in response.data


def test_login_page_renders(client):
    """Verify /auth/login page serves login form with demo credentials pills."""
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Welcome Back" in response.data
    assert b"Quick Demo Access" in response.data


def test_register_page_renders(client):
    """Verify /auth/register serves guest and host registration options."""
    response = client.get("/auth/register")
    assert response.status_code == 200
    assert b"Book Cottages (Guest)" in response.data
    assert b"List My Cottage (Host)" in response.data


def test_404_error_page(client):
    """Verify nonexistent URL triggers custom 404 error page."""
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    assert b"404 - Page Not Found" in response.data


def test_currency_and_date_template_filters(app):
    """Verify custom Jinja filters format Indian currency and dates properly."""
    with app.app_context():
        currency_filter = app.jinja_env.filters["currency_inr"]
        date_filter = app.jinja_env.filters["format_date"]

        assert currency_filter(3800) == "₹3,800.00"
        assert currency_filter(0) == "₹0.00"

        test_date = date(2026, 10, 15)
        assert date_filter(test_date) == "15 Oct 2026"
