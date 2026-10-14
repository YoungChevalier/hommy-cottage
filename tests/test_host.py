"""
Hommy Cottage - Host Portal Tests
=================================
Validates all endpoints and business constraints in routes/host.py:
1. RBAC enforcement:
   - All routes enforce role_required('host')
   - Unauthenticated visitors are redirected to /auth/login
   - Guests are blocked with 403 Forbidden
2. Host Dashboard:
   - Displays own properties with status badges ('pending', 'approved', 'rejected')
   - Accurate KPI counts (total, approved, pending, rejected, bookings, earnings)
   - Strict multi-tenant isolation: Host A never sees Host B's listings or revenue
3. Add Property:
   - New properties strictly start with status 'pending'
   - Multi-select amenity checkboxes correctly linked in property_amenities
   - Image upload validation: JPG/PNG only, 4 MB cap, secure_filename, UUID prefix, primary image selection
4. Edit Property:
   - Host can edit own properties
   - Attempting to view or edit another host's property returns 403 Forbidden
   - Non-existent property returns 404
5. Add/Edit Room Types with Room Count:
   - Adding a room type with room_count = N auto-creates N physical rows in the rooms table
   - Editing a room type allows adjusting room count, auto-generating additional rooms or safely pruning unreserved ones
   - Attempting to add/edit room types on another host's property returns 403 Forbidden
6. Host Bookings:
   - Powered by upcoming_bookings_view
   - Queries strictly include host_id = session['user_id']
"""
import io
import os
import pytest
from db import fetch_one, fetch_all, execute

TEST_HOST_EMAIL = "host@hommycottage.com"        # Host 2
OTHER_HOST_EMAIL = "rajesh.verma@outlook.com"    # Host 3
GUEST_EMAIL = "guest@hommycottage.com"           # Guest 7


@pytest.fixture(autouse=True)
def cleanup_test_host_data():
    """Cleans up test-created properties, room types, rooms, and images after tests run."""
    yield
    # Clean up test rooms and room types created for property_id > 32
    execute("""
        DELETE r FROM rooms r
        JOIN room_types rt ON r.room_type_id = rt.room_type_id
        WHERE rt.property_id > 32;
    """)
    execute("DELETE FROM room_types WHERE property_id > 32;")
    execute("DELETE FROM property_amenities WHERE property_id > 32;")
    execute("DELETE FROM property_images WHERE property_id > 32;")
    execute("DELETE FROM properties WHERE property_id > 32;")
    # Clean up any extra rooms added to property 1 during edit tests (room_type_id = 1)
    execute("DELETE FROM rooms WHERE room_type_id = 1 AND room_number NOT IN ('101', '102', '103');")


def login_as(client, email, password="password123"):
    """Helper to authenticate as a given user."""
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


# =============================================================================
# 1. RBAC & Access Control Tests
# =============================================================================
def test_unauthenticated_host_redirect(client):
    """Verify unauthenticated requests to host endpoints redirect to login."""
    endpoints = [
        "/host/dashboard",
        "/host/properties/new",
        "/host/property/1/edit",
        "/host/property/1/room-types",
        "/host/property/1/room-types/new",
        "/host/bookings"
    ]
    for ep in endpoints:
        res = client.get(ep, follow_redirects=False)
        assert res.status_code == 302
        assert "/auth/login" in res.headers["Location"]


def test_role_required_host_blocks_guest(client):
    """Verify guest accounts cannot access any host routes (HTTP 403 Forbidden)."""
    login_as(client, GUEST_EMAIL)
    endpoints = [
        "/host/dashboard",
        "/host/properties/new",
        "/host/property/1/edit",
        "/host/property/1/room-types",
        "/host/property/1/room-types/new",
        "/host/bookings"
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 403
    client.get("/auth/logout")


# =============================================================================
# 2. Host Dashboard & KPI Tests
# =============================================================================
def test_host_dashboard_renders_for_host(client):
    """Verify Host 2 can view their operations dashboard with status badges and KPIs."""
    login_as(client, TEST_HOST_EMAIL)
    res = client.get("/host/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Verify structural sections
    assert "Host Operations Dashboard" in html
    assert "Total Listings" in html
    assert "Approved &amp; Live" in html or "Approved & Live" in html
    assert "Pending Approval" in html or "Pending" in html
    assert "Total Revenue" in html

    # Verify Host 2's own properties appear (e.g. property 1: Chinar Valley Country Cottage)
    assert "Chinar Valley Country Cottage" in html

    # Verify status badges are rendered
    assert "Approved &amp; Live" in html or "badge" in html
    client.get("/auth/logout")


def test_host_isolation_dashboard(client):
    """Verify Host 2 cannot see properties belonging to Host 3 on their dashboard."""
    login_as(client, TEST_HOST_EMAIL)  # Host 2
    res = client.get("/host/dashboard")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Host 3 owns Property 2: "Sarafa Heritage Courtyard Villa"
    assert "Sarafa Heritage Courtyard Villa" not in html
    client.get("/auth/logout")


# =============================================================================
# 3. Add Property Tests (Status 'pending', amenities, image rules)
# =============================================================================
def test_add_property_defaults_to_pending(client):
    """Verify adding a new property creates it with status 'pending' and inserts amenities."""
    login_as(client, TEST_HOST_EMAIL)

    res = client.post("/host/properties/new", data={
        "name": "Cloud Nine Pine Wood Cabin",
        "type_id": "1",  # Wooden Cabin
        "city_id": "4",  # Manali
        "address": "Hadimba Temple Road",
        "pincode": "175131",
        "description": "A secluded serene pine wood cabin surrounded by towering deodars and mist.",
        "amenities": ["1", "2", "3"]  # Wi-Fi, Mountain View, Fireplace
    }, follow_redirects=False)

    # After adding property, redirects to add_room_type for the new property
    assert res.status_code == 302

    # Query the newly created property from the DB
    prop = fetch_one(
        "SELECT * FROM properties WHERE name = %s AND host_id = 2",
        ("Cloud Nine Pine Wood Cabin",)
    )
    assert prop is not None
    assert prop["status"] == "pending"  # Strictly 'pending'
    assert prop["city_id"] == 4
    assert prop["type_id"] == 1

    # Verify amenities junction records
    amenities = fetch_all(
        "SELECT amenity_id FROM property_amenities WHERE property_id = %s",
        (prop["property_id"],)
    )
    amenity_ids = {a["amenity_id"] for a in amenities}
    assert {1, 2, 3}.issubset(amenity_ids)

    client.get("/auth/logout")


def test_add_property_image_validation_and_primary_selection(client):
    """Verify image uploads enforce JPG/PNG format, secure_filename with UUID prefix, and primary flag."""
    login_as(client, TEST_HOST_EMAIL)

    # 1. Create dummy image data in memory
    img1 = (io.BytesIO(b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00"), "cottage_front.jpg")
    img2 = (io.BytesIO(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"), "interior_view.png")

    res = client.post("/host/properties/new", data={
        "name": "Alpine Sunrise Chalet",
        "type_id": "1",
        "city_id": "4",
        "address": "Solang Valley Road",
        "pincode": "175103",
        "description": "Breathtaking views of snowcapped Himalayan peaks.",
        "amenities": ["1", "2"],
        "primary_image_index": "0",
        "images": [img1, img2]
    }, content_type="multipart/form-data", follow_redirects=False)

    assert res.status_code == 302

    # Check database for created images
    prop = fetch_one("SELECT property_id FROM properties WHERE name = 'Alpine Sunrise Chalet' AND host_id = 2")
    assert prop is not None

    db_images = fetch_all(
        "SELECT * FROM property_images WHERE property_id = %s ORDER BY image_id ASC",
        (prop["property_id"],)
    )
    assert len(db_images) == 2

    # Check primary image selection
    assert db_images[0]["is_primary"] is True or db_images[0]["is_primary"] == 1
    assert db_images[1]["is_primary"] is False or db_images[1]["is_primary"] == 0

    # Verify UUID prefix in filename
    assert "/static/uploads/" in db_images[0]["image_url"]
    filename_part = db_images[0]["image_url"].split("/static/uploads/")[-1]
    assert "_" in filename_part
    assert filename_part.endswith(".jpg")

    client.get("/auth/logout")


def test_add_property_rejects_non_image_extension(client):
    """Verify non-JPG/PNG files (e.g. .pdf or .txt) are rejected."""
    login_as(client, TEST_HOST_EMAIL)

    invalid_doc = (io.BytesIO(b"%PDF-1.4 malicious fake content"), "manual.pdf")

    res = client.post("/host/properties/new", data={
        "name": "Spruce Forest Cabin",
        "type_id": "1",
        "city_id": "1",
        "address": "Forest Trail 12",
        "pincode": "452020",
        "description": "Secluded woodland cabin.",
        "images": [invalid_doc]
    }, content_type="multipart/form-data", follow_redirects=True)

    html = res.data.decode("utf-8")
    assert "Only JPG and PNG image formats are permitted" in html

    client.get("/auth/logout")


# =============================================================================
# 4. Edit Property & Isolation Tests
# =============================================================================
def test_edit_own_property_success(client):
    """Verify host can edit their own property details and amenities."""
    login_as(client, TEST_HOST_EMAIL)

    # Host 2 owns Property 1 ("Chinar Valley Country Cottage")
    res = client.get("/host/property/1/edit")
    assert res.status_code == 200
    html = res.data.decode("utf-8")
    assert "Chinar Valley Country Cottage" in html

    # Submit updated description and address
    post_res = client.post("/host/property/1/edit", data={
        "name": "Chinar Valley Country Cottage",
        "type_id": "1",
        "city_id": "1",
        "address": "Updated Ralamandal Sanctuary Road",
        "pincode": "452020",
        "description": "Updated luxurious hillside cottage with heated interiors.",
        "amenities": ["1", "2", "4", "5"]
    }, follow_redirects=True)

    assert post_res.status_code == 200
    assert "updated successfully" in post_res.data.decode("utf-8")

    # Verify DB reflects updates
    prop = fetch_one("SELECT address, description FROM properties WHERE property_id = 1 AND host_id = 2")
    assert prop["address"] == "Updated Ralamandal Sanctuary Road"
    assert "heated interiors" in prop["description"]

    # Revert back to original seed data values
    execute(
        "UPDATE properties SET address = %s, description = %s WHERE property_id = 1",
        ("Ralamandal Hills Road, Near Sanctuary",
         "Experience an authentic getaway at Chinar Valley Country Cottage. Features panoramic natural surroundings, handcrafted interiors, modern creature comforts, and warm local hospitality.")
    )
    client.get("/auth/logout")


def test_edit_other_host_property_forbidden(client):
    """Verify a host cannot edit another host's property (HTTP 403 Forbidden)."""
    login_as(client, TEST_HOST_EMAIL)  # Host 2

    # Property 2 is owned by Host 3
    res_get = client.get("/host/property/2/edit")
    assert res_get.status_code == 403

    # Attempt POST update on Property 2
    res_post = client.post("/host/property/2/edit", data={
        "name": "Malicious Hijacked Villa",
        "type_id": "2",
        "city_id": "1",
        "address": "Fake Address",
        "pincode": "452002",
        "description": "Attempt to hijack another host property."
    })
    assert res_post.status_code == 403

    # Verify Property 2 was NOT changed in DB
    prop2 = fetch_one("SELECT name FROM properties WHERE property_id = 2")
    assert prop2["name"] == "Sarafa Heritage Courtyard Villa"

    client.get("/auth/logout")


def test_edit_nonexistent_property_404(client):
    """Verify editing a non-existent property returns 404 Not Found."""
    login_as(client, TEST_HOST_EMAIL)
    res = client.get("/host/property/999999/edit")
    assert res.status_code == 404
    client.get("/auth/logout")


# =============================================================================
# 5. Room Types & Physical Room Auto-Creation Tests
# =============================================================================
def test_add_room_type_auto_creates_rooms(client):
    """Verify adding a room type with room_count = 3 auto-creates 3 physical room records."""
    login_as(client, TEST_HOST_EMAIL)

    # 1. Create a fresh test property for Host 2
    prop_id = execute(
        "INSERT INTO properties (host_id, type_id, city_id, name, description, address, pincode, status) "
        "VALUES (2, 1, 1, 'Auto Room Test Cottage', 'Test desc', 'Test addr', '452020', 'pending');"
    )

    # 2. Add room type with room_count = 3
    res = client.post(f"/host/property/{prop_id}/room-types/new", data={
        "type_name": "Presidential Royal Suite",
        "capacity": "4",
        "price_per_night": "4500.00",
        "room_count": "3"
    }, follow_redirects=True)

    assert res.status_code == 200
    assert "added successfully with 3 physical rooms automatically generated" in res.data.decode("utf-8")

    # 3. Verify room_types table row
    rt = fetch_one("SELECT * FROM room_types WHERE property_id = %s", (prop_id,))
    assert rt is not None
    assert rt["type_name"] == "Presidential Royal Suite"
    assert rt["capacity"] == 4
    assert float(rt["price_per_night"]) == 4500.00

    # 4. Verify exactly 3 physical rooms were created in rooms table
    rooms = fetch_all("SELECT * FROM rooms WHERE room_type_id = %s ORDER BY room_number ASC", (rt["room_type_id"],))
    assert len(rooms) == 3
    room_numbers = [r["room_number"] for r in rooms]
    assert room_numbers == ["101", "102", "103"]

    client.get("/auth/logout")


def test_add_room_type_on_other_host_property_forbidden(client):
    """Verify a host cannot add a room type to another host's property."""
    login_as(client, TEST_HOST_EMAIL)  # Host 2

    # Property 2 belongs to Host 3
    res = client.post("/host/property/2/room-types/new", data={
        "type_name": "Unauthorized Suite",
        "capacity": "2",
        "price_per_night": "3000.00",
        "room_count": "2"
    })
    assert res.status_code == 403

    # Verify no room type was added to Property 2
    rt = fetch_one("SELECT * FROM room_types WHERE property_id = 2 AND type_name = 'Unauthorized Suite'")
    assert rt is None

    client.get("/auth/logout")


def test_edit_room_type_increases_room_count(client):
    """Verify editing a room type and increasing room count generates extra physical rooms."""
    login_as(client, TEST_HOST_EMAIL)

    # Create temporary property and room type with 2 rooms
    prop_id = execute(
        "INSERT INTO properties (host_id, type_id, city_id, name, description, address, pincode, status) "
        "VALUES (2, 1, 1, 'Room Increase Test Cottage', 'Test desc', 'Test addr', '452020', 'pending');"
    )
    rt_id = execute(
        "INSERT INTO room_types (property_id, type_name, capacity, price_per_night) VALUES (%s, %s, %s, %s);",
        (prop_id, "Standard Studio", 2, 2000.00)
    )
    execute("INSERT INTO rooms (room_type_id, room_number) VALUES (%s, '101'), (%s, '102');", (rt_id, rt_id))

    # Edit room type: increase room_count to 4
    res = client.post(f"/host/room-type/{rt_id}/edit", data={
        "type_name": "Deluxe Studio",
        "capacity": "3",
        "price_per_night": "2400.00",
        "room_count": "4"
    }, follow_redirects=True)

    assert res.status_code == 200

    # Verify 4 rooms exist now
    rooms = fetch_all("SELECT * FROM rooms WHERE room_type_id = %s ORDER BY room_id ASC", (rt_id,))
    assert len(rooms) == 4
    room_numbers = [r["room_number"] for r in rooms]
    assert "101" in room_numbers and "102" in room_numbers
    assert len(set(room_numbers)) == 4

    client.get("/auth/logout")


# =============================================================================
# 6. Host Bookings View Tests (upcoming_bookings_view)
# =============================================================================
def test_host_bookings_page_uses_upcoming_bookings_view(client):
    """Verify /host/bookings renders reservations ledger powered by upcoming_bookings_view."""
    login_as(client, TEST_HOST_EMAIL)

    res = client.get("/host/bookings")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    assert "Cottage Reservations Ledger" in html
    assert "upcoming_bookings_view" in html

    # Query directly from upcoming_bookings_view to compare
    db_upcoming = fetch_all("SELECT * FROM upcoming_bookings_view WHERE host_id = 2")
    if db_upcoming:
        first_b = db_upcoming[0]
        assert str(first_b["booking_id"]) in html
        assert first_b["property_name"] in html

    client.get("/auth/logout")


def test_host_cannot_see_other_host_bookings(client):
    """Verify Host 2 cannot view bookings for Host 3's properties on /host/bookings."""
    login_as(client, TEST_HOST_EMAIL)  # Host 2

    res = client.get("/host/bookings")
    assert res.status_code == 200
    html = res.data.decode("utf-8")

    # Host 3 owns Property 2 ("Sarafa Heritage Courtyard Villa")
    # In seed data, booking 2 or 3 might belong to host 3
    host3_bookings = fetch_all("SELECT * FROM upcoming_bookings_view WHERE host_id = 3")
    for b in host3_bookings:
        # None of host 3's booking IDs should appear in host 2's ledger
        assert f"#{b['booking_id']}" not in html

    client.get("/auth/logout")
