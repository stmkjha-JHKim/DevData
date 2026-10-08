"""app_lock.py -- the app-level "master password" gate that protects this
whole OraPulse instance (the connect screen, the dashboard, and every
/api/* route -- see backend/routes_app_lock.py's middleware) until the
right password has been typed into the lock screen (public/lock.html).

This exists for a different threat model than "is this server reachable
from the internet" (it isn't -- see main.py's own top-of-file comment,
unchanged by this module): it's "can anyone who can open a browser on
*this* PC -- another Windows account, someone walking up to an unlocked
session, a coworker on a shared machine -- see this app's saved Oracle
connection details without typing anything first." It is NOT a substitute
for Windows login or disk encryption, and does not claim to be; see
README's "App Password" section for the actual, honestly-scoped
guarantee.

Design choice that shapes everything below: this password is a *gate*,
not a *data-encryption key*. Favorites (favorites.py), the Weekly DB
Health Report snapshot history, and the Tuning Advisor's snapshot
(report.py / tuning.py) keep using their own existing, independent
AES-256-GCM keys exactly as before -- nothing about their on-disk format
or key material changes here. Two reasons:
  1. An existing install's encrypted files must keep decrypting after this
     feature is added, with no migration step.
  2. It makes "forgot my password" safe: resetting the gate can never
     weaken or re-key data that was never derived from it in the first
     place. See reset instructions in README / the lock screen's own
     "forgot password" hint -- deleting just LOCK_FILE below resets only
     this gate; it has zero effect on any other store's encryption.

Stored verifier: data/app-lock.json -- {"algorithm", "iterations", "salt"
(hex), "hash" (hex)}. A PBKDF2-HMAC-SHA256 hash of the password, never the
password itself. hashlib.pbkdf2_hmac is used (stdlib, OpenSSL-backed)
rather than adding a new KDF dependency -- this project already uses the
`cryptography` package for AES-GCM elsewhere, but PBKDF2 needs nothing it
doesn't already get from the standard library.

Unlock state (who's currently allowed past the gate) is kept in memory
only (_unlock_tokens below), the same deliberate choice main.py's own
session store and the Weekly Report's last_connected_creds make: nothing
about "is this browser currently unlocked" is meant to survive a server
restart. Restarting OraPulse (including the tray icon's Exit) always asks
for the password again next launch.
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

from paths import DATA_DIR

LOCK_FILE = DATA_DIR / "app-lock.json"

# OWASP's current (2023) minimum recommendation for PBKDF2-HMAC-SHA256 is
# 600,000 iterations. This runs once per setup/unlock attempt (not on every
# request -- see app_lock_gate()'s use of the unlock token instead), and
# hashlib.pbkdf2_hmac is OpenSSL-backed, so this adds well under half a
# second even on modest hardware.
PBKDF2_ITERATIONS = 600_000
PBKDF2_ALGORITHM = "pbkdf2_sha256"
SALT_BYTES = 16

MIN_PASSWORD_LENGTH = 8
# A sanity cap, not a real-world limit anyone would hit -- just keeps a
# pathological request from feeding an enormous string into PBKDF2.
MAX_PASSWORD_LENGTH = 512


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def is_configured() -> bool:
    """Whether an app password has already been set up. False (not an
    error) for a missing, empty, or unreadable LOCK_FILE -- all of those
    mean "treat this as a first run," same as favorites.py treating a
    corrupted favorites.enc as "no favorites" rather than crashing."""
    return LOCK_FILE.exists()


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def validate_new_password(password: str, confirm_password: str) -> Optional[str]:
    """Returns a user-facing error message, or None if this password/confirm
    pair is acceptable to set as the new app password. Deliberately simple
    (length + match only, no composition rules) -- this protects against a
    shared-PC bystander, not a targeted attacker who already has filesystem
    access to this machine (see README's own limits section); a long
    passphrase the user can actually remember is more useful here than
    forced complexity rules."""
    if not isinstance(password, str) or not isinstance(confirm_password, str):
        return "비밀번호를 입력하세요."
    if not password or not confirm_password:
        return "비밀번호와 확인 비밀번호를 모두 입력하세요."
    if len(password) > MAX_PASSWORD_LENGTH:
        return "비밀번호가 너무 깁니다."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"비밀번호는 최소 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다."
    if password != confirm_password:
        return "비밀번호와 확인 비밀번호가 일치하지 않습니다."
    return None


def set_password(password: str) -> None:
    """Writes LOCK_FILE for the first time. Callers must check
    is_configured() themselves first -- this never overwrites an existing
    file (see routes_app_lock.py's /api/app-lock/setup, which is reachable
    without unlocking and would otherwise let anyone replace an already-set
    password without knowing the old one)."""
    _ensure_data_dir()
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _derive(password, salt, PBKDF2_ITERATIONS)
    payload = {
        "algorithm": PBKDF2_ALGORITHM,
        "iterations": PBKDF2_ITERATIONS,
        "salt": salt.hex(),
        "hash": digest.hex(),
    }
    LOCK_FILE.write_text(json.dumps(payload), encoding="utf-8")
    try:
        os.chmod(LOCK_FILE, 0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX permission bits (e.g. Windows)


def verify_password(password: str) -> bool:
    """Constant-time comparison against the stored hash. Any problem
    reading/parsing LOCK_FILE (missing, corrupted, wrong shape) is treated
    as "wrong password" rather than raising -- same defensive posture as
    favorites.py's _read_all()."""
    if not isinstance(password, str) or not password:
        return False
    try:
        payload = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        salt = bytes.fromhex(payload["salt"])
        iterations = int(payload["iterations"])
        expected = bytes.fromhex(payload["hash"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    actual = _derive(password, salt, iterations)
    return hmac.compare_digest(actual, expected)


# --- Brute-force throttle ---
#
# This app is only ever reached by a browser on the same machine (see
# main.py's top-of-file comment), so there's no concern about distinguishing
# "which remote client is attacking" -- a single global counter is enough.
# Resets to zero on every successful verify; an unconfigured gate (no
# LOCK_FILE yet) is never throttled, since there is no secret to brute-force
# until /api/app-lock/setup has actually run once.
_failed_attempts = 0
_last_attempt_monotonic = 0.0

LOCKOUT_THRESHOLD = 3  # first few mistakes (e.g. a fat-fingered attempt) are never delayed
LOCKOUT_BASE_SECONDS = 1.0
LOCKOUT_MAX_SECONDS = 30.0


def lockout_remaining_seconds() -> float:
    """How many more seconds a caller must wait before the next
    /api/app-lock/verify attempt is accepted, or 0 if it's fine to try
    right now. Exponential backoff (1s, 2s, 4s, ... capped at 30s) keyed
    off consecutive failures, not a hard lockout -- a real user who's
    simply forgotten which password they used will still get back in,
    just increasingly slowly, while a scripted guesser is throttled hard."""
    if _failed_attempts < LOCKOUT_THRESHOLD:
        return 0.0
    delay = min(LOCKOUT_MAX_SECONDS, LOCKOUT_BASE_SECONDS * (2 ** (_failed_attempts - LOCKOUT_THRESHOLD)))
    elapsed = time.monotonic() - _last_attempt_monotonic
    return max(0.0, delay - elapsed)


def register_failure() -> None:
    global _failed_attempts, _last_attempt_monotonic
    _failed_attempts += 1
    _last_attempt_monotonic = time.monotonic()


def register_success() -> None:
    global _failed_attempts, _last_attempt_monotonic
    _failed_attempts = 0
    _last_attempt_monotonic = 0.0


# --- Unlock sessions ---
#
# Deliberately separate from backend/core.py's own Session (the `sid`
# cookie, which holds the *Oracle* connection's credentials and is torn
# down by Disconnect / browser-close / its own 30-minute expiry). Mixing
# the two would mean disconnecting from a DB -- an everyday action -- would
# also re-lock the whole app, which isn't what anyone asking for "unlock
# once, then use the app" would expect. A forged/garbage cookie value here
# simply isn't a key in this dict, so it's treated as "not unlocked" the
# same as no cookie at all -- see is_unlocked().
UNLOCK_COOKIE_NAME = "ora_unlock"
UNLOCK_IDLE_SECONDS = 2 * 60 * 60  # 2 hours of inactivity re-locks the app

_unlock_tokens: dict[str, float] = {}  # token -> expiry (time.monotonic() timestamp)


def create_unlock_token() -> str:
    token = secrets.token_urlsafe(32)
    _unlock_tokens[token] = time.monotonic() + UNLOCK_IDLE_SECONDS
    return token


def is_unlocked(token: Optional[str]) -> bool:
    """True if `token` names a still-valid unlock session. Sliding expiry:
    a successful check here also extends that session's own expiry, so an
    actively-used app never times out mid-session, while one left open and
    unattended still re-locks after UNLOCK_IDLE_SECONDS of silence."""
    if not token:
        return False
    expiry = _unlock_tokens.get(token)
    if expiry is None:
        return False
    if expiry < time.monotonic():
        _unlock_tokens.pop(token, None)
        return False
    _unlock_tokens[token] = time.monotonic() + UNLOCK_IDLE_SECONDS
    return True


def destroy_unlock_token(token: Optional[str]) -> None:
    if token:
        _unlock_tokens.pop(token, None)
