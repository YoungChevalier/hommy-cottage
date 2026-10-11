-- =====================================================================
--  HOTEL MANAGEMENT SYSTEM  |  schema.sql  |  MySQL 8.0+  |  BCNF
--  Run order: this file first, then seed.sql.
--  In MySQL Workbench: File > Open SQL Script > run all (lightning icon).
-- =====================================================================

-- Uncomment the next line only if you want to wipe and rebuild everything.
-- DROP DATABASE IF EXISTS hotel_db;

CREATE DATABASE IF NOT EXISTS hotel_db
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hotel_db;

-- =====================================================================
--  1. TABLES  (every table: each determinant is a candidate key => BCNF)
-- =====================================================================

-- ---------- Departments and employees ----------
CREATE TABLE department (
  dept_id     INT AUTO_INCREMENT PRIMARY KEY,
  dept_name   VARCHAR(50) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE employee (
  emp_id      INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(80)  NOT NULL,
  phone       VARCHAR(15)  NOT NULL UNIQUE,
  role        VARCHAR(40)  NOT NULL,
  salary      DECIMAL(10,2) NOT NULL CHECK (salary > 0),
  dept_id     INT NOT NULL,
  hire_date   DATE NOT NULL,
  CONSTRAINT fk_emp_dept FOREIGN KEY (dept_id)
    REFERENCES department(dept_id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------- Guests ----------
CREATE TABLE guest (
  guest_id        INT AUTO_INCREMENT PRIMARY KEY,
  name            VARCHAR(80)  NOT NULL,
  phone           VARCHAR(15)  NOT NULL UNIQUE,
  email           VARCHAR(100) UNIQUE,
  id_proof_type   VARCHAR(30),
  id_proof_no     VARCHAR(40),
  UNIQUE KEY uq_guest_proof (id_proof_type, id_proof_no)
) ENGINE=InnoDB;

-- ---------- Login accounts (Admin / Receptionist / Guest portal) ----------
CREATE TABLE app_user (
  user_id        INT AUTO_INCREMENT PRIMARY KEY,
  username       VARCHAR(40)  NOT NULL UNIQUE,
  password_hash  VARCHAR(255) NOT NULL,           -- store a hash, never plain text
  role           ENUM('Admin','Receptionist','Guest') NOT NULL,
  guest_id       INT NULL UNIQUE,                  -- set for Guest accounts
  emp_id         INT NULL UNIQUE,                  -- set for staff accounts
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_user_guest FOREIGN KEY (guest_id)
    REFERENCES guest(guest_id) ON DELETE CASCADE,
  CONSTRAINT fk_user_emp FOREIGN KEY (emp_id)
    REFERENCES employee(emp_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------- Rooms ----------
CREATE TABLE room_type (
  type_id      INT AUTO_INCREMENT PRIMARY KEY,
  type_name    VARCHAR(40) NOT NULL UNIQUE,
  base_price   DECIMAL(10,2) NOT NULL CHECK (base_price > 0),
  capacity     TINYINT NOT NULL CHECK (capacity > 0),
  description  VARCHAR(255)
) ENGINE=InnoDB;

CREATE TABLE room (
  room_no   INT PRIMARY KEY,
  type_id   INT NOT NULL,
  floor     TINYINT NOT NULL,
  status    ENUM('Available','Occupied','Cleaning','Maintenance')
            NOT NULL DEFAULT 'Available',
  CONSTRAINT fk_room_type FOREIGN KEY (type_id)
    REFERENCES room_type(type_id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------- Dynamic pricing and coupons ----------
CREATE TABLE season_rate (
  season_id    INT AUTO_INCREMENT PRIMARY KEY,
  season_name  VARCHAR(40) NOT NULL UNIQUE,
  start_date   DATE NOT NULL,
  end_date     DATE NOT NULL,
  multiplier   DECIMAL(4,2) NOT NULL CHECK (multiplier > 0),   -- 1.25 = +25%
  CHECK (end_date >= start_date)
) ENGINE=InnoDB;

CREATE TABLE coupon (
  coupon_id         INT AUTO_INCREMENT PRIMARY KEY,
  code              VARCHAR(20) NOT NULL UNIQUE,
  discount_percent  DECIMAL(5,2) NOT NULL CHECK (discount_percent > 0 AND discount_percent <= 100),
  valid_from        DATE NOT NULL,
  valid_to          DATE NOT NULL,
  active            TINYINT(1) NOT NULL DEFAULT 1,
  CHECK (valid_to >= valid_from)
) ENGINE=InnoDB;

-- ---------- Reservations ----------
CREATE TABLE reservation (
  reservation_id  INT AUTO_INCREMENT PRIMARY KEY,
  guest_id        INT NOT NULL,
  check_in        DATE NOT NULL,
  check_out       DATE NOT NULL,
  status          ENUM('Booked','Checked-in','Checked-out','Cancelled')
                  NOT NULL DEFAULT 'Booked',
  coupon_id       INT NULL,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CHECK (check_out > check_in),
  CONSTRAINT fk_res_guest FOREIGN KEY (guest_id)
    REFERENCES guest(guest_id) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT fk_res_coupon FOREIGN KEY (coupon_id)
    REFERENCES coupon(coupon_id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- A reservation can hold several rooms. rate_charged is a price snapshot
-- (nightly rate at booking time), so later price changes do not alter old bills.
CREATE TABLE reservation_room (
  reservation_id  INT NOT NULL,
  room_no         INT NOT NULL,
  rate_charged    DECIMAL(10,2) NOT NULL CHECK (rate_charged > 0),
  PRIMARY KEY (reservation_id, room_no),
  CONSTRAINT fk_rr_res FOREIGN KEY (reservation_id)
    REFERENCES reservation(reservation_id) ON DELETE CASCADE,
  CONSTRAINT fk_rr_room FOREIGN KEY (room_no)
    REFERENCES room(room_no) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

-- ---------- Services ----------
CREATE TABLE service (
  service_id    INT AUTO_INCREMENT PRIMARY KEY,
  service_name  VARCHAR(60) NOT NULL UNIQUE,
  price         DECIMAL(10,2) NOT NULL CHECK (price >= 0)
) ENGINE=InnoDB;

CREATE TABLE service_usage (
  usage_id        INT AUTO_INCREMENT PRIMARY KEY,
  reservation_id  INT NOT NULL,
  service_id      INT NOT NULL,
  quantity        INT NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_price      DECIMAL(10,2) NOT NULL CHECK (unit_price >= 0),  -- price snapshot
  used_on         DATE NOT NULL,
  CONSTRAINT fk_su_res FOREIGN KEY (reservation_id)
    REFERENCES reservation(reservation_id) ON DELETE CASCADE,
  CONSTRAINT fk_su_service FOREIGN KEY (service_id)
    REFERENCES service(service_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ---------- Payments ----------
CREATE TABLE payment (
  payment_id      INT AUTO_INCREMENT PRIMARY KEY,
  reservation_id  INT NOT NULL,
  amount          DECIMAL(10,2) NOT NULL CHECK (amount > 0),
  method          ENUM('Cash','Card','UPI','NetBanking') NOT NULL,
  paid_on         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_pay_res FOREIGN KEY (reservation_id)
    REFERENCES reservation(reservation_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ---------- Reviews (one per stay) ----------
CREATE TABLE review (
  review_id       INT AUTO_INCREMENT PRIMARY KEY,
  reservation_id  INT NOT NULL UNIQUE,
  rating          TINYINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment         VARCHAR(500),
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_rev_res FOREIGN KEY (reservation_id)
    REFERENCES reservation(reservation_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------- Housekeeping board ----------
CREATE TABLE housekeeping_task (
  task_id       INT AUTO_INCREMENT PRIMARY KEY,
  room_no       INT NOT NULL,
  assigned_to   INT NULL,
  status        ENUM('Dirty','Cleaning','Ready') NOT NULL DEFAULT 'Dirty',
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at  DATETIME NULL,
  CONSTRAINT fk_hk_room FOREIGN KEY (room_no)
    REFERENCES room(room_no) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_hk_emp FOREIGN KEY (assigned_to)
    REFERENCES employee(emp_id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------- Audit log (feeds the "Activity feed" page) ----------
CREATE TABLE audit_log (
  log_id      INT AUTO_INCREMENT PRIMARY KEY,
  table_name  VARCHAR(40) NOT NULL,
  record_id   INT NOT NULL,
  action      VARCHAR(20) NOT NULL,
  old_value   VARCHAR(255),
  new_value   VARCHAR(255),
  changed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =====================================================================
--  2. INDEXES
-- =====================================================================
CREATE INDEX idx_res_dates    ON reservation (check_in, check_out);
CREATE INDEX idx_res_status   ON reservation (status);
CREATE INDEX idx_room_status  ON room (status);
CREATE INDEX idx_guest_name   ON guest (name);
CREATE INDEX idx_pay_paid_on  ON payment (paid_on);
CREATE INDEX idx_audit_time   ON audit_log (changed_at);

-- =====================================================================
--  3. VIEWS
-- =====================================================================
CREATE VIEW available_rooms AS
SELECT ro.room_no, ro.floor, rt.type_name, rt.base_price, rt.capacity
FROM room ro
JOIN room_type rt ON rt.type_id = ro.type_id
WHERE ro.status = 'Available';

CREATE VIEW current_guests AS
SELECT r.reservation_id, g.guest_id, g.name AS guest_name, g.phone,
       rr.room_no, r.check_in, r.check_out
FROM reservation r
JOIN guest g             ON g.guest_id = r.guest_id
JOIN reservation_room rr ON rr.reservation_id = r.reservation_id
WHERE r.status = 'Checked-in';

CREATE VIEW todays_arrivals AS
SELECT r.reservation_id, g.name AS guest_name, g.phone, r.check_in, r.check_out
FROM reservation r
JOIN guest g ON g.guest_id = r.guest_id
WHERE r.check_in = CURDATE() AND r.status = 'Booked';

CREATE VIEW todays_departures AS
SELECT r.reservation_id, g.name AS guest_name, g.phone, r.check_in, r.check_out
FROM reservation r
JOIN guest g ON g.guest_id = r.guest_id
WHERE r.check_out = CURDATE() AND r.status = 'Checked-in';

CREATE VIEW monthly_revenue AS
SELECT DATE_FORMAT(paid_on, '%Y-%m') AS month,
       SUM(amount)                   AS total_revenue,
       COUNT(*)                      AS payments_count
FROM payment
GROUP BY DATE_FORMAT(paid_on, '%Y-%m');

-- Window function: rank room types by the room revenue they earned
CREATE VIEW revenue_by_room_type AS
SELECT rt.type_name,
       SUM(rr.rate_charged * DATEDIFF(r.check_out, r.check_in)) AS room_revenue,
       RANK() OVER (ORDER BY SUM(rr.rate_charged * DATEDIFF(r.check_out, r.check_in)) DESC)
         AS revenue_rank
FROM reservation_room rr
JOIN reservation r ON r.reservation_id = rr.reservation_id
JOIN room ro       ON ro.room_no = rr.room_no
JOIN room_type rt  ON rt.type_id = ro.type_id
WHERE r.status <> 'Cancelled'
GROUP BY rt.type_id, rt.type_name;

CREATE VIEW room_type_ratings AS
SELECT rt.type_name,
       ROUND(AVG(rv.rating), 2) AS avg_rating,
       COUNT(rv.review_id)      AS review_count
FROM review rv
JOIN reservation_room rr ON rr.reservation_id = rv.reservation_id
JOIN room ro             ON ro.room_no = rr.room_no
JOIN room_type rt        ON rt.type_id = ro.type_id
GROUP BY rt.type_id, rt.type_name;

CREATE VIEW occupancy_summary AS
SELECT COUNT(*)                                            AS total_rooms,
       SUM(status = 'Occupied')                            AS occupied_rooms,
       ROUND(100 * SUM(status = 'Occupied') / COUNT(*), 1) AS occupancy_percent
FROM room;

-- =====================================================================
--  4. FUNCTIONS (billing helpers)
-- =====================================================================
DELIMITER $$

CREATE FUNCTION fn_reservation_total(p_res INT)
RETURNS DECIMAL(12,2)
READS SQL DATA
BEGIN
  DECLARE v_nights INT;
  DECLARE v_room   DECIMAL(12,2);
  DECLARE v_serv   DECIMAL(12,2);
  DECLARE v_disc   DECIMAL(5,2) DEFAULT 0;

  SELECT DATEDIFF(check_out, check_in) INTO v_nights
  FROM reservation WHERE reservation_id = p_res;

  SELECT COALESCE(SUM(rate_charged), 0) * v_nights INTO v_room
  FROM reservation_room WHERE reservation_id = p_res;

  SELECT COALESCE(SUM(quantity * unit_price), 0) INTO v_serv
  FROM service_usage WHERE reservation_id = p_res;

  SELECT COALESCE(c.discount_percent, 0) INTO v_disc
  FROM reservation r
  LEFT JOIN coupon c ON c.coupon_id = r.coupon_id
  WHERE r.reservation_id = p_res;

  -- Coupon discount applies to room charges only
  RETURN ROUND(v_room * (1 - v_disc / 100) + v_serv, 2);
END$$

CREATE FUNCTION fn_amount_paid(p_res INT)
RETURNS DECIMAL(12,2)
READS SQL DATA
BEGIN
  DECLARE v_paid DECIMAL(12,2);
  SELECT COALESCE(SUM(amount), 0) INTO v_paid
  FROM payment WHERE reservation_id = p_res;
  RETURN v_paid;
END$$

-- =====================================================================
--  5. STORED PROCEDURES
-- =====================================================================

-- Book a room: overlap check + price snapshot with seasonal multiplier.
-- Everything runs in one transaction, so a failure leaves no partial data.
CREATE PROCEDURE book_room(
  IN p_guest INT, IN p_room INT, IN p_in DATE, IN p_out DATE)
BEGIN
  DECLARE v_conflicts INT DEFAULT 0;
  DECLARE v_status    VARCHAR(20);
  DECLARE v_base      DECIMAL(10,2);
  DECLARE v_mult      DECIMAL(4,2) DEFAULT 1;
  DECLARE v_id        INT;

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  IF p_out <= p_in THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Check-out must be after check-in';
  END IF;

  START TRANSACTION;

  SELECT ro.status, rt.base_price INTO v_status, v_base
  FROM room ro JOIN room_type rt ON rt.type_id = ro.type_id
  WHERE ro.room_no = p_room
  FOR UPDATE;

  IF v_base IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room does not exist';
  END IF;
  IF v_status = 'Maintenance' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room is under maintenance';
  END IF;

  -- Double-booking rule: new_in < existing_out AND new_out > existing_in
  SELECT COUNT(*) INTO v_conflicts
  FROM reservation_room rr
  JOIN reservation r ON r.reservation_id = rr.reservation_id
  WHERE rr.room_no = p_room
    AND r.status IN ('Booked','Checked-in')
    AND p_in < r.check_out
    AND p_out > r.check_in;

  IF v_conflicts > 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Room already booked for these dates';
  END IF;

  SELECT COALESCE(MAX(multiplier), 1) INTO v_mult
  FROM season_rate
  WHERE p_in BETWEEN start_date AND end_date;

  INSERT INTO reservation (guest_id, check_in, check_out)
  VALUES (p_guest, p_in, p_out);
  SET v_id = LAST_INSERT_ID();

  INSERT INTO reservation_room (reservation_id, room_no, rate_charged)
  VALUES (v_id, p_room, ROUND(v_base * v_mult, 2));

  COMMIT;
END$$

-- Attach a valid coupon to a reservation
CREATE PROCEDURE apply_coupon(IN p_res INT, IN p_code VARCHAR(20))
BEGIN
  DECLARE v_cid INT DEFAULT NULL;

  SELECT coupon_id INTO v_cid
  FROM coupon
  WHERE code = p_code AND active = 1
    AND CURDATE() BETWEEN valid_from AND valid_to;

  IF v_cid IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid or expired coupon';
  END IF;

  UPDATE reservation SET coupon_id = v_cid WHERE reservation_id = p_res;
END$$

-- Record a payment inside a transaction; refuses to overpay
CREATE PROCEDURE record_payment(
  IN p_res INT, IN p_amount DECIMAL(10,2), IN p_method VARCHAR(20))
BEGIN
  DECLARE v_balance DECIMAL(12,2);

  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;
  SET v_balance = fn_reservation_total(p_res) - fn_amount_paid(p_res);

  IF p_amount > v_balance THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Payment exceeds the balance due';
  END IF;

  INSERT INTO payment (reservation_id, amount, method)
  VALUES (p_res, p_amount, p_method);
  COMMIT;
END$$

-- Bill = room charges + services - coupon discount - payments.
-- Returns two result sets: (1) summary, (2) itemized lines.
CREATE PROCEDURE generate_bill(IN p_res INT)
BEGIN
  SELECT r.reservation_id,
         g.name                                   AS guest_name,
         r.check_in, r.check_out,
         DATEDIFF(r.check_out, r.check_in)        AS nights,
         fn_reservation_total(r.reservation_id)   AS total_payable,
         fn_amount_paid(r.reservation_id)         AS amount_paid,
         fn_reservation_total(r.reservation_id)
           - fn_amount_paid(r.reservation_id)     AS balance_due
  FROM reservation r
  JOIN guest g ON g.guest_id = r.guest_id
  WHERE r.reservation_id = p_res;

  SELECT CONCAT('Room ', rr.room_no)              AS item,
         DATEDIFF(r.check_out, r.check_in)        AS quantity,
         rr.rate_charged                          AS unit_price,
         DATEDIFF(r.check_out, r.check_in) * rr.rate_charged AS amount
  FROM reservation_room rr
  JOIN reservation r ON r.reservation_id = rr.reservation_id
  WHERE rr.reservation_id = p_res
  UNION ALL
  SELECT s.service_name, su.quantity, su.unit_price, su.quantity * su.unit_price
  FROM service_usage su
  JOIN service s ON s.service_id = su.service_id
  WHERE su.reservation_id = p_res;
END$$

-- Rooms free for a date range (used by the booking wizard)
CREATE PROCEDURE find_available_rooms(IN p_in DATE, IN p_out DATE)
BEGIN
  SELECT ro.room_no, ro.floor, rt.type_name, rt.base_price, rt.capacity
  FROM room ro
  JOIN room_type rt ON rt.type_id = ro.type_id
  WHERE ro.status <> 'Maintenance'
    AND ro.room_no NOT IN (
      SELECT rr.room_no
      FROM reservation_room rr
      JOIN reservation r ON r.reservation_id = rr.reservation_id
      WHERE r.status IN ('Booked','Checked-in')
        AND p_in < r.check_out
        AND p_out > r.check_in)
  ORDER BY ro.room_no;
END$$

-- =====================================================================
--  6. TRIGGERS
-- =====================================================================

-- Block illegal status changes (e.g. reviving a cancelled booking)
CREATE TRIGGER trg_res_before_update
BEFORE UPDATE ON reservation
FOR EACH ROW
BEGIN
  IF OLD.status IN ('Checked-out','Cancelled') AND NEW.status <> OLD.status THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'A closed reservation cannot change status';
  END IF;
END$$

-- Keep room status in sync, create housekeeping work, write the audit trail
CREATE TRIGGER trg_res_after_update
AFTER UPDATE ON reservation
FOR EACH ROW
BEGIN
  IF NEW.status = 'Checked-in' AND OLD.status <> 'Checked-in' THEN
    UPDATE room SET status = 'Occupied'
    WHERE room_no IN (SELECT room_no FROM reservation_room
                      WHERE reservation_id = NEW.reservation_id);

  ELSEIF NEW.status = 'Checked-out' AND OLD.status <> 'Checked-out' THEN
    UPDATE room SET status = 'Cleaning'
    WHERE room_no IN (SELECT room_no FROM reservation_room
                      WHERE reservation_id = NEW.reservation_id);

    INSERT INTO housekeeping_task (room_no)
    SELECT room_no FROM reservation_room
    WHERE reservation_id = NEW.reservation_id;
  END IF;

  IF NEW.status <> OLD.status THEN
    INSERT INTO audit_log (table_name, record_id, action, old_value, new_value)
    VALUES ('reservation', NEW.reservation_id, 'STATUS_CHANGE', OLD.status, NEW.status);
  END IF;
END$$

CREATE TRIGGER trg_res_after_insert
AFTER INSERT ON reservation
FOR EACH ROW
BEGIN
  INSERT INTO audit_log (table_name, record_id, action, new_value)
  VALUES ('reservation', NEW.reservation_id, 'CREATED',
          CONCAT('guest ', NEW.guest_id, ', ', NEW.check_in, ' to ', NEW.check_out));
END$$

-- When housekeeping marks a room Ready, the room becomes Available again
CREATE TRIGGER trg_hk_after_update
AFTER UPDATE ON housekeeping_task
FOR EACH ROW
BEGIN
  IF NEW.status = 'Ready' AND OLD.status <> 'Ready' THEN
    UPDATE room SET status = 'Available' WHERE room_no = NEW.room_no;
  END IF;
END$$

CREATE TRIGGER trg_hk_before_update
BEFORE UPDATE ON housekeeping_task
FOR EACH ROW
BEGIN
  IF NEW.status = 'Ready' AND OLD.status <> 'Ready' THEN
    SET NEW.completed_at = NOW();
  END IF;
END$$

CREATE TRIGGER trg_payment_after_insert
AFTER INSERT ON payment
FOR EACH ROW
BEGIN
  INSERT INTO audit_log (table_name, record_id, action, new_value)
  VALUES ('payment', NEW.payment_id, 'PAYMENT',
          CONCAT(NEW.amount, ' via ', NEW.method, ' for reservation ', NEW.reservation_id));
END$$

-- Friendly error before the foreign key would block the delete
CREATE TRIGGER trg_guest_before_delete
BEFORE DELETE ON guest
FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM reservation
             WHERE guest_id = OLD.guest_id
               AND status IN ('Booked','Checked-in')) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Guest has active reservations and cannot be deleted';
  END IF;
END$$

DELIMITER ;

-- =====================================================================
--  End of schema.sql
-- =====================================================================
