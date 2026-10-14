-- =====================================================================
-- Hommy Cottage - Analytical & Operational Views (MySQL 8.0)
-- File: sql/03_views.sql
-- Description: Modular views using CREATE OR REPLACE VIEW with zero duplicated logic.
-- =====================================================================

USE hommy_cottage;

-- ---------------------------------------------------------------------
-- 1. View: property_rating_view
-- Purpose: Aggregates the average star rating and verified review count
--          for each property across all its rooms and confirmed bookings.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW property_rating_view AS
SELECT 
    p.property_id,
    COALESCE(ROUND(AVG(rev.rating), 2), 0.00) AS avg_rating,
    COUNT(rev.review_id) AS review_count
FROM properties p
LEFT JOIN room_types rt ON p.property_id = rt.property_id
LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
LEFT JOIN bookings b ON rm.room_id = b.room_id
LEFT JOIN reviews rev ON b.booking_id = rev.booking_id
GROUP BY p.property_id;

-- ---------------------------------------------------------------------
-- 2. View: property_search_view
-- Purpose: Powers Trivago-style search and filter queries for approved
--          properties. Reuses property_rating_view to display pre-computed
--          ratings without duplicating aggregation logic, and computes
--          starting price from the lowest room_type rate.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW property_search_view AS
SELECT 
    p.property_id,
    p.host_id,
    p.name AS property_name,
    p.description,
    p.address,
    p.pincode,
    c.city_id,
    c.city_name,
    c.state,
    pt.type_id,
    pt.type_name,
    MIN(rt.price_per_night) AS starting_price,
    prv.avg_rating,
    prv.review_count,
    COALESCE(pi.image_url, '/static/img/sample/default.jpg') AS primary_image
FROM properties p
JOIN cities c ON p.city_id = c.city_id
JOIN property_types pt ON p.type_id = pt.type_id
JOIN room_types rt ON p.property_id = rt.property_id
JOIN property_rating_view prv ON p.property_id = prv.property_id
LEFT JOIN property_images pi ON p.property_id = pi.property_id AND pi.is_primary = TRUE
WHERE p.status = 'approved'
GROUP BY 
    p.property_id, 
    p.host_id,
    p.name,
    p.description,
    p.address,
    p.pincode,
    c.city_id, 
    c.city_name,
    c.state,
    pt.type_id, 
    pt.type_name,
    prv.avg_rating, 
    prv.review_count, 
    pi.image_url;

-- ---------------------------------------------------------------------
-- 3. View: host_revenue_view
-- Purpose: Provides host financial analytics, calculating total bookings
--          and gross earnings strictly from successful payment transactions.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW host_revenue_view AS
SELECT 
    u.user_id AS host_id,
    u.name AS host_name,
    COUNT(DISTINCT CASE WHEN pay.status = 'success' THEN b.booking_id END) AS total_bookings,
    COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) AS total_revenue
FROM users u
JOIN properties p ON u.user_id = p.host_id
LEFT JOIN room_types rt ON p.property_id = rt.property_id
LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
LEFT JOIN bookings b ON rm.room_id = b.room_id
LEFT JOIN payments pay ON b.booking_id = pay.booking_id
WHERE u.role = 'host'
GROUP BY u.user_id, u.name;

-- ---------------------------------------------------------------------
-- 4. View: city_revenue_view
-- Purpose: Offers regional marketplace insights per destination city,
--          tabulating total successful bookings and gross revenue.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW city_revenue_view AS
SELECT 
    c.city_id,
    c.city_name,
    COUNT(DISTINCT CASE WHEN pay.status = 'success' THEN b.booking_id END) AS bookings,
    COALESCE(SUM(CASE WHEN pay.status = 'success' THEN pay.amount ELSE 0.00 END), 0.00) AS revenue
FROM cities c
LEFT JOIN properties p ON c.city_id = p.city_id
LEFT JOIN room_types rt ON p.property_id = rt.property_id
LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
LEFT JOIN bookings b ON rm.room_id = b.room_id
LEFT JOIN payments pay ON b.booking_id = pay.booking_id
GROUP BY c.city_id, c.city_name;

-- ---------------------------------------------------------------------
-- 5. View: upcoming_bookings_view
-- Purpose: Powers host dashboards by listing active and future reservations
--          (check_in >= CURRENT_DATE and status = 'confirmed'), detailing
--          guest identity, cottage name, room number, dates, and total amount.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW upcoming_bookings_view AS
SELECT 
    b.booking_id,
    p.host_id,
    u_guest.name AS guest_name,
    u_guest.phone AS guest_phone,
    p.property_id,
    p.name AS property_name,
    rm.room_number,
    rt.type_name AS room_type,
    b.check_in,
    b.check_out,
    b.guests,
    b.status AS booking_status,
    COALESCE(pay.amount, b.price_per_night_at_booking * DATEDIFF(b.check_out, b.check_in)) AS amount,
    pay.status AS payment_status
FROM bookings b
JOIN users u_guest ON b.guest_id = u_guest.user_id
JOIN rooms rm ON b.room_id = rm.room_id
JOIN room_types rt ON rm.room_type_id = rt.room_type_id
JOIN properties p ON rt.property_id = p.property_id
LEFT JOIN payments pay ON b.booking_id = pay.booking_id
WHERE b.check_in >= CURRENT_DATE AND b.status = 'confirmed';
