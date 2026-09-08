"""backend/routes_connect.py -- app version, connect/disconnect lifecycle
(including the browser-close grace period), Favorites, and the DashBoard
tab's /api/db-status-* endpoints.

/api/db-status-* is split into three endpoints instead of one combined
call so the frontend can poll each at its own cadence (session/blocking
data changes fast, instance info almost never does) -- see
public/js/app-shell.js's loadSessionsStatus()/loadResourcesStatus()/
loadInstanceStatus() and their three separate setInterval timers. Each
endpoint still opens and closes its own connection per request (no
pooling), matching every other endpoint in this app."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

import favorites as favorites_store
import report

from . import core
from .core import (
    ORACLE_CLIENT_PROGRAM,
    Session,
    app,
    cache_key,
    dict_rowfactory,
    get_cached_result,
    get_oracle_connection,
    get_session,
    set_cached_result,
)

router = APIRouter()


@router.get("/api/version")
async def get_version():
    return {"success": True, "version": core.APP_VERSION}


# --- End the DB session when the browser actually closes ---
#
# dashboard.html sends a `navigator.sendBeacon('/api/browser-closing')`
# from a `pagehide` handler. There's no reliable way to tell "the tab was
# closed" apart from "the page is about to reload/navigate" at the moment
# the event fires (both fire the same pagehide/beforeunload events) -- so
# instead of disconnecting immediately, this only *schedules* a disconnect
# a few seconds out. Any other request from this browser (the reloaded
# page re-fetching /api/db-status-*, a normal navigation within the app,
# etc.) cancels it via the middleware below. Only a gap with no follow-up
# request at all -- an actual close -- lets it run.
BROWSER_CLOSE_GRACE_SECONDS = 5
_pending_disconnect_task: Optional[asyncio.Task] = None


def _cancel_pending_disconnect() -> None:
    global _pending_disconnect_task
    if _pending_disconnect_task is not None:
        _pending_disconnect_task.cancel()
        _pending_disconnect_task = None


@app.middleware("http")
async def cancel_pending_disconnect_middleware(request: Request, call_next):
    if request.url.path != "/api/browser-closing":
        _cancel_pending_disconnect()
    return await call_next(request)


async def _disconnect_after_delay(session_id: Optional[str]) -> None:
    global _pending_disconnect_task
    try:
        await asyncio.sleep(BROWSER_CLOSE_GRACE_SECONDS)
        # Ends both the dashboard's login session and the Weekly DB Health
        # Report's background collector -- a full stop, not just a logout,
        # matching the explicit "closing the browser should leave nothing
        # still polling this DB" requirement (unlike the Disconnect
        # button, which intentionally leaves the collector running).
        if session_id:
            core._sessions.pop(session_id, None)
            core._session_expiry.pop(session_id, None)
        core.last_connected_creds = None
    except asyncio.CancelledError:
        pass
    finally:
        _pending_disconnect_task = None


@router.post("/api/browser-closing")
async def browser_closing(request: Request) -> Response:
    global _pending_disconnect_task
    _cancel_pending_disconnect()
    _pending_disconnect_task = asyncio.create_task(
        _disconnect_after_delay(request.cookies.get("sid"))
    )
    return Response(status_code=204)


@router.post("/api/connect")
async def connect(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    ip = body.get("ip")
    port = body.get("port")
    sid = body.get("sid")
    account = body.get("account")
    password = body.get("password")

    if not (ip and port and sid and account and password):
        return JSONResponse(
            {
                "success": False,
                "message": "Please fill in all fields (IP, Port, SID, Account, Password).",
            },
            status_code=400,
        )

    connection = None
    try:
        connection = await get_oracle_connection(
            {"ip": ip, "port": port, "sid": sid, "account": account, "password": password}
        )
        # Simple query to confirm the connection
        cursor = connection.cursor()
        await cursor.execute("SELECT 1 FROM dual")

        creds = {"ip": ip, "port": port, "sid": sid, "account": account, "password": password}
        # Store the connection info in the session so it can be reused on
        # the main screen (DB status lookup)
        session.set("db_creds", creds)

        # Also cache it at module scope so the Weekly DB Health Report
        # collector keeps running against the right DB -- see
        # core.last_connected_creds's comment -- and kick off an immediate
        # background snapshot (fire-and-forget) so the report's history
        # starts filling in right away instead of waiting up to 15 minutes.
        core.last_connected_creds = creds
        report.trigger_immediate_collection(creds)

        return {
            "success": True,
            "message": f"Connected successfully to {account}@{ip}:{port}:{sid}.",
        }
    except Exception as err:
        session.set("db_creds", None)
        # NOTE: the archived legacy-nodejs version special-cased
        # node-oracledb's NJS-138 (server older than Oracle 12.1,
        # unsupported in thin mode) to append a friendlier note.
        # python-oracledb raises a different error for the same situation;
        # carrying that same friendly note over is a follow-up once
        # verified against an actual pre-12.1 Oracle instance, rather than
        # guessing the error text/code here.
        return {"success": False, "message": f"Connection failed: {err}"}
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


@router.post("/api/logout")
async def logout(session: Session = Depends(get_session)):
    session.destroy()
    return {"success": True}


# Favorites (saved connection details on the connect screen) -- see
# favorites.py for the encrypted-file storage this reads/writes. No login
# gate here (same as everywhere else in this app -- see main.py's
# top-of-file comment): this feature only exists to be usable before any
# DB connection/session exists yet.
@router.get("/api/favorites")
async def get_favorites():
    try:
        return {"success": True, "favorites": favorites_store.list_favorites()}
    except Exception as err:
        return {"success": False, "message": f"Failed to load favorites: {err}"}


@router.post("/api/favorites")
async def save_favorite_endpoint(request: Request):
    body = await request.json()
    required_fields = ("name", "ip", "port", "sid", "account", "password")
    if not all(body.get(field) for field in required_fields):
        return JSONResponse(
            {
                "success": False,
                "message": "Please fill in all fields (Name, IP, Port, SID, Account, Password).",
            },
            status_code=400,
        )
    try:
        saved = favorites_store.save_favorite(body)
        return {"success": True, "favorite": saved}
    except Exception as err:
        return {"success": False, "message": f"Failed to save favorite: {err}"}


@router.post("/api/favorites-delete")
async def delete_favorite_endpoint(request: Request):
    body = await request.json()
    fav_id = body.get("id")
    if not fav_id:
        return JSONResponse({"success": False, "message": "Missing favorite id."}, status_code=400)
    try:
        favorites_store.delete_favorite(fav_id)
        return {"success": True}
    except Exception as err:
        return {"success": False, "message": f"Failed to delete favorite: {err}"}


@router.get("/api/db-status-sessions")
async def db_status_sessions(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    key = cache_key("db-status-sessions", creds)
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to reconnect to the DB: {err}"},
            status_code=500,
        )

    result = {
        "success": True,
        "sessionCount": None,
        "sessionList": None,
        "blockingSessions": None,
        "longRunningOps": None,
    }

    # 1) Current connected session count (excludes background processes
    #    like PMON/SMON and counts only real user sessions -- and excludes
    #    OraPulse's own brief monitoring connection, which is otherwise
    #    live in v$session for the instant this very query runs; see
    #    core.ORACLE_CLIENT_PROGRAM)
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT COUNT(*) AS cnt FROM v$session
                WHERE type = 'USER' AND (program IS NULL OR program != :client_program)""",
            {"client_program": ORACLE_CLIENT_PROGRAM},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["sessionCount"] = {"ok": True, "data": rows[0]["CNT"]}
    except Exception as err:
        result["sessionCount"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # 2) Current session list (excludes background processes and
    #    OraPulse's own monitoring connection, same as sessionCount above;
    #    type = 'USER', any status -- ACTIVE and INACTIVE both, so the
    #    Status filter on the dashboard actually has something to filter
    #    between, and so idle INACTIVE sessions can be found and killed
    #    from this list). ACTIVE sessions are shown first, then within
    #    each status group sessions are sorted by logon time, oldest first
    #    -- a long-connected ACTIVE session is usually the one worth
    #    looking at first. Capped at 50 rows.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT sid, serial_num, status, machine, program, logon_time_str, sql_id
                 FROM (
                   SELECT sid, serial# AS serial_num, status, machine, program, sql_id,
                          TO_CHAR(logon_time, 'YYYY-MM-DD HH24:MI:SS') AS logon_time_str
                     FROM v$session
                    WHERE type = 'USER' AND (program IS NULL OR program != :client_program)
                    ORDER BY CASE WHEN status = 'ACTIVE' THEN 0 ELSE 1 END,
                             logon_time ASC,
                             sid
                 ) WHERE ROWNUM <= 50""",
            {"client_program": ORACLE_CLIENT_PROGRAM},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()

        cursor2 = connection.cursor()
        await cursor2.execute(
            """SELECT COUNT(*) AS cnt FROM v$session
                WHERE type = 'USER' AND (program IS NULL OR program != :client_program)""",
            {"client_program": ORACLE_CLIENT_PROGRAM},
        )
        dict_rowfactory(cursor2)
        total_count = (await cursor2.fetchall())[0]["CNT"]

        result["sessionList"] = {"ok": True, "data": rows, "truncated": total_count > len(rows)}
    except Exception as err:
        result["sessionList"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # 3) Blocking Session - list of sessions that are blocking other sessions
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT waiter.sid AS waiter_sid, waiter.serial# AS waiter_serial,
                      waiter.username AS waiter_user,
                      blocker.sid AS blocker_sid, blocker.serial# AS blocker_serial,
                      blocker.username AS blocker_user,
                      waiter.machine AS waiter_machine,
                      waiter.wait_class AS wait_class,
                      waiter.seconds_in_wait AS wait_seconds
                 FROM v$session waiter
                 JOIN v$session blocker ON waiter.blocking_session = blocker.sid
                WHERE waiter.blocking_session IS NOT NULL
                ORDER BY waiter.seconds_in_wait DESC"""
        )
        dict_rowfactory(cursor)
        result["blockingSessions"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["blockingSessions"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # 4) Long Running Session - progress of long-running operations (full
    #    table scans, backups, index creation, etc.)
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT sid, serial_num, opname, target, sofar, totalwork,
                      ROUND(sofar / totalwork * 100, 1) AS pct_complete,
                      elapsed_seconds, time_remaining
                 FROM (
                   SELECT sid, serial# AS serial_num, opname, target, sofar, totalwork,
                          elapsed_seconds, time_remaining
                     FROM v$session_longops
                    WHERE totalwork > 0
                      AND sofar < totalwork
                    ORDER BY start_time DESC
                 ) WHERE ROWNUM <= 10"""
        )
        dict_rowfactory(cursor)
        result["longRunningOps"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["longRunningOps"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result


@router.get("/api/db-status-resources")
async def db_status_resources(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    key = cache_key("db-status-resources", creds)
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to reconnect to the DB: {err}"},
            status_code=500,
        )

    result = {"success": True, "cpu": None, "memory": None}

    # 1) CPU usage (Host CPU Utilization %)
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT value FROM (
                 SELECT value FROM v$sysmetric
                  WHERE metric_name = 'Host CPU Utilization (%)'
                  ORDER BY end_time DESC
               ) WHERE ROWNUM = 1"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["cpu"] = (
            {"ok": True, "data": {"pct": float(rows[0]["VALUE"])}}
            if rows
            else {"ok": False, "message": "No results found."}
        )
    except Exception as err:
        result["cpu"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # 2) Memory usage (SGA + PGA usage vs. the configured memory target)
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT
                 ROUND((SELECT SUM(value) FROM v$sga) / 1024 / 1024, 1) AS sga_mb,
                 ROUND((SELECT value FROM v$pgastat WHERE name = 'total PGA allocated') / 1024 / 1024, 1) AS pga_mb,
                 ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'sga_max_size'), 0) / 1024 / 1024, 1) AS sga_max_mb,
                 ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'pga_aggregate_target'), 0) / 1024 / 1024, 1) AS pga_target_mb,
                 ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_target'), 0) / 1024 / 1024, 1) AS memory_target_mb,
                 ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_max_target'), 0) / 1024 / 1024, 1) AS memory_max_target_mb
               FROM dual"""
        )
        dict_rowfactory(cursor)
        d = (await cursor.fetchall())[0]
        sga_mb = float(d["SGA_MB"] or 0)
        pga_mb = float(d["PGA_MB"] or 0)
        used_mb = sga_mb + pga_mb
        memory_target_mb = float(d["MEMORY_TARGET_MB"] or 0)
        memory_max_target_mb = float(d["MEMORY_MAX_TARGET_MB"] or 0)
        if memory_target_mb > 0:
            target_mb = memory_target_mb
        elif memory_max_target_mb > 0:
            target_mb = memory_max_target_mb
        else:
            target_mb = float(d["SGA_MAX_MB"] or 0) + float(d["PGA_TARGET_MB"] or 0)
        pct = round((used_mb / target_mb) * 1000) / 10 if target_mb > 0 else None

        result["memory"] = {
            "ok": True,
            "data": {
                "sgaMb": sga_mb,
                "pgaMb": pga_mb,
                "usedMb": round(used_mb * 10) / 10,
                "targetMb": round(target_mb * 10) / 10 if target_mb > 0 else None,
                "pct": pct,
            },
        }
    except Exception as err:
        result["memory"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result


@router.get("/api/db-status-instance")
async def db_status_instance(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    key = cache_key("db-status-instance", creds)
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return JSONResponse(
            {"success": False, "message": f"Failed to reconnect to the DB: {err}"},
            status_code=500,
        )

    result = {"success": True, "instance": None}

    # Basic instance information
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT instance_name, status, host_name, version_full AS version,
                      TO_CHAR(startup_time, 'YYYY-MM-DD HH24:MI:SS') AS startup_time,
                      ROUND((SYSDATE - startup_time) * 86400) AS uptime_seconds
                 FROM v$instance"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["instance"] = (
            {"ok": True, "data": rows[0]} if rows else {"ok": False, "message": "No results found."}
        )
    except Exception as err:
        result["instance"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result
