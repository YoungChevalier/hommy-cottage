"""
Hommy Cottage - Admin Portal Blueprint
======================================
Provides comprehensive platform administration strictly restricted to administrators:
1. Pending Listings Queue: Moderation workflow with approve/reject (POST only) and optional rejection notes.
2. User Directory: Oversight across Guest, Host, and Admin accounts with activate/deactivate toggling.
3. Financial & Operational Reports:
   - host_revenue_view (host performance and gross receipts)
   - city_revenue_view (regional market demand and volume)
   - Window-function ranking query: Intragroup ranking via RANK() OVER (PARTITION BY city_id)
     and overall platform ranking via DENSE_RANK() OVER (ORDER BY total_revenue DESC).
4. CSV Export: Downloadable revenue report for accounting and audit compliance.
"""
import io
import csv
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, Response, session
)
from db import fetch_all, fetch_one, execute
from auth_utils import role_required, get_current_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# =============================================================================
# 1. Admin Dashboard (Overview & Platform KPIs)
# =============================================================================
@admin_bp.route("/")
@admin_bp.route("/dashboard")
@role_required("admin")
def dashboard():
    """Admin KPI overview, platform health metrics, and recent activity."""
    # Aggregated platform statistics
    stats = {
        "total_users": fetch_one("SELECT COUNT(*) AS c FROM users")["c"],
        "total_hosts": fetch_one("SELECT COUNT(*) AS c FROM users WHERE role = 'host'")["c"],
        "total_guests": fetch_one("SELECT COUNT(*) AS c FROM users WHERE role = 'guest'")["c"],
        "active_hosts": fetch_one("SELECT COUNT(*) AS c FROM users WHERE role = 'host' AND is_active = TRUE")["c"],
        "total_properties": fetch_one("SELECT COUNT(*) AS c FROM properties")["c"],
        "pending_approval": fetch_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'pending'")["c"],
        "approved_properties": fetch_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'approved'")["c"],
        "rejected_properties": fetch_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'rejected'")["c"],
        "total_bookings": fetch_one("SELECT COUNT(*) AS c FROM bookings")["c"],
        "total_revenue": fetch_one("""
            SELECT COALESCE(SUM(amount), 0.00) AS s 
            FROM payments 
            WHERE status = 'success';
        """)["s"],
    }

    # Recent 6 platform-wide bookings
    sql_recent = """
        SELECT 
            b.booking_id,
            b.check_in,
            b.check_out,
            b.status AS booking_status,
            p.name AS property_name,
            c.city_name,
            rm.room_number,
            rt.type_name AS room_type,
            u_guest.name AS guest_name,
            u_host.name AS host_name,
            pay.amount,
            pay.status AS payment_status
        FROM bookings b
        JOIN rooms rm ON b.room_id = rm.room_id
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN properties p ON rt.property_id = p.property_id
        JOIN cities c ON p.city_id = c.city_id
        JOIN users u_guest ON b.guest_id = u_guest.user_id
        JOIN users u_host ON p.host_id = u_host.user_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        ORDER BY b.booking_id DESC
        LIMIT 6;
    """
    recent_bookings = fetch_all(sql_recent)

    # Top 5 pending properties awaiting review
    sql_pending_preview = """
        SELECT 
            p.property_id,
            p.name,
            p.created_at,
            c.city_name,
            pt.type_name,
            u.name AS host_name,
            u.email AS host_email
        FROM properties p
        JOIN cities c ON p.city_id = c.city_id
        JOIN property_types pt ON p.type_id = pt.type_id
        JOIN users u ON p.host_id = u.user_id
        WHERE p.status = 'pending'
        ORDER BY p.created_at ASC
        LIMIT 5;
    """
    pending_preview = fetch_all(sql_pending_preview)

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_bookings=recent_bookings,
        pending_preview=pending_preview
    )


# =============================================================================
# 2. Pending Listings Moderation Queue
# =============================================================================
@admin_bp.route("/listings/pending", endpoint="pending_listings")
@admin_bp.route("/pending")
@admin_bp.route("/cottages", endpoint="cottages_list")
@role_required("admin")
def cottages_list():
    """
    Pending Listings Queue:
    - Lists properties with status 'pending' requiring administrator moderation.
    - Also supports filtering by status ('pending', 'approved', 'rejected', 'all').
    """
    status_filter = request.args.get("status", "pending").strip().lower()
    
    base_sql = """
        SELECT 
            p.property_id,
            p.host_id,
            p.name,
            p.description,
            p.address,
            p.pincode,
            p.status,
            p.rejection_note,
            p.created_at,
            c.city_name,
            c.state,
            pt.type_name,
            u.name AS host_name,
            u.email AS host_email,
            u.phone AS host_phone,
            COALESCE(
                (SELECT image_url FROM property_images WHERE property_id = p.property_id AND is_primary = TRUE LIMIT 1),
                (SELECT image_url FROM property_images WHERE property_id = p.property_id ORDER BY image_id ASC LIMIT 1),
                '/static/img/sample/default.jpg'
            ) AS primary_image,
            COUNT(DISTINCT rt.room_type_id) AS room_types_count,
            COUNT(DISTINCT rm.room_id) AS total_rooms,
            COALESCE(MIN(rt.price_per_night), 0.00) AS starting_price,
            COUNT(DISTINCT b.booking_id) AS total_bookings
        FROM properties p
        JOIN users u ON p.host_id = u.user_id
        JOIN cities c ON p.city_id = c.city_id
        JOIN property_types pt ON p.type_id = pt.type_id
        LEFT JOIN room_types rt ON p.property_id = rt.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        LEFT JOIN bookings b ON rm.room_id = b.room_id
    """

    if status_filter in ["pending", "approved", "rejected"]:
        where_clause = " WHERE p.status = %s "
        params = (status_filter,)
    else:
        where_clause = ""
        params = ()

    group_clause = """
        GROUP BY 
            p.property_id, p.host_id, p.name, p.description, p.address,
            p.pincode, p.status, p.rejection_note, p.created_at, c.city_name,
            c.state, pt.type_name, u.name, u.email, u.phone
        ORDER BY 
            CASE WHEN p.status = 'pending' THEN 1 WHEN p.status = 'approved' THEN 2 ELSE 3 END,
            p.created_at DESC;
    """

    properties = fetch_all(base_sql + where_clause + group_clause, params)

    # Queue summary count pills
    counts = {
        "pending": fetch_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'pending'")["c"],
        "approved": fetch_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'approved'")["c"],
        "rejected": fetch_one("SELECT COUNT(*) AS c FROM properties WHERE status = 'rejected'")["c"],
        "total": fetch_one("SELECT COUNT(*) AS c FROM properties")["c"]
    }

    return render_template(
        "admin/cottages.html",
        properties=properties,
        cottages=properties,  # Backward-compatibility alias
        current_status=status_filter,
        counts=counts
    )


# =============================================================================
# 3. Approve / Reject (POST only with optional rejection note)
# =============================================================================
@admin_bp.route("/property/<int:property_id>/approve", endpoint="approve_property", methods=["POST"])
@admin_bp.route("/cottages/<int:property_id>/approve", methods=["POST"])
@role_required("admin")
def approve_property(property_id):
    """
    Approve Property Listing (POST ONLY):
    Transitions property status to 'approved' and clears any prior rejection notes.
    Makes the listing immediately visible on public search.
    """
    prop = fetch_one("SELECT property_id, name, status FROM properties WHERE property_id = %s", (property_id,))
    if not prop:
        abort(404)

    sql = "UPDATE properties SET status = 'approved', rejection_note = NULL WHERE property_id = %s;"
    execute(sql, (property_id,))

    flash(f"Property '{prop['name']}' has been APPROVED and is now live on Trivago search.", "success")
    return redirect(request.referrer or url_for("admin.cottages_list"))


@admin_bp.route("/property/<int:property_id>/reject", endpoint="reject_property", methods=["POST"])
@admin_bp.route("/cottages/<int:property_id>/reject", methods=["POST"])
@role_required("admin")
def reject_property(property_id):
    """
    Reject Property Listing (POST ONLY):
    Transitions property status to 'rejected' and stores an optional rejection note.
    Removes property from public search results while keeping it visible to its host.
    """
    prop = fetch_one("SELECT property_id, name, status FROM properties WHERE property_id = %s", (property_id,))
    if not prop:
        abort(404)

    rejection_note = request.form.get("rejection_note", "").strip() or None

    sql = "UPDATE properties SET status = 'rejected', rejection_note = %s WHERE property_id = %s;"
    execute(sql, (rejection_note, property_id))

    msg = f"Property '{prop['name']}' has been REJECTED."
    if rejection_note:
        msg += f" Note recorded: \"{rejection_note}\""
    flash(msg, "warning")
    return redirect(request.referrer or url_for("admin.cottages_list"))


# Backward-compatible toggle approval route
@admin_bp.route("/cottages/<int:cottage_id>/toggle-approval", methods=["POST"])
@role_required("admin")
def toggle_approval(cottage_id):
    """Legacy toggle route mapping to approve/reject workflow."""
    prop = fetch_one("SELECT property_id, status FROM properties WHERE property_id = %s", (cottage_id,))
    if not prop:
        abort(404)
    if prop["status"] == "approved":
        return reject_property(cottage_id)
    else:
        return approve_property(cottage_id)


# =============================================================================
# 4. User Account Directory & Host Activation / Deactivation
# =============================================================================
@admin_bp.route("/users", endpoint="users_list")
@role_required("admin")
def users_list():
    """
    User Management:
    - Lists registered accounts with roles ('guest', 'host', 'admin').
    - Displays active/deactivated status.
    - Role filter buttons.
    """
    role_filter = request.args.get("role", "").strip().lower()

    sql = """
        SELECT 
            u.user_id,
            u.name,
            u.name AS full_name,
            u.email,
            u.phone,
            u.role,
            COALESCE(u.is_active, TRUE) AS is_active,
            u.created_at,
            COUNT(DISTINCT p.property_id) AS properties_count,
            COUNT(DISTINCT b.booking_id) AS bookings_count
        FROM users u
        LEFT JOIN properties p ON u.user_id = p.host_id
        LEFT JOIN bookings b ON u.user_id = b.guest_id
    """
    if role_filter in ["guest", "host", "admin"]:
        sql += " WHERE u.role = %s "
        params = (role_filter,)
    else:
        params = ()

    sql += " GROUP BY u.user_id, u.name, u.email, u.phone, u.role, u.is_active, u.created_at ORDER BY u.created_at DESC;"

    users = fetch_all(sql, params)

    counts = {
        "all": fetch_one("SELECT COUNT(*) AS c FROM users")["c"],
        "guest": fetch_one("SELECT COUNT(*) AS c FROM users WHERE role = 'guest'")["c"],
        "host": fetch_one("SELECT COUNT(*) AS c FROM users WHERE role = 'host'")["c"],
        "admin": fetch_one("SELECT COUNT(*) AS c FROM users WHERE role = 'admin'")["c"]
    }

    return render_template(
        "admin/users.html",
        users=users,
        selected_role=role_filter,
        counts=counts
    )


@admin_bp.route("/users/<int:user_id>/toggle-status", endpoint="toggle_user_status", methods=["POST"])
@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@role_required("admin")
def toggle_user_status(user_id):
    """
    Activate / Deactivate Host or User Account (POST ONLY):
    Toggles the is_active flag. Prevents admins from deactivating their own account.
    """
    admin_id = session.get("user_id")
    if user_id == admin_id:
        flash("Action prohibited: You cannot deactivate your own active administrator account.", "danger")
        return redirect(url_for("admin.users_list"))

    target_user = fetch_one("SELECT user_id, name, email, role, is_active FROM users WHERE user_id = %s", (user_id,))
    if not target_user:
        abort(404)

    current_active = bool(target_user.get("is_active", True))
    new_active = not current_active

    execute("UPDATE users SET is_active = %s WHERE user_id = %s;", (new_active, user_id))

    action_label = "activated" if new_active else "deactivated"
    flash(
        f"Account '{target_user['name']}' ({target_user['email']} - {target_user['role'].capitalize()}) "
        f"has been {action_label} successfully.",
        "success" if new_active else "warning"
    )
    return redirect(url_for("admin.users_list"))


@admin_bp.route("/users/<int:user_id>/change-role", methods=["POST"])
@role_required("admin")
def change_role(user_id):
    """Admin updates user account role."""
    new_role = request.form.get("new_role", "guest").strip().lower()
    if new_role not in ["guest", "host", "admin"]:
        flash("Invalid role specified.", "danger")
        return redirect(url_for("admin.users_list"))

    admin_id = session.get("user_id")
    if user_id == admin_id:
        flash("You cannot modify your own administrator role.", "danger")
        return redirect(url_for("admin.users_list"))

    execute("UPDATE users SET role = %s WHERE user_id = %s;", (new_role, user_id))
    flash("User role updated successfully.", "success")
    return redirect(url_for("admin.users_list"))


# =============================================================================
# 5. Financial & Revenue Reports (host_revenue_view, city_revenue_view, Window Function)
# =============================================================================
@admin_bp.route("/reports", endpoint="reports")
@role_required("admin")
def reports():
    """
    Financial & Operational Reports:
    - host_revenue_view: Aggregated host volume and successful bookings.
    - city_revenue_view: Destination revenue and booking counts.
    - Window-Function Query: RANK() OVER (PARTITION BY city_id) and DENSE_RANK() OVER (ORDER BY revenue DESC).
    """
    # 1. Host Revenue View
    sql_host_revenue = """
        SELECT 
            host_id,
            host_name,
            total_bookings,
            total_revenue
        FROM host_revenue_view
        ORDER BY total_revenue DESC;
    """
    host_revenues = fetch_all(sql_host_revenue)

    # 2. City Revenue View
    sql_city_revenue = """
        SELECT 
            city_id,
            city_name,
            bookings,
            revenue
        FROM city_revenue_view
        ORDER BY revenue DESC;
    """
    city_revenues = fetch_all(sql_city_revenue)

    # 3. Window-Function Query Ranking Properties by Revenue (Query 8 in sql/07_queries.sql)
    sql_property_rankings = """
        SELECT
            c.city_name,
            p.property_id,
            p.name AS property_name,
            u.name AS host_name,
            u.email AS host_email,
            COUNT(DISTINCT CASE WHEN pay.status = 'success' THEN b.booking_id END) AS total_bookings,
            COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) AS total_revenue,
            RANK() OVER (
                PARTITION BY c.city_id
                ORDER BY COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) DESC
            ) AS revenue_rank_in_city,
            DENSE_RANK() OVER (
                ORDER BY COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) DESC
            ) AS platform_revenue_rank
        FROM properties p
        INNER JOIN cities c ON p.city_id = c.city_id
        INNER JOIN users u ON p.host_id = u.user_id
        LEFT JOIN room_types rt ON p.property_id = rt.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        LEFT JOIN bookings b ON rm.room_id = b.room_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        WHERE p.status = 'approved'
        GROUP BY c.city_id, c.city_name, p.property_id, p.name, u.name, u.email
        ORDER BY platform_revenue_rank ASC, c.city_name ASC;
    """
    property_rankings = fetch_all(sql_property_rankings)

    # Macro KPIs
    gross_volume = sum(float(r["revenue"]) for r in city_revenues)
    total_successful_bookings = sum(int(r["bookings"]) for r in city_revenues)

    return render_template(
        "admin/reports.html",
        host_revenues=host_revenues,
        city_revenues=city_revenues,
        property_rankings=property_rankings,
        gross_volume=gross_volume,
        total_successful_bookings=total_successful_bookings
    )


# =============================================================================
# 6. CSV Export for Revenue Report
# =============================================================================
@admin_bp.route("/reports/export-csv", endpoint="export_revenue_csv")
@admin_bp.route("/reports/export")
@role_required("admin")
def export_revenue_csv():
    """
    CSV Export: Generates downloadable revenue report containing window-function
    rankings, city partitions, host affiliations, and gross revenue figures.
    """
    sql_property_rankings = """
        SELECT
            DENSE_RANK() OVER (
                ORDER BY COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) DESC
            ) AS platform_revenue_rank,
            RANK() OVER (
                PARTITION BY c.city_id
                ORDER BY COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) DESC
            ) AS revenue_rank_in_city,
            p.property_id,
            p.name AS property_name,
            c.city_name,
            c.state,
            u.name AS host_name,
            u.email AS host_email,
            COUNT(DISTINCT CASE WHEN pay.status = 'success' THEN b.booking_id END) AS total_bookings,
            COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) AS total_revenue
        FROM properties p
        INNER JOIN cities c ON p.city_id = c.city_id
        INNER JOIN users u ON p.host_id = u.user_id
        LEFT JOIN room_types rt ON p.property_id = rt.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        LEFT JOIN bookings b ON rm.room_id = b.room_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        WHERE p.status = 'approved'
        GROUP BY c.city_id, c.city_name, c.state, p.property_id, p.name, u.name, u.email
        ORDER BY platform_revenue_rank ASC, c.city_name ASC;
    """
    rankings = fetch_all(sql_property_rankings)

    output = io.StringIO()
    writer = csv.writer(output)

    # Write Header
    writer.writerow([
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
    ])

    # Write Data Rows
    for r in rankings:
        writer.writerow([
            r["platform_revenue_rank"],
            r["revenue_rank_in_city"],
            r["property_id"],
            r["property_name"],
            r["city_name"],
            r["state"],
            r["host_name"],
            r["host_email"],
            r["total_bookings"],
            f"{float(r['total_revenue']):.2f}"
        ])

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=hommy_cottage_revenue_report.csv",
            "Content-Type": "text/csv; charset=utf-8"
        }
    )


# =============================================================================
# 7. Platform-wide Bookings Overview
# =============================================================================
@admin_bp.route("/bookings", endpoint="bookings_list")
@role_required("admin")
def bookings_list():
    """View and filter all bookings platform-wide."""
    sql = """
        SELECT 
            b.booking_id,
            b.check_in,
            b.check_out,
            b.guests,
            b.status AS booking_status,
            p.property_id,
            p.name AS property_name,
            c.city_name,
            rm.room_number,
            rt.type_name AS room_type,
            u_guest.name AS guest_name,
            u_guest.email AS guest_email,
            u_guest.phone AS guest_phone,
            u_host.name AS host_name,
            u_host.email AS host_email,
            pay.amount,
            pay.method AS payment_method,
            pay.status AS payment_status
        FROM bookings b
        JOIN rooms rm ON b.room_id = rm.room_id
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN properties p ON rt.property_id = p.property_id
        JOIN cities c ON p.city_id = c.city_id
        JOIN users u_guest ON b.guest_id = u_guest.user_id
        JOIN users u_host ON p.host_id = u_host.user_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        ORDER BY b.booking_id DESC;
    """
    bookings = fetch_all(sql)
    return render_template("admin/bookings.html", bookings=bookings)
