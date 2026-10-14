-- =====================================================================
-- Hommy Cottage - Business Integrity Triggers (MySQL 8.0)
-- File: sql/04_triggers.sql
-- Description: Enforces reservation date non-overlap, review eligibility,
--              automated refund on cancellation, and guest capacity limits.
-- =====================================================================

USE hommy_cottage;

DELIMITER $$

-- ---------------------------------------------------------------------
-- 1. Trigger: trg_prevent_overlap
-- Business Rule:
--   Prevents double-booking the same room for overlapping dates upon INSERT.
--   A conflict occurs if an existing active (non-cancelled) reservation has
--   check_in < NEW.check_out AND check_out > NEW.check_in.
--   Same-day checkout and check-in (turnover) is allowed.
--
-- Example Firing:
--   INSERT INTO bookings (booking_id, guest_id, room_id, check_in, check_out, guests, price_per_night_at_booking, status)
--   VALUES (901, 7, 1, '2026-06-06', '2026-06-07', 2, 2250.00, 'confirmed');
--   -- Fires because room 1 is already booked from 2026-06-05 to 2026-06-08.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_prevent_overlap$$
CREATE TRIGGER trg_prevent_overlap
BEFORE INSERT ON bookings
FOR EACH ROW
BEGIN
    DECLARE v_conflict_count INT DEFAULT 0;

    IF NEW.status != 'cancelled' THEN
        SELECT COUNT(*) INTO v_conflict_count
        FROM bookings
        WHERE room_id = NEW.room_id
          AND status != 'cancelled'
          AND check_in < NEW.check_out
          AND check_out > NEW.check_in;

        IF v_conflict_count > 0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Booking conflict: Room is already booked for overlapping dates.';
        END IF;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- 2. Trigger: trg_prevent_overlap_update
-- Business Rule:
--   Ensures date, room, or status modifications on existing bookings
--   do not collide with another active reservation for the same room.
--   Excludes the row itself (booking_id != NEW.booking_id).
--   Same-day checkout and check-in (turnover) is allowed.
--
-- Example Firing:
--   UPDATE bookings SET check_in = '2026-06-06', check_out = '2026-06-09' WHERE booking_id = 2;
--   -- Fires if updating booking 2 creates an overlap with another booking on the same room.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_prevent_overlap_update$$
CREATE TRIGGER trg_prevent_overlap_update
BEFORE UPDATE ON bookings
FOR EACH ROW
BEGIN
    DECLARE v_conflict_count INT DEFAULT 0;

    IF NEW.status != 'cancelled' THEN
        SELECT COUNT(*) INTO v_conflict_count
        FROM bookings
        WHERE room_id = NEW.room_id
          AND booking_id != NEW.booking_id
          AND status != 'cancelled'
          AND check_in < NEW.check_out
          AND check_out > NEW.check_in;

        IF v_conflict_count > 0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Booking conflict: Updated reservation dates overlap with another active booking.';
        END IF;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- 3. Trigger: trg_review_after_checkout
-- Business Rule:
--   Restricts review submissions to verified, completed stays. Rejects
--   the insert if the booking is cancelled or if its check_out date
--   has not yet occurred (future stay).
--
-- Example Firing:
--   INSERT INTO reviews (review_id, booking_id, rating, comment, created_at)
--   VALUES (902, 5, 5, 'Great vacation', NOW());
--   -- Fires because booking 5 is a cancelled reservation.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_review_after_checkout$$
CREATE TRIGGER trg_review_after_checkout
BEFORE INSERT ON reviews
FOR EACH ROW
BEGIN
    DECLARE v_booking_status VARCHAR(20);
    DECLARE v_check_out DATE;

    SELECT status, check_out INTO v_booking_status, v_check_out
    FROM bookings
    WHERE booking_id = NEW.booking_id;

    IF v_booking_status IS NULL THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Review rejected: Associated booking does not exist.';
    ELSEIF v_booking_status = 'cancelled' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Review rejected: Cannot review a cancelled reservation.';
    ELSEIF v_check_out > CURRENT_DATE() THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Review rejected: Reviews can only be submitted after checkout date.';
    END IF;
END$$

-- ---------------------------------------------------------------------
-- 4. Trigger: trg_refund_on_cancel
-- Business Rule:
--   Automated ledger synchronization. When a booking status transitions
--   from non-cancelled to 'cancelled', automatically updates the matching
--   payment status from 'success' to 'refunded'.
--
-- Example Firing:
--   UPDATE bookings SET status = 'cancelled' WHERE booking_id = 1;
--   -- Fires and updates the corresponding row in payments to status = 'refunded'.
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_refund_on_cancel$$
CREATE TRIGGER trg_refund_on_cancel
AFTER UPDATE ON bookings
FOR EACH ROW
BEGIN
    IF NEW.status = 'cancelled' AND OLD.status != 'cancelled' THEN
        UPDATE payments
        SET status = 'refunded'
        WHERE booking_id = NEW.booking_id;
    END IF;
END$$

-- ---------------------------------------------------------------------
-- 5. Trigger: trg_guest_capacity
-- Business Rule:
--   Safety and occupancy enforcement. Rejects booking insertions where
--   the requested number of guests exceeds the maximum capacity of the
--   corresponding room type.
--
-- Example Firing:
--   INSERT INTO bookings (booking_id, guest_id, room_id, check_in, check_out, guests, price_per_night_at_booking, status)
--   VALUES (903, 7, 1, '2027-05-01', '2027-05-05', 20, 2250.00, 'confirmed');
--   -- Fires because 20 guests exceeds room 1 type capacity (capacity = 2).
-- ---------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_guest_capacity$$
CREATE TRIGGER trg_guest_capacity
BEFORE INSERT ON bookings
FOR EACH ROW
BEGIN
    DECLARE v_capacity INT DEFAULT 0;

    SELECT rt.capacity INTO v_capacity
    FROM rooms rm
    JOIN room_types rt ON rm.room_type_id = rt.room_type_id
    WHERE rm.room_id = NEW.room_id;

    IF v_capacity IS NULL OR v_capacity = 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Capacity validation error: Room or room type not found.';
    ELSEIF NEW.guests > v_capacity THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Capacity exceeded: Guest count exceeds maximum room occupancy.';
    END IF;
END$$

DELIMITER ;
