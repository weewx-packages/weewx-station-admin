# Copyright (c) 2026 Manuel Hilgert <hilman2@gmail.com>
"""One administrator password and the sessions that follow from it."""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time

from user.station_admin import common
from user.station_admin.i18n import _

log = logging.getLogger(__name__)

SESSION_SECONDS = 12 * 3600
# Sessions and failures count on a clock that never jumps. A Raspberry Pi has no battery
# clock and sets the date only once it reaches a time server, which can be after somebody
# has chosen the password. The monotonic clock counts from the start of the system and is
# the same in every process, so a stored session stays valid across a restart of this
# service, and ends with a reboot of the system.
clock = time.monotonic
BOOT_ID_PATH = '/proc/sys/kernel/random/boot_id'
MINIMUM_LENGTH = 8
# scrypt parameters: about 16 MB and 50 ms per guess on a Raspberry Pi 4.
COST = dict(n=2 ** 14, r=8, p=1)

# The hash of each session token, with the moment on clock() at which it expires.
_sessions = {}
_loaded = False
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


def set_password(password, keep=None):
    """Store a new password and end every session but the caller's.

    Args:
        password (str): The new password.
        keep (str|None): The token of the caller's session, which stays open. Default is
            None.

    Raises:
        ValueError: The password is too short.
    """
    if len(password) < MINIMUM_LENGTH:
        raise ValueError(_('The password needs at least {count} characters.',
                           count=MINIMUM_LENGTH))
    salt = secrets.token_bytes(16)
    os.makedirs(common.STATE_DIR, exist_ok=True)
    temporary = _password_path() + '.new'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(dict(salt=salt.hex(), hash=_hash(password, salt).hex()), stream)
    os.replace(temporary, _password_path())
    with _lock:
        _load()
        kept = {digest: expiry for digest, expiry in _sessions.items()
                if keep and digest == _digest(keep)}
        _sessions.clear()
        _sessions.update(kept)
        _save()


def check_password(password):
    """Tell whether a password is the administrator's.

    Guesses are limited: after five failures within a minute every further
    attempt fails until that minute has passed, whatever the password is.

    Args:
        password (str): The password to check.

    Returns:
        bool: True if it is correct.
    """
    now = clock()
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


def _sessions_path():
    return os.path.join(common.STATE_DIR, 'sessions.json')


def _boot():
    try:
        with open(BOOT_ID_PATH) as stream:
            return stream.read().strip()
    except OSError:
        return None


def _digest(token):
    # The file holds only hashes, so reading it gives nobody a session.
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _load():
    """Read the sessions of an earlier run of this service, once. Call with _lock held."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_sessions_path()) as stream:
            stored = json.load(stream)
    except (OSError, ValueError):
        return
    # After a reboot clock() starts again at zero, and the stored moments mean nothing.
    if stored.get('boot') != _boot():
        return
    now = clock()
    _sessions.update({digest: expiry for digest, expiry in stored.get('sessions', {}).items()
                      if isinstance(expiry, (int, float)) and expiry > now})


def _save():
    """Write the running sessions. Call with _lock held."""
    now = clock()
    for digest in [digest for digest, expiry in _sessions.items() if expiry < now]:
        del _sessions[digest]
    temporary = _sessions_path() + '.new'
    try:
        os.makedirs(common.STATE_DIR, exist_ok=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(dict(boot=_boot(), sessions=_sessions), stream)
        os.replace(temporary, _sessions_path())
    except OSError as error:
        # The session still works until this service restarts.
        log.warning('Cannot store the sessions: %s', error)


def open_session():
    """Start a session.

    Returns:
        str: The session token for the cookie.
    """
    token = secrets.token_urlsafe(32)
    with _lock:
        _load()
        _sessions[_digest(token)] = clock() + SESSION_SECONDS
        _save()
    return token


def session_valid(token):
    """Tell whether a token belongs to a running session.

    Args:
        token (str|None): The token from the cookie.

    Returns:
        bool: True if the session is valid.
    """
    if not token:
        return False
    with _lock:
        _load()
        expiry = _sessions.get(_digest(token))
        if expiry is None:
            return False
        if expiry < clock():
            del _sessions[_digest(token)]
            _save()
            return False
    return True


def close_session(token):
    """End a session.

    Args:
        token (str|None): The token from the cookie.
    """
    if not token:
        return
    with _lock:
        _load()
        if _sessions.pop(_digest(token), None) is not None:
            _save()
