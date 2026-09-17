"""backend/routes_recovery.py -- recoverability verification.

Deliberately a documented stub for this first version, same call OraVault
Backup's earlier RMAN-based prototype made ("real recovery-test execution
left as a documented stub pending architecture decisions"): actually
proving a dump file restores means running a real DBMS_DATAPUMP IMPORT
into a scratch schema/tablespace, deciding how that scratch target is
provisioned and torn down, measuring elapsed time as RTO, and handling
partial-failure states -- real design work, not a smaller version of the
export path in backend/datapump.py. Rather than pretend a "지금 검증"
click did that, this endpoint clearly says it doesn't yet.

What *is* real here: recovery_checks history storage (so the schema/API
shape is already in place) and listing it back per DB.
"""

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import desc

import registered_dbs
from backend.db import RecoveryCheck, get_session

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


@router.get("")
async def list_recovery_checks():
    session = get_session()
    try:
        dbs = registered_dbs.list_dbs_public()
        out = []
        for d in dbs:
            last = (
                session.query(RecoveryCheck)
                .filter(RecoveryCheck.db_id == d["id"])
                .order_by(desc(RecoveryCheck.checked_at))
                .first()
            )
            out.append({
                "dbId": d["id"],
                "dbName": d["name"],
                "lastCheckedAt": last.checked_at.strftime("%Y-%m-%d %H:%M") if last else None,
                "result": last.result if last else "NEVER",
                "measuredRtoSeconds": last.measured_rto_seconds if last else None,
                "note": last.note if last else None,
            })
        return {"success": True, "checks": out}
    finally:
        session.close()


@router.post("/{db_id}/run")
async def run_recovery_check(db_id: str):
    if registered_dbs.get_db(db_id) is None:
        return {"success": False, "message": "등록되지 않은 DB입니다."}
    session = get_session()
    try:
        check = RecoveryCheck(
            db_id=db_id,
            db_name=registered_dbs.get_db(db_id)["name"],
            checked_at=datetime.utcnow(),
            result="PENDING",
            note="복구 가능성 검증(실제 Import 실행)은 아직 구현되지 않았습니다. "
                 "다음 단계에서 DBMS_DATAPUMP IMPORT를 검증용 스키마로 실행하도록 구현할 예정입니다.",
        )
        session.add(check)
        session.commit()
        return {
            "success": False,
            "message": "복구 검증 실행 기능은 아직 준비 중입니다 (설계 대기 중). 이력에는 PENDING으로 기록했습니다.",
        }
    finally:
        session.close()
