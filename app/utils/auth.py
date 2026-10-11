"""
app/utils/auth.py
─────────────────
In-memory login-attempt throttle (brute-force protection).

Tracks consecutive failed attempts per username. After MAX_ATTEMPTS
failures the account is locked for LOCKOUT_SECONDS.  Successful login
resets the counter.

This is a simple, dependency-free solution suitable for a single-process
server. For multi-process or multi-server deployments, replace the
_store dict with a Redis-backed equivalent (flask-limiter is already
wired up at the blueprint level for IP-rate-limiting).

SECURITY NOTE: We deliberately do NOT surface whether a username exists.
Both "wrong password" and "account not found" go through the same counter
and return the same generic error message.
"""

from __future__ import annotations

import time
import threading
from typing import NamedTuple

# ── Configuration ──────────────────────────────────────────────────────────────
MAX_ATTEMPTS: int = 5
LOCKOUT_SECONDS: int = 300   # 5 minutes


class _Entry(NamedTuple):
    failures: int
    locked_until: float  # epoch seconds; 0 means not locked


# ── Thread-safe in-process store ───────────────────────────────────────────────
_lock: threading.Lock = threading.Lock()
_store: dict[str, _Entry] = {}


def _now() -> float:
    return time.monotonic()


def is_locked(username: str) -> bool:
    """Return True if the username is currently in a lockout window."""
    with _lock:
        entry = _store.get(username)
        if entry is None:
            return False
        if entry.locked_until and _now() < entry.locked_until:
            return True
        if entry.locked_until and _now() >= entry.locked_until:
            # Lockout expired — clear automatically
            _store.pop(username, None)
        return False


def record_failure(username: str) -> int:
    """
    Increment the failure counter.
    Returns the new failure count.  If MAX_ATTEMPTS is reached, sets a lock.
    """
    with _lock:
        entry = _store.get(username, _Entry(0, 0.0))
        new_failures = entry.failures + 1
        locked_until = _now() + LOCKOUT_SECONDS if new_failures >= MAX_ATTEMPTS else 0.0
        _store[username] = _Entry(new_failures, locked_until)
        return new_failures


def record_success(username: str) -> None:
    """Reset failure counter on successful authentication."""
    with _lock:
        _store.pop(username, None)


def remaining_lockout(username: str) -> int:
    """Return remaining lockout seconds (0 if not locked)."""
    with _lock:
        entry = _store.get(username)
        if entry is None or not entry.locked_until:
            return 0
        remaining = entry.locked_until - _now()
        return max(0, int(remaining))
