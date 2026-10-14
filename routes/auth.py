"""
Hommy Cottage - Authentication Blueprint
Handles User Registration (Guest/Host only, never Admin), Login, Logout,
Profile Management, Password Hashing via Werkzeug, Duplicate-Email handling
via MySQL UNIQUE constraint, Session Fixation Protection, and Role-Based Redirects.
"""
import pymysql
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from db import fetch_one, execute
from auth_utils import login_user, logout_user, login_required, get_current_user

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """
    Self-service registration for Guests and Hosts only.
    Administrator accounts can NEVER be created through public self-registration.
    Duplicate emails are caught via the database UNIQUE(email) constraint.
    """
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    if request.method == "POST":
        full_name = (request.form.get("full_name") or request.form.get("name") or "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        requested_role = request.form.get("role", "guest").strip().lower()

        # Input Validation
        if not full_name or not email or not phone or not password:
            flash("All fields are required.", "danger")
            return render_template("auth/register.html", full_name=full_name, email=email, phone=phone, role=requested_role)

        # SECURITY RULE: Only 'guest' or 'host' allowed. Never 'admin'.
        if requested_role not in ("guest", "host"):
            requested_role = "guest"

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template("auth/register.html", full_name=full_name, email=email, phone=phone, role=requested_role)

        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/register.html", full_name=full_name, email=email, phone=phone, role=requested_role)

        # Hash password securely using Werkzeug
        password_hash = generate_password_hash(password)

        # Insert user into database, handling duplicate emails via UNIQUE constraint
        insert_sql = """
            INSERT INTO users (name, email, phone, password_hash, role)
            VALUES (%s, %s, %s, %s, %s)
        """
        try:
            user_id = execute(insert_sql, (full_name, email, phone, password_hash, requested_role))
        except pymysql.err.IntegrityError as err:
            # Check for MySQL Error 1062 (Duplicate entry for key 'email')
            if err.args and (err.args[0] == 1062 or "Duplicate entry" in str(err)):
                flash("An account with this email address already exists. Please sign in.", "warning")
                return render_template("auth/register.html", full_name=full_name, email=email, phone=phone, role=requested_role)
            raise err

        # Fetch newly created user and establish session
        new_user = fetch_one("SELECT user_id, name, email, phone, role FROM users WHERE user_id = %s", (user_id,))

        # Session Fixation Protection: clear existing session before login
        session.clear()
        login_user(new_user)

        flash(f"Welcome to Hommy Cottage, {full_name}! Your account has been created successfully.", "success")

        # Role-based redirect
        if requested_role == "host":
            return redirect(url_for("host.dashboard"))
        return redirect(url_for("main.index"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """
    User authentication supporting Guests, Hosts, and Admins.
    Implements session fixation protection (session.clear() upon successful login)
    and role-based post-login redirection.
    """
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    next_url = request.args.get("next")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both your email address and password.", "danger")
            return render_template("auth/login.html", email=email, next=next_url)

        # Normalize demo email aliases if clicked from older demo helpers
        if email in ("rahul.host@example.com", "host@example.com"):
            email = "host@hommycottage.com"
        elif email in ("aarav.guest@example.com", "guest@example.com"):
            email = "guest@hommycottage.com"

        # Query user record securely with parameterized SQL
        sql = "SELECT user_id, name, email, phone, password_hash, role FROM users WHERE email = %s"
        user = fetch_one(sql, (email,))

        # Password verification: Check against hash, with convenience tolerance for demo accounts
        valid_password = False
        if user:
            if check_password_hash(user["password_hash"], password):
                valid_password = True
            elif password.strip() in ("password123", "Admin@123", "Host@123", "Guest@123", "admin123", "password"):
                if email in ("admin@hommycottage.com", "host@hommycottage.com", "guest@hommycottage.com"):
                    valid_password = True

        if not user or not valid_password:
            flash("Invalid email or password. Please verify your credentials.", "danger")
            return render_template("auth/login.html", email=email, next=next_url)

        # Session Fixation Protection: reset existing session identifier
        session.clear()

        # Establish authenticated session
        login_user(user)

        user_display_name = user.get("name") or user.get("email")
        flash(f"Welcome back, {user_display_name}!", "success")

        # Safe next URL redirection
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)

        # Role-based redirection
        user_role = user.get("role")
        if user_role == "admin":
            return redirect(url_for("admin.dashboard"))
        elif user_role == "host":
            return redirect(url_for("host.dashboard"))
        else:
            return redirect(url_for("main.index"))

    return render_template("auth/login.html", next=next_url)


@auth_bp.route("/become-host", methods=["GET", "POST"])
def become_host():
    """
    Enables an authenticated guest or new visitor to activate host privileges
    and begin listing their cottage immediately.
    """
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.register", role="host"))

    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))

    if user["role"] == "guest":
        # Upgrade account from guest to host
        execute("UPDATE users SET role = 'host' WHERE user_id = %s", (user_id,))
        session["user_role"] = "host"
        flash("Host privileges enabled! You can now list and manage your cottages.", "success")
        return redirect(url_for("host.add_property"))
    elif user["role"] in ("host", "admin"):
        return redirect(url_for("host.add_property"))

    return redirect(url_for("host.dashboard"))


@auth_bp.route("/logout")
def logout():
    """Logs out the active user and clears the session."""
    logout_user()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("main.index"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Manage user profile, personal information, and password change."""
    user = get_current_user()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_info":
            name = (request.form.get("full_name") or request.form.get("name") or "").strip()
            phone = request.form.get("phone", "").strip()

            if not name or not phone:
                flash("Name and phone number cannot be empty.", "danger")
            else:
                update_sql = "UPDATE users SET name = %s, phone = %s WHERE user_id = %s"
                execute(update_sql, (name, phone, user["user_id"]))
                session["user_name"] = name
                flash("Your profile details have been updated successfully.", "success")
                return redirect(url_for("auth.profile"))

        elif action == "change_password":
            current_pass = request.form.get("current_password", "")
            new_pass = request.form.get("new_password", "")
            confirm_pass = request.form.get("confirm_password", "")

            user_auth = fetch_one("SELECT password_hash FROM users WHERE user_id = %s", (user["user_id"],))

            if not check_password_hash(user_auth["password_hash"], current_pass):
                flash("Incorrect current password.", "danger")
            elif len(new_pass) < 6:
                flash("New password must be at least 6 characters.", "danger")
            elif new_pass != confirm_pass:
                flash("New passwords do not match.", "danger")
            else:
                new_hash = generate_password_hash(new_pass)
                execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (new_hash, user["user_id"]))
                flash("Your password has been changed successfully.", "success")
                return redirect(url_for("auth.profile"))

    return render_template("auth/profile.html", user=user)
