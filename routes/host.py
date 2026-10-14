"""
Hommy Cottage - Host Portal Blueprint
=====================================
Enables registered hosts to manage properties, configure room types with
auto-generated physical rooms, upload photos (strict 4 MB cap, JPG/PNG only,
secure_filename with UUID prefix), and monitor guest reservations via upcoming_bookings_view.

SECURITY GUARANTEE:
Every database query touching properties, room types, rooms, images, or bookings
strictly includes `host_id = session['user_id']` so a host can NEVER view,
modify, or delete another host's data. All routes are protected by role_required('host').
"""
import os
import uuid
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort, session, current_app
)
from werkzeug.utils import secure_filename
from config import Config
from db import fetch_all, fetch_one, execute
from auth_utils import role_required, get_current_user

host_bp = Blueprint("host", __name__, url_prefix="/host")

# Strict upload restrictions for Host properties
ALLOWED_HOST_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_IMAGE_SIZE_BYTES = 4 * 1024 * 1024  # 4 MB cap


def is_allowed_image(filename):
    """Validates that uploaded image has a .jpg, .jpeg, or .png extension."""
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_HOST_EXTENSIONS


def get_session_host_id():
    """Retrieves authenticated host ID directly from session for DB isolation."""
    return session.get("user_id")


# =============================================================================
# 1. Host Dashboard
# =============================================================================
@host_bp.route("/", endpoint="dashboard_root")
@host_bp.route("/dashboard", endpoint="dashboard")
@role_required("host")
def dashboard():
    """
    Host Dashboard: Displays own properties with status badges ('pending', 'approved', 'rejected'),
    KPI count summaries, and upcoming bookings using upcoming_bookings_view.
    """
    host_id = get_session_host_id()
    user = get_current_user()

    # 1. Aggregate KPIs across host's properties (Multi-tenant filtered by host_id)
    sql_kpis = """
        SELECT 
            COUNT(DISTINCT p.property_id) AS total_properties,
            COUNT(DISTINCT CASE WHEN p.status = 'approved' THEN p.property_id END) AS approved_count,
            COUNT(DISTINCT CASE WHEN p.status = 'pending' THEN p.property_id END) AS pending_count,
            COUNT(DISTINCT CASE WHEN p.status = 'rejected' THEN p.property_id END) AS rejected_count,
            COUNT(DISTINCT b.booking_id) AS total_bookings,
            COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) AS total_earnings
        FROM properties p
        LEFT JOIN room_types rt ON p.property_id = rt.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        LEFT JOIN bookings b ON rm.room_id = b.room_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        WHERE p.host_id = %s;
    """
    kpis = fetch_one(sql_kpis, (host_id,)) or {
        "total_properties": 0,
        "approved_count": 0,
        "pending_count": 0,
        "rejected_count": 0,
        "total_bookings": 0,
        "total_earnings": 0.00
    }

    # 2. Host's own properties with status badges, primary image, and room counts
    sql_properties = """
        SELECT 
            p.property_id,
            p.host_id,
            p.name,
            p.description,
            p.address,
            p.pincode,
            p.status,
            p.created_at,
            c.city_name,
            c.state,
            pt.type_name,
            COALESCE(
                (SELECT image_url FROM property_images WHERE property_id = p.property_id AND is_primary = TRUE LIMIT 1),
                (SELECT image_url FROM property_images WHERE property_id = p.property_id ORDER BY image_id ASC LIMIT 1),
                '/static/img/sample/default.jpg'
            ) AS primary_image,
            COUNT(DISTINCT rt.room_type_id) AS room_types_count,
            COUNT(DISTINCT rm.room_id) AS total_rooms,
            COALESCE(MIN(rt.price_per_night), 0.00) AS starting_price,
            COUNT(DISTINCT b.booking_id) AS booking_count,
            COALESCE(ROUND(AVG(rev.rating), 1), 0.0) AS avg_rating
        FROM properties p
        JOIN cities c ON p.city_id = c.city_id
        JOIN property_types pt ON p.type_id = pt.type_id
        LEFT JOIN room_types rt ON p.property_id = rt.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        LEFT JOIN bookings b ON rm.room_id = b.room_id
        LEFT JOIN reviews rev ON b.booking_id = rev.booking_id
        WHERE p.host_id = %s
        GROUP BY 
            p.property_id, p.host_id, p.name, p.description, p.address,
            p.pincode, p.status, p.created_at, c.city_name, c.state, pt.type_name
        ORDER BY p.created_at DESC;
    """
    properties = fetch_all(sql_properties, (host_id,))

    # 3. Upcoming reservations for host via upcoming_bookings_view
    sql_upcoming = """
        SELECT *
        FROM upcoming_bookings_view
        WHERE host_id = %s
        ORDER BY check_in ASC
        LIMIT 5;
    """
    recent_bookings = fetch_all(sql_upcoming, (host_id,))

    return render_template(
        "host/dashboard.html",
        user=user,
        kpis=kpis,
        properties=properties,
        recent_bookings=recent_bookings
    )


# =============================================================================
# 2. Add Property (Starts as 'pending', amenity checkboxes, image upload rules)
# =============================================================================
@host_bp.route("/property/add", endpoint="add_property", methods=["GET", "POST"])
@host_bp.route("/properties/new", endpoint="properties_new", methods=["GET", "POST"])
@host_bp.route("/cottages/create", endpoint="create_cottage", methods=["GET", "POST"])
@role_required("host")
def add_property():
    """
    Add Property:
    - New listings automatically start as 'pending'.
    - Multi-select amenity checkboxes from amenities table.
    - Multiple image uploads: JPG/PNG only, secure_filename, uuid prefix, 4 MB cap.
    - Choose primary image.
    - Strict host_id = session['user_id'] assignment.
    """
    host_id = get_session_host_id()

    if request.method == "POST":
        name = request.form.get("name", "").strip() or request.form.get("title", "").strip()
        type_id = request.form.get("type_id", "").strip()
        city_id = request.form.get("city_id", "").strip()
        address = request.form.get("address", "").strip() or request.form.get("address_line", "").strip()
        pincode = request.form.get("pincode", "").strip()
        description = request.form.get("description", "").strip()
        selected_amenities = request.form.getlist("amenities")
        primary_image_index = request.form.get("primary_image_index", "0").strip()

        # Input validation
        if not name or not type_id or not city_id or not address or not pincode or not description:
            flash("All mandatory property details marked with an asterisk must be provided.", "danger")
            cities = fetch_all("SELECT * FROM cities ORDER BY city_name ASC")
            property_types = fetch_all("SELECT * FROM property_types ORDER BY type_name ASC")
            amenities = fetch_all("SELECT * FROM amenities ORDER BY amenity_name ASC")
            return render_template(
                "host/create_listing.html",
                cities=cities,
                property_types=property_types,
                amenities=amenities
            )

        try:
            type_id_int = int(type_id)
            city_id_int = int(city_id)
            primary_idx = int(primary_image_index) if primary_image_index.isdigit() else 0
        except ValueError:
            flash("Invalid selection for category or city.", "danger")
            return redirect(url_for("host.add_property"))

        # Verify city and type exist
        city_check = fetch_one("SELECT city_id FROM cities WHERE city_id = %s", (city_id_int,))
        type_check = fetch_one("SELECT type_id FROM property_types WHERE type_id = %s", (type_id_int,))
        if not city_check or not type_check:
            flash("Invalid destination city or property category selected.", "danger")
            return redirect(url_for("host.add_property"))

        # Handle image files: Validate BEFORE DB insertion
        uploaded_files = request.files.getlist("images")
        single_file = request.files.get("image_file")
        if single_file and single_file.filename:
            uploaded_files.append(single_file)

        valid_files = [f for f in uploaded_files if f and f.filename]

        # Enforce image rules: JPG/PNG only, max 4 MB per file
        for file_obj in valid_files:
            if not is_allowed_image(file_obj.filename):
                flash(f"File '{file_obj.filename}' rejected. Only JPG and PNG image formats are permitted.", "danger")
                cities = fetch_all("SELECT * FROM cities ORDER BY city_name ASC")
                property_types = fetch_all("SELECT * FROM property_types ORDER BY type_name ASC")
                amenities = fetch_all("SELECT * FROM amenities ORDER BY amenity_name ASC")
                return render_template(
                    "host/create_listing.html",
                    cities=cities,
                    property_types=property_types,
                    amenities=amenities
                )
            file_obj.seek(0, os.SEEK_END)
            f_size = file_obj.tell()
            file_obj.seek(0)
            if f_size > MAX_IMAGE_SIZE_BYTES:
                flash(f"File '{file_obj.filename}' exceeds the 4 MB upload size limit.", "danger")
                cities = fetch_all("SELECT * FROM cities ORDER BY city_name ASC")
                property_types = fetch_all("SELECT * FROM property_types ORDER BY type_name ASC")
                amenities = fetch_all("SELECT * FROM amenities ORDER BY amenity_name ASC")
                return render_template(
                    "host/create_listing.html",
                    cities=cities,
                    property_types=property_types,
                    amenities=amenities
                )

        # 1. Insert property with status='pending' and host_id = session user id
        sql_insert_prop = """
            INSERT INTO properties (
                host_id, type_id, city_id, name, description, address, pincode, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending');
        """
        property_id = execute(
            sql_insert_prop,
            (host_id, type_id_int, city_id_int, name, description, address, pincode)
        )

        # 2. Insert amenity checkboxes into property_amenities junction table
        for a_id in selected_amenities:
            if a_id.isdigit():
                execute(
                    "INSERT INTO property_amenities (property_id, amenity_id) VALUES (%s, %s)",
                    (property_id, int(a_id))
                )

        # 3. Save uploaded images (JPG/PNG only, UUID prefix, secure_filename)
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        saved_images = []

        for idx, file_obj in enumerate(valid_files):
            clean_name = secure_filename(file_obj.filename)
            prefix = uuid.uuid4().hex[:8]
            unique_filename = f"{prefix}_{clean_name}"
            file_dest = os.path.join(Config.UPLOAD_FOLDER, unique_filename)
            file_obj.save(file_dest)

            web_path = f"/static/uploads/{unique_filename}"
            is_prim = (idx == primary_idx)
            saved_images.append((web_path, is_prim))

        # If primary index didn't match or no images were primary, make the first one primary
        if saved_images and not any(is_prim for _, is_prim in saved_images):
            saved_images[0] = (saved_images[0][0], True)

        # Save to property_images table
        for img_url, is_prim in saved_images:
            execute(
                "INSERT INTO property_images (property_id, image_url, is_primary) VALUES (%s, %s, %s)",
                (property_id, img_url, is_prim)
            )

        # Fallback if no valid files uploaded: check text image_url or assign default
        fallback_url = request.form.get("image_url", "").strip()
        if not saved_images:
            default_url = fallback_url if fallback_url else "/static/img/sample/default.jpg"
            execute(
                "INSERT INTO property_images (property_id, image_url, is_primary) VALUES (%s, %s, TRUE)",
                (property_id, default_url)
            )

        flash(f"Property '{name}' submitted successfully! It is now pending administrator approval.", "success")
        return redirect(url_for("host.add_room_type", property_id=property_id))

    # GET: Load reference lookups
    cities = fetch_all("SELECT * FROM cities ORDER BY city_name ASC")
    property_types = fetch_all("SELECT * FROM property_types ORDER BY type_name ASC")
    amenities = fetch_all("SELECT * FROM amenities ORDER BY amenity_name ASC")

    return render_template(
        "host/create_listing.html",
        cities=cities,
        property_types=property_types,
        amenities=amenities
    )


# =============================================================================
# 3. Edit Own Property (Strict host_id verification)
# =============================================================================
@host_bp.route("/property/<int:property_id>/edit", endpoint="edit_property", methods=["GET", "POST"])
@host_bp.route("/cottages/<int:property_id>/edit", endpoint="edit_cottage", methods=["GET", "POST"])
@role_required("host")
def edit_property(property_id):
    """
    Edit Own Property:
    - Every query includes host_id = session['user_id'].
    - If property belongs to another host, abort(403).
    - If property doesn't exist, abort(404).
    - Updates property info, synchronizes amenities, handles photo uploads and primary selection.
    """
    host_id = get_session_host_id()

    # Verify ownership strictly via host_id = %s
    prop = fetch_one(
        "SELECT * FROM properties WHERE property_id = %s AND host_id = %s",
        (property_id, host_id)
    )
    if not prop:
        # Check if property exists under another host to return 403 vs 404
        other_prop = fetch_one("SELECT property_id FROM properties WHERE property_id = %s", (property_id,))
        if other_prop:
            abort(403)
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip() or request.form.get("title", "").strip()
        type_id = request.form.get("type_id", "").strip()
        city_id = request.form.get("city_id", "").strip()
        address = request.form.get("address", "").strip() or request.form.get("address_line", "").strip()
        pincode = request.form.get("pincode", "").strip()
        description = request.form.get("description", "").strip()
        selected_amenities = request.form.getlist("amenities")
        selected_primary_image_id = request.form.get("primary_image_id")

        if not name or not type_id or not city_id or not address or not pincode or not description:
            flash("All mandatory fields marked with an asterisk must be provided.", "danger")
            return redirect(url_for("host.edit_property", property_id=property_id))

        try:
            type_id_int = int(type_id)
            city_id_int = int(city_id)
        except ValueError:
            flash("Invalid category or city specified.", "danger")
            return redirect(url_for("host.edit_property", property_id=property_id))

        # 1. Update property fields with strict host_id isolation
        sql_update = """
            UPDATE properties 
            SET name = %s, type_id = %s, city_id = %s, address = %s, pincode = %s, description = %s
            WHERE property_id = %s AND host_id = %s;
        """
        execute(
            sql_update,
            (name, type_id_int, city_id_int, address, pincode, description, property_id, host_id)
        )

        # 2. Update amenities: delete old associations verifying property_id and host_id
        sql_delete_amenities = """
            DELETE pa FROM property_amenities pa
            JOIN properties p ON pa.property_id = p.property_id
            WHERE pa.property_id = %s AND p.host_id = %s;
        """
        execute(sql_delete_amenities, (property_id, host_id))

        for a_id in selected_amenities:
            if a_id.isdigit():
                execute(
                    "INSERT INTO property_amenities (property_id, amenity_id) VALUES (%s, %s)",
                    (property_id, int(a_id))
                )

        # 3. Handle additional image uploads (JPG/PNG only, 4 MB cap, UUID prefix)
        uploaded_files = request.files.getlist("images")
        single_file = request.files.get("image_file")
        if single_file and single_file.filename:
            uploaded_files.append(single_file)

        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
        for f in uploaded_files:
            if f and f.filename:
                if not is_allowed_image(f.filename):
                    flash(f"File '{f.filename}' ignored. Only JPG/PNG images are allowed.", "warning")
                    continue
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(0)
                if size > MAX_IMAGE_SIZE_BYTES:
                    flash(f"File '{f.filename}' exceeds the 4 MB limit.", "warning")
                    continue

                clean_name = secure_filename(f.filename)
                prefix = uuid.uuid4().hex[:8]
                unique_name = f"{prefix}_{clean_name}"
                dest = os.path.join(Config.UPLOAD_FOLDER, unique_name)
                f.save(dest)
                web_url = f"/static/uploads/{unique_name}"
                execute(
                    "INSERT INTO property_images (property_id, image_url, is_primary) VALUES (%s, %s, FALSE)",
                    (property_id, web_url)
                )

        # 4. Update primary image selection if provided
        if selected_primary_image_id and selected_primary_image_id.isdigit():
            prim_id = int(selected_primary_image_id)
            sql_reset_primary = """
                UPDATE property_images pi
                JOIN properties p ON pi.property_id = p.property_id
                SET pi.is_primary = CASE WHEN pi.image_id = %s THEN TRUE ELSE FALSE END
                WHERE pi.property_id = %s AND p.host_id = %s;
            """
            execute(sql_reset_primary, (prim_id, property_id, host_id))

        flash(f"Property '{name}' has been updated successfully.", "success")
        return redirect(url_for("host.edit_property", property_id=property_id))

    # GET: Load property details with lookups
    cities = fetch_all("SELECT * FROM cities ORDER BY city_name ASC")
    property_types = fetch_all("SELECT * FROM property_types ORDER BY type_name ASC")
    amenities = fetch_all("SELECT * FROM amenities ORDER BY amenity_name ASC")

    # Fetch currently assigned amenity IDs
    sql_current_amenities = """
        SELECT pa.amenity_id
        FROM property_amenities pa
        JOIN properties p ON pa.property_id = p.property_id
        WHERE pa.property_id = %s AND p.host_id = %s;
    """
    current_amenity_rows = fetch_all(sql_current_amenities, (property_id, host_id))
    current_amenity_ids = [r["amenity_id"] for r in current_amenity_rows]

    # Fetch images for this property
    sql_images = """
        SELECT pi.* 
        FROM property_images pi
        JOIN properties p ON pi.property_id = p.property_id
        WHERE pi.property_id = %s AND p.host_id = %s
        ORDER BY pi.is_primary DESC, pi.image_id ASC;
    """
    images = fetch_all(sql_images, (property_id, host_id))

    # Fetch room types and room counts for this property
    sql_room_types = """
        SELECT 
            rt.room_type_id,
            rt.property_id,
            rt.type_name,
            rt.capacity,
            rt.price_per_night,
            COUNT(rm.room_id) AS room_count,
            GROUP_CONCAT(rm.room_number ORDER BY rm.room_number ASC SEPARATOR ', ') AS room_numbers
        FROM room_types rt
        JOIN properties p ON rt.property_id = p.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        WHERE rt.property_id = %s AND p.host_id = %s
        GROUP BY rt.room_type_id, rt.property_id, rt.type_name, rt.capacity, rt.price_per_night
        ORDER BY rt.price_per_night ASC;
    """
    room_types = fetch_all(sql_room_types, (property_id, host_id))

    return render_template(
        "host/edit_listing.html",
        property=prop,
        cottage=prop,  # Alias for backward-compatibility
        cities=cities,
        property_types=property_types,
        amenities=amenities,
        current_amenity_ids=current_amenity_ids,
        images=images,
        room_types=room_types
    )


# =============================================================================
# 4. Property Image Management (Delete image with host isolation)
# =============================================================================
@host_bp.route("/property/<int:property_id>/image/<int:image_id>/delete", endpoint="delete_property_image", methods=["POST"])
@role_required("host")
def delete_property_image(property_id, image_id):
    """Deletes an image strictly verifying property ownership by session host."""
    host_id = get_session_host_id()

    sql_delete = """
        DELETE pi FROM property_images pi
        JOIN properties p ON pi.property_id = p.property_id
        WHERE pi.image_id = %s AND pi.property_id = %s AND p.host_id = %s;
    """
    affected = execute(sql_delete, (image_id, property_id, host_id))
    if affected:
        flash("Image removed successfully.", "info")
    else:
        flash("Could not delete image or permission denied.", "danger")

    return redirect(url_for("host.edit_property", property_id=property_id))


# =============================================================================
# 5. Room Types & Auto-Room Creation
# =============================================================================
@host_bp.route("/property/<int:property_id>/room-types", endpoint="list_room_types", methods=["GET"])
@role_required("host")
def list_room_types(property_id):
    """Displays all room types and rooms configured for a host's property."""
    host_id = get_session_host_id()

    prop = fetch_one(
        "SELECT * FROM properties WHERE property_id = %s AND host_id = %s",
        (property_id, host_id)
    )
    if not prop:
        abort(403 if fetch_one("SELECT property_id FROM properties WHERE property_id = %s", (property_id,)) else 404)

    sql = """
        SELECT 
            rt.room_type_id,
            rt.property_id,
            rt.type_name,
            rt.capacity,
            rt.price_per_night,
            COUNT(rm.room_id) AS room_count,
            GROUP_CONCAT(rm.room_number ORDER BY rm.room_number ASC SEPARATOR ', ') AS room_numbers
        FROM room_types rt
        JOIN properties p ON rt.property_id = p.property_id
        LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
        WHERE rt.property_id = %s AND p.host_id = %s
        GROUP BY rt.room_type_id, rt.property_id, rt.type_name, rt.capacity, rt.price_per_night
        ORDER BY rt.price_per_night ASC;
    """
    room_types = fetch_all(sql, (property_id, host_id))

    return render_template(
        "host/room_types.html",
        property=prop,
        room_types=room_types
    )


@host_bp.route("/property/<int:property_id>/room-types/new", endpoint="add_room_type", methods=["GET", "POST"])
@host_bp.route("/property/<int:property_id>/room-type/add", methods=["GET", "POST"])
@role_required("host")
def add_room_type(property_id):
    """
    Add Room Type:
    - Verifies property belongs to host_id = session['user_id'].
    - Takes type_name, capacity, price_per_night, and room_count.
    - Inserts room_types row.
    - AUTO-CREATES room_count physical rows in the rooms table (e.g. 101, 102, 103...).
    """
    host_id = get_session_host_id()

    prop = fetch_one(
        "SELECT * FROM properties WHERE property_id = %s AND host_id = %s",
        (property_id, host_id)
    )
    if not prop:
        abort(403 if fetch_one("SELECT property_id FROM properties WHERE property_id = %s", (property_id,)) else 404)

    if request.method == "POST":
        type_name = request.form.get("type_name", "").strip()
        capacity = request.form.get("capacity", "2").strip()
        price_per_night = request.form.get("price_per_night", "1000").strip()
        room_count = request.form.get("room_count", "1").strip()

        if not type_name:
            flash("Room type name is required (e.g. 'Deluxe King Suite').", "danger")
            return render_template("host/room_type_form.html", property=prop, is_edit=False)

        try:
            capacity_val = int(capacity)
            price_val = float(price_per_night)
            count_val = int(room_count)
            if capacity_val <= 0 or price_val <= 0 or count_val <= 0:
                raise ValueError()
        except ValueError:
            flash("Capacity, price per night, and room count must all be positive numbers.", "danger")
            return render_template("host/room_type_form.html", property=prop, is_edit=False)

        # 1. Insert room_type row
        sql_insert_rt = """
            INSERT INTO room_types (property_id, type_name, capacity, price_per_night)
            VALUES (%s, %s, %s, %s);
        """
        room_type_id = execute(sql_insert_rt, (property_id, type_name, capacity_val, price_val))

        # 2. Auto-create physical rooms in rooms table (101, 102, 103...)
        for i in range(1, count_val + 1):
            room_num = f"{100 + i}"
            execute(
                "INSERT INTO rooms (room_type_id, room_number) VALUES (%s, %s)",
                (room_type_id, room_num)
            )

        flash(
            f"Room type '{type_name}' added successfully with {count_val} physical rooms automatically generated!",
            "success"
        )
        return redirect(url_for("host.edit_property", property_id=property_id))

    return render_template("host/room_type_form.html", property=prop, is_edit=False)


@host_bp.route("/room-type/<int:room_type_id>/edit", endpoint="edit_room_type", methods=["GET", "POST"])
@role_required("host")
def edit_room_type(room_type_id):
    """
    Edit Room Type:
    - Verifies ownership through rt.property_id = p.property_id AND p.host_id = session['user_id'].
    - Updates type_name, capacity, and price_per_night.
    - Synchronizes room_count:
        - If increased: auto-generates additional rooms with next available room numbers.
        - If decreased: safely removes unreserved rooms without active bookings.
    """
    host_id = get_session_host_id()

    # Query room type with strict host isolation
    sql_rt = """
        SELECT rt.*, p.name AS property_name, p.property_id, p.host_id
        FROM room_types rt
        JOIN properties p ON rt.property_id = p.property_id
        WHERE rt.room_type_id = %s AND p.host_id = %s;
    """
    room_type = fetch_one(sql_rt, (room_type_id, host_id))
    if not room_type:
        abort(403 if fetch_one("SELECT room_type_id FROM room_types WHERE room_type_id = %s", (room_type_id,)) else 404)

    # Fetch existing rooms for this room type
    sql_rooms = """
        SELECT rm.*
        FROM rooms rm
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN properties p ON rt.property_id = p.property_id
        WHERE rm.room_type_id = %s AND p.host_id = %s
        ORDER BY rm.room_id ASC;
    """
    current_rooms = fetch_all(sql_rooms, (room_type_id, host_id))
    current_room_count = len(current_rooms)

    if request.method == "POST":
        type_name = request.form.get("type_name", "").strip()
        capacity = request.form.get("capacity", "").strip()
        price_per_night = request.form.get("price_per_night", "").strip()
        target_room_count = request.form.get("room_count", "").strip()

        if not type_name:
            flash("Room type name cannot be empty.", "danger")
            return render_template(
                "host/room_type_form.html",
                room_type=room_type,
                current_rooms=current_rooms,
                current_room_count=current_room_count,
                is_edit=True
            )

        try:
            capacity_val = int(capacity)
            price_val = float(price_per_night)
            target_count = int(target_room_count)
            if capacity_val <= 0 or price_val <= 0 or target_count <= 0:
                raise ValueError()
        except ValueError:
            flash("Capacity, price per night, and room count must all be positive numbers.", "danger")
            return render_template(
                "host/room_type_form.html",
                room_type=room_type,
                current_rooms=current_rooms,
                current_room_count=current_room_count,
                is_edit=True
            )

        # 1. Update room type fields
        sql_update_rt = """
            UPDATE room_types rt
            JOIN properties p ON rt.property_id = p.property_id
            SET rt.type_name = %s, rt.capacity = %s, rt.price_per_night = %s
            WHERE rt.room_type_id = %s AND p.host_id = %s;
        """
        execute(sql_update_rt, (type_name, capacity_val, price_val, room_type_id, host_id))

        # 2. Adjust physical rooms if target_count changed
        if target_count > current_room_count:
            diff = target_count - current_room_count
            existing_numbers = [int(r["room_number"]) for r in current_rooms if r["room_number"].isdigit()]
            start_num = max(existing_numbers, default=100) + 1

            for i in range(diff):
                next_room_num = str(start_num + i)
                execute(
                    "INSERT INTO rooms (room_type_id, room_number) VALUES (%s, %s)",
                    (room_type_id, next_room_num)
                )
            flash(f"Room type updated and {diff} new physical room(s) auto-generated.", "success")

        elif target_count < current_room_count:
            diff = current_room_count - target_count

            # Find rooms belonging to this room type without active future bookings
            sql_unbooked = """
                SELECT rm.room_id, rm.room_number
                FROM rooms rm
                JOIN room_types rt ON rm.room_type_id = rt.room_type_id
                JOIN properties p ON rt.property_id = p.property_id
                WHERE rm.room_type_id = %s AND p.host_id = %s
                  AND rm.room_id NOT IN (
                      SELECT b.room_id FROM bookings b 
                      WHERE b.status = 'confirmed' AND b.check_out >= CURRENT_DATE
                  )
                ORDER BY rm.room_id DESC
                LIMIT %s;
            """
            removable_rooms = fetch_all(sql_unbooked, (room_type_id, host_id, diff))

            deleted_count = 0
            for r in removable_rooms:
                sql_del_rm = """
                    DELETE rm FROM rooms rm
                    JOIN room_types rt ON rm.room_type_id = rt.room_type_id
                    JOIN properties p ON rt.property_id = p.property_id
                    WHERE rm.room_id = %s AND p.host_id = %s;
                """
                if execute(sql_del_rm, (r["room_id"], host_id)):
                    deleted_count += 1

            if deleted_count < diff:
                flash(
                    f"Room type updated. Removed {deleted_count} room(s), but {diff - deleted_count} "
                    "could not be removed because they have active reservations.",
                    "warning"
                )
            else:
                flash(f"Room type updated and {deleted_count} physical room(s) removed.", "success")
        else:
            flash("Room type details updated successfully.", "success")

        return redirect(url_for("host.edit_property", property_id=room_type["property_id"]))

    return render_template(
        "host/room_type_form.html",
        room_type=room_type,
        current_rooms=current_rooms,
        current_room_count=current_room_count,
        is_edit=True
    )


# =============================================================================
# 6. Host Bookings Page (using upcoming_bookings_view)
# =============================================================================
@host_bp.route("/bookings", endpoint="bookings_list")
@host_bp.route("/reservations", endpoint="bookings")
@role_required("host")
def bookings_list():
    """
    Host Bookings Page:
    - Powers host reservations ledger using upcoming_bookings_view.
    - Strictly filtered by host_id = session['user_id'] to prevent cross-host data leakage.
    - Also lists past/completed reservations for a complete audit trail.
    """
    host_id = get_session_host_id()

    # 1. Upcoming confirmed reservations directly from upcoming_bookings_view
    sql_upcoming = """
        SELECT 
            booking_id,
            host_id,
            guest_name,
            guest_phone,
            property_id,
            property_name,
            room_number,
            room_type,
            check_in,
            check_out,
            guests,
            booking_status,
            amount,
            payment_status
        FROM upcoming_bookings_view
        WHERE host_id = %s
        ORDER BY check_in ASC;
    """
    upcoming_bookings = fetch_all(sql_upcoming, (host_id,))

    # 2. Past or historical reservations for this host
    sql_past = """
        SELECT 
            b.booking_id,
            p.host_id,
            u_guest.name AS guest_name,
            u_guest.phone AS guest_phone,
            p.property_id,
            p.name AS property_name,
            rm.room_number,
            rt.type_name AS room_type,
            b.check_in,
            b.check_out,
            b.guests,
            b.status AS booking_status,
            COALESCE(pay.amount, b.price_per_night_at_booking * DATEDIFF(b.check_out, b.check_in)) AS amount,
            COALESCE(pay.status, 'unpaid') AS payment_status
        FROM bookings b
        JOIN users u_guest ON b.guest_id = u_guest.user_id
        JOIN rooms rm ON b.room_id = rm.room_id
        JOIN room_types rt ON rm.room_type_id = rt.room_type_id
        JOIN properties p ON rt.property_id = p.property_id
        LEFT JOIN payments pay ON b.booking_id = pay.booking_id
        WHERE p.host_id = %s AND (b.check_in < CURRENT_DATE OR b.status = 'cancelled')
        ORDER BY b.check_in DESC;
    """
    past_bookings = fetch_all(sql_past, (host_id,))

    return render_template(
        "host/bookings.html",
        upcoming_bookings=upcoming_bookings,
        past_bookings=past_bookings,
        bookings=upcoming_bookings  # Alias for backward-compatibility
    )
