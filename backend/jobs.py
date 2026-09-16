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
