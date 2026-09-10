"""backend/routes_ops.py -- Ops tab: operational/performance-tuning views
loosely modeled on AWR report sections that can be produced from current
v$ views alone (no Diagnostics Pack license assumed). Structured as a
`result` dict with one key per item so more Ops items can be added later
without changing this endpoint's response shape. Not part of the
15-second auto-refresh cycle."""

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


@router.get("/api/ops-usage")
async def ops_usage(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    key = cache_key("ops-usage", creds)
    cached = get_cached_result(key)
    if cached is not None:
        return cached

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return {"success": False, "message": f"Failed to connect to the DB: {err}"}

    result = {
        "success": True,
        "topQueries": None,
        "topQueriesCpu": None,
        "topQueriesBufferGets": None,
        "topWaitEvents": None,
        "instanceEfficiency": None,
        "loadProfile": None,
        "tablespaceIo": None,
        "keyParameters": None,
        "tempTablespaceUsage": None,
        "tempSessionUsage": None,
        "datafileAutoextend": None,
        "redoLogStatus": None,
        "undoConfig": None,
        "undoStatus": None,
    }

    # Top 5 by elapsed_time (cumulative since the cursor entered the shared
    # pool, not a single-execution time). All three Top SQL rankings below
    # are restricted to real user schemas -- excluding NULL parsing_schema_name
    # (recursive/internal SQL) and any schema DBA_USERS marks
    # ORACLE_MAINTAINED = 'Y' (SYS, SYSTEM, and the other Oracle-installed
    # accounts, a 12c+ column consistent with this app's 12.1+ baseline) --
    # so these rankings reflect application workload, not the database's own
    # internal housekeeping SQL.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT sql_id,
                      parsing_schema_name,
                      executions,
                      ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
                      ROUND(cpu_time / 1000000, 3) AS cpu_sec,
                      TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time
                 FROM (
                        SELECT sql_id, parsing_schema_name, executions, elapsed_time, cpu_time, last_active_time
                          FROM v$sql s
                         WHERE elapsed_time > 0
                           AND parsing_schema_name IS NOT NULL
                           AND NOT EXISTS (
                                 SELECT 1 FROM dba_users u
                                  WHERE u.username = s.parsing_schema_name
                                    AND u.oracle_maintained = 'Y'
                               )
                         ORDER BY elapsed_time DESC
                      )
                WHERE ROWNUM <= 5"""
        )
        dict_rowfactory(cursor)
        result["topQueries"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["topQueries"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Top 5 by cpu_time.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT sql_id,
                      parsing_schema_name,
                      executions,
                      ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
                      ROUND(cpu_time / 1000000, 3) AS cpu_sec,
                      TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time
                 FROM (
                        SELECT sql_id, parsing_schema_name, executions, elapsed_time, cpu_time, last_active_time
                          FROM v$sql s
                         WHERE cpu_time > 0
                           AND parsing_schema_name IS NOT NULL
                           AND NOT EXISTS (
                                 SELECT 1 FROM dba_users u
                                  WHERE u.username = s.parsing_schema_name
                                    AND u.oracle_maintained = 'Y'
                               )
                         ORDER BY cpu_time DESC
                      )
                WHERE ROWNUM <= 5"""
        )
        dict_rowfactory(cursor)
        result["topQueriesCpu"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["topQueriesCpu"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Top 5 by buffer_gets.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT sql_id,
                      parsing_schema_name,
                      executions,
                      buffer_gets,
                      ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
                      TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time
                 FROM (
                        SELECT sql_id, parsing_schema_name, executions, buffer_gets, elapsed_time, last_active_time
                          FROM v$sql s
                         WHERE buffer_gets > 0
                           AND parsing_schema_name IS NOT NULL
                           AND NOT EXISTS (
                                 SELECT 1 FROM dba_users u
                                  WHERE u.username = s.parsing_schema_name
                                    AND u.oracle_maintained = 'Y'
                               )
                         ORDER BY buffer_gets DESC
                      )
                WHERE ROWNUM <= 5"""
        )
        dict_rowfactory(cursor)
        result["topQueriesBufferGets"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["topQueriesBufferGets"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Top 5 Wait Events (excludes Idle waits, cumulative since instance startup).
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT event, wait_class, total_waits, time_waited, average_wait FROM (
                 SELECT event, wait_class, total_waits, time_waited, average_wait
                   FROM v$system_event
                  WHERE wait_class != 'Idle'
                  ORDER BY time_waited DESC
               ) WHERE ROWNUM <= 5"""
        )
        dict_rowfactory(cursor)
        result["topWaitEvents"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["topWaitEvents"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Instance Efficiency Percentages.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT
                 ROUND((1 - ((SELECT value FROM v$sysstat WHERE name = 'physical reads') /
                             NULLIF((SELECT value FROM v$sysstat WHERE name = 'db block gets') +
                                    (SELECT value FROM v$sysstat WHERE name = 'consistent gets'), 0))) * 100, 2)
                   AS buffer_hit_ratio,
                 ROUND((1 - ((SELECT SUM(reloads) FROM v$librarycache) /
                             NULLIF((SELECT SUM(pins) FROM v$librarycache), 0))) * 100, 2)
                   AS library_hit_ratio,
                 ROUND((1 - ((SELECT value FROM v$sysstat WHERE name = 'parse count (hard)') /
                             NULLIF((SELECT value FROM v$sysstat WHERE name = 'parse count (total)'), 0))) * 100, 2)
                   AS soft_parse_pct,
                 ROUND((1 - ((SELECT value FROM v$sysstat WHERE name = 'parse count (total)') /
                             NULLIF((SELECT value FROM v$sysstat WHERE name = 'execute count'), 0))) * 100, 2)
                   AS execute_to_parse_pct
               FROM dual"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["instanceEfficiency"] = {"ok": True, "data": rows[0] if rows else {}}
    except Exception as err:
        result["instanceEfficiency"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Load Profile, adapted: per-second averaged over the entire instance
    # uptime rather than one AWR snapshot interval.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT ROUND(redo_size / NULLIF(uptime_seconds, 0), 2) AS redo_size_per_sec,
                      ROUND(logical_reads / NULLIF(uptime_seconds, 0), 2) AS logical_reads_per_sec,
                      ROUND(physical_reads / NULLIF(uptime_seconds, 0), 2) AS physical_reads_per_sec,
                      ROUND(user_calls / NULLIF(uptime_seconds, 0), 2) AS user_calls_per_sec,
                      ROUND(executes / NULLIF(uptime_seconds, 0), 2) AS executes_per_sec,
                      ROUND((user_commits + user_rollbacks) / NULLIF(uptime_seconds, 0), 2) AS transactions_per_sec,
                      uptime_seconds
                 FROM (
                        SELECT
                          (SELECT value FROM v$sysstat WHERE name = 'redo size') AS redo_size,
                          (SELECT value FROM v$sysstat WHERE name = 'session logical reads') AS logical_reads,
                          (SELECT value FROM v$sysstat WHERE name = 'physical reads') AS physical_reads,
                          (SELECT value FROM v$sysstat WHERE name = 'user calls') AS user_calls,
                          (SELECT value FROM v$sysstat WHERE name = 'execute count') AS executes,
                          (SELECT value FROM v$sysstat WHERE name = 'user commits') AS user_commits,
                          (SELECT value FROM v$sysstat WHERE name = 'user rollbacks') AS user_rollbacks,
                          ROUND((SYSDATE - i.startup_time) * 86400) AS uptime_seconds
                        FROM v$instance i
                      )"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["loadProfile"] = {"ok": True, "data": rows[0] if rows else {}}
    except Exception as err:
        result["loadProfile"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Tablespace I/O Stats, at the datafile level, top 10 by physical reads
    # -- read-heavy datafiles are usually the ones worth investigating first.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT tablespace_name, file_name, physical_reads, physical_writes, avg_read_ms, avg_write_ms
                 FROM (
                        SELECT ts.name AS tablespace_name,
                               df.name AS file_name,
                               fs.phyrds AS physical_reads,
                               fs.phywrts AS physical_writes,
                               ROUND(fs.readtim / NULLIF(fs.phyrds, 0), 2) AS avg_read_ms,
                               ROUND(fs.writetim / NULLIF(fs.phywrts, 0), 2) AS avg_write_ms
                          FROM v$filestat fs
                          JOIN v$datafile df ON fs.file# = df.file#
                          JOIN v$tablespace ts ON df.ts# = ts.ts#
                         ORDER BY fs.phyrds DESC
                      )
                WHERE ROWNUM <= 10"""
        )
        dict_rowfactory(cursor)
        result["tablespaceIo"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["tablespaceIo"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Key Instance Parameters.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT
                 (SELECT limit FROM dba_profiles WHERE profile = 'DEFAULT' AND resource_name = 'PASSWORD_LIFE_TIME') AS password_life_time,
                 (SELECT value FROM v$parameter WHERE name = 'spfile') AS spfile,
                 (SELECT value FROM v$parameter WHERE name = 'audit_trail') AS audit_trail,
                 (SELECT value FROM v$parameter WHERE name = 'processes') AS processes,
                 (SELECT value FROM v$parameter WHERE name = 'sessions') AS sessions,
                 (SELECT value FROM v$parameter WHERE name = 'open_cursors') AS open_cursors,
                 (SELECT value FROM v$parameter WHERE name = 'db_files') AS db_files,
                 (SELECT value FROM v$parameter WHERE name = 'undo_retention') AS undo_retention,
                 (SELECT value FROM v$parameter WHERE name = 'optimizer_mode') AS optimizer_mode,
                 (SELECT value FROM v$parameter WHERE name = 'log_buffer') AS log_buffer,
                 (SELECT log_mode FROM v$database) AS archive_mode
               FROM dual"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["keyParameters"] = {"ok": True, "data": rows[0] if rows else {}}
    except Exception as err:
        result["keyParameters"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # TEMP Tablespace Usage. Percent is against each tempfile's own max size
    # (autoextend MAXBYTES when autoextensible, otherwise its current size),
    # not against the currently allocated total -- an autoextensible temp
    # file that's mostly-full today but can still grow to 32 GB shouldn't
    # read as "95% used" when it's really nowhere near its actual ceiling.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """WITH temp_max AS (
                 SELECT tablespace_name,
                        SUM(CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                                 THEN maxbytes ELSE bytes END) AS max_bytes
                   FROM dba_temp_files
                  GROUP BY tablespace_name
               ),
               temp_used AS (
                 SELECT tablespace_name,
                        SUM(bytes_used) AS used_bytes,
                        SUM(bytes_free) AS free_bytes,
                        SUM(bytes_used + bytes_free) AS alloc_bytes
                   FROM v$temp_space_header
                  GROUP BY tablespace_name
               )
               SELECT tu.tablespace_name,
                      ROUND(tu.used_bytes / 1024 / 1024 / 1024, 2) AS used_gb,
                      ROUND(tu.free_bytes / 1024 / 1024 / 1024, 2) AS free_gb,
                      ROUND(tu.alloc_bytes / 1024 / 1024 / 1024, 2) AS total_gb,
                      ROUND(tm.max_bytes / 1024 / 1024 / 1024, 2) AS max_gb,
                      ROUND(tu.used_bytes / NULLIF(tm.max_bytes, 0) * 100, 2) AS used_pct
                 FROM temp_used tu
                 LEFT JOIN temp_max tm ON tm.tablespace_name = tu.tablespace_name
                ORDER BY used_pct DESC NULLS LAST"""
        )
        dict_rowfactory(cursor)
        result["tempTablespaceUsage"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["tempTablespaceUsage"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # TEMP Usage by Session.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT s.sid,
                      s.serial# AS serial_num,
                      s.username,
                      s.machine,
                      s.program,
                      s.sql_id,
                      ROUND(SUM(u.blocks * t.block_size) / 1024 / 1024, 2) AS temp_mb
                 FROM v$tempseg_usage u
                 JOIN v$session s ON u.session_addr = s.saddr
                 JOIN dba_tablespaces t ON u.tablespace = t.tablespace_name
                GROUP BY s.sid, s.serial#, s.username, s.machine, s.program, s.sql_id
                ORDER BY temp_mb DESC"""
        )
        dict_rowfactory(cursor)
        result["tempSessionUsage"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["tempSessionUsage"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Datafile Autoextend Status -- for each datafile, whether AUTOEXTEND is
    # enabled and (if so) how close it is to hitting MAXSIZE. A datafile
    # with autoextend off simply fails with "ORA-01653: unable to extend"
    # once its tablespace fills up, so this is an early-warning list, with
    # the files closest to their max size (or without autoextend at all)
    # surfaced first, capped at 20 rows.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT * FROM (
                 SELECT tablespace_name,
                        file_name,
                        autoextensible,
                        ROUND(bytes / 1024 / 1024, 2) AS current_mb,
                        CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                             THEN ROUND(maxbytes / 1024 / 1024 / 1024, 2) END AS max_gb,
                        CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                             THEN ROUND(bytes / maxbytes * 100, 2) END AS used_pct_of_max
                   FROM dba_data_files
                  ORDER BY used_pct_of_max DESC NULLS LAST
               ) WHERE ROWNUM <= 20
              ORDER BY used_pct_of_max DESC NULLS LAST"""
        )
        dict_rowfactory(cursor)
        result["datafileAutoextend"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["datafileAutoextend"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Redo Log Status.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT group#,
                      status,
                      members,
                      ROUND(bytes / 1024 / 1024) AS size_mb,
                      archived,
                      TO_CHAR(first_time, 'YYYY-MM-DD HH24:MI:SS') AS first_time
                 FROM v$log
                ORDER BY group#"""
        )
        dict_rowfactory(cursor)
        result["redoLogStatus"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["redoLogStatus"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Undo Configuration.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT
                 (SELECT value FROM v$parameter WHERE name = 'undo_management') AS undo_management,
                 (SELECT value FROM v$parameter WHERE name = 'undo_tablespace') AS undo_tablespace,
                 (SELECT value FROM v$parameter WHERE name = 'undo_retention') AS undo_retention,
                 (SELECT retention FROM dba_tablespaces
                   WHERE tablespace_name = (SELECT value FROM v$parameter WHERE name = 'undo_tablespace')) AS retention_guarantee
               FROM dual"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["undoConfig"] = {"ok": True, "data": rows[0] if rows else {}}
    except Exception as err:
        result["undoConfig"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    # Undo Status.
    try:
        cursor = connection.cursor()
        await cursor.execute(
            """WITH ut AS (
                 SELECT value AS tablespace_name FROM v$parameter WHERE name = 'undo_tablespace'
               )
               SELECT
                 ut.tablespace_name AS undo_tablespace,
                 ROUND(df.total_bytes / 1024 / 1024) AS total_mb,
                 ROUND((df.total_bytes - NVL(fsp.free_bytes, 0)) / 1024 / 1024) AS used_mb,
                 ROUND((1 - NVL(fsp.free_bytes, 0) / NULLIF(df.total_bytes, 0)) * 100, 2) AS used_pct,
                 (SELECT tuned_undoretention FROM (
                    SELECT tuned_undoretention FROM v$undostat ORDER BY end_time DESC
                  ) WHERE ROWNUM = 1) AS tuned_undo_retention_sec
               FROM ut
               LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS total_bytes FROM dba_data_files GROUP BY tablespace_name) df
                 ON df.tablespace_name = ut.tablespace_name
               LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS free_bytes FROM dba_free_space GROUP BY tablespace_name) fsp
                 ON fsp.tablespace_name = ut.tablespace_name"""
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["undoStatus"] = {"ok": True, "data": rows[0] if rows else {}}
    except Exception as err:
        result["undoStatus"] = {"ok": False, "message": f"You do not have permission to view this. ({err})"}

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    set_cached_result(key, result)
    return result
