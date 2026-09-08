"""backend/routes_alert_log.py -- Alert Log Analysis card: surfaces
noteworthy entries from the database alert log via V$DIAG_ALERT_EXT. Not
part of the auto-refresh cycle -- loaded once on screen open and again via
its own "Refresh" action."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .core import (
    Session,
    cache_key,
    dict_rowfactory,
    get_cached_result,
    get_oracle_connection,
    get_session,
    set_cached_result,
)

router = APIRouter()


@router.get("/api/alert-log")
async def alert_log(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    try:
        days = int(request.query_params.get("days", ""))
    except ValueError:
        days = 7
    if days <= 0:
        days = 7
    if days > 30:
        days = 30

    key = cache_key("alert-log", creds, (days,))
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        # "Result = ORA-0"/"Result = ORA-30" are Oracle's own unpadded,
        # non-error result codes for normal completion, not real errors --
        # genuine error codes are always the full zero-padded 5-digit form
        # (ORA-00060, ORA-00942, etc.), so matching the *extracted* code for
        # an exact "ORA-0"/"ORA-30" excludes only those markers, never a
        # real error whose code happens to start the same way.
        await cursor.execute(
            """SELECT log_time, message_type, message_level, ora_code, message_text FROM (
                 SELECT
                        TO_CHAR(originating_timestamp, 'YYYY-MM-DD HH24:MI:SS') AS log_time,
                        message_type,
                        message_level,
                        REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') AS ora_code,
                        message_text
                   FROM v$diag_alert_ext
                  WHERE originating_timestamp > SYSDATE - :days
                    AND (message_text LIKE '%ORA-%' OR message_type IN (2, 3))
                    AND (REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') IS NULL
                         OR REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') NOT IN ('ORA-0', 'ORA-30'))
                  ORDER BY originating_timestamp DESC
               ) WHERE ROWNUM <= 30""",
            {"days": days},
        )
        dict_rowfactory(cursor)
        result = {"success": True, "data": await cursor.fetchall(), "days": days}
        set_cached_result(key, result)
        return result
    except Exception as err:
        return {
            "success": False,
            "message": f"You do not have permission to view this. Access to V$DIAG_ALERT_EXT is required "
            f"(typically granted via SELECT_CATALOG_ROLE or the SELECT ANY DICTIONARY privilege). ({err})",
        }
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")
