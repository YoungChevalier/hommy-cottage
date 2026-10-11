# Hommy Cottage — Hotel Management System

A full-stack hotel management backend built with **Python 3 / Flask** and **MySQL 8+**.

> **Currently implemented: Phases 1–3 — Project skeleton · Authentication & RBAC · Guest management**

---

## Tech Stack

| Layer | Choice |
|---|---|
| Database | MySQL 8+ · `schema.sql` |
| Backend | Python 3.12 + Flask 3.x |
| DB driver | `mysql-connector-python` |
| Config | `python-dotenv` |
| Auth | `Werkzeug` password hashing · Flask sessions |
| CSRF | `Flask-WTF` |
| Rate limiting | `Flask-Limiter` |
| Testing | `pytest` + `pytest-flask` |

---

## Project Structure

```
hommy-cottage/
├── app/
│   ├── __init__.py          # Application factory
│   ├── config.py            # Environment-driven config (Dev / Prod / Test)
│   ├── db.py                # MySQL connection pool
│   ├── decorators.py        # @login_required, @roles_required
│   ├── extensions.py        # CSRFProtect, Limiter singletons
│   ├── commands.py          # flask create-admin CLI
│   ├── routes/
│   │   ├── health.py        # GET /api/health, /api/health/db
│   │   ├── auth.py          # POST /api/auth/login, /logout, GET /me, POST /change-password
│   │   └── guests.py        # Full CRUD /api/guests
│   ├── services/
│   │   ├── auth_service.py  # Auth business logic
│   │   └── guest_service.py # Guest business logic
│   └── utils/
│       ├── responses.py     # JSON envelope helpers
│       ├── validators.py    # Input validation helpers
│       └── auth.py          # Login-attempt throttle
├── tests/
│   ├── conftest.py          # Shared pytest fixtures
│   ├── test_health.py       # Phase 1 tests (38 tests)
│   ├── test_auth.py         # Phase 2 tests (50 tests)
│   └── test_guests.py       # Phase 3 tests (75 tests)
├── schema.sql               # Full MySQL schema (BCNF, triggers, views, procedures)
├── run.py                   # Dev entry-point
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Quick Start

### 1. Clone and create a virtual environment

```powershell
git clone https://github.com/YoungChevalier/hommy-cottage.git
cd hommy-cottage

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Load the database schema (one-time)

```powershell
# Using MySQL CLI:
mysql -u root -p < schema.sql
```

Flask **never** creates or modifies the schema automatically.

### 3. Configure environment variables

```powershell
copy .env.example .env
```

Edit `.env`:

```env
DB_HOST=localhost
DB_PORT=3306
DB_NAME=hotel_db
DB_USER=root
DB_PASSWORD=your_mysql_password
SECRET_KEY=your-random-32-char-hex-string
FLASK_ENV=development
FLASK_DEBUG=1
```

### 4. Bootstrap the first Admin account (one-time)

```powershell
flask --app run create-admin
# Enter username and password when prompted (password is hidden)
```

### 5. Start the development server

```powershell
python run.py
```

Server starts at `http://127.0.0.1:5000`.

---

## API Reference

### Response Envelope

Every response follows this structure:

```json
{
  "success": true | false,
  "data":    <payload> | null,
  "error":   null | { "code": "...", "message": "..." }
}
```

### Health

| Method | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/api/health` | None | Liveness check |
| `GET` | `/api/health/db` | None | Database connectivity check |

### Authentication

| Method | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/api/auth/csrf-token` | None | Get CSRF token for SPA clients |
| `POST` | `/api/auth/login` | None | Login (JSON body: `username`, `password`) |
| `POST` | `/api/auth/logout` | ✅ | Destroy session |
| `GET` | `/api/auth/me` | ✅ | Get own profile |
| `POST` | `/api/auth/change-password` | ✅ | Change password (`current_password`, `new_password`) |

### Guests

| Method | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/api/guests` | Admin, Receptionist | List / search / paginate guests |
| `GET` | `/api/guests/<id>` | Admin, Receptionist, own Guest | Get one guest |
| `POST` | `/api/guests` | Admin, Receptionist | Create guest |
| `PUT` | `/api/guests/<id>` | Admin, Receptionist | Update guest |
| `DELETE` | `/api/guests/<id>` | Admin only | Delete guest |

#### Guest list query parameters

| Param | Default | Description |
|---|---|---|
| `search` | — | Substring match on name, phone, email |
| `page` | 1 | Page number |
| `limit` | 20 | Records per page (max 100) |
| `sort_by` | `guest_id` | `guest_id` \| `name` \| `phone` \| `email` |
| `sort_dir` | `asc` | `asc` \| `desc` |

---

## Roles & Permissions

| Role | Description | Linked record |
|---|---|---|
| `Admin` | Full access to all resources | None |
| `Receptionist` | Manage guests, view reservations | `employee` record |
| `Guest` | View own guest record only | `guest` record |

---

## Security

- Passwords hashed with Werkzeug (`pbkdf2:sha256`). Plaintext never stored or logged.
- Parameterized SQL throughout — no string interpolation.
- CSRF protection on all state-changing requests (`X-CSRFToken` header).
- Session cookies: `HttpOnly`, `SameSite=Lax`, `Secure` (production).
- Login brute-force protection: 5 failures → 5-minute per-username lockout.
- Generic login error messages — never reveals whether a username exists.
- Role-record integrity enforced in Python (not FK alone).

---

## Running Tests

```powershell
pytest                          # all tests
pytest tests/test_auth.py -v    # auth tests only
pytest tests/test_guests.py -v  # guest tests only
```

DB-dependent tests skip automatically if MySQL is not reachable.

**Current test coverage: 163 tests · 0 failures**

---

## Planned Phases

- [x] Phase 1 — Project skeleton, health endpoints, DB pool
- [x] Phase 2 — Authentication, sessions, RBAC, CSRF
- [x] Phase 3 — Guest management CRUD
- [ ] Phase 4 — Room management
- [ ] Phase 5 — Reservations and check-in/check-out
- [ ] Phase 6 — Payments and billing
- [ ] Phase 7 — Services, housekeeping, reporting

---

## License

MIT
