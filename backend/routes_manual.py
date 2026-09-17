"""backend/routes_manual.py -- "메뉴얼 백업" tab: an ad hoc, one-off Data
Pump export the operator configures and runs by hand, without first
creating a BackupPolicy (see backend/jobs.py's run_manual_sync).

The directory list is scoped to what the connected account can actually
use: DIRECTORY objects aren't schema objects the account owns, so "can
this account write a dump file here" is a privilege question, not an
ownership one. A directory only qualifies if the account holds both READ
and WRITE on it (checked via USER_TAB_PRIVS, which reports privileges
received directly or through PUBLIC -- not through a role; an account
that only has directory access via a role won't see it listed here).

The schema/table lists (for TABLE-scope backups) are read straight off
ALL_TABLES using the connected account -- no filtering of Oracle-maintained
schemas, so a highly-privileged backup account will see its own noise
(SYS, SYSTEM, ...) alongside the real application schemas.

/{db_id}/run itself only starts the job and returns (see
backend/jobs.py's run_manual_sync) -- it does not block for the whole
export. /runs/{run_id}/progress is what the frontend polls afterward for
status/percentage until the run reaches SUCCESS or FAILED.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

import registered_dbs
from backend.core import get_oracle_connection, oracle_error_message
from backend.datapump import query_job_progress
from backend.db import JobRun, get_session
from backend.jobs import run_manual_async

router = APIRouter(prefix="/api/manual", tags=["manual"])

_DIRECTORIES_SQL = """
    SELECT d.directory_name, d.directory_path
    FROM all_directories d
    WHERE d.directory_name IN (
        SELECT table_name FROM user_tab_privs WHERE owner = 'SYS' AND privilege = 'READ'
        INTERSECT
        SELECT table_name FROM user_tab_privs WHERE owner = 'SYS' AND privilege = 'WRITE'
    )
    ORDER BY d.directory_name
"""

_SCHEMAS_SQL = "SELECT DISTINCT owner FROM all_tables ORDER BY owner"

# NUM_ROWS/BLOCKS/SAMPLE_SIZE are optimizer statistics (DBMS_STATS), not
# live counts -- NULL for a table that's never been analyzed, and possibly
# stale for one that's changed a lot since its last gather. Good enough to
# gauge relative table size before picking backup targets; not meant to be
# exact.
_TABLES_SQL = """
    SELECT table_name, num_rows, blocks, sample_size
    FROM all_tables
    WHERE owner = :schema
    ORDER BY table_name
"""


class ManualRunPayload(BaseModel):
    scope: str = "FULL"
    scope_value: Optional[str] = None
    directory: str


async def _query(db_id: str, sql: str, params: Optional[dict] = None) -> dict:
    """Connects with the registered DB's own creds, runs one read-only
    query, and always closes the connection -- shared by the directory/
    schema/table list endpoints below, which are otherwise identical
    boilerplate around three different catalog queries."""
    record = registered_dbs.get_db(db_id)
    if record is None:
        return {"success": False, "message": "등록되지 않은 DB입니다."}
    try:
        conn = await get_oracle_connection(registered_dbs.to_creds(record))
    except Exception as err:
        return {"success": False, "message": oracle_error_message(err)}
    try:
        cur = conn.cursor()
        await cur.execute(sql, params or {})
        rows = await cur.fetchall()
        return {"success": True, "rows": rows}
    except Exception as err:
        return {"success": False, "message": oracle_error_message(err)}
    finally:
        await conn.close()


@router.get("/{db_id}/directories")
async def list_directories(db_id: str):
    res = await _query(db_id, _DIRECTORIES_SQL)
    if not res["success"]:
        return res
    return {"success": True, "directories": [{"name": r[0], "path": r[1]} for r in res["rows"]]}


@router.get("/{db_id}/schemas")
async def list_schemas(db_id: str):
    res = await _query(db_id, _SCHEMAS_SQL)
    if not res["success"]:
        return res
    return {"success": True, "schemas": [r[0] for r in res["rows"]]}


@router.get("/{db_id}/tables")
async def list_tables(db_id: str, schema: str):
    res = await _query(db_id, _TABLES_SQL, {"schema": schema.upper()})
    if not res["success"]:
        return res
    return {
        "success": True,
        "tables": [
            {"name": r[0], "numRows": r[1], "blocks": r[2], "sampleSize": r[3]}
            for r in res["rows"]
        ],
    }


@router.post("/{db_id}/run")
async def run_manual(db_id: str, payload: ManualRunPayload):
    if not payload.directory:
        return {"success": False, "message": "백업 디렉토리를 선택하세요."}
    return await run_manual_async(db_id, payload.directory, payload.scope, payload.scope_value)


@router.get("/runs/{run_id}/progress")
async def run_progress(run_id: str):
    """Polled by the "메뉴얼 백업" tab while a run is RUNNING. The JobRun
    row itself (SUCCESS/FAILED once _finish_manual_run's background thread
    updates it) is authoritative and always returned; a live Oracle-side
    state/percentage is layered on top only while still RUNNING, since
    once our own row says done there's nothing left to poll for."""
    session = get_session()
    try:
        run = session.get(JobRun, run_id)
        if run is None:
            return {"success": False, "message": "실행 이력을 찾을 수 없습니다."}
        out = {
            "success": True,
            "runId": run.id,
            "status": run.status,
            "dumpFile": run.dump_file,
            "dumpSizeBytes": run.dump_size_bytes,
            "durationSeconds": run.duration_seconds,
            "message": run.error_text if run.status == "FAILED" else ("백업이 완료되었습니다." if run.status == "SUCCESS" else None),
            "jobState": None,
            "percentDone": None,
        }
        db_id, job_name = run.db_id, run.job_name
    finally:
        session.close()

    if out["status"] == "RUNNING" and job_name:
        record = registered_dbs.get_db(db_id)
        if record is not None:
            try:
                live = await asyncio.to_thread(query_job_progress, registered_dbs.to_creds(record), job_name)
                out["jobState"] = live.get("state")
                out["percentDone"] = live.get("percentDone")
            except Exception:
                pass  # live progress is best-effort -- our own JobRun.status is still accurate
    return out
