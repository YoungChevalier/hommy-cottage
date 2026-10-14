-- =====================================================================
-- Hommy Cottage - Stored Procedures & Functions (MySQL 8.0)
-- File: sql/05_procedures.sql
-- Description: ACID-compliant reservation booking procedure, guest-authorized
--              cancellation procedure, and room inventory availability function.
-- =====================================================================

USE hommy_cottage;

DELIMITER $$

-- ---------------------------------------------------------------------
-- 1. Procedure: sp_book_room
-- Purpose:
--   Performs an atomic booking operation inside a single transaction:
--   - Validates input dates and room type capacity
--   - Locks candidate rooms of the requested type with SELECT ... FOR UPDATE
--   - Allocates the first available room (no overlapping active bookings)
--   - Inserts booking with historical price snapshot
--   - Inserts simulated payment record with status 'success'
--   - Commits transaction and returns the new booking ID via OUT parameter
--   - Rolls back and resignals if any exception occurs or no room is free
--
-- How to Call:
--   CALL sp_book_room(7, 1, '2026-11-01', '2026-11-05', 2, 'upi', @new_booking_id);
--   SELECT @new_booking_id AS booked_id;
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_book_room$$
CREATE PROCEDURE sp_book_room(
    IN  p_guest_id      INT,
    IN  p_room_type_id  INT,
    IN  p_check_in      DATE,
    IN  p_check_out     DATE,
    IN  p_guests        INT,
    IN  p_method        VARCHAR(20),
    OUT p_booking_id    INT
)
BEGIN
    DECLARE v_capacity INT DEFAULT 0;
    DECLARE v_price_per_night DECIMAL(10, 2) DEFAULT 0.00;
    DECLARE v_total_rooms INT DEFAULT 0;
    DECLARE v_selected_room_id INT DEFAULT NULL;
    DECLARE v_nights INT DEFAULT 0;
    DECLARE v_total_amount DECIMAL(10, 2) DEFAULT 0.00;

    -- Rollback on SQLEXCEPTION and re-raise the error
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    -- 1. Date Validation
    IF p_check_in IS NULL OR p_check_out IS NULL THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: Check-in and check-out dates are required.';
    END IF;

    IF p_check_out <= p_check_in THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: Check-out date must be strictly after check-in date.';
    END IF;

    IF p_check_in < CURRENT_DATE() THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: Check-in date cannot be in the past.';
    END IF;

    IF p_guests IS NULL OR p_guests < 1 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: Guest count must be at least 1.';
    END IF;

    -- 2. Verify Room Type and Capacity
    SELECT capacity, price_per_night
    INTO v_capacity, v_price_per_night
    FROM room_types
    WHERE room_type_id = p_room_type_id;

    IF v_capacity IS NULL OR v_capacity = 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: Room type not found.';
    END IF;

    IF p_guests > v_capacity THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: Requested guests exceed maximum room type capacity.';
    END IF;

    -- 3. Begin Transaction & Lock Room Inventory
    START TRANSACTION;

    -- Lock room rows of that type to prevent race conditions during allocation
    SELECT COUNT(*)
    INTO v_total_rooms
    FROM rooms
    WHERE room_type_id = p_room_type_id
    FOR UPDATE;

    IF v_total_rooms = 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: No rooms configured for this room type.';
    END IF;

    -- Pick the first free room for the requested dates
    SELECT rm.room_id
    INTO v_selected_room_id
    FROM rooms rm
    WHERE rm.room_type_id = p_room_type_id
      AND NOT EXISTS (
          SELECT 1
          FROM bookings b
          WHERE b.room_id = rm.room_id
            AND b.status != 'cancelled'
            AND b.check_in < p_check_out
            AND b.check_out > p_check_in
      )
    ORDER BY rm.room_id ASC
    LIMIT 1
    FOR UPDATE;

    -- Reject if no free room found
    IF v_selected_room_id IS NULL THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Booking failed: No available rooms found for the selected dates and room type.';
    END IF;

    -- 4. Calculate Nights and Total Amount
    SET v_nights = DATEDIFF(p_check_out, p_check_in);
    SET v_total_amount = v_nights * v_price_per_night;

    -- 5. Insert Booking
    INSERT INTO bookings (
        guest_id,
        room_id,
        check_in,
        check_out,
        guests,
        price_per_night_at_booking,
        status
    ) VALUES (
        p_guest_id,
        v_selected_room_id,
        p_check_in,
        p_check_out,
        p_guests,
        v_price_per_night,
        'confirmed'
    );

    SET p_booking_id = LAST_INSERT_ID();

    -- 6. Insert Matching Payment Record
    INSERT INTO payments (
        booking_id,
        amount,
        method,
        status,
        paid_at
    ) VALUES (
        p_booking_id,
        v_total_amount,
        COALESCE(p_method, 'upi'),
        'success',
        CURRENT_TIMESTAMP
    );

    COMMIT;
END$$


-- ---------------------------------------------------------------------
-- 2. Procedure: sp_cancel_booking
-- Purpose:
--   Cancels a reservation.
--   Enforces business rules:
--   - Booking must exist
--   - Booking must belong to the requesting guest (p_guest_id)
--   - Cancellation is allowed ONLY before check-in (check_in > CURRENT_DATE())
--   - Rejects cancellation if already cancelled
--   - Updates booking status to 'cancelled' and payment to 'refunded'
--
-- How to Call:
--   CALL sp_cancel_booking(15, 7);
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS sp_cancel_booking$$
CREATE PROCEDURE sp_cancel_booking(
    IN p_booking_id INT,
    IN p_guest_id   INT
)
BEGIN
    DECLARE v_owner_id INT;
    DECLARE v_check_in DATE;
    DECLARE v_status VARCHAR(20);
    DECLARE v_found INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT guest_id, check_in, status, 1
    INTO v_owner_id, v_check_in, v_status, v_found
    FROM bookings
    WHERE booking_id = p_booking_id
    FOR UPDATE;

    IF v_found = 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cancellation failed: Booking not found.';
    END IF;

    IF v_owner_id != p_guest_id THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cancellation failed: You can only cancel your own bookings.';
    END IF;

    IF v_status = 'cancelled' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cancellation failed: Booking is already cancelled.';
    END IF;

    IF v_check_in <= CURRENT_DATE() THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Cancellation failed: Cancellations are only permitted prior to the check-in date.';
    END IF;

    -- Update booking status
    UPDATE bookings
    SET status = 'cancelled'
    WHERE booking_id = p_booking_id;

    -- Update payment to refunded
    UPDATE payments
    SET status = 'refunded'
    WHERE booking_id = p_booking_id;

    COMMIT;
END$$


-- ---------------------------------------------------------------------
-- 3. Function: fn_available_rooms
-- Purpose:
--   Computes and returns the number of unreserved rooms for a given room
--   type across the specified date interval [p_check_in, p_check_out).
--   Correctly accounts for same-day checkout/check-in turnover.
--
-- How to Call / Query:
--   SELECT fn_available_rooms(1, '2026-11-01', '2026-11-05') AS available_rooms;
-- ---------------------------------------------------------------------
DROP FUNCTION IF EXISTS fn_available_rooms$$
CREATE FUNCTION fn_available_rooms(
    p_room_type_id INT,
    p_check_in     DATE,
    p_check_out    DATE
)
RETURNS INT
READS SQL DATA
DETERMINISTIC
BEGIN
    DECLARE v_available_count INT DEFAULT 0;

    -- Return 0 if invalid date range
    IF p_check_in IS NULL OR p_check_out IS NULL OR p_check_out <= p_check_in THEN
        RETURN 0;
    END IF;

    SELECT COUNT(*)
    INTO v_available_count
    FROM rooms rm
    WHERE rm.room_type_id = p_room_type_id
      AND NOT EXISTS (
          SELECT 1
          FROM bookings b
          WHERE b.room_id = rm.room_id
            AND b.status != 'cancelled'
            AND b.check_in < p_check_out
            AND b.check_out > p_check_in
      );

    RETURN v_available_count;
END$$

DELIMITER ;
