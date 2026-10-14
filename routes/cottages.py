"""
Hommy Cottage - Cottages Blueprint
Implements the Trivago-style search engine & filters + detailed cottage listing pages.
Strictly uses parameterized SQL (%s placeholders) with dynamic clause building.
"""
from datetime import datetime
from flask import Blueprint, render_template, request, abort
from db import query_all, query_one

cottages_bp = Blueprint("cottages", __name__, url_prefix="/cottages")


@cottages_bp.route("")
def search():
    """
    Trivago-style search with multi-parameter filtering:
    - City / Destination keyword
    - Check-in & Check-out date overlap conflict exclusion
    - Guest capacity
    - Price range (min and max)
    - Property type
    - Amenities filter
    - Sorting (price, rating, recency)
    """
    city = request.args.get("city", "").strip()
    check_in = request.args.get("check_in", "").strip()
    check_out = request.args.get("check_out", "").strip()
    guests = request.args.get("guests", "").strip()
    min_price = request.args.get("min_price", "").strip()
    max_price = request.args.get("max_price", "").strip()
    property_type = request.args.get("property_type", "").strip()
    selected_amenities = request.args.getlist("amenities")
    sort_by = request.args.get("sort", "rating_desc")

    # Base WHERE clauses with active & approved criteria
    where_clauses = ["c.is_active = TRUE", "c.is_approved = TRUE"]
    params = []

    # 1. City / Location Filter
    if city:
        where_clauses.append("(LOWER(c.city) LIKE %s OR LOWER(c.state) LIKE %s OR LOWER(c.title) LIKE %s)")
        search_term = f"%{city.lower()}%"
        params.extend([search_term, search_term, search_term])

    # 2. Guests Filter
    if guests and guests.isdigit():
        where_clauses.append("c.max_guests >= %s")
        params.append(int(guests))

    # 3. Price Filter
    if min_price and min_price.isdigit():
        where_clauses.append("c.base_price_per_night >= %s")
        params.append(float(min_price))

    if max_price and max_price.isdigit():
        where_clauses.append("c.base_price_per_night <= %s")
        params.append(float(max_price))

    # 4. Property Type Filter
    if property_type:
        where_clauses.append("c.property_type = %s")
        params.append(property_type)

    # 5. Date Overlap Availability Check (Exclude cottages booked in this window)
    if check_in and check_out:
        try:
            # Validate valid date strings
            datetime.strptime(check_in, "%Y-%m-%d")
            datetime.strptime(check_out, "%Y-%m-%d")
            where_clauses.append("""
                c.cottage_id NOT IN (
                    SELECT b.cottage_id FROM bookings b
                    WHERE b.booking_status = 'confirmed'
                    AND NOT (b.check_out_date <= %s OR b.check_in_date >= %s)
                )
            """)
            params.extend([check_in, check_out])
        except ValueError:
            pass  # Ignore invalid date formats safely

    # 6. Selected Amenities Filter
    if selected_amenities:
        valid_amenity_ids = [int(a) for a in selected_amenities if a.isdigit()]
        if valid_amenity_ids:
            placeholders = ", ".join(["%s"] * len(valid_amenity_ids))
            where_clauses.append(f"""
                c.cottage_id IN (
                    SELECT ca.cottage_id FROM cottage_amenities ca
                    WHERE ca.amenity_id IN ({placeholders})
                    GROUP BY ca.cottage_id
                    HAVING COUNT(DISTINCT ca.amenity_id) = %s
                )
            """)
            params.extend(valid_amenity_ids)
            params.append(len(valid_amenity_ids))

    # Assemble SQL WHERE clause
    where_sql = " AND ".join(where_clauses)

    # 7. Sorting
    order_by_sql = "ORDER BY avg_rating DESC, c.cottage_id ASC"
    if sort_by == "price_asc":
        order_by_sql = "ORDER BY c.base_price_per_night ASC"
    elif sort_by == "price_desc":
        order_by_sql = "ORDER BY c.base_price_per_night DESC"
    elif sort_by == "newest":
        order_by_sql = "ORDER BY c.created_at DESC"

    # Main parameterized query joining cottage images and reviews
    sql = f"""
        SELECT 
            c.cottage_id, c.title, c.property_type, c.city, c.state, 
            c.max_guests, c.bedrooms, c.bathrooms, c.base_price_per_night,
            COALESCE(img.image_url, '/static/uploads/default_cottage.jpg') AS primary_image,
            COALESCE(AVG(r.rating), 0) AS avg_rating,
            COUNT(r.review_id) AS review_count
        FROM cottages c
        LEFT JOIN cottage_images img 
            ON c.cottage_id = img.cottage_id AND img.is_primary = TRUE
        LEFT JOIN reviews r 
            ON c.cottage_id = r.cottage_id
        WHERE {where_sql}
        GROUP BY c.cottage_id, img.image_url
        {order_by_sql};
    """
    cottages = query_all(sql, tuple(params))

    # Fetch all amenities for sidebar filter options
    amenities = query_all("SELECT amenity_id, name, icon_class FROM amenities ORDER BY name ASC")

    # Fetch unique property types for dropdown filter
    prop_types = query_all("SELECT DISTINCT property_type FROM cottages ORDER BY property_type ASC")

    return render_template(
        "cottages/search.html",
        cottages=cottages,
        amenities=amenities,
        property_types=[p["property_type"] for p in prop_types],
        city=city,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        min_price=min_price,
        max_price=max_price,
        property_type=property_type,
        selected_amenities=[int(a) for a in selected_amenities if a.isdigit()],
        sort_by=sort_by,
        total_results=len(cottages)
    )


@cottages_bp.route("/<int:cottage_id>")
def detail(cottage_id):
    """
    Displays full details for a cottage:
    - Host contact details
    - Image gallery
    - Amenities list
    - Verified guest reviews and rating breakdown
    - Booked date intervals for availability calendar
    """
    # 1. Fetch Cottage & Host details
    sql_cottage = """
        SELECT 
            c.*, 
            u.full_name AS host_name, 
            u.email AS host_email, 
            u.phone AS host_phone,
            COALESCE(AVG(r.rating), 0) AS avg_rating,
            COUNT(r.review_id) AS review_count
        FROM cottages c
        JOIN users u ON c.host_id = u.user_id
        LEFT JOIN reviews r ON c.cottage_id = r.cottage_id
        WHERE c.cottage_id = %s
        GROUP BY c.cottage_id, u.user_id;
    """
    cottage = query_one(sql_cottage, (cottage_id,))
    if not cottage:
        abort(404)

    # 2. Fetch all images for this cottage
    sql_images = """
        SELECT image_id, image_url, is_primary 
        FROM cottage_images 
        WHERE cottage_id = %s 
        ORDER BY is_primary DESC, image_id ASC;
    """
    images = query_all(sql_images, (cottage_id,))

    # 3. Fetch amenities associated with this cottage
    sql_amenities = """
        SELECT a.amenity_id, a.name, a.icon_class
        FROM amenities a
        JOIN cottage_amenities ca ON a.amenity_id = ca.amenity_id
        WHERE ca.cottage_id = %s
        ORDER BY a.name ASC;
    """
    amenities = query_all(sql_amenities, (cottage_id,))

    # 4. Fetch verified guest reviews
    sql_reviews = """
        SELECT 
            r.review_id, r.rating, r.comment, r.created_at,
            u.full_name AS guest_name
        FROM reviews r
        JOIN users u ON r.guest_id = u.user_id
        WHERE r.cottage_id = %s
        ORDER BY r.created_at DESC;
    """
    reviews = query_all(sql_reviews, (cottage_id,))

    # 5. Fetch booked date ranges for booking calendar disabling
    sql_booked_dates = """
        SELECT check_in_date, check_out_date 
        FROM bookings 
        WHERE cottage_id = %s AND booking_status = 'confirmed'
        AND check_out_date >= CURRENT_DATE;
    """
    booked_dates = query_all(sql_booked_dates, (cottage_id,))

    return render_template(
        "cottages/detail.html",
        cottage=cottage,
        images=images,
        amenities=amenities,
        reviews=reviews,
        booked_dates=booked_dates
    )
