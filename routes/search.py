"""
Hommy Cottage - Search & Property Exploration Blueprint
======================================================
Queries MySQL 8.0 views: property_search_view and property_rating_view.
Implements:
- GET /: Landing page with search form, cities, and amenities loaded from DB.
- GET /search: Multi-filter property search (city, check-in/out, guests, max price,
  min rating, amenities with relational division via HAVING COUNT(DISTINCT),
  sorting, pagination 9/page, status='approved', and NOT EXISTS availability check).
- GET /property/<id>: Cottage details, photo gallery, amenities, room types with live
  availability computed via fn_available_rooms, and verified guest reviews.
  Pending/rejected properties return 404 unless the viewer is the listing host or admin.
"""
import math
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, abort, redirect, url_for
from db import fetch_all, fetch_one
from auth_utils import get_current_user

search_bp = Blueprint("search", __name__)


@search_bp.route("/")
def index():
    """
    Home page displaying search form, popular cities, amenities from DB,
    and top-rated featured properties using property_search_view.
    """
    # 1. Fetch cities from DB with approved property counts
    sql_cities = """
        SELECT 
            c.city_id, 
            c.city_name, 
            c.city_name AS city, 
            c.state, 
            COUNT(p.property_id) AS cottage_count
        FROM cities c
        LEFT JOIN properties p ON c.city_id = p.city_id AND p.status = 'approved'
        GROUP BY c.city_id, c.city_name, c.state
        ORDER BY cottage_count DESC, c.city_name ASC;
    """
    cities = fetch_all(sql_cities)

    # 2. Fetch all amenities from DB for quick search filters
    sql_amenities = """
        SELECT amenity_id, amenity_name, amenity_name AS name
        FROM amenities
        ORDER BY amenity_name ASC;
    """
    amenities = fetch_all(sql_amenities)

    # 3. Fetch property categories / types
    sql_types = """
        SELECT type_id, type_name 
        FROM property_types 
        ORDER BY type_name ASC;
    """
    property_types = fetch_all(sql_types)

    # 4. Fetch featured top-rated properties from property_search_view
    sql_featured = """
        SELECT 
            v.property_id,
            v.property_id AS cottage_id,
            v.host_id,
            v.property_name,
            v.property_name AS title,
            v.description,
            v.city_id,
            v.city_name,
            v.city_name AS city,
            v.state,
            v.type_name,
            v.type_name AS property_type,
            v.starting_price,
            v.starting_price AS base_price_per_night,
            v.avg_rating,
            v.review_count,
            v.primary_image,
            (SELECT MAX(rt.capacity) FROM room_types rt WHERE rt.property_id = v.property_id) AS max_guests
        FROM property_search_view v
        ORDER BY v.avg_rating DESC, v.review_count DESC, v.property_id ASC
        LIMIT 6;
    """
    featured_properties = fetch_all(sql_featured)

    # 5. Platform aggregate counts
    stats = {
        "cottages": (fetch_one("SELECT COUNT(*) AS cnt FROM properties WHERE status = 'approved'") or {}).get("cnt", 0),
        "cities": (fetch_one("SELECT COUNT(DISTINCT city_id) AS cnt FROM properties WHERE status = 'approved'") or {}).get("cnt", 0),
        "bookings": (fetch_one("SELECT COUNT(*) AS cnt FROM bookings WHERE status = 'confirmed'") or {}).get("cnt", 0),
        "hosts": (fetch_one("SELECT COUNT(*) AS cnt FROM users WHERE role = 'host'") or {}).get("cnt", 0)
    }

    return render_template(
        "main/index.html",
        cities=cities,
        popular_cities=cities[:8],
        amenities=amenities,
        property_types=property_types,
        featured_cottages=featured_properties,
        featured_properties=featured_properties,
        stats=stats
    )


@search_bp.route("/search")
def search():
    """
    Multi-filter search engine querying property_search_view and property_rating_view:
    - Filters: city, check-in, check-out, guests, max price, min rating, amenities
    - Amenities relational division: HAVING COUNT(DISTINCT) = len(selected_amenities)
    - Date availability anti-semijoin: NOT EXISTS overlapping bookings
    - Always strictly filters status='approved'
    - Sorting (price asc/desc, rating)
    - Pagination (9 items per page)
    """
    city = request.args.get("city", "").strip()
    check_in = request.args.get("check_in", "").strip()
    check_out = request.args.get("check_out", "").strip()
    guests = request.args.get("guests", "").strip()
    min_price = request.args.get("min_price", "").strip()
    max_price = request.args.get("max_price", "").strip()
    min_rating = request.args.get("min_rating", "").strip()
    property_type = request.args.get("property_type", "").strip()
    sort_by = request.args.get("sort", "rating").strip()

    # Normalize amenities list from query parameters
    selected_amenities = request.args.getlist("amenities")
    if len(selected_amenities) == 1 and "," in str(selected_amenities[0]):
        selected_amenities = [x.strip() for x in selected_amenities[0].split(",") if x.strip()]

    # Separate numeric amenity IDs from named amenities
    valid_amenity_ids = [int(a) for a in selected_amenities if str(a).strip().isdigit()]
    valid_amenity_names = [str(a).strip() for a in selected_amenities if not str(a).strip().isdigit() and str(a).strip()]

    # Base WHERE clauses strictly filtering approved listings
    where_clauses = ["p.status = 'approved'"]
    params = []

    # 1. City / Location Filter
    if city:
        if city.isdigit():
            where_clauses.append("(v.city_id = %s OR LOWER(v.city_name) LIKE %s)")
            params.extend([int(city), f"%{city.lower()}%"])
        else:
            where_clauses.append("(LOWER(v.city_name) LIKE %s OR LOWER(v.state) LIKE %s OR LOWER(v.property_name) LIKE %s)")
            search_term = f"%{city.lower()}%"
            params.extend([search_term, search_term, search_term])

    # 2. Guest Capacity Filter
    if guests and str(guests).isdigit() and int(guests) > 0:
        where_clauses.append("""
            EXISTS (
                SELECT 1 FROM room_types rt
                WHERE rt.property_id = v.property_id
                  AND rt.capacity >= %s
            )
        """)
        params.append(int(guests))

    # 3. Minimum and Maximum Price Filters
    if min_price:
        try:
            min_p = float(min_price)
            if min_p > 0:
                where_clauses.append("v.starting_price >= %s")
                params.append(min_p)
        except (ValueError, TypeError):
            pass

    if max_price:
        try:
            max_p = float(max_price)
            if max_p > 0:
                where_clauses.append("v.starting_price <= %s")
                params.append(max_p)
        except (ValueError, TypeError):
            pass

    # 4. Minimum Rating Filter
    if min_rating:
        try:
            min_r = float(min_rating)
            if min_r > 0:
                where_clauses.append("v.avg_rating >= %s")
                params.append(min_r)
        except (ValueError, TypeError):
            pass

    # 5. Property Type Category Filter
    if property_type:
        if property_type.isdigit():
            where_clauses.append("v.type_id = %s")
            params.append(int(property_type))
        else:
            where_clauses.append("v.type_name = %s")
            params.append(property_type)

    # 6. Selected Amenities Filter via Relational Division (Must have ALL selected)
    if valid_amenity_ids:
        placeholders = ", ".join(["%s"] * len(valid_amenity_ids))
        where_clauses.append(f"""
            v.property_id IN (
                SELECT pa.property_id
                FROM property_amenities pa
                WHERE pa.amenity_id IN ({placeholders})
                GROUP BY pa.property_id
                HAVING COUNT(DISTINCT pa.amenity_id) = %s
            )
        """)
        params.extend(valid_amenity_ids)
        params.append(len(valid_amenity_ids))
    elif valid_amenity_names:
        placeholders = ", ".join(["%s"] * len(valid_amenity_names))
        where_clauses.append(f"""
            v.property_id IN (
                SELECT pa.property_id
                FROM property_amenities pa
                JOIN amenities a ON pa.amenity_id = a.amenity_id
                WHERE a.amenity_name IN ({placeholders})
                GROUP BY pa.property_id
                HAVING COUNT(DISTINCT a.amenity_id) = %s
            )
        """)
        params.extend(valid_amenity_names)
        params.append(len(valid_amenity_names))

    # 7. Date-Range Availability (NOT EXISTS Overlapping Confirmed Bookings)
    dates_valid = False
    if check_in and check_out:
        try:
            ci = datetime.strptime(check_in, "%Y-%m-%d").date()
            co = datetime.strptime(check_out, "%Y-%m-%d").date()
            if co > ci:
                dates_valid = True
                where_clauses.append("""
                    v.property_id IN (
                        SELECT rt.property_id
                        FROM room_types rt
                        JOIN rooms rm ON rt.room_type_id = rm.room_type_id
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM bookings b
                            WHERE b.room_id = rm.room_id
                              AND b.status != 'cancelled'
                              AND b.check_in < %s
                              AND b.check_out > %s
                        )
                    )
                """)
                params.extend([check_out, check_in])
        except (ValueError, TypeError):
            dates_valid = False

    # 8. Sorting Logic
    if sort_by == "price_asc":
        order_sql = "ORDER BY v.starting_price ASC, v.property_id ASC"
    elif sort_by == "price_desc":
        order_sql = "ORDER BY v.starting_price DESC, v.property_id ASC"
    elif sort_by in ("rating", "rating_desc"):
        order_sql = "ORDER BY v.avg_rating DESC, v.review_count DESC, v.property_id ASC"
    else:
        sort_by = "rating"
        order_sql = "ORDER BY v.avg_rating DESC, v.review_count DESC, v.property_id ASC"

    # 9. Pagination Setup (9 properties per page)
    per_page = 9
    try:
        page = int(request.args.get("page", 1))
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1

    where_sql = " AND ".join(where_clauses)

    # Count total matching properties
    count_sql = f"""
        SELECT COUNT(DISTINCT v.property_id) AS total
        FROM property_search_view v
        JOIN properties p ON v.property_id = p.property_id
        WHERE {where_sql};
    """
    count_row = fetch_one(count_sql, tuple(params))
    total_results = count_row["total"] if count_row else 0
    total_pages = max(1, math.ceil(total_results / per_page))

    if page > total_pages and total_results > 0:
        page = total_pages
    offset = (page - 1) * per_page

    # Execute main search query
    search_sql = f"""
        SELECT 
            v.property_id,
            v.property_id AS cottage_id,
            v.host_id,
            v.property_name,
            v.property_name AS title,
            v.description,
            v.address,
            v.pincode,
            v.city_id,
            v.city_name,
            v.city_name AS city,
            v.state,
            v.type_id,
            v.type_name,
            v.type_name AS property_type,
            v.starting_price,
            v.starting_price AS base_price_per_night,
            v.avg_rating,
            v.review_count,
            v.primary_image,
            (SELECT MAX(rt.capacity) FROM room_types rt WHERE rt.property_id = v.property_id) AS max_guests
        FROM property_search_view v
        JOIN properties p ON v.property_id = p.property_id
        WHERE {where_sql}
        {order_sql}
        LIMIT %s OFFSET %s;
    """
    search_params = list(params) + [per_page, offset]
    properties = fetch_all(search_sql, tuple(search_params))

    # Amenities and Property Types for Filter Panel
    amenities = fetch_all("SELECT amenity_id, amenity_name, amenity_name AS name FROM amenities ORDER BY amenity_name ASC")
    types = fetch_all("SELECT type_id, type_name FROM property_types ORDER BY type_name ASC")

    # Selected amenity IDs for checkbox preservation
    selected_amenity_ids = valid_amenity_ids

    empty_message = "No approved cottages found matching your search criteria. Please try adjusting your filters, dates, or destination."

    return render_template(
        "cottages/search.html",
        properties=properties,
        cottages=properties,
        amenities=amenities,
        property_types=[t["type_name"] for t in types],
        city=city,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        min_price=min_price,
        max_price=max_price,
        min_rating=min_rating,
        property_type=property_type,
        selected_amenities=selected_amenity_ids,
        sort_by=sort_by,
        page=page,
        total_pages=total_pages,
        total_results=total_results,
        per_page=per_page,
        empty_message=empty_message
    )


@search_bp.route("/property/<int:property_id>")
def property_detail(property_id=None, cottage_id=None):
    """
    Displays comprehensive property details:
    - Core details (address, description, host, ratings)
    - Image gallery from property_images
    - Amenities list from property_amenities
    - Room types with live availability computed via fn_available_rooms
    - Verified guest reviews
    Access Control:
    - Pending or rejected properties return 404 unless viewed by the listing owner or admin.
    """
    target_id = property_id if property_id is not None else cottage_id
    if target_id is None:
        abort(404)

    # 1. Fetch Property Details joined with city, type, host, and rating view
    sql_property = """
        SELECT 
            p.property_id,
            p.property_id AS cottage_id,
            p.host_id,
            p.type_id,
            p.city_id,
            p.name AS property_name,
            p.name AS title,
            p.description,
            p.address,
            p.address AS address_line,
            p.pincode,
            p.status,
            p.created_at,
            c.city_name,
            c.city_name AS city,
            c.state,
            pt.type_name,
            pt.type_name AS property_type,
            u.name AS host_name,
            u.email AS host_email,
            u.phone AS host_phone,
            prv.avg_rating,
            prv.review_count,
            (SELECT MIN(rt.price_per_night) FROM room_types rt WHERE rt.property_id = p.property_id) AS starting_price,
            (SELECT MIN(rt.price_per_night) FROM room_types rt WHERE rt.property_id = p.property_id) AS base_price_per_night,
            (SELECT MAX(rt.capacity) FROM room_types rt WHERE rt.property_id = p.property_id) AS max_guests
        FROM properties p
        JOIN cities c ON p.city_id = c.city_id
        JOIN property_types pt ON p.type_id = pt.type_id
        JOIN users u ON p.host_id = u.user_id
        JOIN property_rating_view prv ON p.property_id = prv.property_id
        WHERE p.property_id = %s;
    """
    prop = fetch_one(sql_property, (target_id,))
    if not prop:
        abort(404)

    # 2. Access Control on Pending / Rejected listings
    if prop["status"] != "approved":
        current_user = get_current_user()
        is_owner = current_user and (current_user.get("user_id") == prop["host_id"])
        is_admin = current_user and (current_user.get("role") == "admin")
        if not (is_owner or is_admin):
            abort(404)

    # 3. Fetch Photo Gallery
    sql_images = """
        SELECT image_id, property_id, image_url, is_primary
        FROM property_images
        WHERE property_id = %s
        ORDER BY is_primary DESC, image_id ASC;
    """
    images = fetch_all(sql_images, (target_id,))

    # 4. Fetch Amenities
    sql_amenities = """
        SELECT a.amenity_id, a.amenity_name, a.amenity_name AS name
        FROM property_amenities pa
        JOIN amenities a ON pa.amenity_id = a.amenity_id
        WHERE pa.property_id = %s
        ORDER BY a.amenity_name ASC;
    """
    amenities = fetch_all(sql_amenities, (target_id,))

    # 5. Calculate Live Room Type Availability via fn_available_rooms
    req_check_in = request.args.get("check_in", "").strip()
    req_check_out = request.args.get("check_out", "").strip()
    today = date.today()
    default_ci = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    default_co = (today + timedelta(days=2)).strftime("%Y-%m-%d")

    try:
        ci_dt = datetime.strptime(req_check_in, "%Y-%m-%d").date()
        co_dt = datetime.strptime(req_check_out, "%Y-%m-%d").date()
        if co_dt <= ci_dt:
            avail_ci, avail_co = default_ci, default_co
        else:
            avail_ci, avail_co = req_check_in, req_check_out
    except (ValueError, TypeError):
        avail_ci, avail_co = default_ci, default_co

    # Try calling fn_available_rooms directly; fallback to subquery if function unavailable
    sql_rooms_fn = """
        SELECT 
            rt.room_type_id,
            rt.property_id,
            rt.type_name,
            rt.capacity,
            rt.price_per_night,
            fn_available_rooms(rt.room_type_id, %s, %s) AS available_rooms,
            (SELECT COUNT(*) FROM rooms rm WHERE rm.room_type_id = rt.room_type_id) AS total_rooms
        FROM room_types rt
        WHERE rt.property_id = %s
        ORDER BY rt.price_per_night ASC;
    """
    sql_rooms_fallback = """
        SELECT 
            rt.room_type_id,
            rt.property_id,
            rt.type_name,
            rt.capacity,
            rt.price_per_night,
            (
                SELECT COUNT(*)
                FROM rooms rm
                WHERE rm.room_type_id = rt.room_type_id
                  AND NOT EXISTS (
                      SELECT 1
                      FROM bookings b
                      WHERE b.room_id = rm.room_id
                        AND b.status != 'cancelled'
                        AND b.check_in < %s
                        AND b.check_out > %s
                  )
            ) AS available_rooms,
            (SELECT COUNT(*) FROM rooms rm WHERE rm.room_type_id = rt.room_type_id) AS total_rooms
        FROM room_types rt
        WHERE rt.property_id = %s
        ORDER BY rt.price_per_night ASC;
    """
    try:
        room_types = fetch_all(sql_rooms_fn, (avail_ci, avail_co, target_id))
    except Exception:
        room_types = fetch_all(sql_rooms_fallback, (avail_co, avail_ci, target_id))

    # 6. Fetch Verified Guest Reviews
    sql_reviews = """
        SELECT 
            rev.review_id,
            rev.rating,
            rev.comment,
            rev.created_at,
            u.name AS guest_name
        FROM reviews rev
        JOIN bookings b ON rev.booking_id = b.booking_id
        JOIN rooms rm ON b.room_id = rm.room_id
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN users u ON b.guest_id = u.user_id
        WHERE rt.property_id = %s
        ORDER BY rev.created_at DESC;
    """
    reviews = fetch_all(sql_reviews, (target_id,))

    return render_template(
        "cottages/detail.html",
        property=prop,
        cottage=prop,
        images=images,
        amenities=amenities,
        room_types=room_types,
        reviews=reviews,
        check_in=req_check_in or avail_ci,
        check_out=req_check_out or avail_co,
        avail_ci=avail_ci,
        avail_co=avail_co
    )


# Backward-compatibility alias for routes linking to /cottages
@search_bp.route("/cottages")
def cottages_search_alias():
    return search()


@search_bp.route("/cottages/<int:property_id>", endpoint="cottages_detail_alias")
def cottages_detail_alias(property_id=None, cottage_id=None):
    return property_detail(property_id, cottage_id)

