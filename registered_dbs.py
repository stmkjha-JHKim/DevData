"""backend/registered_dbs.py -- the set of Oracle DBs this instance backs
up. Unlike OraPulse (which connects to exactly one DB per browser session,
chosen fresh on the connect screen), OraVault Backup is meant to manage
several DBs' backup policies/history centrally -- so a registered DB is a
first-class, named, persisted record (id/ip/port/sid/account/password),
not a one-off connection. Storage reuses the exact same encrypted-file
approach OraPulse used for its Favorites feature (see crypto_store.py) --
this *is* effectively "Favorites promoted to the primary object", which is
why the on-disk shape below mirrors favorites.py's record shape closely.
"""

import secrets
import time
from typing import Optional

from crypto_store import EncryptedListStore
from oracle_dsn import normalize_connect_type, validate_identifier

_store = EncryptedListStore("registered_dbs.enc", ".registered_dbs-key")

# Fields safe to hand back to the browser -- everything except password.
PUBLIC_FIELDS = ("id", "name", "ip", "port", "sid", "connectType", "account", "createdAt")


def public_view(record: dict) -> dict:
    return {k: record.get(k) for k in PUBLIC_FIELDS}


def list_dbs() -> list:
    """Full records, password included -- internal use only (connecting,
    running Data Pump jobs). Never return this directly from a route."""
    return _store.read_all()


def list_dbs_public() -> list:
    return [public_view(d) for d in _store.read_all()]


def get_db(db_id: str) -> Optional[dict]:
    if not db_id:
        return None
    for d in _store.read_all():
        if d.get("id") == db_id:
            return d
    return None


def register_db(payload: dict) -> dict:
    connect_type = normalize_connect_type(payload.get("connectType"))
    if connect_type is None:
        raise ValueError("Invalid connect type.")
    id_err = validate_identifier(payload.get("sid"), connect_type)
    if id_err:
        raise ValueError(id_err)
    if not payload.get("password"):
        raise ValueError("비밀번호를 입력하세요.")
    if not payload.get("name") or not str(payload["name"]).strip():
        raise ValueError("DB 이름을 입력하세요.")

    dbs = _store.read_all()
    record = {
        "id": f"db_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
        "name": payload["name"].strip(),
        "ip": payload["ip"],
        "port": payload["port"],
        "sid": payload["sid"],
        "connectType": connect_type,
        "account": payload["account"],
        "password": payload["password"],
        "createdAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    dbs.append(record)
    _store.write_all(dbs)
    return record


def delete_db(db_id: str) -> None:
    _store.write_all([d for d in _store.read_all() if d["id"] != db_id])


def to_creds(record: dict) -> dict:
    """Reshapes a registered-DB record into the `creds` dict shape
    oracle_dsn.dsn_from_creds()/the connection helpers expect."""
    return {
        "ip": record["ip"],
        "port": record["port"],
        "sid": record["sid"],
        "connectType": record.get("connectType", "sid"),
        "account": record["account"],
        "password": record["password"],
    }
