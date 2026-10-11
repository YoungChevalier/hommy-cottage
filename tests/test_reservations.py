"""
Tests for reservation booking and lifecycle endpoints.
"""

from __future__ import annotations

import concurrent.futures
import json
import random

import pytest


def _json(resp) -> dict:
    assert resp.content_type == "application/json", resp.data.decode()
    return json.loads(resp.data)


def _unique() -> str:
    return str(random.randint(100000, 999999))


def _client_with_session(app, role: str, *, guest_id=None):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = random.randint(100000, 999999)
            sess["username"] = f"pytest_{role.lower()}_{_unique()}"
            sess["role"] = role
            sess["guest_id"] = guest_id
        yield client


@pytest.fixture()
def as_admin(app):
    yield from _client_with_session(app, "Admin")


@pytest.fixture()
def as_receptionist(app):
    yield from _client_with_session(app, "Receptionist")


@pytest.fixture()
def reservation_data(app, require_db):
    created = {"reservation_ids": [], "room_nos": [], "guest_ids": [], "type_ids": []}

    def make_guest():
        with app.app_context():
            from app.db import db_cursor
            with db_cursor(commit_on_exit=True) as cur:
                cur.execute(
                    "INSERT INTO guest (name, phone, email) VALUES (%s, %s, %s)",
                    ("Reservation Test Guest", f"+701{_unique()}", f"res_{_unique()}@example.com"),
                )
                guest_id = cur.lastrowid
        created["guest_ids"].append(guest_id)
        return guest_id

    def make_room(*, status="Available", floor=6, base_price="150.00"):
        suffix = _unique()
        room_no = int(f"6{suffix}")
        with app.app_context():
            from app.db import db_cursor
            with db_cursor(commit_on_exit=True) as cur:
                cur.execute(
                    "INSERT INTO room_type (type_name, base_price, capacity, description) "
                    "VALUES (%s, %s, %s, %s)",
                    (f"_pytest_res_type_{suffix}", base_price, 2, "temporary reservation test type"),
                )
                type_id = cur.lastrowid
                cur.execute(
                    "INSERT INTO room (room_no, type_id, floor, status) VALUES (%s, %s, %s, %s)",
                    (room_no, type_id, floor, status),
                )
        created["type_ids"].append(type_id)
        created["room_nos"].append(room_no)
        return {"room_no": room_no, "type_id": type_id}

    def remember_reservation(reservation_id):
        if reservation_id not in created["reservation_ids"]:
            created["reservation_ids"].append(reservation_id)

    yield {
        "created": created,
        "make_guest": make_guest,
        "make_room": make_room,
        "remember_reservation": remember_reservation,
    }

    with app.app_context():
        from app.db import db_cursor
        with db_cursor(commit_on_exit=True) as cur:
            for reservation_id in created["reservation_ids"]:
                cur.execute("DELETE FROM payment WHERE reservation_id = %s", (reservation_id,))
                cur.execute("DELETE FROM service_usage WHERE reservation_id = %s", (reservation_id,))
                cur.execute("DELETE FROM review WHERE reservation_id = %s", (reservation_id,))
                cur.execute("DELETE FROM reservation_room WHERE reservation_id = %s", (reservation_id,))
                cur.execute("DELETE FROM reservation WHERE reservation_id = %s", (reservation_id,))
            for room_no in created["room_nos"]:
                cur.execute("DELETE FROM housekeeping_task WHERE room_no = %s", (room_no,))
                cur.execute("DELETE FROM room WHERE room_no = %s", (room_no,))
            for type_id in created["type_ids"]:
                cur.execute("DELETE FROM room_type WHERE type_id = %s", (type_id,))
            for guest_id in created["guest_ids"]:
                cur.execute("DELETE FROM app_user WHERE guest_id = %s", (guest_id,))
                cur.execute("DELETE FROM guest WHERE guest_id = %s", (guest_id,))


@pytest.fixture()
def guest_client(app, reservation_data):
    guest_id = reservation_data["make_guest"]()
    yield from _client_with_session(app, "Guest", guest_id=guest_id)


def _book(client, guest_id, room_no, check_in="2032-01-10", check_out="2032-01-12"):
    return client.post(
        "/api/reservations",
        json={
            "guest_id": guest_id,
            "room_no": room_no,
            "check_in": check_in,
            "check_out": check_out,
        },
    )


class TestReservationBooking:
    def test_valid_booking_uses_database_price_snapshot(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"](base_price="175.50")

        resp = _book(as_admin, guest_id, room["room_no"])
        assert resp.status_code == 201
        body = _json(resp)["data"]
        reservation_data["remember_reservation"](body["reservation_id"])
        assert body["guest_id"] == guest_id
        assert body["rooms"][0]["room_no"] == room["room_no"]
        assert body["rooms"][0]["rate_charged"] == 175.50

    @pytest.mark.parametrize(
        "payload",
        [
            {"check_in": "2032-01-10", "check_out": "2032-01-10"},
            {"check_in": "2032-01-11", "check_out": "2032-01-10"},
            {"check_in": "01-10-2032", "check_out": "2032-01-12"},
            {"check_in": "2032-01-10"},
        ],
    )
    def test_invalid_dates(self, as_admin, reservation_data, payload, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        data = {"guest_id": guest_id, "room_no": room["room_no"], **payload}
        resp = as_admin.post("/api/reservations", json=data)
        assert resp.status_code == 400
        assert _json(resp)["error"]["code"] == "VALIDATION_ERROR"

    def test_overlapping_reservation_rejected(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        guest_two = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        first = _book(as_admin, guest_id, room["room_no"], "2032-02-10", "2032-02-15")
        assert first.status_code == 201
        reservation_data["remember_reservation"](_json(first)["data"]["reservation_id"])

        second = _book(as_admin, guest_two, room["room_no"], "2032-02-14", "2032-02-16")
        assert second.status_code == 409
        assert "booked" in _json(second)["error"]["message"].lower()

    def test_adjacent_reservations_are_allowed(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        guest_two = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        first = _book(as_admin, guest_id, room["room_no"], "2032-03-10", "2032-03-15")
        assert first.status_code == 201
        reservation_data["remember_reservation"](_json(first)["data"]["reservation_id"])

        second = _book(as_admin, guest_two, room["room_no"], "2032-03-15", "2032-03-18")
        assert second.status_code == 201
        reservation_data["remember_reservation"](_json(second)["data"]["reservation_id"])

    def test_nonexistent_room_and_guest(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()

        missing_room = _book(as_admin, guest_id, 999999999)
        assert missing_room.status_code == 404

        missing_guest = _book(as_admin, 999999999, room["room_no"])
        assert missing_guest.status_code == 404

    def test_maintenance_room_rejected(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"](status="Maintenance")
        resp = _book(as_admin, guest_id, room["room_no"])
        assert resp.status_code == 409
        assert "maintenance" in _json(resp)["error"]["message"].lower()

    def test_frontend_price_is_rejected(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        resp = as_admin.post(
            "/api/reservations",
            json={
                "guest_id": guest_id,
                "room_no": room["room_no"],
                "check_in": "2032-04-01",
                "check_out": "2032-04-03",
                "rate_charged": "1.00",
            },
        )
        assert resp.status_code == 400

    def test_multi_room_payload_rejected_without_compensating_delete(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room_one = reservation_data["make_room"]()
        room_two = reservation_data["make_room"]()
        resp = as_admin.post(
            "/api/reservations",
            json={
                "guest_id": guest_id,
                "rooms": [room_one["room_no"], room_two["room_no"]],
                "check_in": "2032-04-10",
                "check_out": "2032-04-12",
            },
        )
        assert resp.status_code == 400
        assert "multi-room" in _json(resp)["error"]["message"].lower()


class TestReservationAccessAndOwnership:
    def test_unauthenticated_access_rejected(self, app):
        with app.test_client() as client:
            assert client.get("/api/reservations").status_code == 401
            assert client.post("/api/reservations", json={}).status_code == 401

    def test_guest_can_only_see_own_reservations(self, app, as_admin, reservation_data, require_db):
        own_guest = reservation_data["make_guest"]()
        other_guest = reservation_data["make_guest"]()
        room_one = reservation_data["make_room"]()
        room_two = reservation_data["make_room"]()
        own = _book(as_admin, own_guest, room_one["room_no"], "2032-05-01", "2032-05-03")
        other = _book(as_admin, other_guest, room_two["room_no"], "2032-05-01", "2032-05-03")
        own_id = _json(own)["data"]["reservation_id"]
        other_id = _json(other)["data"]["reservation_id"]
        reservation_data["remember_reservation"](own_id)
        reservation_data["remember_reservation"](other_id)

        with app.test_client() as guest:
            with guest.session_transaction() as sess:
                sess["user_id"] = random.randint(100000, 999999)
                sess["username"] = "guest_owner"
                sess["role"] = "Guest"
                sess["guest_id"] = own_guest
            assert guest.get(f"/api/reservations/{own_id}").status_code == 200
            assert guest.get(f"/api/reservations/{other_id}").status_code == 404
            listed = guest.get("/api/reservations")
            assert listed.status_code == 200
            ids = [row["reservation_id"] for row in _json(listed)["data"]["reservations"]]
            assert own_id in ids
            assert other_id not in ids

    def test_guest_cannot_book_for_other_guest(self, app, reservation_data, require_db):
        own_guest = reservation_data["make_guest"]()
        other_guest = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        with app.test_client() as guest:
            with guest.session_transaction() as sess:
                sess["user_id"] = random.randint(100000, 999999)
                sess["username"] = "guest_other"
                sess["role"] = "Guest"
                sess["guest_id"] = own_guest
            resp = _book(guest, other_guest, room["room_no"], "2032-06-01", "2032-06-03")
            assert resp.status_code == 400
            assert "own" in _json(resp)["error"]["message"].lower()

    def test_guest_can_create_own_reservation_without_supplying_guest_id(self, app, reservation_data, require_db):
        own_guest = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        with app.test_client() as guest:
            with guest.session_transaction() as sess:
                sess["user_id"] = random.randint(100000, 999999)
                sess["username"] = "guest_self"
                sess["role"] = "Guest"
                sess["guest_id"] = own_guest
            resp = guest.post(
                "/api/reservations",
                json={"room_no": room["room_no"], "check_in": "2032-06-10", "check_out": "2032-06-12"},
            )
            assert resp.status_code == 201
            reservation_data["remember_reservation"](_json(resp)["data"]["reservation_id"])


class TestReservationTransitions:
    def test_checkin_and_checkout_update_room_status_via_triggers(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        booked = _book(as_admin, guest_id, room["room_no"], "2032-07-01", "2032-07-03")
        reservation_id = _json(booked)["data"]["reservation_id"]
        reservation_data["remember_reservation"](reservation_id)

        checkin = as_admin.post(f"/api/reservations/{reservation_id}/checkin")
        assert checkin.status_code == 200
        assert _json(checkin)["data"]["status"] == "Checked-in"
        assert _json(checkin)["data"]["rooms"][0]["room_status"] == "Occupied"

        checkout = as_admin.post(f"/api/reservations/{reservation_id}/checkout")
        assert checkout.status_code == 200
        assert _json(checkout)["data"]["status"] == "Checked-out"
        assert _json(checkout)["data"]["rooms"][0]["room_status"] == "Cleaning"

    def test_cancel_booked_reservation(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        booked = _book(as_admin, guest_id, room["room_no"], "2032-07-10", "2032-07-13")
        reservation_id = _json(booked)["data"]["reservation_id"]
        reservation_data["remember_reservation"](reservation_id)

        cancel = as_admin.post(f"/api/reservations/{reservation_id}/cancel")
        assert cancel.status_code == 200
        assert _json(cancel)["data"]["status"] == "Cancelled"

    def test_illegal_state_transitions(self, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        booked = _book(as_admin, guest_id, room["room_no"], "2032-08-01", "2032-08-03")
        reservation_id = _json(booked)["data"]["reservation_id"]
        reservation_data["remember_reservation"](reservation_id)

        checkout_first = as_admin.post(f"/api/reservations/{reservation_id}/checkout")
        assert checkout_first.status_code == 409

        cancel = as_admin.post(f"/api/reservations/{reservation_id}/cancel")
        assert cancel.status_code == 200

        revive = as_admin.post(f"/api/reservations/{reservation_id}/checkin")
        assert revive.status_code == 409

    def test_guest_cannot_checkin_or_checkout(self, app, as_admin, reservation_data, require_db):
        guest_id = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()
        booked = _book(as_admin, guest_id, room["room_no"], "2032-08-10", "2032-08-13")
        reservation_id = _json(booked)["data"]["reservation_id"]
        reservation_data["remember_reservation"](reservation_id)

        with app.test_client() as guest:
            with guest.session_transaction() as sess:
                sess["user_id"] = random.randint(100000, 999999)
                sess["username"] = "guest_transition"
                sess["role"] = "Guest"
                sess["guest_id"] = guest_id
            assert guest.post(f"/api/reservations/{reservation_id}/checkin").status_code == 403
            assert guest.post(f"/api/reservations/{reservation_id}/checkout").status_code == 403


class TestReservationConcurrency:
    def test_concurrent_overlapping_booking_attempts_cannot_both_succeed(self, app, reservation_data, require_db):
        guest_one = reservation_data["make_guest"]()
        guest_two = reservation_data["make_guest"]()
        room = reservation_data["make_room"]()

        def attempt(guest_id):
            from app.services import reservation_service
            with app.app_context():
                reservation, err = reservation_service.create_reservation({
                    "guest_id": guest_id,
                    "room_no": room["room_no"],
                    "check_in": __import__("datetime").date(2032, 9, 1),
                    "check_out": __import__("datetime").date(2032, 9, 4),
                })
                if reservation:
                    reservation_data["remember_reservation"](reservation["reservation_id"])
                return reservation, err

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, [guest_one, guest_two]))

        successes = [reservation for reservation, err in results if reservation is not None]
        errors = [err for reservation, err in results if err]
        assert len(successes) == 1
        assert len(errors) == 1
        assert "already booked" in errors[0].lower()
