"""
Tests for room management and date-based availability.

These tests use the real MySQL schema and create temporary records because
schema.sql intentionally does not seed rooms or room types.
"""

from __future__ import annotations

import json
import random

import pytest


def _json(resp) -> dict:
    assert resp.content_type == "application/json", resp.data.decode()
    return json.loads(resp.data)


def _unique() -> str:
    return str(random.randint(100000, 999999))


def _authed_client(app, role: str):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = random.randint(100000, 999999)
            sess["username"] = f"pytest_{role.lower()}"
            sess["role"] = role
        yield client


@pytest.fixture()
def as_admin(app):
    yield from _authed_client(app, "Admin")


@pytest.fixture()
def as_receptionist(app):
    yield from _authed_client(app, "Receptionist")


@pytest.fixture()
def as_guest_role(app):
    yield from _authed_client(app, "Guest")


@pytest.fixture()
def room_fixture(app, require_db):
    created = {"reservation_ids": [], "room_nos": [], "guest_ids": [], "type_ids": []}

    def factory(*, status="Available", floor=9, base_price="123.45", capacity=2):
        suffix = _unique()
        room_no = int(f"9{suffix}")
        type_name = f"_pytest_type_{suffix}"
        with app.app_context():
            from app.db import db_cursor
            with db_cursor(commit_on_exit=True) as cur:
                cur.execute(
                    "INSERT INTO room_type (type_name, base_price, capacity, description) "
                    "VALUES (%s, %s, %s, %s)",
                    (type_name, base_price, capacity, "temporary room test type"),
                )
                type_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO room (room_no, type_id, floor, status) VALUES (%s, %s, %s, %s)",
                    (room_no, type_id, floor, status),
                )
        created["type_ids"].append(type_id)
        created["room_nos"].append(room_no)
        return {"room_no": room_no, "type_id": type_id, "type_name": type_name}

    yield factory, created

    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            for reservation_id in created["reservation_ids"]:
                cur.execute("DELETE FROM reservation_room WHERE reservation_id = %s", (reservation_id,))
                cur.execute("DELETE FROM reservation WHERE reservation_id = %s", (reservation_id,))
            for room_no in created["room_nos"]:
                cur.execute("DELETE FROM housekeeping_task WHERE room_no = %s", (room_no,))
                cur.execute("DELETE FROM room WHERE room_no = %s", (room_no,))
            for type_id in created["type_ids"]:
                cur.execute("DELETE FROM room_type WHERE type_id = %s", (type_id,))
            for guest_id in created["guest_ids"]:
                cur.execute("DELETE FROM guest WHERE guest_id = %s", (guest_id,))


def _create_guest(app, created):
    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "INSERT INTO guest (name, phone, email) VALUES (%s, %s, %s)",
                ("Room Test Guest", f"+700{_unique()}", f"room_{_unique()}@example.com"),
            )
            guest_id = cur.lastrowid
    created["guest_ids"].append(guest_id)
    return guest_id


def _create_reservation(app, created, room_no, *, status="Booked",
                        check_in="2031-05-10", check_out="2031-05-15"):
    guest_id = _create_guest(app, created)
    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            cur.execute(
                "INSERT INTO reservation (guest_id, check_in, check_out, status) "
                "VALUES (%s, %s, %s, %s)",
                (guest_id, check_in, check_out, status),
            )
            reservation_id = cur.lastrowid
            cur.execute(
                "INSERT INTO reservation_room (reservation_id, room_no, rate_charged) "
                "VALUES (%s, %s, %s)",
                (reservation_id, room_no, "123.45"),
            )
    created["reservation_ids"].append(reservation_id)
    return reservation_id


class TestRoomAvailability:
    def test_valid_availability_search_uses_date_range(self, as_guest_role, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Available")
        resp = as_guest_role.get("/api/rooms/available?from=2031-05-01&to=2031-05-03")
        assert resp.status_code == 200
        body = _json(resp)
        room_nos = [item["room_no"] for item in body["data"]["rooms"]]
        assert room["room_no"] in room_nos
        assert body["data"]["availability_source"] == "find_available_rooms"

    @pytest.mark.parametrize(
        "query",
        [
            "from=2031-05-03&to=2031-05-03",
            "from=2031-05-04&to=2031-05-03",
            "from=05-03-2031&to=2031-05-04",
            "from=2031-05-03",
        ],
    )
    def test_invalid_date_ranges(self, as_guest_role, query):
        resp = as_guest_role.get(f"/api/rooms/available?{query}")
        assert resp.status_code == 400
        assert _json(resp)["error"]["code"] == "VALIDATION_ERROR"

    def test_overlapping_active_reservations_are_excluded(self, app, as_guest_role, room_fixture, require_db):
        factory, created = room_fixture
        room = factory(status="Available")
        _create_reservation(app, created, room["room_no"], check_in="2031-05-10", check_out="2031-05-15")

        resp = as_guest_role.get("/api/rooms/available?from=2031-05-12&to=2031-05-14")
        assert resp.status_code == 200
        assert room["room_no"] not in [item["room_no"] for item in _json(resp)["data"]["rooms"]]

    def test_maintenance_rooms_are_excluded(self, as_guest_role, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Maintenance")
        resp = as_guest_role.get("/api/rooms/available?from=2031-05-01&to=2031-05-03")
        assert resp.status_code == 200
        assert room["room_no"] not in [item["room_no"] for item in _json(resp)["data"]["rooms"]]

    def test_current_checked_in_occupancy_is_excluded_by_overlap(self, app, as_guest_role, room_fixture, require_db):
        factory, created = room_fixture
        room = factory(status="Occupied")
        _create_reservation(
            app, created, room["room_no"],
            status="Checked-in", check_in="2031-06-10", check_out="2031-06-12",
        )
        resp = as_guest_role.get("/api/rooms/available?from=2031-06-10&to=2031-06-11")
        assert resp.status_code == 200
        assert room["room_no"] not in [item["room_no"] for item in _json(resp)["data"]["rooms"]]

    def test_cleaning_room_status_is_reported_as_discrepancy(self, as_guest_role, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Cleaning")
        resp = as_guest_role.get("/api/rooms/available?from=2031-07-01&to=2031-07-03")
        assert resp.status_code == 200
        body = _json(resp)["data"]
        assert room["room_no"] in [item["room_no"] for item in body["rooms"]]
        assert {"room_no": room["room_no"], "status": "Cleaning"} in body["status_availability_discrepancies"]

    def test_concurrent_booking_attempts_are_rejected_by_database_procedure(self, app, room_fixture, require_db):
        factory, created = room_fixture
        room = factory(status="Available")
        guest_one = _create_guest(app, created)
        guest_two = _create_guest(app, created)

        with app.app_context():
            from app.db import get_db, release_db
            conn = get_db()
            cur = conn.cursor()
            try:
                cur.callproc("book_room", (guest_one, room["room_no"], "2031-08-01", "2031-08-04"))
                conn.commit()
                cur.execute(
                    "SELECT reservation_id FROM reservation_room WHERE room_no = %s",
                    (room["room_no"],),
                )
                created["reservation_ids"].extend(row[0] for row in cur.fetchall())
                with pytest.raises(Exception):
                    cur.callproc("book_room", (guest_two, room["room_no"], "2031-08-02", "2031-08-03"))
            finally:
                cur.close()
                release_db(conn)


class TestRoomReadsAndWrites:
    def test_receptionist_can_view_rooms_status_and_details(self, as_receptionist, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Available")
        assert as_receptionist.get("/api/rooms").status_code == 200
        assert as_receptionist.get("/api/rooms/status").status_code == 200
        detail = as_receptionist.get(f"/api/rooms/{room['room_no']}")
        assert detail.status_code == 200
        assert _json(detail)["data"]["room_no"] == room["room_no"]

    def test_missing_room_id_returns_404(self, as_admin, require_db):
        resp = as_admin.get("/api/rooms/999999999")
        assert resp.status_code == 404

    def test_guest_cannot_view_internal_room_status(self, as_guest_role):
        assert as_guest_role.get("/api/rooms").status_code == 403
        assert as_guest_role.get("/api/rooms/status").status_code == 403

    def test_guest_can_view_room_types(self, as_guest_role, require_db):
        resp = as_guest_role.get("/api/room-types")
        assert resp.status_code == 200
        assert "room_types" in _json(resp)["data"]

    def test_unauthorized_modifications(self, as_receptionist, as_guest_role, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Available")
        assert as_receptionist.post("/api/rooms", json={}).status_code == 403
        assert as_guest_role.put(f"/api/rooms/{room['room_no']}", json={"floor": 4}).status_code == 403
        assert as_guest_role.post("/api/room-types", json={}).status_code == 403

    def test_admin_can_create_room_type_and_room(self, app, as_admin, require_db):
        suffix = _unique()
        type_name = f"_pytest_api_type_{suffix}"
        room_no = int(f"8{suffix}")
        created_type_id = None
        try:
            type_resp = as_admin.post(
                "/api/room-types",
                json={"type_name": type_name, "base_price": "199.99", "capacity": 3},
            )
            assert type_resp.status_code == 201
            created_type_id = _json(type_resp)["data"]["type_id"]

            room_resp = as_admin.post(
                "/api/rooms",
                json={"room_no": room_no, "type_id": created_type_id, "floor": 8},
            )
            assert room_resp.status_code == 201
            assert _json(room_resp)["data"]["status"] == "Available"
        finally:
            with app.app_context():
                from app.db import db_cursor
                with db_cursor(commit_on_exit=True) as cur:
                    cur.execute("DELETE FROM room WHERE room_no = %s", (room_no,))
                    if created_type_id:
                        cur.execute("DELETE FROM room_type WHERE type_id = %s", (created_type_id,))

    def test_admin_can_update_floor_and_permitted_status(self, as_admin, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Available")
        resp = as_admin.put(f"/api/rooms/{room['room_no']}", json={"floor": 7, "status": "Maintenance"})
        assert resp.status_code == 200
        body = _json(resp)["data"]
        assert body["floor"] == 7
        assert body["status"] == "Maintenance"

    def test_admin_cannot_set_occupied_directly(self, as_admin, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Available")
        resp = as_admin.put(f"/api/rooms/{room['room_no']}", json={"status": "Occupied"})
        assert resp.status_code == 400
        assert "workflow" in _json(resp)["error"]["message"].lower()

    def test_room_type_validation(self, as_admin, require_db):
        resp = as_admin.post("/api/room-types", json={"type_name": "", "base_price": -1, "capacity": 0})
        assert resp.status_code == 400
        message = _json(resp)["error"]["message"]
        assert "type_name" in message
        assert "base_price" in message
        assert "capacity" in message

    def test_database_constraint_violations_return_conflict(self, as_admin, room_fixture, require_db):
        factory, _created = room_fixture
        room = factory(status="Available")
        resp = as_admin.post(
            "/api/rooms",
            json={"room_no": room["room_no"], "type_id": room["type_id"], "floor": 9},
        )
        assert resp.status_code == 409
