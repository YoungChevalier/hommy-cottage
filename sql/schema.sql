-- =====================================================================
-- Hommy Cottage - Relational Database Schema
-- DBMS Project Specification: MySQL 8.0 strictly in 3NF / BCNF
-- =====================================================================

-- Drop existing tables in reverse dependency order to avoid foreign key errors
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS bookings;
DROP TABLE IF EXISTS cottage_images;
DROP TABLE IF EXISTS cottage_amenities;
DROP TABLE IF EXISTS amenities;
DROP TABLE IF EXISTS cottages;
DROP TABLE IF EXISTS users;

-- ---------------------------------------------------------------------
-- Table: users
-- Stores registered accounts for Guests, Cottage Hosts, and Admins.
-- Functional Dependencies: user_id -> email, password_hash, full_name, phone, role, created_at; email -> user_id (All determinants are candidate keys; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    role ENUM('guest', 'host', 'admin') NOT NULL DEFAULT 'guest',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: cottages
-- Stores cottage & homestay listings created by hosts (OYO-style self-listing).
-- Functional Dependencies: cottage_id -> host_id, title, description, property_type, address_line, city, state, pincode, max_guests, bedrooms, bathrooms, base_price_per_night, is_active, is_approved, created_at, updated_at (Determinant is PK; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE cottages (
    cottage_id INT AUTO_INCREMENT PRIMARY KEY,
    host_id INT NOT NULL,
    title VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    property_type VARCHAR(50) NOT NULL DEFAULT 'Cottage',
    address_line VARCHAR(255) NOT NULL,
    city VARCHAR(80) NOT NULL,
    state VARCHAR(80) NOT NULL,
    pincode VARCHAR(12) NOT NULL,
    max_guests INT NOT NULL DEFAULT 2,
    bedrooms INT NOT NULL DEFAULT 1,
    bathrooms INT NOT NULL DEFAULT 1,
    base_price_per_night DECIMAL(10, 2) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_approved BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_cottages_host FOREIGN KEY (host_id) 
        REFERENCES users(user_id) ON DELETE CASCADE,
    INDEX idx_cottages_city (city),
    INDEX idx_cottages_price (base_price_per_night),
    INDEX idx_cottages_guests (max_guests),
    INDEX idx_cottages_approved_active (is_approved, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: amenities
-- Master catalog of cottage features & comforts.
-- Functional Dependencies: amenity_id -> name, icon_class; name -> amenity_id, icon_class (All determinants are candidate keys; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE amenities (
    amenity_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    icon_class VARCHAR(50) NOT NULL DEFAULT 'bi bi-check-circle'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: cottage_amenities
-- Decomposed junction table for M:N relationship between cottages and amenities.
-- Functional Dependencies: (cottage_id, amenity_id) -> NULL (All attributes form composite candidate key; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE cottage_amenities (
    cottage_id INT NOT NULL,
    amenity_id INT NOT NULL,
    PRIMARY KEY (cottage_id, amenity_id),
    CONSTRAINT fk_ca_cottage FOREIGN KEY (cottage_id) 
        REFERENCES cottages(cottage_id) ON DELETE CASCADE,
    CONSTRAINT fk_ca_amenity FOREIGN KEY (amenity_id) 
        REFERENCES amenities(amenity_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: cottage_images
-- Stores image filepaths or URLs for cottages.
-- Functional Dependencies: image_id -> cottage_id, image_url, is_primary, created_at (Determinant is PK; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE cottage_images (
    image_id INT AUTO_INCREMENT PRIMARY KEY,
    cottage_id INT NOT NULL,
    image_url VARCHAR(255) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ci_cottage FOREIGN KEY (cottage_id) 
        REFERENCES cottages(cottage_id) ON DELETE CASCADE,
    INDEX idx_ci_cottage (cottage_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: bookings
-- Stores guest reservations with historical price snapshots and date intervals.
-- Functional Dependencies: booking_id -> booking_code, cottage_id, guest_id, check_in_date, check_out_date, num_guests, total_nights, price_per_night, subtotal_amount, tax_amount, total_amount, booking_status, special_requests, created_at; booking_code -> booking_id (Determinants are candidate keys; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE bookings (
    booking_id INT AUTO_INCREMENT PRIMARY KEY,
    booking_code VARCHAR(24) NOT NULL UNIQUE,
    cottage_id INT NOT NULL,
    guest_id INT NOT NULL,
    check_in_date DATE NOT NULL,
    check_out_date DATE NOT NULL,
    num_guests INT NOT NULL,
    total_nights INT NOT NULL,
    price_per_night DECIMAL(10, 2) NOT NULL,
    subtotal_amount DECIMAL(10, 2) NOT NULL,
    tax_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
    total_amount DECIMAL(10, 2) NOT NULL,
    booking_status ENUM('confirmed', 'cancelled', 'completed') NOT NULL DEFAULT 'confirmed',
    special_requests TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_bookings_cottage FOREIGN KEY (cottage_id) 
        REFERENCES cottages(cottage_id) ON DELETE RESTRICT,
    CONSTRAINT fk_bookings_guest FOREIGN KEY (guest_id) 
        REFERENCES users(user_id) ON DELETE RESTRICT,
    CONSTRAINT chk_booking_dates CHECK (check_out_date > check_in_date),
    INDEX idx_bookings_cottage_dates (cottage_id, check_in_date, check_out_date),
    INDEX idx_bookings_guest (guest_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: payments
-- Simulated payment ledger recording transaction status and payment methods.
-- Functional Dependencies: payment_id -> booking_id, transaction_ref, payment_method, amount, payment_status, paid_at; transaction_ref -> payment_id (Determinants are candidate keys; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE payments (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    booking_id INT NOT NULL,
    transaction_ref VARCHAR(50) NOT NULL UNIQUE,
    payment_method ENUM('card', 'upi', 'netbanking') NOT NULL DEFAULT 'upi',
    amount DECIMAL(10, 2) NOT NULL,
    payment_status ENUM('pending', 'completed', 'failed', 'refunded') NOT NULL DEFAULT 'completed',
    paid_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_payments_booking FOREIGN KEY (booking_id) 
        REFERENCES bookings(booking_id) ON DELETE CASCADE,
    INDEX idx_payments_booking (booking_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Table: reviews
-- Verified guest reviews and ratings (1 to 5 stars).
-- Functional Dependencies: review_id -> cottage_id, guest_id, booking_id, rating, comment, created_at; booking_id -> review_id, cottage_id, guest_id, rating, comment, created_at (Determinants are candidate keys; in BCNF)
-- ---------------------------------------------------------------------
CREATE TABLE reviews (
    review_id INT AUTO_INCREMENT PRIMARY KEY,
    cottage_id INT NOT NULL,
    guest_id INT NOT NULL,
    booking_id INT NOT NULL UNIQUE,
    rating INT NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reviews_cottage FOREIGN KEY (cottage_id) 
        REFERENCES cottages(cottage_id) ON DELETE CASCADE,
    CONSTRAINT fk_reviews_guest FOREIGN KEY (guest_id) 
        REFERENCES users(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_reviews_booking FOREIGN KEY (booking_id) 
        REFERENCES bookings(booking_id) ON DELETE CASCADE,
    CONSTRAINT chk_rating_range CHECK (rating BETWEEN 1 AND 5),
    INDEX idx_reviews_cottage (cottage_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
