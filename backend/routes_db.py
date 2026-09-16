"""backend/routes_db.py -- register/list/test/delete the Oracle DBs this
instance backs up. See registered_dbs.py for storage; this module is just
the HTTP surface plus the live-connection test.
"""

from fastapi import APIRouter
from pydantic import BaseModel

import registered_dbs
from backend.core import get_oracle_connection, oracle_error_message

router = APIRouter(prefix="/api/dbs", tags=["dbs"])


class RegisterDbPayload(BaseModel):
    name: str
    ip: str
    port: str
    sid: str
    connectType: str = "sid"
    account: str
    password: str


class TestConnectPayload(BaseModel):
    ip: str
    port: str
    sid: str
    connectType: str = "sid"
    account: str
    password: str


async def _test_connect(creds: dict) -> dict:
    try:
        conn = await get_oracle_connection(creds)
        await conn.close()
        return {"success": True, "message": "연결에 성공했습니다."}
    except Exception as err:
        return {"success": False, "message": oracle_error_message(err)}


@router.get("")
async def list_dbs():
    dbs = registered_dbs.list_dbs_public()
    return {"success": True, "dbs": dbs}


@router.post("/test-connect")
async def test_connect(payload: TestConnectPayload):
    return await _test_connect(payload.model_dump())


@router.post("")
async def register(payload: RegisterDbPayload):
    creds = payload.model_dump()
    result = await _test_connect(creds)
    if not result["success"]:
        return {"success": False, "message": f"연결 실패로 등록하지 않았습니다: {result['message']}"}
    try:
        record = registered_dbs.register_db(creds)
    except ValueError as err:
        return {"success": False, "message": str(err)}
    return {"success": True, "db": registered_dbs.public_view(record)}


@router.post("/{db_id}/test")
async def test_existing(db_id: str):
    record = registered_dbs.get_db(db_id)
    if record is None:
        return {"success": False, "message": "등록되지 않은 DB입니다."}
    return await _test_connect(registered_dbs.to_creds(record))


@router.delete("/{db_id}")
async def delete(db_id: str):
    registered_dbs.delete_db(db_id)
    return {"success": True}
