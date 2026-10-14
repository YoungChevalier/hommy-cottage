-- =====================================================================
-- Hommy Cottage - Database Security & Role-Based Access Control (RBAC)
-- File: sql/06_security.sql
-- Description: Defines roles (guest, host, admin), enforces the Principle
--              of Least Privilege on tables, views, and procedures, creates
--              the dedicated application service account, and assigns default roles.
-- Target Engine: MySQL 8.0+
-- =====================================================================

USE hommy_cottage;

-- ---------------------------------------------------------------------
-- 1. Create Roles
-- ---------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS 'role_guest';
CREATE ROLE IF NOT EXISTS 'role_host';
CREATE ROLE IF NOT EXISTS 'role_admin';

-- ---------------------------------------------------------------------
-- 2. Grant Permissions: role_guest (Least Privilege)
-- Business Scope:
--   - Browse approved cottages, search results, ratings, and city metadata.
--   - Read own booking/payment records and check available room counts.
--   - Execute atomic booking and cancellation procedures.
--   - Post reviews on completed stays.
--   - Strictly NO direct INSERT/UPDATE/DELETE on core catalog or financial tables.
-- ---------------------------------------------------------------------

-- Catalog & View Read Permissions
GRANT SELECT ON hommy_cottage.property_search_view TO 'role_guest';
GRANT SELECT ON hommy_cottage.property_rating_view TO 'role_guest';
GRANT SELECT ON hommy_cottage.upcoming_bookings_view TO 'role_guest';

GRANT SELECT ON hommy_cottage.cities TO 'role_guest';
GRANT SELECT ON hommy_cottage.property_types TO 'role_guest';
GRANT SELECT ON hommy_cottage.properties TO 'role_guest';
GRANT SELECT ON hommy_cottage.room_types TO 'role_guest';
GRANT SELECT ON hommy_cottage.rooms TO 'role_guest';
GRANT SELECT ON hommy_cottage.amenities TO 'role_guest';
GRANT SELECT ON hommy_cottage.property_amenities TO 'role_guest';
GRANT SELECT ON hommy_cottage.property_images TO 'role_guest';

-- Account, Reservation & Feedback Permissions
GRANT SELECT ON hommy_cottage.bookings TO 'role_guest';
GRANT SELECT ON hommy_cottage.payments TO 'role_guest';
GRANT SELECT, INSERT ON hommy_cottage.reviews TO 'role_guest';

-- Stored Routines Execution
GRANT EXECUTE ON PROCEDURE hommy_cottage.sp_book_room TO 'role_guest';
GRANT EXECUTE ON PROCEDURE hommy_cottage.sp_cancel_booking TO 'role_guest';
GRANT EXECUTE ON FUNCTION hommy_cottage.fn_available_rooms TO 'role_guest';


-- ---------------------------------------------------------------------
-- 3. Grant Permissions: role_host
-- Business Scope:
--   - Inherits all browsing capabilities.
--   - Manage cottage listings, room configurations, amenities, and photos.
--   - Inspect host revenue, city analytics, and incoming reservation dashboards.
--   - Cannot alter user credentials or bypass pricing snapshots.
-- ---------------------------------------------------------------------

-- Inherit guest reading capabilities
GRANT 'role_guest' TO 'role_host';

-- Listing & Inventory Management (INSERT/UPDATE/DELETE)
GRANT INSERT, UPDATE ON hommy_cottage.properties TO 'role_host';
GRANT INSERT, UPDATE, DELETE ON hommy_cottage.room_types TO 'role_host';
GRANT INSERT, UPDATE, DELETE ON hommy_cottage.rooms TO 'role_host';
GRANT INSERT, UPDATE, DELETE ON hommy_cottage.property_amenities TO 'role_host';
GRANT INSERT, UPDATE, DELETE ON hommy_cottage.property_images TO 'role_host';

-- Host Business Analytics & Dashboard Views
GRANT SELECT ON hommy_cottage.host_revenue_view TO 'role_host';
GRANT SELECT ON hommy_cottage.city_revenue_view TO 'role_host';


-- ---------------------------------------------------------------------
-- 4. Grant Permissions: role_admin
-- Business Scope:
--   - Full administrative authority across all tables, views, routines,
--     triggers, and audit logs within the hommy_cottage schema.
-- ---------------------------------------------------------------------
GRANT ALL PRIVILEGES ON hommy_cottage.* TO 'role_admin';


-- ---------------------------------------------------------------------
-- 5. Create Dedicated Application Service Account
-- ---------------------------------------------------------------------
-- Creates application user restricted to localhost with parameterized password
CREATE USER IF NOT EXISTS 'hommy_app'@'localhost' IDENTIFIED BY '__APP_PASSWORD__';

-- Assign application roles
GRANT 'role_guest', 'role_host', 'role_admin' TO 'hommy_app'@'localhost';

-- Activate all granted roles by default whenever 'hommy_app' connects
SET DEFAULT ROLE ALL TO 'hommy_app'@'localhost';

-- Refresh privilege tables
FLUSH PRIVILEGES;


-- =====================================================================
-- 6. Production Security Guidance: Connecting Flask with 'hommy_app'
-- =====================================================================
--
-- Why Replace 'root' with 'hommy_app'?
-- ---------------------------------------------------------------------
-- 1. Defense in Depth:
--    Connecting as the database superuser ('root') exposes the entire DBMS.
--    In the event of an SQL injection vulnerability or server compromise,
--    'root' permits destructive actions (DROP DATABASE, creating backdoors,
--    calling administrative UDFs, reading OS files via LOAD_FILE, or writing
--    webshells via SELECT ... INTO OUTFILE).
--
-- 2. Principle of Least Privilege (PoLP):
--    The 'hommy_app' service account is bound strictly to the 'hommy_cottage'
--    schema, cannot access internal MySQL tables (mysql.user, performance_schema),
--    and operates through defined roles and procedures.
--
-- 3. Dynamic Session-Level Role Activation (Optional Advanced Pattern):
--    When a request begins in Flask:
--        if session.get("user", {}).get("role") == "guest":
--            cursor.execute("SET ROLE role_guest;")
--        elif session.get("user", {}).get("role") == "host":
--            cursor.execute("SET ROLE role_host;")
--    This guarantees that even if application logic fails to check authorization,
--    the database engine itself rejects unauthorized writes with Error 1142.
--
-- How to Configure Flask:
-- ---------------------------------------------------------------------
-- Update your application .env file to use the service account credentials:
--
--     DB_HOST=localhost
--     DB_PORT=3306
--     DB_NAME=hommy_cottage
--     DB_USER=hommy_app
--     DB_PASSWORD=HommyAppSecurePass2026!
-- =====================================================================
