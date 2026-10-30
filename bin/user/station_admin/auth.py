# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""One administrator password and the sessions that follow from it."""

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from user.station_admin import common

SESSION_SECONDS = 12 * 3600
MINIMUM_LENGTH = 8
# scrypt parameters: about 16 MB and 50 ms per guess on a Raspberry Pi 4.
COST = dict(n=2 ** 14, r=8, p=1)

_sessions = {}
_failures = []
_lock = threading.Lock()


def _password_path():
    return os.path.join(common.STATE_DIR, 'password.json')


def _hash(password, salt):
    return hashlib.scrypt(password.encode('utf-8'), salt=salt, maxmem=64 * 1024 * 1024,
                          **COST)


def has_password():
    """Return True once the administrator has chosen a password."""
    return os.path.exists(_password_path())


def set_password(password):
    """Store a new password. Every open session stays valid only if it is the caller's.

    Args:
        password (str): The new password.

    Raises:
        ValueError: The password is too short.
    """
    if len(password) < MINIMUM_LENGTH:
        raise ValueError('The password needs at least %d characters.' % MINIMUM_LENGTH)
    salt = secrets.token_bytes(16)
    os.makedirs(common.STATE_DIR, exist_ok=True)
    temporary = _password_path() + '.new'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(dict(salt=salt.hex(), hash=_hash(password, salt).hex()), stream)
    os.replace(temporary, _password_path())


def check_password(password):
    """Tell whether a password is the administrator's.

    Guesses are limited: after five failures within a minute every further
    attempt fails until that minute has passed, whatever the password is.

    Args:
        password (str): The password to check.

    Returns:
        bool: True if it is correct.
    """
    now = time.time()
    with _lock:
        _failures[:] = [moment for moment in _failures if now - moment < 60]
        if len(_failures) >= 5:
            return False
    try:
        with open(_password_path()) as stream:
            stored = json.load(stream)
    except OSError:
        return False
    correct = hmac.compare_digest(_hash(password, bytes.fromhex(stored['salt'])).hex(),
                                  stored['hash'])
    if not correct:
        with _lock:
            _failures.append(now)
    return correct


def open_session():
    """Start a session.

    Returns:
        str: The session token for the cookie.
    """
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = time.time() + SESSION_SECONDS
    return token


def session_valid(token):
    """Tell whether a token belongs to a running session.

    Args:
        token (str|None): The token from the cookie.

    Returns:
        bool: True if the session is valid.
    """
    with _lock:
        expiry = _sessions.get(token)
        if expiry is None:
            return False
        if expiry < time.time():
            del _sessions[token]
            return False
    return True


def close_session(token):
    """End a session.

    Args:
        token (str|None): The token from the cookie.
    """
    with _lock:
        _sessions.pop(token, None)
