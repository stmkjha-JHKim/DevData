"""backend/routes_jobs.py -- DashBoard tab: DBMS_SCHEDULER / legacy
DBMS_JOB failure history, shown above Alert Log Analysis. Not part of the
15-second auto-refresh cycle -- loaded once on screen open and again via
its own "Refresh" action, same pattern as Alert Log."""

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


@router.get("/api/job-failures")
async def job_failures(request: Request, session: Session = Depends(get_session)):
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

    key = cache_key("job-failures", creds, (days,))
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return {"success": False, "message": f"Failed to connect to the DB: {err}"}

    result = {"success": True, "schedulerFailures": None, "legacyJobFailures": None, "days": days}

    # DBMS_SCHEDULER job run history -- any outcome other than SUCCEEDED
    # (FAILED, STOPPED, TIMED_OUT, etc.), most recent first. How far back
    # this can actually see depends on each job class's own log_history
    # retention setting, same caveat that already applies to the Alert Log
    # card's "trailing N days" window.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT owner, job_name, status, error#, additional_info, log_date, run_duration_sec
                 FROM (
                   SELECT owner, job_name, status, error#, additional_info,
                          TO_CHAR(log_date, 'YYYY-MM-DD HH24:MI:SS') AS log_date,
                          EXTRACT(DAY FROM run_duration) * 86400
                            + EXTRACT(HOUR FROM run_duration) * 3600
                            + EXTRACT(MINUTE FROM run_duration) * 60
                            + EXTRACT(SECOND FROM run_duration) AS run_duration_sec
                     FROM dba_scheduler_job_run_details
                    WHERE status != 'SUCCEEDED'
                      AND log_date > SYSDATE - :days
                    ORDER BY log_date DESC
                 ) WHERE ROWNUM <= 50""",
            {"days": days},
        )
        dict_rowfactory(cursor)
        result["schedulerFailures"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["schedulerFailures"] = {
            "ok": False,
            "message": f"You do not have permission to view this. Access to DBA_SCHEDULER_JOB_RUN_DETAILS is required. ({err})",
        }

    # Legacy DBMS_JOB (DBA_JOBS) -- unlike DBMS_SCHEDULER above, there is no
    # per-run history table for this older job type, only a live snapshot:
    # jobs currently marked BROKEN, or with a nonzero cumulative failure
    # count, are surfaced here as an early-warning list rather than a true
    # history.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT job, schema_user, log_user, what, broken, failures,
                      TO_CHAR(last_date, 'YYYY-MM-DD HH24:MI:SS') AS last_date,
                      TO_CHAR(next_date, 'YYYY-MM-DD HH24:MI:SS') AS next_date
                 FROM dba_jobs
                WHERE broken = 'Y' OR failures > 0
                ORDER BY failures DESC, broken DESC"""
        )
        dict_rowfactory(cursor)
        result["legacyJobFailures"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["legacyJobFailures"] = {
            "ok": False,
            "message": f"You do not have permission to view this. ({err})",
        }

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result
