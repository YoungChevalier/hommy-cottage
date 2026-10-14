-- =====================================================================
-- Hommy Cottage - Sample Seed Data
-- Provides realistic seed data for DBMS viva & demonstration:
-- 1 Admin, 3 Hosts, 3 Guests, 8 Cottages, 12 Amenities, Bookings & Reviews
-- =====================================================================

-- ---------------------------------------------------------------------
-- Users (Pass: Admin@123, Host@123, Guest@123)
-- ---------------------------------------------------------------------
INSERT INTO users (user_id, email, password_hash, full_name, phone, role) VALUES
(1, 'admin@hommycottage.com', 'scrypt:32768:8:1$LKw5Ka2BsT1hmtJy$960c4807acabab08ef6fd43ea981ee54fde4f6ace56cd7ad2a613b37d261a4da8e5fbe4332919b67de131ba10997a08bc3aaf1b86dab3bdc96aa83ed35cd2994', 'System Administrator', '+91 9876543210', 'admin'),
(2, 'rahul.host@example.com', 'scrypt:32768:8:1$uKmHHBVnjdbJvo8n$f28e09aadfcd272b02d351ef53c3482c58e0a07680b022a4c9737b152b1c691d82155a7a4cd2b84ad4fb21aa8fdebfe6e550c7368c019b403188fe4791cff215', 'Rahul Sharma', '+91 9811122233', 'host'),
(3, 'priya.host@example.com', 'scrypt:32768:8:1$uKmHHBVnjdbJvo8n$f28e09aadfcd272b02d351ef53c3482c58e0a07680b022a4c9737b152b1c691d82155a7a4cd2b84ad4fb21aa8fdebfe6e550c7368c019b403188fe4791cff215', 'Priya Nair', '+91 9822233344', 'host'),
(4, 'vikram.host@example.com', 'scrypt:32768:8:1$uKmHHBVnjdbJvo8n$f28e09aadfcd272b02d351ef53c3482c58e0a07680b022a4c9737b152b1c691d82155a7a4cd2b84ad4fb21aa8fdebfe6e550c7368c019b403188fe4791cff215', 'Vikram Mehra', '+91 9833344455', 'host'),
(5, 'aarav.guest@example.com', 'scrypt:32768:8:1$Yu1rogJCwjzxwLGu$2c16f8bcf74d56edd88664f6aecc76336bdcf0c494be46cb6fe7ae955c558dc44a4d06d9cc8f2e89360e299aa0321f5ce9df3dc443b9c0b1251b6d274234c901', 'Aarav Patel', '+91 9844455566', 'guest'),
(6, 'sneha.guest@example.com', 'scrypt:32768:8:1$Yu1rogJCwjzxwLGu$2c16f8bcf74d56edd88664f6aecc76336bdcf0c494be46cb6fe7ae955c558dc44a4d06d9cc8f2e89360e299aa0321f5ce9df3dc443b9c0b1251b6d274234c901', 'Sneha Rao', '+91 9855566677', 'guest'),
(7, 'rohan.guest@example.com', 'scrypt:32768:8:1$Yu1rogJCwjzxwLGu$2c16f8bcf74d56edd88664f6aecc76336bdcf0c494be46cb6fe7ae955c558dc44a4d06d9cc8f2e89360e299aa0321f5ce9df3dc443b9c0b1251b6d274234c901', 'Rohan Verma', '+91 9866677788', 'guest');

-- ---------------------------------------------------------------------
-- Amenities Master Catalog
-- ---------------------------------------------------------------------
INSERT INTO amenities (amenity_id, name, icon_class) VALUES
(1, 'High-Speed Wi-Fi', 'bi bi-wifi'),
(2, 'Mountain View', 'bi bi-image-alt'),
(3, 'Cozy Fireplace', 'bi bi-fire'),
(4, 'Private Bonfire Pit', 'bi bi-brightness-high'),
(5, 'Equipped Kitchenette', 'bi bi-cup-hot'),
(6, '24/7 Hot Water Geyser', 'bi bi-droplet-fill'),
(7, 'Free Private Parking', 'bi bi-p-circle'),
(8, 'Swimming Pool', 'bi bi-water'),
(9, 'Pet Friendly', 'bi bi-heart-fill'),
(10, 'Complimentary Breakfast', 'bi bi-egg-fried'),
(11, 'Air Conditioning / Heater', 'bi bi-snow'),
(12, 'Power Backup / Inverter', 'bi bi-lightning-charge');

-- ---------------------------------------------------------------------
-- Cottages (OYO-style self-listing properties)
-- ---------------------------------------------------------------------
INSERT INTO cottages (cottage_id, host_id, title, description, property_type, address_line, city, state, pincode, max_guests, bedrooms, bathrooms, base_price_per_night, is_active, is_approved) VALUES
(1, 2, 'Pinecrest Alpine Wooden Cottage', 'Nestled in the pristine cedar forests of Old Manali, this handcrafted cedar-wood cottage offers panoramic snow-peak Himalayan views, private sundeck, stone fireplace, and organic orchard walks.', 'Wooden Cabin', 'Log Huts Road, Old Manali', 'Manali', 'Himachal Pradesh', '175131', 4, 2, 2, 3800.00, TRUE, TRUE),

(2, 2, 'Whispering Valley Chalet', 'A secluded hillside chalet overlooking Solang valley. Experience morning mist, pine scented breeze, cozy attic bedrooms, stargazing balcony, and a warm hearth for memorable evenings.', 'Hillside Villa', 'Near Solang Ropeway, Palchan', 'Manali', 'Himachal Pradesh', '175103', 6, 3, 2, 4950.00, TRUE, TRUE),

(3, 3, 'Tea Garden Heritage Cottage', 'Step back in time in this 19th-century colonial tea bungalow located right inside a working tea estate. Features high ceilings, antique rosewood furniture, private tea-tasting sessions, and tranquil hill panoramas.', 'Heritage Cottage', 'Club Road, Near Botanical Gardens', 'Ooty', 'Tamil Nadu', '643001', 5, 2, 2, 4200.00, TRUE, TRUE),

(4, 3, 'Misty Cloud Treehouse & Chalet', 'Perched in the lush Western Ghats cloud cover, this unique wooden treehouse cottage features wrap-around glass balconies, babbling stream sounds, birdwatching perches, and Kerala home-cooked delights.', 'Treehouse', 'Pothamedu Viewpoint Road', 'Munnar', 'Kerala', '685612', 3, 1, 1, 3200.00, TRUE, TRUE),

(5, 4, 'Emerald Palms Coastal Chalet', 'A sunny Portuguese-influenced coastal homestay tucked 200m away from serene Mandrem beach. Boasts a private plunge pool, swaying coconut palms, outdoor hammocks, and fresh seafood barbecue.', 'Beach Chalet', 'Junas Waddo, Mandrem Beach Road', 'Goa', 'Goa', '403527', 4, 2, 2, 4500.00, TRUE, TRUE),

(6, 4, 'Coffee Mist Plantation Haven', 'Immerse in the aromatic Arabica coffee plantations of Madikeri. Includes guided estate trails, private bonfire beneath star-studded skies, fireplace, and traditional Kodava culinary hospitality.', 'Plantation Cottage', 'Galibeedu Road, Madikeri', 'Coorg', 'Karnataka', '571201', 6, 3, 3, 5200.00, TRUE, TRUE),

(7, 2, 'Ganges Riverside Stone Cottage', 'A peaceful stone haven located along the holy riverbanks of Rishikesh. Features sound of cascading waters, private yoga deck, meditation lawn, and proximity to scenic hiking trails.', 'Riverfront Cottage', 'Tapovan Badrinath Road', 'Rishikesh', 'Uttarakhand', '249192', 2, 1, 1, 2600.00, TRUE, TRUE),

(8, 4, 'Royal Rajputana Lakeview Haveli Suite', 'Traditional heritage stone architecture facing scenic Lake Pichola. Features carved jharokhas, rooftop terrace, royal brass bathtubs, and peaceful sunset dining.', 'Heritage Cottage', 'Haridas Ji Ki Magri, Lake Pichola', 'Udaipur', 'Rajasthan', '313001', 4, 2, 2, 5800.00, TRUE, TRUE);

-- ---------------------------------------------------------------------
-- Cottage Amenities (M:N Junction)
-- ---------------------------------------------------------------------
-- Cottage 1 (Manali Wooden Cottage): Wi-Fi, Mountain View, Fireplace, Bonfire, Hot Water, Parking, Breakfast, Heater
INSERT INTO cottage_amenities (cottage_id, amenity_id) VALUES
(1, 1), (1, 2), (1, 3), (1, 4), (1, 6), (1, 7), (1, 10), (1, 11),
-- Cottage 2 (Solang Chalet): Wi-Fi, Mountain View, Fireplace, Kitchenette, Hot Water, Parking, Power Backup
(2, 1), (2, 2), (2, 3), (2, 5), (2, 6), (2, 7), (2, 12),
-- Cottage 3 (Ooty Heritage): Wi-Fi, Mountain View, Fireplace, Hot Water, Parking, Breakfast, Heater
(3, 1), (3, 2), (3, 3), (3, 6), (3, 7), (3, 10), (3, 11),
-- Cottage 4 (Munnar Treehouse): Wi-Fi, Mountain View, Hot Water, Breakfast, Pet Friendly
(4, 1), (4, 2), (4, 6), (4, 9), (4, 10),
-- Cottage 5 (Goa Beach Chalet): Wi-Fi, Swimming Pool, Parking, AC, Pet Friendly, Kitchenette
(5, 1), (5, 5), (5, 7), (5, 8), (5, 9), (5, 11),
-- Cottage 6 (Coorg Plantation): Wi-Fi, Mountain View, Bonfire, Hot Water, Parking, Breakfast, Pet Friendly, Power Backup
(6, 1), (6, 2), (6, 4), (6, 6), (6, 7), (6, 9), (6, 10), (6, 12),
-- Cottage 7 (Rishikesh Stone): Wi-Fi, Mountain View, Hot Water, Breakfast, Power Backup
(7, 1), (7, 2), (7, 6), (7, 10), (7, 12),
-- Cottage 8 (Udaipur Lakeview): Wi-Fi, AC, Breakfast, Parking, Power Backup, Hot Water
(8, 1), (8, 6), (8, 7), (8, 10), (8, 11), (8, 12);

-- ---------------------------------------------------------------------
-- Cottage Images
-- ---------------------------------------------------------------------
INSERT INTO cottage_images (cottage_id, image_url, is_primary) VALUES
(1, 'https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=1200&q=80', TRUE),
(1, 'https://images.unsplash.com/photo-1510798831971-661eb04b3739?auto=format&fit=crop&w=800&q=80', FALSE),
(2, 'https://images.unsplash.com/photo-1449158743715-0a90ebb6d2d8?auto=format&fit=crop&w=1200&q=80', TRUE),
(2, 'https://images.unsplash.com/photo-1518780664697-55e3ad937233?auto=format&fit=crop&w=800&q=80', FALSE),
(3, 'https://images.unsplash.com/photo-1587061949409-02df41d5e562?auto=format&fit=crop&w=1200&q=80', TRUE),
(3, 'https://images.unsplash.com/photo-1570129477492-45c003edd2be?auto=format&fit=crop&w=800&q=80', FALSE),
(4, 'https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?auto=format&fit=crop&w=1200&q=80', TRUE),
(5, 'https://images.unsplash.com/photo-1499793983690-e29da59ef1c2?auto=format&fit=crop&w=1200&q=80', TRUE),
(5, 'https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=800&q=80', FALSE),
(6, 'https://images.unsplash.com/photo-1470770841072-f978cf4d019e?auto=format&fit=crop&w=1200&q=80', TRUE),
(7, 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=1200&q=80', TRUE),
(8, 'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1200&q=80', TRUE);

-- ---------------------------------------------------------------------
-- Bookings (Completed, Confirmed, Cancelled)
-- ---------------------------------------------------------------------
INSERT INTO bookings (booking_id, booking_code, cottage_id, guest_id, check_in_date, check_out_date, num_guests, total_nights, price_per_night, subtotal_amount, tax_amount, total_amount, booking_status, special_requests) VALUES
(1, 'HC-2026-MN01', 1, 5, '2026-09-10', '2026-09-13', 2, 3, 3800.00, 11400.00, 1368.00, 12768.00, 'completed', 'Late check-in requested at 6 PM.'),
(2, 'HC-2026-GA02', 5, 6, '2026-09-18', '2026-09-21', 3, 3, 4500.00, 13500.00, 1620.00, 15120.00, 'completed', 'Extra towels and coconut water on arrival.'),
(3, 'HC-2026-CG03', 6, 7, '2026-10-20', '2026-10-23', 4, 3, 5200.00, 15600.00, 1872.00, 17472.00, 'confirmed', 'Arrangement for estate tour.'),
(4, 'HC-2026-OT04', 3, 5, '2026-11-05', '2026-11-08', 2, 3, 4200.00, 12600.00, 1512.00, 14112.00, 'confirmed', 'Ground floor room preferred.');

-- ---------------------------------------------------------------------
-- Payments (Simulated Ledger)
-- ---------------------------------------------------------------------
INSERT INTO payments (payment_id, booking_id, transaction_ref, payment_method, amount, payment_status) VALUES
(1, 1, 'TXN-HC-88491023', 'upi', 12768.00, 'completed'),
(2, 2, 'TXN-HC-99214751', 'card', 15120.00, 'completed'),
(3, 3, 'TXN-HC-11029384', 'upi', 17472.00, 'completed'),
(4, 4, 'TXN-HC-33948572', 'netbanking', 14112.00, 'completed');

-- ---------------------------------------------------------------------
-- Reviews (Verified guest reviews for completed stays)
-- ---------------------------------------------------------------------
INSERT INTO reviews (review_id, cottage_id, guest_id, booking_id, rating, comment) VALUES
(1, 1, 5, 1, 5, 'Absolutely magical stay! The wooden architecture, warm cedar aroma, and breathtaking sunrise over snow peaks were unforgettable. Host Rahul was incredibly hospitable!'),
(2, 5, 6, 2, 5, 'The best coastal homestay in North Goa. Pristine private pool, tranquil vibe away from crowded spots, and pristine beach 2 mins away. Highly recommended!');
