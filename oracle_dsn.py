"""oracle_dsn.py -- the one shared place that turns a target description
(host/port/identifier/connect type) into an Oracle TNS connect descriptor.

Before this module existed, `backend/core.py` and `report.py` each kept
their own byte-for-byte-identical copy of this function (report.py is
deliberately self-contained in every other way -- own encryption, own SQL,
own DB connection -- specifically so it could be dropped into another
project unchanged; see its own top-of-file comment). Adding Service Name
support to two independent copies would have meant either two divergent
implementations or two places to keep in perfect sync by hand, so this one
was pulled out instead. It has zero dependencies beyond the standard
library, so both `backend/core.py` and `report.py` can import it without
creating a cycle between them.

Every `creds` dict across the app already carries an `ip`/`port`/`sid`
triple (plus `account`/`password`); this module adds one more optional
key, `connectType` (`"sid"` or `"service_name"`), read via
`normalize_connect_type()` so that a `creds` dict -- or a favorite, a
cached session, an on-disk snapshot -- predating this feature and simply
lacking the key is always interpreted as `"sid"`, exactly matching its
only previous behavior.
"""

import re

CONNECT_TYPE_SID = "sid"
CONNECT_TYPE_SERVICE_NAME = "service_name"
VALID_CONNECT_TYPES = (CONNECT_TYPE_SID, CONNECT_TYPE_SERVICE_NAME)

# A SID is a plain Oracle identifier: ASCII letters/digits plus _ $ #.
SID_RE = re.compile(r"^[A-Za-z0-9_$#]+$")

# A Service Name is usually a DNS-style name (GLOBAL_NAME-derived, e.g.
# "orclpdb1.example.com") registered with the listener -- Oracle itself
# doesn't restrict it to the same bare-identifier charset a SID uses, so
# this additionally allows '.' and '-'. Whitespace, quotes, parentheses,
# and other characters that could break out of the DESCRIPTION= string
# it's embedded into are still rejected either way.
SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_$#.\-]+$")


def normalize_connect_type(value, default=CONNECT_TYPE_SID):
    """Returns a valid connect type string, or None if `value` was given
    but isn't one of the recognized values (the caller should treat that
    as a validation error, not silently fall back). A missing/blank value
    -- the case for every favorite, session, or snapshot saved before this
    feature existed -- returns `default` ("sid"), preserving old behavior
    exactly."""
    if value is None or value == "":
        return default
    v = str(value).strip().lower()
    return v if v in VALID_CONNECT_TYPES else None


def validate_identifier(identifier, connect_type):
    """Returns an error message string if `identifier` is empty or
    contains a character not valid for `connect_type`, else None."""
    if not identifier or not str(identifier).strip():
        return "값을 입력하세요."
    pattern = SERVICE_NAME_RE if connect_type == CONNECT_TYPE_SERVICE_NAME else SID_RE
    if not pattern.match(str(identifier)):
        label = "Service Name" if connect_type == CONNECT_TYPE_SERVICE_NAME else "SID"
        return f"{label}에 허용되지 않는 문자가 포함되어 있습니다."
    return None


def build_connect_string(ip, port, identifier, connect_type=CONNECT_TYPE_SID) -> str:
    """The full TNS connect descriptor. `connect_type` selects whether
    `identifier` is placed into CONNECT_DATA as SID= or SERVICE_NAME=;
    anything other than exactly "service_name" is treated as "sid" (the
    same default `normalize_connect_type()` uses), so a caller that
    forgets to normalize first still gets the historical behavior rather
    than an exception."""
    ct = (connect_type or CONNECT_TYPE_SID).strip().lower()
    connect_data = (
        f"(SERVICE_NAME={identifier})" if ct == CONNECT_TYPE_SERVICE_NAME else f"(SID={identifier})"
    )
    return (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={ip})(PORT={port}))"
        f"(CONNECT_DATA={connect_data}))"
    )


def dsn_from_creds(creds: dict) -> str:
    """Same as build_connect_string(), reading ip/port/sid/connectType
    straight out of a `creds` dict -- the one shape used everywhere in
    this app (connect form, favorites, session store, snapshots)."""
    return build_connect_string(
        creds["ip"], creds["port"], creds["sid"], creds.get("connectType", CONNECT_TYPE_SID)
    )
