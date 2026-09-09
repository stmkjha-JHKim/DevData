"""favorites.py -- server-side storage for the "Favorites" feature on the
connect screen (public/index.html): saved IP/Port/SID/Account/password so a
known DB can be connected to with one click instead of retyping its details
every time.

Stored as a small encrypted file on disk (data/favorites.enc): AES-256-GCM
with a key generated once into its own file (data/.favorites-key) the first
time this module needs it. Uses the *exact same wire format* as the original
Node version (favorites.js) -- iv(12 bytes) + GCM auth tag(16 bytes) +
ciphertext, base64-encoded, key stored as hex text -- so this reads/writes
the same data/favorites.enc file the Node backend already wrote, no
migration needed. (cryptography's AESGCM.encrypt() returns
ciphertext+tag appended, the opposite order from Node's iv+tag+ciphertext
layout -- _encrypt/_decrypt below explicitly re-order bytes to match.)

There's no login gate on the /api/favorites* routes in main.py (same as
everywhere else in this app -- see the top-of-file comment in main.py):
this whole feature only exists to be usable from the connect screen, before
any DB connection/session exists yet.
"""

import base64
import json
import os
import secrets
import time
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paths import DATA_DIR

FAVORITES_FILE = DATA_DIR / "favorites.enc"
KEY_FILE = DATA_DIR / ".favorites-key"

_cached_key: Optional[bytes] = None


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_encryption_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    _ensure_data_dir()
    if KEY_FILE.exists():
        _cached_key = bytes.fromhex(KEY_FILE.read_text().strip())
    else:
        _cached_key = secrets.token_bytes(32)
        KEY_FILE.write_text(_cached_key.hex())
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass  # best-effort on platforms without POSIX permission bits (e.g. Windows)
    return _cached_key


def _encrypt(value) -> str:
    iv = secrets.token_bytes(12)
    combined = AESGCM(_get_encryption_key()).encrypt(iv, json.dumps(value).encode("utf-8"), None)
    ciphertext, tag = combined[:-16], combined[-16:]
    return base64.b64encode(iv + tag + ciphertext).decode("ascii")


def _decrypt(b64: str):
    raw = base64.b64decode(b64)
    iv, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
    plaintext = AESGCM(_get_encryption_key()).decrypt(iv, ciphertext + tag, None)
    return json.loads(plaintext.decode("utf-8"))


# The whole list is stored as one encrypted blob (rather than encrypting
# individual fields within a plain-JSON array) -- simplest way to guarantee
# nothing about a favorite (name, IP, port, SID, account, password) ever
# touches disk unencrypted.
def _read_all() -> list:
    _ensure_data_dir()
    if not FAVORITES_FILE.exists():
        return []
    raw = FAVORITES_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = _decrypt(raw)
        return data if isinstance(data, list) else []
    except Exception as err:
        # Wrong/rotated key or a corrupted file -- treated as "no favorites"
        # rather than crashing the connect screen over it.
        print(f"[favorites] could not decrypt favorites.enc, treating as empty: {err}")
        return []


def _write_all(favorites_list: list) -> None:
    _ensure_data_dir()
    FAVORITES_FILE.write_text(_encrypt(favorites_list), encoding="utf-8")


# Fields safe to hand back to the browser -- everything in a favorite
# record *except* password. Used everywhere a favorite crosses the API
# boundary (the list endpoint, and the save endpoint's own response) so
# there's exactly one place that decides what "safe to show" means,
# rather than every call site having to remember to drop the field itself.
PUBLIC_FIELDS = ("id", "name", "ip", "port", "sid", "account")


def public_view(record: dict) -> dict:
    return {k: record.get(k) for k in PUBLIC_FIELDS}


def list_favorites() -> list:
    """Full records, password included -- for internal server-side use
    only (save_favorite's own overwrite-by-id lookup, connect-favorite's
    decrypt-and-connect). Never return this directly from an API route;
    see list_favorites_public()/public_view() for what a route should
    actually send to the browser."""
    return _read_all()


def list_favorites_public() -> list:
    """What GET /api/favorites actually returns: every field a saved
    connection needs to display and reconnect through, except the
    password itself -- see public_view()."""
    return [public_view(f) for f in _read_all()]


def get_favorite(fav_id: str) -> Optional[dict]:
    """Full record (password included) for one favorite by id, or None if
    it doesn't exist -- a forged/stale/already-deleted id is simply "not
    found", the same as a corrupted store (_read_all() already treats that
    as an empty list rather than raising). Internal server-side use only
    (POST /api/connect-favorite); never returned to a route as-is."""
    if not fav_id:
        return None
    for f in _read_all():
        if f.get("id") == fav_id:
            return f
    return None


# Upserts by id: a new favorite gets a generated id, an existing one (same
# id passed back in, e.g. when the user chose to overwrite an existing
# name) is replaced in place.
#
# `favorite["password"]` is optional: omitted (or empty/None) while
# overwriting an *existing* id keeps that favorite's current password
# unchanged -- the only way this can work at all, since the browser is
# never given the decrypted password back to resend in the first place
# (see public_view() above). A blank password is only rejected outright
# for a genuinely new favorite, where there is no existing password to
# fall back to.
def save_favorite(favorite: dict) -> dict:
    favorites_list = _read_all()
    fav_id = favorite.get("id")
    existing = next((f for f in favorites_list if f["id"] == fav_id), None) if fav_id else None
    resolved_id = existing["id"] if existing else f"fav_{int(time.time() * 1000)}_{secrets.token_hex(4)}"

    password = favorite.get("password") or None
    if password is None:
        if existing is None:
            raise ValueError("A password is required to save a new favorite.")
        password = existing["password"]

    record = {
        "id": resolved_id,
        "name": favorite["name"],
        "ip": favorite["ip"],
        "port": favorite["port"],
        "sid": favorite["sid"],
        "account": favorite["account"],
        "password": password,
    }
    idx = next((i for i, f in enumerate(favorites_list) if f["id"] == resolved_id), -1)
    if idx >= 0:
        favorites_list[idx] = record
    else:
        favorites_list.append(record)
    _write_all(favorites_list)
    return record


def delete_favorite(fav_id: str) -> None:
    _write_all([f for f in _read_all() if f["id"] != fav_id])
