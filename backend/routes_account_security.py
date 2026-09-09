"""backend/routes_account_security.py -- DashBoard tab: locked Oracle
accounts and accounts whose password is expiring soon or has already
expired, from DBA_USERS. Sits right after Scheduler/Job Failures, same
lazy-load-once + manual-refresh pattern (not part of the 15-second
auto-refresh cycle) as that card and Alert Log Analysis.

EXPIRY_DATE is Oracle's own already-computed expiry date for each account
(it already reflects that account's PROFILE's PASSWORD_LIFE_TIME setting),
so this reads it directly rather than re-deriving it from DBA_PROFILES."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .core import (
    IS_DEMO_MODE,
    Session,
    cache_key,
    dict_rowfactory,
    get_cached_result,
    get_oracle_connection,
    get_session,
    set_cached_result,
)

router = APIRouter()


@router.get("/api/account-security")
async def account_security(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    # Demo build: this card is hidden outright (see dashboard.html's
    # data-demo-hide attribute on it and applyDemoModeUi() in
    # app-shell.js), so skip DBA_USERS entirely rather than fetching data
    # nothing will ever display.
    if IS_DEMO_MODE:
        return {"success": True, "demoDisabled": True, "lockedAccounts": None, "expiringPasswords": None, "days": 7}

    try:
        days = int(request.query_params.get("days", ""))
    except ValueError:
        days = 7
    if days <= 0:
        days = 7
    if days > 30:
        days = 30

    key = cache_key("account-security", creds, (days,))
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return {"success": False, "message": f"Failed to connect to the DB: {err}"}

    result = {"success": True, "lockedAccounts": None, "expiringPasswords": None, "days": days}

    # Currently locked accounts (manually locked, or auto-locked after too
    # many failed login attempts per the account's PROFILE) -- ACCOUNT_STATUS
    # can be a combined state like 'EXPIRED & LOCKED', hence LIKE rather than
    # an exact match.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT username, account_status, profile,
                      TO_CHAR(lock_date, 'YYYY-MM-DD HH24:MI:SS') AS lock_date
                 FROM dba_users
                WHERE account_status LIKE '%LOCKED%'
                ORDER BY lock_date DESC NULLS LAST"""
        )
        dict_rowfactory(cursor)
        result["lockedAccounts"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["lockedAccounts"] = {
            "ok": False,
            "message": f"You do not have permission to view this. DBA privileges are required. ({err})",
        }

    # Accounts whose password has already expired or will within the
    # requested window -- a negative days_until_expiry means already
    # expired. Accounts with no expiry at all (UNLIMITED PASSWORD_LIFE_TIME,
    # common for SYS/SYSTEM-style accounts) have a NULL EXPIRY_DATE and are
    # correctly excluded by the WHERE clause below, not just sorted last.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT username, account_status, profile,
                      TO_CHAR(expiry_date, 'YYYY-MM-DD HH24:MI:SS') AS expiry_date,
                      ROUND(expiry_date - SYSDATE) AS days_until_expiry
                 FROM dba_users
                WHERE expiry_date IS NOT NULL
                  AND expiry_date <= SYSDATE + :days
                ORDER BY expiry_date ASC""",
            {"days": days},
        )
        dict_rowfactory(cursor)
        result["expiringPasswords"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["expiringPasswords"] = {
            "ok": False,
            "message": f"You do not have permission to view this. DBA privileges are required. ({err})",
        }

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result
