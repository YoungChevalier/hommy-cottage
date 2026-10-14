# Hommy Cottage - Boutique Vacation Stays & Cottage Booking Platform

A full-stack vacation rental web platform pairing comprehensive stay discovery and multi-criteria comparison with self-service cottage hosting. Built with Python Flask, responsive Bootstrap 5 / Vanilla CSS, and high-performance MySQL 8.0 ACID relational storage.

---

## 🌟 Key Platform Features

1. **Guest Stay Discovery & Filtering Engine:**
   - Multi-parameter filtering: Destination, Check-in / Check-out dates, Guests count, Price range (min & max), Property category, and Amenities checklists.
   - **Date Conflict Detection**: Excludes rooms or cottages that already have confirmed bookings during requested stay dates.
   - Dynamic sorting: Highest Rated, Price (Low to High), Price (High to Low), and Newest.

2. **Host Self-Listing & Inventory Management:**
   - Host onboarding and property management dashboard.
   - Comprehensive property wizard: title, description, category, full address, guest capacity, bedrooms, bathrooms, nightly rates, amenities, and photo uploads.
   - Multi-room category support with automatic inventory synchronization.
   - Real-time earnings KPIs, active listing toggles, and reservation ledgers.

3. **Booking Engine & Secure Ledger:**
   - Dynamic stay calculation (Nights × Base Price + Hospitality GST + Service Fee = Total).
   - Simulated payment gateways: UPI (Instant QR / VPA), Credit/Debit Card, Net Banking.
   - Unique alphanumeric booking references (`HC-2026-XXXXXX`) and transaction references (`TXN-HC-XXXXXXXX`).
   - Guest "My Bookings" portal with cancellation workflows and post-stay reviews.

4. **Admin Control Center:**
   - Platform KPIs: Total users (Guests / Hosts), approved listings, active reservations, gross revenue.
   - Listing moderation queue: One-click approval/rejection before properties go live.
   - User account directory: Role elevation and account management.
   - Revenue analytics with instant CSV export.

5. **Relational Architecture & Security:**
   - Strict 3NF / BCNF normalized schema preventing insertion, update, and deletion anomalies.
   - Stored procedures (`sp_book_room`, `sp_cancel_booking`) with atomic transaction isolation (`START TRANSACTION`, `COMMIT`, `ROLLBACK`).
   - Concurrency protection: Trigger-enforced double-booking prevention (`trg_prevent_overlap`).
   - Parametric PyMySQL query bindings (`%s`) preventing SQL injection.
   - Scrypt password hashing via Werkzeug security.

---

## 📁 Repository Layout

```text
Hommy Cottage/
├── app.py                 # Flask application factory and blueprint registration
├── config.py              # Environment configuration loader (from .env)
├── db.py                  # PyMySQL connection pooling and parameterization engine
├── auth_utils.py          # Session auth helpers and @role_required decorators
├── init_db.py             # Database creation and SQL execution runner
├── requirements.txt       # Production Python dependencies
├── Procfile               # PaaS production web server entrypoint (Gunicorn)
├── .gitignore             # Git exclusion rules
├── .env.example           # Environment template
├── sql/                   # Relational database scripts (01-07)
│   ├── 01_schema.sql      # Tables, primary keys, and foreign keys
│   ├── 02_seed.sql        # Initial sample destinations, cottages, and amenities
│   ├── 03_views.sql       # High-performance search and KPI views
│   ├── 04_triggers.sql    # Overlap prevention & audit triggers
│   ├── 05_procedures.sql  # Atomic booking & cancellation procedures
│   ├── 06_security.sql    # Role permissions & least-privilege grants
│   └── 07_queries.sql     # Complex analytical and reporting queries
├── routes/                # Modular Flask Blueprints
│   ├── search.py          # Home search, destination filter, detail page
│   ├── auth.py            # Login, register, profile, role upgrade
│   ├── host.py            # Host dashboard, listing wizard, room types, reservations
│   ├── admin.py           # Admin moderation, users, reports, revenue exports
│   ├── booking.py         # Checkout, payment simulation, cancellations, reviews
│   └── main.py            # Landing & About Us brand story
├── templates/             # Jinja2 HTML5 semantic templates
│   ├── base.html          # Global layout, responsive navbar, footer
│   ├── main/              # index.html, about.html
│   ├── auth/              # login.html, register.html, profile.html
│   ├── cottages/          # search.html, detail.html
│   ├── bookings/          # book.html, confirmation.html, my_bookings.html
│   ├── host/              # dashboard.html, create_listing.html, edit_listing.html, room_types.html
│   ├── admin/             # dashboard.html, cottages.html, users.html, reports.html
│   └── errors/            # 403.html, 404.html, 500.html
├── static/                # Static assets
│   ├── css/style.css      # Alpine cozy luxury stylesheet
│   ├── js/main.js         # Interactive search, price calculators, alerts
│   ├── img/               # Brand logo (SVG & PNG), favicon, sample gallery
│   └── uploads/           # User-uploaded cottage images
└── tests/                 # Automated test suite (120+ tests)
    ├── conftest.py        # Pytest fixtures and test clients
    ├── test_app.py        # 11-spec end-to-end integration test against test DB
    ├── test_auth.py       # Authentication and role access tests
    ├── test_booking.py    # Reservation logic, cancellation, refunds
    ├── test_host.py       # Multi-tenant host isolation and listing wizard
    ├── test_search.py     # Date filtering, sorting, and availability
    └── ...
```

---

## ⚙️ Quick Start (Local Setup)

### 1. Clone & Setup Python Virtual Environment
```bash
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Copy the environment template:
```bash
cp .env.example .env
```
Configure your MySQL database credentials in `.env`:
```ini
SECRET_KEY=generate_a_secure_random_key_here
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_mysql_password
DB_NAME=hommy_cottage
DB_SSL=auto
```

### 3. Initialize Database Schema & Seed Data
```bash
python init_db.py --seed
```

### 4. Run the Development Server
```bash
python app.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your browser.

---

## 🚀 Cloud Deployment Guide

### Deploying to Render / Railway / Heroku
1. **Repository Setup**: Push this repository to GitHub or GitLab.
2. **Database**: Create a MySQL 8.0 instance on **Aiven**, **TiDB Cloud**, or **Railway MySQL**.
3. **Environment Variables**: Configure the following in your cloud dashboard:
   - `SECRET_KEY`: Long random string
   - `DB_HOST`: Hostname of cloud MySQL
   - `DB_PORT`: Port (e.g., 3306 or Aiven port)
   - `DB_USER`: Database username
   - `DB_PASSWORD`: Database password
   - `DB_NAME`: Database name (e.g., `defaultdb` or `hommy_cottage`)
   - `DB_SSL`: `REQUIRED` (for cloud SSL connections)
4. **Build & Start Command**:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn "app:create_app()"` (or uses the included [`Procfile`](file:///c:/Users/Lenovo/Desktop/Languages/Hommy%20Cottage/Procfile))

### Deploying via Docker (Optional)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:create_app()"]
```

---

## 🧪 Running Automated Tests

Run the complete test suite:
```bash
pytest
```

Run the isolated integration test against the dedicated test database:
```bash
pytest tests/test_app.py -v
```

---

## 📄 License
Designed & Developed for Hommy Cottage Technologies. Distributed under the MIT License.
