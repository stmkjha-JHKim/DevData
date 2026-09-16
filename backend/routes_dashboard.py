"""backend/routes_dashboard.py -- aggregates registered_dbs + the policy/
job-run metadata store into the Overview tab's summary cards. Every number
here is computed from what's actually stored -- no placeholder/sample
figures; an instance with nothing registered yet just reports zeros.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import desc

import registered_dbs
from backend.db import BackupPolicy, JobRun, get_session

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def summary():
    session = get_session()
    try:
        dbs = registered_dbs.list_dbs_public()
        policies = session.query(BackupPolicy).all()

        db_rows = []
        for d in dbs:
            last_run = (
                session.query(JobRun)
                .filter(JobRun.db_id == d["id"])
                .order_by(desc(JobRun.started_at))
                .first()
            )
            db_rows.append({
                "id": d["id"],
                "name": d["name"],
                "lastBackupAt": last_run.started_at.strftime("%Y-%m-%d %H:%M") if last_run else None,
                "lastBackupStatus": last_run.status if last_run else None,
            })

        scope_counts = {"FULL": 0, "SCHEMA": 0, "TABLE": 0}
        for p in policies:
            if p.enabled:
                scope_counts[p.scope] = scope_counts.get(p.scope, 0) + 1
        active_policy_count = sum(1 for p in policies if p.enabled)

        since = datetime.utcnow() - timedelta(hours=24)
        recent_failures = (
            session.query(JobRun)
            .filter(JobRun.status == "FAILED", JobRun.started_at >= since)
            .order_by(desc(JobRun.started_at))
            .all()
        )

        recent_runs = (
            session.query(JobRun).order_by(desc(JobRun.started_at)).limit(10).all()
        )

        warnings = []
        for run in recent_failures:
            warnings.append({
                "kind": "실패",
                "text": f"{run.policy_name} 작업이 실패했습니다"
                        + (f" ({run.error_text[:80]})" if run.error_text else "."),
            })
        for p in policies:
            if not p.enabled:
                continue
            last_run = (
                session.query(JobRun)
                .filter(JobRun.policy_id == p.id)
                .order_by(desc(JobRun.started_at))
                .first()
            )
            if last_run is None:
                warnings.append({"kind": "미실행", "text": f"{p.name} 정책이 아직 한 번도 실행되지 않았습니다."})

        return {
            "success": True,
            "dbCount": len(dbs),
            "activePolicyCount": active_policy_count,
            "scopeCounts": scope_counts,
            "failuresLast24h": len(recent_failures),
            "dbs": db_rows,
            "recentRuns": [
                {
                    "id": r.id,
                    "policyName": r.policy_name,
                    "dbName": r.db_name,
                    "status": r.status,
                    "startedAt": r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else None,
                    "durationSeconds": r.duration_seconds,
                    "dumpSizeBytes": r.dump_size_bytes,
                }
                for r in recent_runs
            ],
            "warnings": warnings[:10],
        }
    finally:
        session.close()
