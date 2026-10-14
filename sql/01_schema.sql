-- =====================================================================
-- Hommy Cottage - Relational Database Schema (MySQL 8.0)
-- File: sql/01_schema.sql
-- Description: Core 3NF / BCNF normalized schema without seed data, views or triggers.
-- =====================================================================

DROP DATABASE IF EXISTS hommy_cottage;
CREATE DATABASE hommy_cottage CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hommy_cottage;

-- ---------------------------------------------------------------------
-- Table 1: users
-- Functional Dependencies:
--   user_id -> name, email, phone, password_hash, role, created_at
--   email -> user_id, name, phone, password_hash, role, created_at
-- Normal Form: BCNF (Candidate keys are user_id and email; every determinant is a superkey, eliminating partial and transitive dependencies)
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('guest', 'host', 'admin') NOT NULL DEFAULT 'guest',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 2: cities
-- Functional Dependencies:
--   city_id -> city_name, state
--   (city_name, state) -> city_id
-- Normal Form: BCNF (Candidate keys are city_id and composite (city_name, state); every determinant is a candidate key)
-- ---------------------------------------------------------------------
CREATE TABLE cities (
    city_id INT AUTO_INCREMENT PRIMARY KEY,
    city_name VARCHAR(100) NOT NULL,
    state VARCHAR(100) NOT NULL,
    CONSTRAINT uq_cities_name_state UNIQUE (city_name, state)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 3: property_types
-- Functional Dependencies:
--   type_id -> type_name
--   type_name -> type_id
-- Normal Form: BCNF (Candidate keys are type_id and type_name; every determinant is a candidate key)
-- ---------------------------------------------------------------------
CREATE TABLE property_types (
    type_id INT AUTO_INCREMENT PRIMARY KEY,
    type_name VARCHAR(50) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 4: properties
-- Functional Dependencies:
--   property_id -> host_id, type_id, city_id, name, description, address, pincode, status, created_at
-- Normal Form: BCNF (Candidate key is property_id; all non-key attributes are fully dependent only on property_id, with no transitive dependencies)
-- ---------------------------------------------------------------------
CREATE TABLE properties (
    property_id INT AUTO_INCREMENT PRIMARY KEY,
    host_id INT NOT NULL,
    type_id INT NOT NULL,
    city_id INT NOT NULL,
    name VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    address VARCHAR(255) NOT NULL,
    pincode VARCHAR(10) NOT NULL,
    status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending',
    rejection_note TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_properties_host FOREIGN KEY (host_id)
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_properties_type FOREIGN KEY (type_id)
        REFERENCES property_types(type_id) ON DELETE RESTRICT,
    CONSTRAINT fk_properties_city FOREIGN KEY (city_id)
        REFERENCES cities(city_id) ON DELETE RESTRICT,
    INDEX idx_properties_city_status (city_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 5: room_types
-- Functional Dependencies:
--   room_type_id -> property_id, type_name, capacity, price_per_night
-- Normal Form: BCNF (Candidate key is room_type_id; the determinant is a superkey and all non-key attributes depend solely upon it)
-- ---------------------------------------------------------------------
CREATE TABLE room_types (
    room_type_id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    type_name VARCHAR(100) NOT NULL,
    capacity INT NOT NULL,
    price_per_night DECIMAL(10, 2) NOT NULL,
    CONSTRAINT chk_room_type_capacity CHECK (capacity > 0),
    CONSTRAINT chk_room_type_price CHECK (price_per_night > 0),
    CONSTRAINT fk_room_types_property FOREIGN KEY (property_id)
        REFERENCES properties(property_id) ON DELETE CASCADE,
    INDEX idx_room_types_price (price_per_night)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 6: rooms
-- Functional Dependencies:
--   room_id -> room_type_id, room_number
--   (room_type_id, room_number) -> room_id
-- Normal Form: BCNF (Candidate keys are room_id and composite (room_type_id, room_number); all determinants are candidate keys)
-- ---------------------------------------------------------------------
CREATE TABLE rooms (
    room_id INT AUTO_INCREMENT PRIMARY KEY,
    room_type_id INT NOT NULL,
    room_number VARCHAR(20) NOT NULL,
    CONSTRAINT uq_rooms_type_number UNIQUE (room_type_id, room_number),
    CONSTRAINT fk_rooms_room_type FOREIGN KEY (room_type_id)
        REFERENCES room_types(room_type_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 7: amenities
-- Functional Dependencies:
--   amenity_id -> amenity_name
--   amenity_name -> amenity_id
-- Normal Form: BCNF (Candidate keys are amenity_id and amenity_name; determinants are superkeys)
-- ---------------------------------------------------------------------
CREATE TABLE amenities (
    amenity_id INT AUTO_INCREMENT PRIMARY KEY,
    amenity_name VARCHAR(100) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 8: property_amenities
-- Functional Dependencies:
--   (property_id, amenity_id) -> NULL
-- Normal Form: BCNF (Decomposed M:N junction table; all attributes are part of composite candidate key, trivially in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE property_amenities (
    property_id INT NOT NULL,
    amenity_id INT NOT NULL,
    PRIMARY KEY (property_id, amenity_id),
    CONSTRAINT fk_pa_property FOREIGN KEY (property_id)
        REFERENCES properties(property_id) ON DELETE CASCADE,
    CONSTRAINT fk_pa_amenity FOREIGN KEY (amenity_id)
        REFERENCES amenities(amenity_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 9: property_images
-- Functional Dependencies:
--   image_id -> property_id, image_url, is_primary
-- Normal Form: BCNF (Candidate key is image_id; determinant is a superkey)
-- ---------------------------------------------------------------------
CREATE TABLE property_images (
    image_id INT AUTO_INCREMENT PRIMARY KEY,
    property_id INT NOT NULL,
    image_url VARCHAR(255) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_pi_property FOREIGN KEY (property_id)
        REFERENCES properties(property_id) ON DELETE CASCADE,
    INDEX idx_pi_property (property_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 10: bookings
-- Functional Dependencies:
--   booking_id -> guest_id, room_id, check_in, check_out, guests, price_per_night_at_booking, status
-- Normal Form: BCNF (Candidate key is booking_id; the only determinant is a superkey, preserving historical pricing integrity)
-- ---------------------------------------------------------------------
CREATE TABLE bookings (
    booking_id INT AUTO_INCREMENT PRIMARY KEY,
    guest_id INT NOT NULL,
    room_id INT NOT NULL,
    check_in DATE NOT NULL,
    check_out DATE NOT NULL,
    guests INT NOT NULL DEFAULT 1,
    price_per_night_at_booking DECIMAL(10, 2) NOT NULL,
    status ENUM('confirmed', 'cancelled') NOT NULL DEFAULT 'confirmed',
    CONSTRAINT chk_booking_dates CHECK (check_out > check_in),
    CONSTRAINT chk_booking_guests CHECK (guests > 0),
    CONSTRAINT chk_booking_price CHECK (price_per_night_at_booking > 0),
    CONSTRAINT fk_bookings_guest FOREIGN KEY (guest_id)
        REFERENCES users(user_id) ON DELETE RESTRICT,
    CONSTRAINT fk_bookings_room FOREIGN KEY (room_id)
        REFERENCES rooms(room_id) ON DELETE RESTRICT,
    INDEX idx_bookings_room_dates (room_id, check_in, check_out),
    INDEX idx_bookings_guest (guest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 11: payments
-- Functional Dependencies:
--   payment_id -> booking_id, amount, method, status, paid_at
--   booking_id -> payment_id, amount, method, status, paid_at
-- Normal Form: BCNF (Candidate keys are payment_id and booking_id due to UNIQUE constraint; all determinants are candidate keys)
-- ---------------------------------------------------------------------
CREATE TABLE payments (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL UNIQUE,
    amount DECIMAL(10, 2) NOT NULL,
    method ENUM('upi', 'card', 'netbanking', 'cash') NOT NULL DEFAULT 'upi',
    status ENUM('success', 'failed', 'refunded') NOT NULL DEFAULT 'success',
    paid_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_payment_amount CHECK (amount > 0),
    CONSTRAINT fk_payments_booking FOREIGN KEY (booking_id)
        REFERENCES bookings(booking_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table 12: reviews
-- Functional Dependencies:
--   review_id -> booking_id, rating, comment, created_at
--   booking_id -> review_id, rating, comment, created_at
-- Normal Form: BCNF (Candidate keys are review_id and booking_id due to UNIQUE constraint ensuring 1 review per booking; determinants are candidate keys)
-- ---------------------------------------------------------------------
CREATE TABLE reviews (
    review_id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL UNIQUE,
    rating INT NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_review_rating CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT fk_reviews_booking FOREIGN KEY (booking_id)
        REFERENCES bookings(booking_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
