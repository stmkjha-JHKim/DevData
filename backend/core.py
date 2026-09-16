"""backend/core.py -- shared infra: the FastAPI app instance, the Oracle
connection helper, and a couple of small formatting helpers. Split out the
same way OraPulse's backend/core.py is, for the same reason: nothing here
is specific to one tab/feature.
"""

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

import oracledb
from fastapi import FastAPI

from oracle_dsn import dsn_from_creds
from paths import APP_DIR, PUBLIC_DIR

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", 8000))

# Distinguishes this app's own brief connect-test/status connections from
# the Data Pump job connections it opens (see backend/datapump.py's own
# ORACLE_CLIENT_PROGRAM) in V$SESSION.PROGRAM, same convention OraPulse
# uses to filter its own monitoring connections out of the session list.
ORACLE_CLIENT_PROGRAM = "OraPulseBackup"

try:
    APP_VERSION = (APP_DIR / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "unknown"

app = FastAPI(title="OraPulse Backup", version=APP_VERSION)

oracledb.defaults.fetch_lobs = False


async def get_oracle_connection(creds: dict) -> oracledb.AsyncConnection:
    return await oracledb.connect_async(
        user=creds["account"],
        password=creds["password"],
        dsn=dsn_from_creds(creds),
        program=ORACLE_CLIENT_PROGRAM,
    )


def dict_rowfactory(cursor) -> None:
    columns = [d[0] for d in cursor.description]
    cursor.rowfactory = lambda *args: dict(zip(columns, args))


def format_db_value(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, timedelta):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return "<binary data, not shown>"
    return str(v)


def oracle_error_message(err: Exception) -> str:
    """python-oracledb's DatabaseError carries its real message on
    args[0].message (ORA-12541, ORA-01017, ...); falls back to str(err)
    for anything else (network-level errors, etc.)."""
    if isinstance(err, oracledb.DatabaseError) and err.args:
        return getattr(err.args[0], "message", str(err))
    return str(err)
