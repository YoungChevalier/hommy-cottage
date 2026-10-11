"""
run.py
──────
Development entry point.

    python run.py

For production use a WSGI server (gunicorn, uWSGI) instead:
    gunicorn "app:create_app()" --bind 0.0.0.0:5000
"""

from __future__ import annotations

import os

# Load .env BEFORE importing the app factory so that all os.environ reads
# inside config.py and db.py see the correct values.
from dotenv import load_dotenv
load_dotenv(override=False)   # does NOT overwrite variables already in the shell environment

from app import create_app  # noqa: E402  (import after load_dotenv is intentional)

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    app.run(host=host, port=port, debug=debug)
