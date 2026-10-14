-- =====================================================================
-- Hommy Cottage - Analytical & Operational SQL Queries (MySQL 8.0)
-- File: sql/07_queries.sql
-- Description: 15 numbered and documented queries demonstrating key relational
--              DBMS concepts on seed data: Joins, Aggregation, Subqueries,
--              NOT EXISTS, Relational Division, Window Functions, CTEs,
--              CASE Expressions, Date Arithmetic, Set Operations, Pagination,
--              and Execution Plan Inspection (EXPLAIN).
-- =====================================================================

USE hommy_cottage;


-- =====================================================================
-- Query 1: INNER JOIN
-- Question:
--   Which cottages are currently approved, and who are their hosts,
--   property types, and city locations?
-- Concept:
--   INNER JOIN across four tables (properties, users, cities, property_types)
--   returning only matching rows across all relations.
-- =====================================================================
SELECT
    p.property_id,
    p.name AS property_name,
    pt.type_name,
    c.city_name,
    c.state,
    u.name AS host_name,
    u.email AS host_email
FROM properties p
INNER JOIN users u ON p.host_id = u.user_id
INNER JOIN cities c ON p.city_id = c.city_id
INNER JOIN property_types pt ON p.type_id = pt.type_id
WHERE p.status = 'approved'
ORDER BY c.city_name ASC, p.name ASC;


-- =====================================================================
-- Query 2: LEFT JOIN & COALESCE Aggregation
-- Question:
--   What is the average rating and review count for every approved cottage,
--   including newly added cottages that have zero reviews so far?
-- Concept:
--   LEFT JOIN preserving all approved properties regardless of review existence,
--   with COALESCE() to supply a clean default 0.00 rating.
-- =====================================================================
SELECT
    p.property_id,
    p.name AS property_name,
    c.city_name,
    COUNT(r.review_id) AS total_reviews,
    COALESCE(ROUND(AVG(r.rating), 2), 0.00) AS avg_rating
FROM properties p
INNER JOIN cities c ON p.city_id = c.city_id
LEFT JOIN room_types rt ON p.property_id = rt.property_id
LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
LEFT JOIN bookings b ON rm.room_id = b.room_id
LEFT JOIN reviews r ON b.booking_id = r.booking_id
WHERE p.status = 'approved'
GROUP BY p.property_id, p.name, c.city_name
ORDER BY avg_rating DESC, total_reviews DESC;


-- =====================================================================
-- Query 3: GROUP BY + HAVING
-- Question:
--   Which hosts manage a substantial portfolio of at least 5 approved cottages,
--   and how many total physical rooms do they administer?
-- Concept:
--   GROUP BY with HAVING clause filtering aggregated groups after multi-table joins.
-- =====================================================================
SELECT
    u.user_id AS host_id,
    u.name AS host_name,
    COUNT(DISTINCT p.property_id) AS approved_properties_count,
    COUNT(DISTINCT rm.room_id) AS total_rooms_count
FROM users u
INNER JOIN properties p ON u.user_id = p.host_id
INNER JOIN room_types rt ON p.property_id = rt.property_id
INNER JOIN rooms rm ON rt.room_type_id = rm.room_type_id
WHERE p.status = 'approved'
GROUP BY u.user_id, u.name
HAVING COUNT(DISTINCT p.property_id) >= 5
ORDER BY approved_properties_count DESC, total_rooms_count DESC;


-- =====================================================================
-- Query 4: Subquery in WHERE (Scalar Subquery)
-- Question:
--   Which room types are priced strictly above the global platform average
--   nightly room rate?
-- Concept:
--   Subquery in WHERE clause evaluating a scalar aggregate against each outer row.
-- =====================================================================
SELECT
    rt.room_type_id,
    p.name AS property_name,
    c.city_name,
    rt.type_name AS room_type,
    rt.capacity,
    rt.price_per_night
FROM room_types rt
INNER JOIN properties p ON rt.property_id = p.property_id
INNER JOIN cities c ON p.city_id = c.city_id
WHERE rt.price_per_night > (
    SELECT AVG(price_per_night)
    FROM room_types
)
ORDER BY rt.price_per_night DESC;


-- =====================================================================
-- Query 5: Correlated Subquery
-- Question:
--   For each cottage, which room type represents the highest-priced
--   tier within that specific property?
-- Concept:
--   Correlated Subquery where the inner query depends on the outer row's
--   rt.property_id to dynamically evaluate the maximum price per property.
-- =====================================================================
SELECT
    p.property_id,
    p.name AS property_name,
    rt.room_type_id,
    rt.type_name AS premium_room_type,
    rt.price_per_night
FROM room_types rt
INNER JOIN properties p ON rt.property_id = p.property_id
WHERE rt.price_per_night = (
    SELECT MAX(inner_rt.price_per_night)
    FROM room_types inner_rt
    WHERE inner_rt.property_id = rt.property_id
)
ORDER BY p.property_id ASC;


-- =====================================================================
-- Query 6: NOT EXISTS (Date-Range Availability Anti-Semijoin)
-- Question:
--   Which rooms in Manali are free and unbooked for the stay window
--   from '2026-11-01' to '2026-11-05'?
-- Concept:
--   NOT EXISTS clause checking against active, overlapping bookings.
--   Enforces non-overlap condition (check_in < p_out AND check_out > p_in).
-- =====================================================================
SELECT
    rm.room_id,
    rm.room_number,
    rt.type_name AS room_type,
    rt.price_per_night,
    p.name AS property_name,
    c.city_name
FROM rooms rm
INNER JOIN room_types rt ON rm.room_type_id = rt.room_type_id
INNER JOIN properties p ON rt.property_id = p.property_id
INNER JOIN cities c ON p.city_id = c.city_id
WHERE c.city_name = 'Manali'
  AND p.status = 'approved'
  AND NOT EXISTS (
      SELECT 1
      FROM bookings b
      WHERE b.room_id = rm.room_id
        AND b.status != 'cancelled'
        AND b.check_in < '2026-11-05'
        AND b.check_out > '2026-11-01'
  )
ORDER BY p.name ASC, rm.room_number ASC;


-- =====================================================================
-- Query 7: Relational Division (IN + Exact Amenity Set Matching)
-- Question:
--   Which cottages feature ALL THREE of the following amenities:
--   'High-Speed Wi-Fi', 'Mountain View', and 'Free Private Parking'?
-- Concept:
--   Relational Division pattern implemented using WHERE a.amenity_name IN (...)
--   combined with GROUP BY and HAVING COUNT(DISTINCT) equal to target set size (3).
-- =====================================================================
SELECT
    p.property_id,
    p.name AS property_name,
    c.city_name,
    COUNT(DISTINCT pa.amenity_id) AS matched_amenities_count
FROM properties p
INNER JOIN cities c ON p.city_id = c.city_id
INNER JOIN property_amenities pa ON p.property_id = pa.property_id
INNER JOIN amenities a ON pa.amenity_id = a.amenity_id
WHERE a.amenity_name IN ('High-Speed Wi-Fi', 'Mountain View', 'Free Private Parking')
  AND p.status = 'approved'
GROUP BY p.property_id, p.name, c.city_name
HAVING COUNT(DISTINCT pa.amenity_id) = 3
ORDER BY p.name ASC;


-- =====================================================================
-- Query 8: Window Function (RANK of Properties by Revenue per City)
-- Question:
--   Within each city, how do approved cottages rank based on cumulative
--   successful booking revenue?
-- Concept:
--   Window function RANK() OVER (PARTITION BY city_id ORDER BY SUM(amount) DESC)
--   performing intra-group analytical ranking without collapsing rows.
-- =====================================================================
SELECT
    c.city_name,
    p.property_id,
    p.name AS property_name,
    COALESCE(SUM(pay.amount), 0.00) AS total_revenue,
    RANK() OVER (
        PARTITION BY c.city_id
        ORDER BY COALESCE(SUM(pay.amount), 0.00) DESC
    ) AS revenue_rank_in_city
FROM properties p
INNER JOIN cities c ON p.city_id = c.city_id
LEFT JOIN room_types rt ON p.property_id = rt.property_id
LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
LEFT JOIN bookings b ON rm.room_id = b.room_id
LEFT JOIN payments pay ON b.booking_id = pay.booking_id AND pay.status = 'success'
WHERE p.status = 'approved'
GROUP BY c.city_id, c.city_name, p.property_id, p.name
ORDER BY c.city_name ASC, revenue_rank_in_city ASC;


-- =====================================================================
-- Query 9: Common Table Expression (CTE)
-- Question:
--   Who are our repeat guests (more than 1 completed booking), what is their
--   total spend, and what is their average spend per booking?
-- Concept:
--   Common Table Expression (WITH ... AS) modularizing multi-table reservation
--   aggregates prior to secondary projection and filtering.
-- =====================================================================
WITH guest_booking_summary AS (
    SELECT
        b.guest_id,
        u.name AS guest_name,
        u.email AS guest_email,
        COUNT(b.booking_id) AS completed_bookings,
        SUM(pay.amount) AS total_spent
    FROM bookings b
    INNER JOIN users u ON b.guest_id = u.user_id
    INNER JOIN payments pay ON b.booking_id = pay.booking_id
    WHERE b.status = 'confirmed'
      AND pay.status = 'success'
      AND b.check_out <= '2026-10-14'
    GROUP BY b.guest_id, u.name, u.email
)
SELECT
    guest_id,
    guest_name,
    guest_email,
    completed_bookings,
    total_spent,
    ROUND(total_spent / completed_bookings, 2) AS avg_spend_per_booking
FROM guest_booking_summary
WHERE completed_bookings > 1
ORDER BY total_spent DESC;


-- =====================================================================
-- Query 10: Date Functions (DATEDIFF & Length of Stay)
-- Question:
--   What is the duration in nights for each reservation, and what was the
--   effective nightly rate billed after factoring simulated charges?
-- Concept:
--   Temporal computation using DATEDIFF(check_out, check_in) to derive stay
--   durations, validating historical rates against total payment amount.
-- =====================================================================
SELECT
    b.booking_id,
    u.name AS guest_name,
    p.name AS property_name,
    rm.room_number,
    b.check_in,
    b.check_out,
    DATEDIFF(b.check_out, b.check_in) AS nights_stayed,
    b.price_per_night_at_booking,
    pay.amount AS total_amount_paid,
    ROUND(pay.amount / DATEDIFF(b.check_out, b.check_in), 2) AS effective_rate_per_night
FROM bookings b
INNER JOIN users u ON b.guest_id = u.user_id
INNER JOIN rooms rm ON b.room_id = rm.room_id
INNER JOIN room_types rt ON rm.room_type_id = rt.room_type_id
INNER JOIN properties p ON rt.property_id = p.property_id
INNER JOIN payments pay ON b.booking_id = pay.booking_id
WHERE b.status = 'confirmed'
ORDER BY nights_stayed DESC, b.booking_id ASC;


-- =====================================================================
-- Query 11: CASE Conditional Logic
-- Question:
--   How do room offerings classify into budget segments and occupancy tiers
--   based on nightly price and maximum capacity?
-- Concept:
--   CASE WHEN expressions producing dynamic categorical dimensions for UI
--   tiering and analytics.
-- =====================================================================
SELECT
    rt.room_type_id,
    p.name AS property_name,
    rt.type_name,
    rt.price_per_night,
    CASE
        WHEN rt.price_per_night < 2500.00 THEN 'Budget Friendly (< 2,500)'
        WHEN rt.price_per_night BETWEEN 2500.00 AND 4500.00 THEN 'Mid-Scale Premium (2,500 - 4,500)'
        ELSE 'Luxury Elite (> 4,500)'
    END AS price_category,
    CASE
        WHEN rt.capacity = 1 THEN 'Solo Traveler (1)'
        WHEN rt.capacity = 2 THEN 'Couple (2)'
        WHEN rt.capacity BETWEEN 3 AND 4 THEN 'Family (3-4)'
        ELSE 'Group (5+)'
    END AS occupancy_tier
FROM room_types rt
INNER JOIN properties p ON rt.property_id = p.property_id
ORDER BY rt.price_per_night DESC;


-- =====================================================================
-- Query 12: UNION ALL Set Operation
-- Question:
--   Can we generate a unified financial ledger combining all successful
--   booking inflows (credits) alongside all cancellation refunds (debits)?
-- Concept:
--   UNION ALL set operation merging distinct transactional rows with uniform
--   schema projection and chronological ordering.
-- =====================================================================
SELECT
    pay.payment_id AS transaction_id,
    pay.booking_id,
    b.guest_id,
    'CREDIT (Booking Revenue)' AS ledger_type,
    pay.amount,
    pay.method,
    pay.paid_at AS transaction_timestamp
FROM payments pay
INNER JOIN bookings b ON pay.booking_id = b.booking_id
WHERE pay.status = 'success'

UNION ALL

SELECT
    pay.payment_id AS transaction_id,
    pay.booking_id,
    b.guest_id,
    'DEBIT (Cancellation Refund)' AS ledger_type,
    pay.amount,
    pay.method,
    pay.paid_at AS transaction_timestamp
FROM payments pay
INNER JOIN bookings b ON pay.booking_id = b.booking_id
WHERE pay.status = 'refunded'

ORDER BY transaction_timestamp DESC, transaction_id DESC;


-- =====================================================================
-- Query 13: Top-N with LIMIT & OFFSET (Pagination)
-- Question:
--   What are the Top 5 most reviewed and highest rated cottages on the platform,
--   and how does the UI page through the catalog?
-- Concept:
--   Top-N ranking using ORDER BY ... DESC with LIMIT count OFFSET offset
--   pattern for paginated API responses.
-- =====================================================================
SELECT
    p.property_id,
    p.name AS property_name,
    c.city_name,
    ROUND(AVG(r.rating), 2) AS avg_rating,
    COUNT(r.review_id) AS review_count
FROM properties p
INNER JOIN cities c ON p.city_id = c.city_id
INNER JOIN room_types rt ON p.property_id = rt.property_id
INNER JOIN rooms rm ON rt.room_type_id = rm.room_type_id
INNER JOIN bookings b ON rm.room_id = b.room_id
INNER JOIN reviews r ON b.booking_id = r.booking_id
WHERE p.status = 'approved'
GROUP BY p.property_id, p.name, c.city_name
HAVING COUNT(r.review_id) >= 1
ORDER BY avg_rating DESC, review_count DESC
LIMIT 5 OFFSET 0;


-- =====================================================================
-- Query 14: Multi-Condition Search (Trivago-Style Filter)
-- Question:
--   Which cottages in 'North Goa' have starting price under 4,000, accommodate
--   at least 2 guests, and maintain an average rating of 4.0 or higher?
-- Concept:
--   Complex multi-condition search query integrating joins, aggregate MIN/MAX,
--   HAVING thresholds, and composite sorting.
-- =====================================================================
SELECT
    p.property_id,
    p.name AS property_name,
    c.city_name,
    pt.type_name AS property_type,
    MIN(rt.price_per_night) AS starting_price,
    MAX(rt.capacity) AS max_capacity,
    COALESCE(ROUND(AVG(r.rating), 2), 0.00) AS avg_rating,
    COUNT(DISTINCT r.review_id) AS total_reviews
FROM properties p
INNER JOIN cities c ON p.city_id = c.city_id
INNER JOIN property_types pt ON p.type_id = pt.type_id
INNER JOIN room_types rt ON p.property_id = rt.property_id
LEFT JOIN rooms rm ON rt.room_type_id = rm.room_type_id
LEFT JOIN bookings b ON rm.room_id = b.room_id
LEFT JOIN reviews r ON b.booking_id = r.booking_id
WHERE p.status = 'approved'
  AND c.city_name = 'North Goa'
GROUP BY p.property_id, p.name, c.city_name, pt.type_name
HAVING starting_price <= 4000.00
   AND max_capacity >= 2
ORDER BY avg_rating DESC, starting_price ASC;


-- =====================================================================
-- Query 15: EXPLAIN Query Plan (Search Index Usage Analysis)
-- Question:
--   How does the MySQL execution engine execute our primary search query,
--   and how do the defined indexes optimize table lookups?
-- Concept:
--   EXPLAIN command showing access types (ref, range, eq_ref), evaluated
--   keys (idx_properties_city_status, idx_room_types_price), and estimated rows.
-- =====================================================================
EXPLAIN
SELECT
    p.property_id,
    p.name AS property_name,
    c.city_name,
    MIN(rt.price_per_night) AS min_price
FROM properties p
INNER JOIN cities c ON p.city_id = c.city_id
INNER JOIN room_types rt ON p.property_id = rt.property_id
WHERE p.status = 'approved'
  AND c.city_name = 'Indore'
  AND rt.price_per_night BETWEEN 1500.00 AND 3500.00
GROUP BY p.property_id, p.name, c.city_name;
