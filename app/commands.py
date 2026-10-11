"""
app/commands.py
───────────────
Flask CLI commands for administrative tasks.

Usage
─────
    # Activate venv first, then:
    flask --app run create-admin

This will prompt interactively for username and password (input is hidden).
The password is hashed before insertion — plaintext is never stored.

Bootstrap procedure (one-time, no public endpoint)
───────────────────────────────────────────────────
1.  Ensure hotel_db schema is loaded (schema.sql).
2.  Activate the virtual environment.
3.  Set FLASK_APP=run (or ensure run.py is in the project root).
4.  Run:
        flask --app run create-admin
5.  Enter a username and a strong password (min 8 chars).
6.  The Admin account is inserted into app_user with:
        role='Admin', guest_id=NULL, emp_id=NULL

Security notes
──────────────
* Uses getpass() so the password is never echoed to the terminal.
* Password is hashed with Werkzeug before DB insertion.
* Accepts an optional --username flag (useful in non-interactive CI
  environments when combined with a secret piped to stdin).
"""

from __future__ import annotations

import getpass
import sys

import click
from flask import current_app
from flask.cli import with_appcontext


def register_commands(app) -> None:
    """Register all CLI commands with the Flask app."""
    app.cli.add_command(create_admin)


@click.command("create-admin")
@click.option("--username", prompt=True, help="Admin username")
@with_appcontext
def create_admin(username: str) -> None:
    """
    Bootstrap the first Admin account.

    Prompts for a username (or pass --username) and a password (hidden input).
    The password is hashed before being stored in app_user.
    """
    from app.services.auth_service import create_user

    # Securely prompt for password
    try:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
    except (KeyboardInterrupt, EOFError):
        click.echo("\nAborted.")
        sys.exit(1)

    if password != confirm:
        click.echo("Error: Passwords do not match.", err=True)
        sys.exit(1)

    if len(password) < 8:
        click.echo("Error: Password must be at least 8 characters.", err=True)
        sys.exit(1)

    user, err = create_user(
        username=username.strip(),
        password=password,
        role="Admin",
        guest_id=None,
        emp_id=None,
    )

    if err:
        click.echo(f"Error: {err}", err=True)
        sys.exit(1)

    click.echo(
        f"Admin account created successfully.\n"
        f"  user_id  : {user['user_id']}\n"
        f"  username : {user['username']}\n"
        f"  role     : {user['role']}\n"
        f"Keep these credentials safe. Do not share your password."
    )
