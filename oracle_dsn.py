"""oracle_dsn.py -- builds an Oracle TNS connect descriptor from a target
description (host/port/identifier/connect type), and validates the bits a
user can type in on the DB registration screen.

This is a straight port of OraPulse's own oracle_dsn.py (same module name,
same function names/signatures) -- OraPulse Backup is meant to reuse that
project's environment, and every "creds"-shaped dict elsewhere in this app
(registered_dbs.py, the connect-test endpoint, the Data Pump driver) is
built the same way OraPulse's `creds` dicts are, so this stays a drop-in
match rather than a reinvention.
"""

import re

CONNECT_TYPE_SID = "sid"
CONNECT_TYPE_SERVICE_NAME = "service_name"
VALID_CONNECT_TYPES = (CONNECT_TYPE_SID, CONNECT_TYPE_SERVICE_NAME)

SID_RE = re.compile(r"^[A-Za-z0-9_$#]+$")
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_$#.\-]+$")


def normalize_connect_type(value, default=CONNECT_TYPE_SID):
    if value is None or value == "":
        return default
    v = str(value).strip().lower()
    return v if v in VALID_CONNECT_TYPES else None


def validate_identifier(identifier, connect_type):
    if not identifier or not str(identifier).strip():
        return "값을 입력하세요."
    pattern = SERVICE_NAME_RE if connect_type == CONNECT_TYPE_SERVICE_NAME else SID_RE
    if not pattern.match(str(identifier)):
        label = "Service Name" if connect_type == CONNECT_TYPE_SERVICE_NAME else "SID"
        return f"{label}에 허용되지 않는 문자가 포함되어 있습니다."
    return None


def build_connect_string(ip, port, identifier, connect_type=CONNECT_TYPE_SID) -> str:
    ct = (connect_type or CONNECT_TYPE_SID).strip().lower()
    connect_data = (
        f"(SERVICE_NAME={identifier})" if ct == CONNECT_TYPE_SERVICE_NAME else f"(SID={identifier})"
    )
    return (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={ip})(PORT={port}))"
        f"(CONNECT_DATA={connect_data}))"
    )


def dsn_from_creds(creds: dict) -> str:
    return build_connect_string(
        creds["ip"], creds["port"], creds["sid"], creds.get("connectType", CONNECT_TYPE_SID)
    )
