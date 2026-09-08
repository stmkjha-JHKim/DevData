"""backend/routes_tuning.py -- Tuning tab: a rule-based health check that
works on any Oracle edition or version with no Diagnostics/Tuning Pack
license -- see tuning.py's own top-of-file comment for the reasoning and
what each rule checks. Structured findings only (rule id + severity +
numeric values); the dashboard's own i18n layer renders each one into a
localized title and message, the same split every other live tab uses."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

import tuning

from .core import Session, cache_key, get_cached_result, get_oracle_connection, get_session, set_cached_result

router = APIRouter()


@router.get("/api/tuning-check")
async def tuning_check(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    key = cache_key("tuning-check", creds)
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        result = await tuning.run_tuning_check(connection, creds)
        set_cached_result(key, result)
        return result
    except Exception as err:
        return {"success": False, "message": f"Failed to run the tuning check: {err}"}
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")
