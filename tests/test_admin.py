"""
Hommy Cottage - Admin Portal Test Suite
=======================================
Validates all administrative endpoints and security constraints in routes/admin.py:
1. Role-Based Access Control (RBAC):
   - All admin routes strictly enforce @role_required('admin')
   - Unauthenticated visitors are redirected to /auth/login (302)
   - Guests (role='guest') and hosts (role='host') are blocked with 403 Forbidden
   - Admins (role='admin') receive 200 OK
2. Pending Listings Moderation Queue:
   - GET /admin/listings/pending (and /admin/cottages) defaults to status='pending'
   - Supports status filtering: ?status=approved, ?status=rejected, ?status=all
   - Displays property name, host contact info, and pricing
3. Listing Approval Workflow:
   - POST /admin/property/<id>/approve is strictly POST ONLY (GET returns 405)
   - Updates status to 'approved' and clears any prior rejection_note (NULL)
   - Non-existent property returns 404
4. Listing Rejection Workflow:
   - POST /admin/property/<id>/reject is strictly POST ONLY (GET returns 405)
   - Supports optional rejection_note; records note in database
   - Updates status to 'rejected'
   - Non-existent property returns 404
5. User Account Directory & Host Status Toggle:
   - GET /admin/users lists platform users with role filtering (?role=host, ?role=guest)
   - POST /admin/users/<id>/toggle-status is strictly POST ONLY (GET returns 405)
   - Toggles is_active between TRUE and FALSE for hosts / guests
   - Prohibits admin self-deactivation (session admin cannot deactivate themselves)
   - Non-existent user returns 404
6. Operational & Financial Reports:
   - GET /admin/reports queries:
     * host_revenue_view
     * city_revenue_view
     * Window-function ranking query: RANK() OVER (PARTITION BY city_id) and DENSE_RANK() OVER (ORDER BY revenue DESC)
7. CSV Export for Revenue Report:
   - GET /admin/reports/export-csv returns status 200 with mimetype text/csv
   - Sets Content-Disposition header with hommy_cottage_revenue_report.csv
   - Includes standard header row and accurate property revenue rows
"""
import io
import csv
import pytest
from db import fetch_one, fetch_all, execute

ADMIN_EMAIL = "admin@hommycottage.com"
HOST_EMAIL = "host@hommycottage.com"
GUEST_EMAIL = "guest@hommycottage.com"


@pytest.fixture(autouse=True)
def restore_admin_test_state():
    """Restores baseline state for modified properties and users after each test."""
    yield
    # Restore properties 27-30 to pending, 31-32 to rejected, 1-26 to approved
    execute("UPDATE properties SET status = 'pending', rejection_note = NULL WHERE property_id IN (27, 28, 29, 30);")
    execute("UPDATE properties SET status = 'rejected', rejection_note = NULL WHERE property_id IN (31, 32);")
    execute("UPDATE properties SET status = 'approved', rejection_note = NULL WHERE property_id BETWEEN 1 AND 26;")
    # Ensure users 1, 2, 3, 7 have is_active = TRUE and original roles
    execute("UPDATE users SET is_active = TRUE WHERE user_id IN (1, 2, 3, 7);")
    execute("UPDATE users SET role = 'admin' WHERE user_id = 1;")
    execute("UPDATE users SET role = 'host' WHERE user_id IN (2, 3);")
    execute("UPDATE users SET role = 'guest' WHERE user_id = 7;")


def login_as(client, email, password="password123"):
    """Authenticates the test client with given user credentials."""
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


# =============================================================================
# 1. RBAC & Access Control Tests
# =============================================================================
@pytest.mark.parametrize("endpoint", [
    "/admin/dashboard",
    "/admin/listings/pending",
    "/admin/cottages",
    "/admin/users",
    "/admin/reports",
    "/admin/reports/export-csv",
    "/admin/bookings"
])
def test_admin_routes_unauthenticated_redirect(client, endpoint):
    """Unauthenticated users attempting to access admin routes must be redirected to login."""
    res = client.get(endpoint)
    assert res.status_code == 302
    assert "/auth/login" in res.headers["Location"]


@pytest.mark.parametrize("endpoint", [
    "/admin/dashboard",
    "/admin/listings/pending",
    "/admin/cottages",
    "/admin/users",
    "/admin/reports",
    "/admin/reports/export-csv",
    "/admin/bookings"
])
def test_admin_routes_forbidden_for_guest(client, endpoint):
    """Guests (role='guest') must be blocked with 403 Forbidden on all admin endpoints."""
    login_as(client, GUEST_EMAIL)
    res = client.get(endpoint)
    assert res.status_code == 403


@pytest.mark.parametrize("endpoint", [
    "/admin/dashboard",
    "/admin/listings/pending",
    "/admin/cottages",
    "/admin/users",
    "/admin/reports",
    "/admin/reports/export-csv",
    "/admin/bookings"
])
def test_admin_routes_forbidden_for_host(client, endpoint):
    """Hosts (role='host') must be blocked with 403 Forbidden on all admin endpoints."""
    login_as(client, HOST_EMAIL)
    res = client.get(endpoint)
    assert res.status_code == 403


def test_admin_dashboard_success(client):
    """Administrator receives 200 OK on admin dashboard with KPIs and recent bookings."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Platform Administration" in html
    assert "Pending Approval" in html or "Pending Queue" in html
    assert "Total Users" in html


# =============================================================================
# 2. Pending Listings Moderation Queue Tests
# =============================================================================
def test_pending_listings_queue_default(client):
    """GET /admin/listings/pending defaults to pending properties."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/listings/pending")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Property Listings Moderation Queue" in html
    assert "Pending Queue" in html

    # Verify at least one known pending property from seed appears (e.g., ID 27 or 28)
    assert "Tea Garden Cloud Canopy Treehouse" in html or "Misty Western Ghats" in html


def test_pending_listings_queue_filter_status(client):
    """Filtering by status displays matching properties."""
    login_as(client, ADMIN_EMAIL)

    # Approved filter
    res_app = client.get("/admin/listings/pending?status=approved")
    assert res_app.status_code == 200
    html_app = res_app.data.decode("utf-8")
    assert "Chinar Valley Country Cottage" in html_app

    # Rejected filter
    res_rej = client.get("/admin/listings/pending?status=rejected")
    assert res_rej.status_code == 200
    html_rej = res_rej.data.decode("utf-8")
    assert "Neelkanth Forest View Yoga Villa" in html_rej or "Shivpuri Riverstone Beach Treehouse" in html_rej

    # All filter
    res_all = client.get("/admin/listings/pending?status=all")
    assert res_all.status_code == 200


# =============================================================================
# 3. Listing Approval Workflow Tests (POST ONLY)
# =============================================================================
def test_approve_property_post_only(client):
    """GET request to approve endpoint must be rejected with 405 Method Not Allowed."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/property/27/approve")
    assert res.status_code == 405


def test_approve_property_success(client):
    """POST /admin/property/<id>/approve transitions status to 'approved' and clears rejection_note."""
    login_as(client, ADMIN_EMAIL)

    # Ensure property 27 is initially pending
    prop_before = fetch_one("SELECT status FROM properties WHERE property_id = 27")
    assert prop_before["status"] == "pending"

    res = client.post("/admin/property/27/approve", follow_redirects=True)
    assert res.status_code == 200

    prop_after = fetch_one("SELECT status, rejection_note FROM properties WHERE property_id = 27")
    assert prop_after["status"] == "approved"
    assert prop_after["rejection_note"] is None


def test_approve_property_alias_endpoint(client):
    """Legacy alias POST /admin/cottages/<id>/approve also works."""
    login_as(client, ADMIN_EMAIL)
    res = client.post("/admin/cottages/28/approve", follow_redirects=True)
    assert res.status_code == 200

    prop_after = fetch_one("SELECT status FROM properties WHERE property_id = 28")
    assert prop_after["status"] == "approved"


def test_approve_property_nonexistent(client):
    """Approving non-existent property returns 404."""
    login_as(client, ADMIN_EMAIL)
    res = client.post("/admin/property/999999/approve")
    assert res.status_code == 404


# =============================================================================
# 4. Listing Rejection Workflow Tests (POST ONLY)
# =============================================================================
def test_reject_property_post_only(client):
    """GET request to reject endpoint must be rejected with 405 Method Not Allowed."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/property/29/reject")
    assert res.status_code == 405


def test_reject_property_without_note(client):
    """POST /admin/property/<id>/reject transitions status to 'rejected' without a note."""
    login_as(client, ADMIN_EMAIL)

    res = client.post("/admin/property/29/reject", data={}, follow_redirects=True)
    assert res.status_code == 200

    prop_after = fetch_one("SELECT status, rejection_note FROM properties WHERE property_id = 29")
    assert prop_after["status"] == "rejected"
    assert prop_after["rejection_note"] is None


def test_reject_property_with_optional_note(client):
    """POST /admin/property/<id>/reject with a rejection note saves the note in DB."""
    login_as(client, ADMIN_EMAIL)

    test_note = "Missing mandatory municipal fire safety permit and high-resolution exterior images."
    res = client.post(
        "/admin/property/30/reject",
        data={"rejection_note": test_note},
        follow_redirects=True
    )
    assert res.status_code == 200

    prop_after = fetch_one("SELECT status, rejection_note FROM properties WHERE property_id = 30")
    assert prop_after["status"] == "rejected"
    assert prop_after["rejection_note"] == test_note

    # Check flash message contains rejection note
    html = res.data.decode("utf-8")
    assert "REJECTED" in html
    assert "Missing mandatory municipal fire safety permit" in html


def test_reject_property_nonexistent(client):
    """Rejecting non-existent property returns 404."""
    login_as(client, ADMIN_EMAIL)
    res = client.post("/admin/property/999999/reject", data={"rejection_note": "Test note"})
    assert res.status_code == 404


# =============================================================================
# 5. User Account Directory & Host Status Toggle Tests
# =============================================================================
def test_users_list_view(client):
    """Admin views user directory with contact info and roles."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/users")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "User Account Directory" in html
    assert "admin@hommycottage.com" in html
    assert "host@hommycottage.com" in html
    assert "guest@hommycottage.com" in html


def test_users_list_filter_role(client):
    """Filtering users directory by role."""
    login_as(client, ADMIN_EMAIL)

    res_hosts = client.get("/admin/users?role=host")
    assert res_hosts.status_code == 200
    html_hosts = res_hosts.data.decode("utf-8")
    assert "host@hommycottage.com" in html_hosts


def test_toggle_user_status_post_only(client):
    """GET request to toggle-status must be rejected with 405 Method Not Allowed."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/users/2/toggle-status")
    assert res.status_code == 405


def test_toggle_host_active_status(client):
    """Admin deactivates and subsequently reactivates a host account."""
    login_as(client, ADMIN_EMAIL)

    # 1. Deactivate host 2
    res_deact = client.post("/admin/users/2/toggle-status", follow_redirects=True)
    assert res_deact.status_code == 200
    user_deact = fetch_one("SELECT is_active FROM users WHERE user_id = 2")
    assert bool(user_deact["is_active"]) is False

    # 2. Reactivate host 2
    res_react = client.post("/admin/users/2/toggle-status", follow_redirects=True)
    assert res_react.status_code == 200
    user_react = fetch_one("SELECT is_active FROM users WHERE user_id = 2")
    assert bool(user_react["is_active"]) is True


def test_toggle_user_status_self_deactivation_prohibited(client):
    """Admin cannot deactivate their own active administrator account."""
    login_as(client, ADMIN_EMAIL)

    admin_record = fetch_one("SELECT user_id, is_active FROM users WHERE email = %s", (ADMIN_EMAIL,))
    admin_id = admin_record["user_id"]

    res = client.post(f"/admin/users/{admin_id}/toggle-status", follow_redirects=True)
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "cannot deactivate your own active administrator account" in html

    # Verify admin remains active in DB
    admin_after = fetch_one("SELECT is_active FROM users WHERE user_id = %s", (admin_id,))
    assert bool(admin_after["is_active"]) is True


def test_toggle_user_status_nonexistent(client):
    """Toggling status of non-existent user returns 404."""
    login_as(client, ADMIN_EMAIL)
    res = client.post("/admin/users/999999/toggle-status")
    assert res.status_code == 404


# =============================================================================
# 6. Financial & Revenue Reports Tests
# =============================================================================
def test_admin_reports_page(client):
    """Admin reports page renders host_revenue_view, city_revenue_view, and window-function rankings."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/reports")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Page Header and KPIs
    assert "Platform Revenue &amp; Performance" in html or "Platform Revenue & Performance" in html or "Revenue & Analytical Reports" in html
    assert "Export Revenue Report (CSV)" in html

    # Section 1: Window Function Rankings
    assert "Property Revenue Leaderboard" in html
    assert "RANK() OVER" in html
    assert "City Rank" in html

    # Section 2: Host Performance View
    assert "Host Revenue Performance" in html
    assert "host_revenue_view" in html

    # Section 3: Regional Volume View
    assert "Destination Marketplace Volume" in html
    assert "city_revenue_view" in html


# =============================================================================
# 7. CSV Export for Revenue Report Tests
# =============================================================================
def test_admin_revenue_csv_export(client):
    """GET /admin/reports/export-csv produces a downloadable UTF-8 CSV with revenue ranks."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/reports/export-csv")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("Content-Type", "")
    assert "attachment" in res.headers.get("Content-Disposition", "")
    assert "hommy_cottage_revenue_report.csv" in res.headers.get("Content-Disposition", "")

    # Parse CSV contents
    csv_text = res.data.decode("utf-8")
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    # Validate Header
    expected_header = [
        "Platform Rank",
        "City Rank",
        "Property ID",
        "Property Name",
        "City",
        "State",
        "Host Name",
        "Host Email",
        "Successful Bookings",
        "Total Revenue (INR)"
    ]
    assert len(rows) >= 2, "CSV must contain at least a header and data rows"
    assert rows[0] == expected_header

    # Validate Data Rows contain numbers and valid property names
    for row in rows[1:]:
        assert len(row) == 10
        # Platform Rank must be an integer
        assert row[0].isdigit()
        # City Rank must be an integer
        assert row[1].isdigit()
        # Total Revenue must be a parseable float
        float(row[9])


def test_admin_revenue_csv_alias(client):
    """GET /admin/reports/export also produces valid CSV export."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/reports/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("Content-Type", "")


# =============================================================================
# 8. Admin Bookings Overview Tests
# =============================================================================
def test_admin_bookings_view(client):
    """Admin views platform-wide reservations."""
    login_as(client, ADMIN_EMAIL)
    res = client.get("/admin/bookings")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Global Bookings & Payment Ledger" in html or "Platform Bookings" in html
