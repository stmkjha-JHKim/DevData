"""backend/routes_policies.py -- backup policy CRUD plus "지금 실행"
(run now). See backend/jobs.py for what actually happens on a run.
"""

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import desc

import registered_dbs
from backend.db import BackupPolicy, JobRun, get_session
from backend.jobs import run_policy_async

router = APIRouter(prefix="/api/policies", tags=["policies"])


class PolicyPayload(BaseModel):
    name: str
    db_id: str
    scope: str = "FULL"
    scope_value: Optional[str] = None
    directory_object: str = "DATA_PUMP_DIR"
    dump_file_pattern: str = "%POLICY%_%DATE%.dmp"
    compression: str = "METADATA_ONLY"
    parallel_degree: int = 1
    content: str = "ALL"
    schedule_kind: str = "DAILY"
    schedule_time: Optional[str] = "03:00"
    schedule_weekday: Optional[int] = None
    interval_hours: Optional[int] = None
    retention_days: int = 14
    rpo_tier: str = "TIER2"
    notify_email: Optional[str] = None
    enabled: bool = True


def _db_name_map() -> dict:
    return {d["id"]: d["name"] for d in registered_dbs.list_dbs_public()}


def _policy_view(policy: BackupPolicy, db_names: dict, last_run: Optional[JobRun]) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "dbId": policy.db_id,
        "dbName": db_names.get(policy.db_id, "(삭제된 DB)"),
        "scope": policy.scope,
        "scopeValue": policy.scope_value,
        "directoryObject": policy.directory_object,
        "dumpFilePattern": policy.dump_file_pattern,
        "compression": policy.compression,
        "parallelDegree": policy.parallel_degree,
        "content": policy.content,
        "scheduleKind": policy.schedule_kind,
        "scheduleTime": policy.schedule_time,
        "scheduleWeekday": policy.schedule_weekday,
        "intervalHours": policy.interval_hours,
        "retentionDays": policy.retention_days,
        "rpoTier": policy.rpo_tier,
        "notifyEmail": policy.notify_email,
        "enabled": policy.enabled,
        "lastRunStatus": last_run.status if last_run else None,
        "lastRunAt": last_run.started_at.strftime("%Y-%m-%d %H:%M:%S") if last_run else None,
    }


@router.get("")
async def list_policies():
    session = get_session()
    try:
        policies = session.query(BackupPolicy).order_by(BackupPolicy.created_at.desc()).all()
        db_names = _db_name_map()
        out = []
        for p in policies:
            last_run = (
                session.query(JobRun)
                .filter(JobRun.policy_id == p.id)
                .order_by(desc(JobRun.started_at))
                .first()
            )
            out.append(_policy_view(p, db_names, last_run))
        return {"success": True, "policies": out}
    finally:
        session.close()


@router.post("")
async def create_policy(payload: PolicyPayload):
    if registered_dbs.get_db(payload.db_id) is None:
        return {"success": False, "message": "선택한 DB가 등록되어 있지 않습니다."}
    session = get_session()
    try:
        policy = BackupPolicy(**payload.model_dump())
        session.add(policy)
        session.commit()
        return {"success": True, "policy": _policy_view(policy, _db_name_map(), None)}
    finally:
        session.close()


@router.put("/{policy_id}")
async def update_policy(policy_id: str, payload: PolicyPayload):
    session = get_session()
    try:
        policy = session.get(BackupPolicy, policy_id)
        if policy is None:
            return {"success": False, "message": "정책을 찾을 수 없습니다."}
        for key, value in payload.model_dump().items():
            setattr(policy, key, value)
        session.commit()
        last_run = (
            session.query(JobRun)
            .filter(JobRun.policy_id == policy.id)
            .order_by(desc(JobRun.started_at))
            .first()
        )
        return {"success": True, "policy": _policy_view(policy, _db_name_map(), last_run)}
    finally:
        session.close()


@router.delete("/{policy_id}")
async def delete_policy(policy_id: str):
    session = get_session()
    try:
        policy = session.get(BackupPolicy, policy_id)
        if policy is not None:
            session.delete(policy)
            session.commit()
        return {"success": True}
    finally:
        session.close()


@router.post("/{policy_id}/run")
async def run_now(policy_id: str):
    return await run_policy_async(policy_id, trigger="MANUAL")
