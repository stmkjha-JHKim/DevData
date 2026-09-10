"""backend/core.py -- shared infrastructure every route module in this
package depends on: the FastAPI app instance itself, the DB connection
helper, the hand-rolled server-side session store, and a couple of small
value-formatting helpers used across multiple endpoints.

Split out of what used to be the top of main.py (see main.py's own
top-of-file comment for the app's overall design). Nothing in here is
specific to any one tab/feature -- if a helper is only used by one route
module, it stays in that module instead of here.
"""

import os
import re
import secrets
import sys
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

# The packaged .exe runs with no console at all (see OraPulse.spec /
# OraPulse-Folder.spec's console=False -- it's a tray-icon app now, see
# tray.py), which means sys.stdout/sys.stderr are None, not just non-a-tty.
# uvicorn's default logging setup calls sys.stdout.isatty() unconditionally
# while configuring its formatter; against None that raises
# AttributeError, which crashes the process before the server ever starts
# -- silently, since there's no console to show the traceback on. Standard
# fix for windowed PyInstaller apps: give stdout/stderr a harmless
# writable/isatty-able stand-in before anything (uvicorn, or our own
# stray print()) can touch them. Only None when actually windowed with no
# console (running from source always has a real console here).
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import browser
from oracle_dsn import dsn_from_creds
from paths import app_dir, resource_dir

import oracledb
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

import report

# public/ is a bundled, read-only resource -- resource_dir() resolves to
# PyInstaller's extraction directory when running as a frozen .exe, or
# next to this file when running from source. See paths.py.
PUBLIC_DIR = resource_dir() / "public"

# 127.0.0.1 only: this must never be reachable from the network or from
# another machine, only from a browser on this same computer. See
# main.py's top-of-file comment if you're deliberately setting this up as
# a shared server instead.
HOST = "127.0.0.1"
# 0 is a sentinel meaning "not decided yet": main.py replaces this with a
# fresh OS-assigned free port right before starting uvicorn (see
# main.py's _pick_free_port()), unless PORT is set explicitly here via the
# environment (used by this project's own test scripts, which need a
# fixed, predictable port to talk to). Read as a plain module attribute
# (core.PORT), not imported by name, by anything that needs the *final*
# value -- see main.py's own comment on this.
PORT = int(os.environ.get("PORT", 0))

# python-oracledb's own default for a connection's V$SESSION.PROGRAM is
# sys.executable, which -- for this app specifically -- means every one of
# OraPulse's own brief monitoring connections would otherwise show up as
# "python.exe" (running from source) or "OraPulse.exe" (packaged .exe) in
# the Current Session List, alongside the real user sessions it's meant to
# monitor. Overriding it to a single fixed, known value here means every
# view that lists sessions can reliably filter this one out (see
# routes_connect.py's db_status_sessions()) regardless of how the app is
# being run.
ORACLE_CLIENT_PROGRAM = "OraPulse"

# Version scheme: 1.NNNN, where NNNN is a zero-padded counter bumped by one
# for every change (1.0000 -> 1.0001 -> 1.0002 -> ...), not decimal
# arithmetic. VERSION is a plain text file at the project root (also
# copied next to the .exe by build.ps1/build-folder.ps1) so it reads the
# same way whether running from source or packaged. "unknown" is only a
# defensive fallback -- it should never actually show up outside of a
# broken build.
try:
    APP_VERSION = (app_dir() / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "unknown"

# The most recently successful /api/connect credentials, kept at module
# scope (outside any one session) so the background "Weekly DB Health
# Report" snapshot collector (report.py) can keep running against the
# right DB even after the browser tab that connected is closed or the
# session cookie expires. Set by routes_connect.py's /api/connect and
# cleared by its browser-close handling; overwritten by the next
# successful connect; never read back by anything except that collector.
last_connected_creds: Optional[dict] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Opens the app window once the server is actually listening (this
    # fires after uvicorn has bound the socket, right before it starts
    # accepting requests) -- so double-clicking the packaged .exe takes
    # the user straight to the connect screen instead of leaving them to
    # find the right address themselves in the console output. Reads the
    # bare module global PORT (not a value captured earlier), since by the
    # time this actually runs main.py has already replaced it with this
    # launch's real, freshly-picked port -- see main.py's
    # _pick_free_port() and its own comment on why. See browser.py's own
    # comment for why this isn't a plain webbrowser.open().
    browser.open_app_window(f"http://{HOST}:{PORT}")
    # Background collector for the Weekly DB Health Report feature -- a
    # no-op tick whenever nothing has connected yet (see report.py). Reads
    # last_connected_creds by name (not by value) on every tick, so it
    # always sees whatever routes_connect.py has most recently set it to.
    report.start_collector(lambda: last_connected_creds)
    yield


app = FastAPI(lifespan=lifespan, title="OraPulse", version=APP_VERSION)

# The ad-hoc SQL Query Runner (routes_sql_runner.py) lets the user SELECT
# from arbitrary tables/views, including ones with CLOB columns. Without
# this, python-oracledb returns CLOB/BLOB columns as LOB objects that
# can't be JSON-serialized; fetching them as plain str/bytes instead means
# the runner works without per-query column-type awareness. (Matches
# node-oracledb's `oracledb.fetchAsString = [oracledb.CLOB]` in the
# archived legacy-nodejs/main.js -- BLOB still isn't JSON-serializable,
# same documented limitation as that version.)
oracledb.defaults.fetch_lobs = False

# Identifier validation shared by every route that accepts a raw
# owner/table/partition name from the client and has to interpolate it
# into DDL-ish statements (ALTER SYSTEM, DBMS_STATS calls) that don't
# support bind variables for object names -- restricting to Oracle's own
# valid identifier character set closes any injection surface before the
# value is ever used.
IDENT_RE = re.compile(r"^[A-Za-z0-9_$#]+$")


async def get_oracle_connection(creds: dict) -> oracledb.AsyncConnection:
    return await oracledb.connect_async(
        user=creds["account"],
        password=creds["password"],
        dsn=dsn_from_creds(creds),
        program=ORACLE_CLIENT_PROGRAM,
    )


def dict_rowfactory(cursor: oracledb.AsyncCursor) -> None:
    """Makes fetchall()/fetchone() return rows as {COLUMN_NAME: value}
    dicts instead of plain tuples -- the equivalent of node-oracledb's
    `{ outFormat: oracledb.OUT_FORMAT_OBJECT }`, and what every endpoint
    in this package relies on for its JSON response shape. Must be called
    after execute() (cursor.description isn't populated until then)."""
    columns = [d[0] for d in cursor.description]
    cursor.rowfactory = lambda *args: dict(zip(columns, args))


# Used only by the ad-hoc SQL Query Runner (routes_sql_runner.py), since
# that endpoint executes whatever SELECT the user typed and can't rely on
# every column already being a JSON-safe type or already wrapped in
# TO_CHAR(...) the way this package's own built-in queries are.
#
# This has to be more thorough than the equivalent formatDbValue() in the
# archived legacy-nodejs version: JS's JSON.stringify() will silently
# coerce almost any value (falling back to {} for a type it doesn't know
# how to handle) and never throw, but Python's json module raises
# TypeError on a type it doesn't recognize -- and that raise happens
# inside FastAPI's response serialization, *after* this endpoint's own
# try/except has already returned, so it can't be caught there. A single
# unconverted value (an INTERVAL column coming back as datetime.timedelta,
# a NUMBER as decimal.Decimal, a RAW/BLOB as bytes) would surface as a raw
# "Internal Server Error" the frontend can't even parse as JSON, instead
# of the query's own success/failure message. So every value the user's
# arbitrary SELECT could produce is normalized to a JSON-safe type here,
# with a guaranteed-safe str() fallback for anything not explicitly
# handled.
def format_db_value(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, datetime):
        # Oracle DATE/TIMESTAMP have no zone of their own, so there's no
        # conversion to undo -- same as node-oracledb's Date object read
        # back with UTC getters in the archived legacy-nodejs version.
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, timedelta):
        # INTERVAL DAY TO SECOND
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        # RAW/BLOB/LONG RAW: no sensible plain-text rendering for
        # arbitrary binary data -- same documented limitation as the
        # legacy-nodejs version, just spelled out instead of silently
        # becoming `{}`.
        return "<binary data, not shown>"
    return str(v)


# ---------------------------------------------------------------------
# Session store: server-side, in-memory, keyed by an opaque cookie value.
#
# The old Node version's express-session used its default MemoryStore,
# keeping session data (including the raw DB password in `dbCreds`)
# entirely on the server, with the browser only ever holding a random
# session-id cookie. Starlette's own SessionMiddleware does the opposite
# -- it signs the cookie but stores the data *in* it, which would put the
# DB password in the browser's cookie jar. So this is a small hand-rolled
# equivalent of express-session's model instead: session data lives in
# the _sessions dict, the cookie only carries the id. maxAge (30 minutes)
# is fixed at creation time and not refreshed on every request, same as
# express-session's default resave:false/rolling:false.
# ---------------------------------------------------------------------
SESSION_MAX_AGE_SECONDS = 30 * 60
_sessions: dict[str, dict] = {}
_session_expiry: dict[str, float] = {}


class Session:
    def __init__(self, request: Request, response: Response):
        self._response = response
        sid = request.cookies.get("sid")
        if sid and sid in _sessions and _session_expiry.get(sid, 0) >= time.time():
            self.id: Optional[str] = sid
        else:
            self.id = None
        self.data: dict = _sessions.get(self.id, {}) if self.id else {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value) -> None:
        self.data[key] = value
        if self.id is None:
            self.id = secrets.token_urlsafe(32)
        _session_expiry[self.id] = time.time() + SESSION_MAX_AGE_SECONDS
        _sessions[self.id] = self.data
        self._response.set_cookie(
            "sid",
            self.id,
            httponly=True,
            max_age=SESSION_MAX_AGE_SECONDS,
            samesite="lax",
        )

    def destroy(self) -> None:
        if self.id:
            _sessions.pop(self.id, None)
            _session_expiry.pop(self.id, None)
        self.data = {}
        self._response.delete_cookie("sid")


def get_session(request: Request, response: Response) -> Session:
    return Session(request, response)


# --- Short-lived server-side result cache ---
#
# Several browser tabs/windows can end up querying the exact same DB
# target within the same few seconds -- a manual refresh click racing an
# auto-refresh tick, a non-leader tab's manual refresh (leader election in
# public/js/app-shell.js only stops *automatic* polling, not manual
# clicks), or simply two of the DashBoard's own tiers happening to land
# close together. Rather than each of those re-querying Oracle, an
# identical request (same endpoint, same DB target, same extra params like
# `days`) reuses whatever result was already fetched in the last
# RESULT_CACHE_TTL_SECONDS. Deliberately in-process/in-memory only (this
# app has no shared state across processes, and doesn't need one -- a
# single OraPulse instance is what a single user runs).
RESULT_CACHE_TTL_SECONDS = 15
_result_cache: dict[tuple, tuple[float, object]] = {}


def cache_key(endpoint: str, creds: dict, extra: tuple = ()) -> tuple:
    """Identifies "the same request against the same DB" -- keyed by
    target + account (not just target) so a lower-privileged account
    never sees another account's cached "permission denied" or vice
    versa. connectType is part of the target too: a SID and a Service
    Name that happen to spell the same identifier are not the same
    database, and must never share a cache entry."""
    return (endpoint, creds["ip"], creds["port"], creds["sid"], creds.get("connectType", "sid"), creds["account"], extra)


def get_cached_result(key: tuple):
    entry = _result_cache.get(key)
    if entry is None:
        return None
    cached_at, result = entry
    if time.monotonic() - cached_at > RESULT_CACHE_TTL_SECONDS:
        return None
    return result


def set_cached_result(key: tuple, result) -> None:
    _result_cache[key] = (time.monotonic(), result)


def invalidate_cached_result(endpoint: str, creds: dict, extra: tuple = ()) -> None:
    """Called right after an action that makes a cached read stale before
    its TTL would naturally expire it (e.g. killing a session should be
    reflected immediately, not up to 15s later)."""
    _result_cache.pop(cache_key(endpoint, creds, extra), None)
