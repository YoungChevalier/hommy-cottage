"""
Hommy Cottage - Authentication & Role-Based Authorization Utilities
Provides session management, login enforcement, role protection decorators,
date parsing, and upload validation helpers.
"""
from functools import wraps
from datetime import datetime, date
from flask import session, redirect, url_for, flash, request, abort
from config import Config
from db import fetch_one


def parse_date(date_str, fmt="%Y-%m-%d"):
    """
    Safely parses a string date into a python date object.
    Returns None if the string is empty or invalid.
    """
    if not date_str:
        return None
    if isinstance(date_str, (date, datetime)):
        return date_str if isinstance(date_str, date) else date_str.date()
    try:
        return datetime.strptime(str(date_str).strip(), fmt).date()
    except (ValueError, TypeError):
        return None


def allowed_file(filename, allowed_extensions=None):
    """
    Validates if an uploaded file has an allowed file extension.
    Defaults to Config.ALLOWED_EXTENSIONS ({'png', 'jpg', 'jpeg', 'webp'}).
    """
    if not filename or "." not in filename:
        return False
    if allowed_extensions is None:
        allowed_extensions = Config.ALLOWED_EXTENSIONS
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in allowed_extensions


def get_current_user():
    """
    Fetches fresh user data from the database using the user_id stored in session.
    Returns None if user is not logged in.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None
    # Parameterized SQL query: retrieves active user account
    sql = "SELECT user_id, name, name AS full_name, email, phone, role, created_at FROM users WHERE user_id = %s"
    return fetch_one(sql, (user_id,))


def login_user(user):
    """
    Stores minimal user identity and role in the session upon successful password verification.
    Supports both 'name' and 'full_name' dict keys for compatibility.
    """
    name = user.get("name") or user.get("full_name") or ""
    session["user_id"] = user["user_id"]
    session["user_email"] = user["email"]
    session["user_name"] = name
    session["user_role"] = user["role"]


def logout_user():
    """Clears user authentication keys from the active session."""
    session.clear()


def login_required(f):
    """
    Decorator to protect routes requiring an authenticated user.
    Redirects unauthenticated visitors to login page with friendly notice.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    """
    Decorator to restrict route access to specific user roles (e.g., 'host', 'admin').
    Usage:
        @role_required('host')
        @role_required('admin')
        @role_required('host', 'admin')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please sign in to continue.", "warning")
                return redirect(url_for("auth.login", next=request.url))

            user_role = session.get("user_role")
            if user_role not in allowed_roles:
                flash("Access denied: You do not have permission for this section.", "danger")
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
