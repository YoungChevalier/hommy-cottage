"""
Hommy Cottage - Configuration Module
Loads settings from environment variables with safe defaults.
Enforces the Principle of Least Privilege by connecting as the dedicated
'hommy_app' service user defined in sql/06_security.sql.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load .env file if present
load_dotenv(BASE_DIR / ".env")


class Config:
    """Application configuration loaded from environment variables."""
    # Flask Security & Session Management
    SECRET_KEY = os.getenv("SECRET_KEY", "hommy-cottage-dev-secret-key-change-in-production")

    # MySQL Database Settings (PyMySQL raw connection parameters)
    # Connects as the least-privileged 'hommy_app' user by default
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "hommy_app")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "HommyAppSecurePass2026!")
    DB_NAME = os.getenv("DB_NAME", "hommy_cottage")

    # SSL / TLS Settings for TiDB Cloud / Remote MySQL
    DB_SSL = os.getenv("DB_SSL", "auto")
    DB_SSL_CA = os.getenv("DB_SSL_CA", "")

    # File Uploads for Cottage Listings
    UPLOAD_FOLDER = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "static/uploads"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(16 * 1024 * 1024)))  # 16 MB max
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    # Pricing & Taxes (Simulated for billing calculation)
    GST_TAX_RATE = 0.12  # 12% standard hospitality tax
    CLEANING_FEE = 350.00  # Flat service/cleaning charge in INR
