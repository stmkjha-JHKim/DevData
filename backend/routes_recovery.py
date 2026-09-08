"""backend/routes_recovery.py -- Recovery tab: Fast Recovery Area (FRA)
space usage overview, a breakdown by file type, and Recent DML. Not part
of the 15-second auto-refresh cycle."""

from fastapi import APIRouter, Depends
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


@router.get("/api/recovery-usage")
async def recovery_usage(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    key = cache_key("recovery-usage", creds)
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return {"success": False, "message": f"Failed to connect to the DB: {err}"}

    result = {"success": True, "destUsage": None, "typeUsage": None, "recentDml": None}

    # 1) Overall FRA configuration and usage (one row per configured
    #    recovery file destination -- normally just one).
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT name,
                      ROUND(space_limit / 1024 / 1024 / 1024, 2) AS space_limit_gb,
                      ROUND(space_used / 1024 / 1024 / 1024, 2) AS space_used_gb,
                      ROUND(space_reclaimable / 1024 / 1024 / 1024, 2) AS space_reclaimable_gb,
                      ROUND((space_used - space_reclaimable) / NULLIF(space_limit, 0) * 100, 2) AS used_pct_net,
                      number_of_files
                 FROM v$recovery_file_dest"""
        )
        dict_rowfactory(cursor)
        result["destUsage"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["destUsage"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # 2) FRA usage broken down by file type.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT file_type,
                      ROUND(percent_space_used, 2) AS percent_space_used,
                      ROUND(percent_space_reclaimable, 2) AS percent_space_reclaimable,
                      number_of_files
                 FROM v$flash_recovery_area_usage
                ORDER BY percent_space_used DESC"""
        )
        dict_rowfactory(cursor)
        result["typeUsage"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["typeUsage"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # 3) Recent DML (INSERT/UPDATE/DELETE/MERGE), top 50, most recently
    #    active first. command_type: 2=INSERT, 6=UPDATE, 7=DELETE, 189=MERGE.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT sql_id,
                      CASE command_type
                        WHEN 2 THEN 'INSERT'
                        WHEN 6 THEN 'UPDATE'
                        WHEN 7 THEN 'DELETE'
                        WHEN 189 THEN 'MERGE'
                        ELSE TO_CHAR(command_type)
                      END AS command_name,
                      parsing_schema_name,
                      executions,
                      TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time,
                      DBMS_LOB.SUBSTR(sql_fulltext, 500, 1) AS sql_text
                 FROM v$sql
                WHERE command_type IN (2, 6, 7, 189)
                ORDER BY last_active_time DESC
                FETCH FIRST 50 ROWS ONLY"""
        )
        dict_rowfactory(cursor)
        result["recentDml"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["recentDml"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result
