"""backend/jobs.py -- the one place that actually runs a backup policy:
looks up the policy and its target DB, records a JobRun row, calls
backend/datapump.py, and writes the result back. Used by both the manual
"지금 실행" endpoint (routes_policies.py) and the scheduler (scheduler.py)
so a scheduled run and a manual run go through identical code.

run_policy_sync() is the real, blocking implementation (safe to call
directly from an APScheduler job, which already runs off the asyncio event
loop). run_policy_async() is the thin `asyncio.to_thread` wrapper a FastAPI
route should use instead -- see backend/datapump.py's own docstring for why
this must never run directly on the event loop.
"""

import asyncio
import threading
from datetime import datetime

import registered_dbs
from backend import datapump
from backend.db import BackupPolicy, JobRun, get_session


def run_policy_sync(policy_id: str, trigger: str = "MANUAL") -> dict:
    session = get_session()
    try:
        policy = session.get(BackupPolicy, policy_id)
        if policy is None:
            return {"success": False, "message": "정책을 찾을 수 없습니다."}
        db_record = registered_dbs.get_db(policy.db_id)
        if db_record is None:
            return {"success": False, "message": "정책이 가리키는 DB가 더 이상 등록되어 있지 않습니다."}

        run = JobRun(
            policy_id=policy.id,
            policy_name=policy.name,
            db_id=db_record["id"],
            db_name=db_record["name"],
            run_type="EXPORT",
            status="RUNNING",
            trigger=trigger,
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.commit()
        run_id = run.id

        spec = datapump.ExportSpec(
            policy_name=policy.name,
            directory=policy.directory_object,
            dump_file_pattern=policy.dump_file_pattern,
            scope=policy.scope,
            scope_value=policy.scope_value,
            compression=policy.compression,
            parallel_degree=policy.parallel_degree,
            content=policy.content,
        )
        creds = registered_dbs.to_creds(db_record)
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    finally:
        session.close()

    started = datetime.utcnow()
    result = datapump.run_export_job(creds, spec, run_ts)
    finished = datetime.utcnow()

    session = get_session()
    try:
        run = session.get(JobRun, run_id)
        if run is not None:
            run.status = "SUCCESS" if result.success else "FAILED"
            run.finished_at = finished
            run.duration_seconds = (finished - started).total_seconds()
            run.dump_file = result.dump_file
            run.dump_size_bytes = result.dump_size_bytes
            run.log_text = result.log_text
            run.error_text = result.error_text
            session.commit()
        return {
            "success": result.success,
            "runId": run_id,
            "status": "SUCCESS" if result.success else "FAILED",
            "message": "백업이 완료되었습니다." if result.success else result.error_text,
        }
    finally:
        session.close()


async def run_policy_async(policy_id: str, trigger: str = "MANUAL") -> dict:
    return await asyncio.to_thread(run_policy_sync, policy_id, trigger)


def _finish_manual_run(run_id: str, creds: dict, directory: str, started: "datapump.StartResult") -> None:
    """Runs in its own detached background thread, started right after
    start_export_job() returns -- this is the (possibly long) WAIT_FOR_JOB
    part, deliberately kept off of run_manual_sync's own return path so the
    "지금 백업" HTTP request doesn't have to stay open for the whole backup.
    Whatever's polling GET /api/manual/runs/{run_id}/progress sees the
    JobRun row this eventually updates."""
    wait_started = datetime.utcnow()
    result = datapump.wait_export_job(creds, directory, started.job_name, started.dump_file, started.log_file)
    finished = datetime.utcnow()

    session = get_session()
    try:
        run = session.get(JobRun, run_id)
        if run is not None:
            run.status = "SUCCESS" if result.success else "FAILED"
            run.finished_at = finished
            run.duration_seconds = (finished - wait_started).total_seconds()
            run.dump_file = result.dump_file
            run.dump_size_bytes = result.dump_size_bytes
            run.log_text = result.log_text
            run.error_text = result.error_text
            session.commit()
    finally:
        session.close()


def _manual_target_name(scope: str, scope_value: str | None) -> str:
    """Dump/log file names for a manual run use %POLICY% (see
    datapump._substitute_filename) as the actual backup target's name
    instead of a fixed "MANUAL" -- TABLE scope: the table name(s);
    SCHEMA scope: the schema name(s); FULL (no single target): "MANUAL".
    Capped at 3 names before falling back to "first name + ETCn" so a
    50-table selection doesn't produce an absurdly long filename."""
    scope = (scope or "FULL").upper()
    names: list[str] = []
    if scope == "TABLE" and scope_value and ":" in scope_value:
        _, tables_part = scope_value.split(":", 1)
        names = [t.strip() for t in tables_part.split(",") if t.strip()]
    elif scope == "SCHEMA" and scope_value:
        names = [s.strip() for s in scope_value.split(",") if s.strip()]
    if not names:
        return "MANUAL"
    if len(names) <= 3:
        return "_".join(names)
    return f"{names[0]}_ETC{len(names) - 1}"


def run_manual_sync(db_id: str, directory: str, scope: str, scope_value: str | None) -> dict:
    """One-off, ad hoc export -- no BackupPolicy involved (policy_id stays
    NULL on the JobRun row, same as a policy that's since been deleted).
    Used by the "메뉴얼 백업" tab, where the operator picks the directory
    and scope by hand for a single immediate run instead of scheduling a
    recurring policy. Fixed PARALLEL/CONTENT defaults for now, matching
    BackupPolicy's own defaults -- exposing those as tab options too is a
    likely next iteration, not added yet. COMPRESSION defaults to
    METADATA_ONLY, a real DBMS_DATAPUMP COMPRESSION value (unlike the
    BASIC/LOW/MEDIUM/HIGH scale, which is the separate, license-gated
    COMPRESSION_ALGORITHM parameter this app doesn't set -- passing one of
    those as COMPRESSION is exactly what raises ORA-39207).

    Only runs start_export_job() (OPEN..START_JOB..DETACH) synchronously --
    fast, and surfaces a real argument error (e.g. ORA-39001 from a bad
    scope/schema/table name) immediately instead of after a long wait.
    The actual WAIT_FOR_JOB happens in a background thread
    (_finish_manual_run), so this returns with a job name to poll as soon
    as the job is confirmed running, not once it's finished."""
    db_record = registered_dbs.get_db(db_id)
    if db_record is None:
        return {"success": False, "message": "선택한 DB가 등록되어 있지 않습니다."}

    session = get_session()
    try:
        run = JobRun(
            policy_id=None,
            policy_name="수동 백업",
            db_id=db_record["id"],
            db_name=db_record["name"],
            run_type="EXPORT",
            status="RUNNING",
            trigger="MANUAL",
            started_at=datetime.utcnow(),
        )
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()

    spec = datapump.ExportSpec(
        policy_name=_manual_target_name(scope, scope_value),
        directory=directory,
        dump_file_pattern="%POLICY%_%DATE%.dmp",
        scope=scope,
        scope_value=scope_value,
        compression="METADATA_ONLY",
        parallel_degree=1,
        content="ALL",
    )
    creds = registered_dbs.to_creds(db_record)
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        started = datapump.start_export_job(creds, spec, run_ts)
    except datapump.DataPumpError as err:
        session = get_session()
        try:
            run = session.get(JobRun, run_id)
            if run is not None:
                run.status = "FAILED"
                run.finished_at = datetime.utcnow()
                run.duration_seconds = 0.0
                run.dump_file = err.dump_file or None
                run.error_text = str(err)
                session.commit()
        finally:
            session.close()
        return {"success": False, "runId": run_id, "status": "FAILED", "message": str(err), "scriptText": ""}

    session = get_session()
    try:
        run = session.get(JobRun, run_id)
        if run is not None:
            run.job_name = started.job_name
            run.dump_file = started.dump_file
            session.commit()
    finally:
        session.close()

    threading.Thread(
        target=_finish_manual_run, args=(run_id, creds, directory, started), daemon=True,
    ).start()

    return {
        "success": True,
        "runId": run_id,
        "jobName": started.job_name,
        "status": "RUNNING",
        "message": "백업이 시작되었습니다. 진행 상태를 확인하세요.",
        "scriptText": started.script_text,
    }


async def run_manual_async(db_id: str, directory: str, scope: str, scope_value: str | None) -> dict:
    return await asyncio.to_thread(run_manual_sync, db_id, directory, scope, scope_value)
