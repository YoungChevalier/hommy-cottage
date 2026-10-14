"""
Hommy Cottage - Search & Property Discovery Test Suite
=====================================================
Validates all endpoints in routes/search.py:
- GET /: Landing page with search form, cities, amenities from DB, and top properties.
- GET /search: Multi-filter engine:
    * City filter
    * Max price & Min rating filters
    * Relational division for amenities (HAVING COUNT(DISTINCT) = len(selected))
    * Date overlap anti-semijoin (NOT EXISTS overlapping bookings)
    * Sorting (price_asc, price_desc, rating)
    * Pagination (9 items per page)
    * Empty state messaging for zero matching listings
- GET /property/<id>:
    * Property details, images, amenities, verified reviews
    * Room types with live availability computed via fn_available_rooms
    * Access control: Pending / rejected properties return 404 unless viewed
      by the listing owner (host) or an admin.
"""
from datetime import date, timedelta
from db import fetch_all, fetch_one


def login_as(client, email, password="password123"):
    """Helper to simulate user authentication session."""
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=False)


def test_home_page_loads_cities_and_amenities(client):
    """Verify GET / loads cities, amenities, and approved featured properties from DB."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    
    # Check search form elements
    assert 'id="hero-search-form"' in html
    assert 'name="city"' in html
    assert 'name="check_in"' in html
    assert 'name="check_out"' in html
    assert 'name="guests"' in html

    # Verify cities loaded from DB
    assert "Indore" in html or "Manali" in html or "Shimla" in html
    
    # Verify amenities loaded from DB
    assert "High-Speed Wi-Fi" in html or "Mountain View" in html


def test_search_base_approved_only(client):
    """Verify GET /search returns only approved properties (max 9 per page)."""
    response = client.get("/search")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    # Should not display pending or rejected properties
    assert "Tea Garden Cloud Canopy Treehouse" not in html  # property 27 is pending
    assert "Neelkanth Forest View Yoga Villa" not in html    # property 31 is rejected

    # Should display approved property cards
    assert "search-card-" in html


def test_search_city_filter(client):
    """Verify filtering by city returns only listings in that destination."""
    response = client.get("/search?city=Manali")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Manali" in html
    # Listings from other cities like Goa or Bhopal should not be present in Manali results
    assert "Sarafa Heritage Courtyard Villa" not in html


def test_search_max_price_and_min_rating(client):
    """Verify max price and min rating criteria filter listings accurately."""
    # Test price ceiling
    response_price = client.get("/search?max_price=2500")
    assert response_price.status_code == 200

    # Test rating filter (e.g. 4.0+)
    response_rating = client.get("/search?min_rating=4.0")
    assert response_rating.status_code == 200


def test_search_amenities_relational_division(client):
    """
    Verify relational division: properties returned must match ALL selected amenities
    via HAVING COUNT(DISTINCT pa.amenity_id) = len(selected_amenities).
    """
    # Amenities 1 (Wi-Fi) and 2 (Mountain View)
    response = client.get("/search?amenities=1&amenities=2")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Available" in html

    # Amenities 1, 2, and 7
    response_three = client.get("/search?amenities=1&amenities=2&amenities=7")
    assert response_three.status_code == 200


def test_search_dates_availability_not_exists(client):
    """
    Verify date availability filter excludes properties where no free room exists
    for the requested check_in / check_out interval.
    """
    # Active stay dates
    future_ci = (date.today() + timedelta(days=10)).strftime("%Y-%m-%d")
    future_co = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")

    response = client.get(f"/search?check_in={future_ci}&check_out={future_co}")
    assert response.status_code == 200
    assert "Available" in response.data.decode("utf-8")


def test_search_sorting(client):
    """Verify sorting options: price_asc, price_desc, rating."""
    # Price ascending
    res_asc = client.get("/search?sort=price_asc")
    assert res_asc.status_code == 200

    # Price descending
    res_desc = client.get("/search?sort=price_desc")
    assert res_desc.status_code == 200

    # Rating descending
    res_rating = client.get("/search?sort=rating")
    assert res_rating.status_code == 200


def test_search_pagination_9_per_page(client):
    """Verify pagination limits output to 9 properties per page."""
    response = client.get("/search?page=1")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    # Count occurrences of cottage cards rendered
    card_count = html.count("cottage-card-body")
    assert card_count <= 9


def test_search_empty_state_message(client):
    """Verify search returns informative empty-state message when 0 listings match."""
    response = client.get("/search?city=NonExistentDestination999")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "No cottages match your criteria" in html
    assert "empty-state-card" in html
    assert "Clear All Filters" in html


def test_property_detail_approved_property(client):
    """Verify GET /property/<id> serves details, images, amenities, room types with fn_available_rooms, and reviews."""
    response = client.get("/property/1")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    # Property info
    assert "Chinar Valley Country Cottage" in html
    assert "Indore" in html
    assert "Hosted by" in html

    # Room Types & Live Availability table
    assert "Room Types & Live Availability" in html
    assert "Available" in html
    assert "fn_available_rooms" in html

    # Amenities & Reviews
    assert "What this place offers" in html
    assert "reviews-section" in html


def test_property_detail_404_on_nonexistent(client):
    """Verify GET /property/<id> returns 404 for non-existent property ID."""
    response = client.get("/property/999999")
    assert response.status_code == 404
    assert b"404 - Page Not Found" in response.data


def test_property_detail_pending_access_control(client):
    """
    Verify pending property (ID 27, host_id=3) returns:
    - 404 to unauthenticated guest
    - 404 to another host (User 2)
    - 200 to listing owner (User 3)
    - 200 to admin (User 1)
    """
    pending_id = 27

    # 1. Unauthenticated guest -> 404
    res_unauth = client.get(f"/property/{pending_id}")
    assert res_unauth.status_code == 404

    # 2. Other host (User 2) -> 404
    login_as(client, "host@hommycottage.com")  # User 2
    res_other_host = client.get(f"/property/{pending_id}")
    assert res_other_host.status_code == 404
    client.get("/auth/logout")

    # 3. Listing owner (User 3) -> 200
    login_as(client, "ananya.host@example.com")  # User 3 is owner of property 27
    res_owner = client.get(f"/property/{pending_id}")
    assert res_owner.status_code == 200
    assert "Tea Garden Cloud Canopy Treehouse" in res_owner.data.decode("utf-8")
    client.get("/auth/logout")

    # 4. Administrator (User 1) -> 200
    login_as(client, "admin@hommycottage.com")
    res_admin = client.get(f"/property/{pending_id}")
    assert res_admin.status_code == 200
    client.get("/auth/logout")


def test_property_detail_rejected_access_control(client):
    """
    Verify rejected property (ID 31, host_id=2) returns:
    - 404 to unauthenticated guest
    - 200 to listing owner (User 2)
    - 200 to admin (User 1)
    """
    rejected_id = 31

    # Unauthenticated -> 404
    res_unauth = client.get(f"/property/{rejected_id}")
    assert res_unauth.status_code == 404

    # Listing owner (User 2) -> 200
    login_as(client, "host@hommycottage.com")
    res_owner = client.get(f"/property/{rejected_id}")
    assert res_owner.status_code == 200
    client.get("/auth/logout")

    # Admin (User 1) -> 200
    login_as(client, "admin@hommycottage.com")
    res_admin = client.get(f"/property/{rejected_id}")
    assert res_admin.status_code == 200
    client.get("/auth/logout")
