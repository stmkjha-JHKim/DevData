"""backend/routes_session.py -- Current Session List row actions: wait
detail (with file/block object lookup), viewing a session's running SQL
text, and killing a session."""

import re

import sqlparse
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import sql_plan_analysis
from .core import Session, dict_rowfactory, get_oracle_connection, get_session, invalidate_cached_result

router = APIRouter()


@router.get("/api/session-wait-detail")
async def session_wait_detail(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    try:
        sid = int(request.query_params.get("sid", ""))
    except ValueError:
        sid = -1
    if sid <= 0:
        return JSONResponse(
            {"success": False, "message": "A valid sid parameter is required."}, status_code=400
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT inst_id,
                      sid,
                      serial# AS serial_num,
                      sql_id,
                      event,
                      state,
                      seconds_in_wait,
                      p1text,
                      p1,
                      p2text,
                      p2,
                      p3text,
                      p3,
                      row_wait_obj# AS row_wait_obj,
                      row_wait_file# AS row_wait_file,
                      row_wait_block# AS row_wait_block,
                      blocking_instance,
                      blocking_session
                 FROM gv$session
                WHERE sid = :sid""",
            {"sid": sid},
        )
        dict_rowfactory(cursor)
        return {"success": True, "data": await cursor.fetchall()}
    except Exception as err:
        return {"success": False, "message": f"You do not have permission to view this. ({err})"}
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


# Looks up the currently-cached SQL text (and a few execution stats) for a
# given SQL_ID, for the "View Running Query" item in the Current Session
# List's right-click/long-press context menu (and the Ops tab's SQL_ID
# links, and Recovery's Recent DML table).
@router.get("/api/session-sql")
async def session_sql(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    sql_id = (request.query_params.get("sqlId") or "").strip()
    if not sql_id or not re.fullmatch(r"[0-9a-zA-Z]+", sql_id):
        return JSONResponse(
            {"success": False, "message": "A valid sqlId parameter is required."}, status_code=400
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        # sql_fulltext is a CLOB; DBMS_LOB.SUBSTR keeps the result a plain
        # VARCHAR2 (up to 4000 chars) so no special CLOB fetch handling is
        # needed. A cursor can have multiple child_number rows for the same
        # sql_id (different bind/plan variants) -- just show the most
        # recently active one.
        await cursor.execute(
            """SELECT sql_id,
                      child_number,
                      parsing_schema_name,
                      executions,
                      ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
                      ROUND(cpu_time / 1000000, 3) AS cpu_sec,
                      TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time,
                      DBMS_LOB.SUBSTR(sql_fulltext, 4000, 1) AS sql_text
                 FROM v$sql
                WHERE sql_id = :sqlId
                ORDER BY last_active_time DESC
                FETCH FIRST 1 ROWS ONLY""",
            {"sqlId": sql_id},
        )
        dict_rowfactory(cursor)
        return {"success": True, "data": await cursor.fetchall()}
    except Exception as err:
        return {"success": False, "message": f"You do not have permission to view this. ({err})"}
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


# Loaded lazily as a second section of the SQL detail modal (after the
# SQL-text section from /api/session-sql above has already rendered) for
# every SQL_ID link across the app: a formatted (reindented) copy of the
# same shared-pool SQL text, its current execution plan from V$SQL_PLAN,
# and a rule-based analysis of that plan (see sql_plan_analysis.py). Reads
# only V$SQL/V$SQL_PLAN -- no EXPLAIN PLAN re-execution and no DBMS_XPLAN
# package privilege needed -- so, like the SQL text itself, this is only
# available while the cursor is still cached in the shared pool.
@router.get("/api/sql-plan")
async def sql_plan(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    sql_id = (request.query_params.get("sqlId") or "").strip()
    if not sql_id or not re.fullmatch(r"[0-9a-zA-Z]+", sql_id):
        return JSONResponse(
            {"success": False, "message": "A valid sqlId parameter is required."}, status_code=400
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT child_number,
                      DBMS_LOB.SUBSTR(sql_fulltext, 4000, 1) AS sql_text
                 FROM v$sql
                WHERE sql_id = :sqlId
                ORDER BY last_active_time DESC
                FETCH FIRST 1 ROWS ONLY""",
            {"sqlId": sql_id},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        if not rows:
            return {"success": True, "found": False}

        child_number = rows[0]["CHILD_NUMBER"]
        raw_sql = rows[0]["SQL_TEXT"] or ""
        try:
            formatted_sql = (
                sqlparse.format(raw_sql, reindent=True, keyword_case="upper", indent_width=2)
                if raw_sql
                else ""
            )
        except Exception:
            formatted_sql = raw_sql

        await cursor.execute(
            """SELECT id,
                      parent_id,
                      depth,
                      operation,
                      options,
                      object_owner,
                      object_name,
                      object_type,
                      cost,
                      cardinality,
                      bytes,
                      access_predicates,
                      filter_predicates
                 FROM v$sql_plan
                WHERE sql_id = :sqlId AND child_number = :childNumber
                ORDER BY id""",
            {"sqlId": sql_id, "childNumber": child_number},
        )
        dict_rowfactory(cursor)
        plan_rows = await cursor.fetchall()
        findings = sql_plan_analysis.analyze_plan(plan_rows)

        return {
            "success": True,
            "found": True,
            "sqlId": sql_id,
            "formattedSql": formatted_sql,
            "plan": plan_rows,
            "findings": findings,
        }
    except Exception as err:
        return {"success": False, "message": f"You do not have permission to view this. ({err})"}
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


# Uses the P1(FILE_NO) / P2(BLOCK_NO) values from the wait detail info above
# to look up the object (segment) that the actual file/block belongs to.
@router.get("/api/block-object")
async def block_object(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    try:
        file_no = int(request.query_params.get("fileno", ""))
        block_no = int(request.query_params.get("blockno", ""))
    except ValueError:
        file_no, block_no = -1, -1
    if file_no <= 0 or block_no < 0:
        return JSONResponse(
            {"success": False, "message": "A valid fileno/blockno parameter is required."},
            status_code=400,
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT owner,
                      segment_name,
                      partition_name,
                      segment_type,
                      tablespace_name,
                      relative_fno,
                      block_id AS extent_start_block,
                      block_id + blocks - 1 AS extent_end_block,
                      :blockNo - block_id AS block_offset
                 FROM dba_extents
                WHERE relative_fno = :fileNo
                  AND :blockNo BETWEEN block_id AND block_id + blocks - 1""",
            {"fileNo": file_no, "blockNo": block_no},
        )
        dict_rowfactory(cursor)
        return {"success": True, "data": await cursor.fetchall()}
    except Exception as err:
        return {
            "success": False,
            "message": f"You do not have permission to view this. DBA privileges are required. ({err})",
        }
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


# Right-clicking a row in the Current Session List opens a context menu
# with "Kill Session (IMMEDIATE)", which calls this endpoint. Runs
# ALTER SYSTEM KILL SESSION '<sid>,<serial#>' IMMEDIATE, requiring the
# connected account to have the ALTER SYSTEM privilege. IMMEDIATE means
# Oracle rolls back the session's transaction and reclaims its resources
# right away rather than waiting for it to reach a safe point on its own --
# this forcibly terminates whatever that session was doing.
#
# ALTER SYSTEM statements don't support bind variables for their target
# (Oracle has no placeholder syntax for this particular DDL-like command),
# so sid/serial are validated as plain non-negative integers first and then
# interpolated directly -- since only digits can survive that validation,
# there's no injection surface despite the string formatting.
@router.post("/api/kill-session")
async def kill_session(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    try:
        sid = int(body.get("sid"))
        serial = int(body.get("serial"))
    except (TypeError, ValueError):
        sid, serial = -1, -1
    if sid <= 0 or serial < 0:
        return JSONResponse(
            {"success": False, "message": "A valid sid/serial is required."}, status_code=400
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute(f"ALTER SYSTEM KILL SESSION '{sid},{serial}' IMMEDIATE")
        # So the DashBoard's session list reflects this immediately instead
        # of waiting out the rest of the 15s result-cache TTL (see
        # backend/core.py) -- the caller always re-fetches
        # /api/db-status-sessions right after a successful kill.
        invalidate_cached_result("db-status-sessions", creds)
        return {
            "success": True,
            "message": f"Kill session (IMMEDIATE) requested for SID {sid}, SERIAL# {serial}.",
        }
    except Exception as err:
        return {
            "success": False,
            "message": f"Failed to kill session. The ALTER SYSTEM privilege is required. ({err})",
        }
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")
