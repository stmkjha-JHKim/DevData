"""backend/routes_history.py -- execution history: list job runs (with
db/status/date filters) and fetch one run's full log text.
"""

from typing import Optional

from fastapi import APIRouter
from sqlalchemy import desc

from backend.db import JobRun, get_session

router = APIRouter(prefix="/api/history", tags=["history"])


def _run_view(run: JobRun, include_log: bool = False) -> dict:
    out = {
        "id": run.id,
        "policyId": run.policy_id,
        "policyName": run.policy_name,
        "dbId": run.db_id,
        "dbName": run.db_name,
        "runType": run.run_type,
        "status": run.status,
        "trigger": run.trigger,
        "startedAt": run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else None,
        "finishedAt": run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if run.finished_at else None,
        "durationSeconds": run.duration_seconds,
        "dumpFile": run.dump_file,
        "dumpSizeBytes": run.dump_size_bytes,
    }
    if include_log:
        out["logText"] = run.log_text
        out["errorText"] = run.error_text
    return out


@router.get("")
async def list_history(db_id: Optional[str] = None, status: Optional[str] = None, limit: int = 200):
    session = get_session()
    try:
        q = session.query(JobRun)
        if db_id:
            q = q.filter(JobRun.db_id == db_id)
        if status:
            q = q.filter(JobRun.status == status.upper())
        runs = q.order_by(desc(JobRun.started_at)).limit(min(limit, 500)).all()
        return {"success": True, "runs": [_run_view(r) for r in runs]}
    finally:
        session.close()


@router.get("/{run_id}")
async def get_run(run_id: str):
    session = get_session()
    try:
        run = session.get(JobRun, run_id)
        if run is None:
            return {"success": False, "message": "실행 이력을 찾을 수 없습니다."}
        return {"success": True, "run": _run_view(run, include_log=True)}
    finally:
        session.close()
