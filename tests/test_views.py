"""
Hommy Cottage - Database Views Verification Tests
Validates sql/03_views.sql:
1. property_rating_view
2. property_search_view
3. host_revenue_view
4. city_revenue_view
5. upcoming_bookings_view
"""
from pathlib import Path


def test_views_file_structure():
    """Verify sql/03_views.sql exists, uses CREATE OR REPLACE VIEW, and has comments for each view."""
    views_path = Path("sql/03_views.sql")
    assert views_path.exists(), "sql/03_views.sql must exist"
    content = views_path.read_text(encoding="utf-8")

    views = [
        "property_rating_view",
        "property_search_view",
        "host_revenue_view",
        "city_revenue_view",
        "upcoming_bookings_view"
    ]
    for view in views:
        assert f"CREATE OR REPLACE VIEW {view}" in content, f"CREATE OR REPLACE VIEW {view} missing"
        assert f"View: {view}" in content, f"Header comment for {view} missing"
        assert "Purpose:" in content, "Purpose explanation comment missing"


def test_views_query_results_and_logic(app):
    """Verify all 5 views return accurate aggregated data and observe business constraints."""
    from db import query_one, query_all

    with app.app_context():
        # 1. property_rating_view
        ratings = query_all("SELECT * FROM property_rating_view")
        assert len(ratings) > 0
        for r in ratings:
            assert "property_id" in r
            assert "avg_rating" in r
            assert "review_count" in r
            assert 0.0 <= float(r["avg_rating"]) <= 5.0
            assert int(r["review_count"]) >= 0

        # 2. property_search_view (only approved properties)
        search_rows = query_all("SELECT * FROM property_search_view")
        assert len(search_rows) == 26  # Exactly 26 approved properties
        for s in search_rows:
            assert float(s["starting_price"]) > 0.0
            assert s["city_name"] is not None
            assert s["type_name"] is not None
            assert s["primary_image"].startswith("/static/img/sample/")
            assert float(s["avg_rating"]) >= 0.0

        # 3. host_revenue_view (counts only successful payments)
        host_rev = query_all("SELECT * FROM host_revenue_view")
        assert len(host_rev) == 5  # 5 hosts
        total_host_rev = sum(float(h["total_revenue"]) for h in host_rev)
        assert total_host_rev > 0

        # 4. city_revenue_view
        city_rev = query_all("SELECT * FROM city_revenue_view")
        assert len(city_rev) == 12  # 12 cities
        for c in city_rev:
            assert "city_id" in c
            assert "city_name" in c
            assert int(c["bookings"]) >= 0
            assert float(c["revenue"]) >= 0.0

        # 5. upcoming_bookings_view (only future / active confirmed reservations)
        upcoming = query_all("SELECT * FROM upcoming_bookings_view")
        assert len(upcoming) > 0
        for u in upcoming:
            assert u["booking_status"] == "confirmed"
            assert str(u["check_in"]) >= "2026-10-14"
            assert float(u["amount"]) > 0
            assert u["guest_name"] is not None
            assert u["property_name"] is not None
            assert u["room_number"] is not None
