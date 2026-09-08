"""backend/routes_object_view.py -- Obj View/SQL tab's object explorer: a
small object browser (schema -> list of objects -> click one to see its
script), similar in spirit to a desktop DB client's object explorer.
/api/object-list backs the left-hand list; /api/object-ddl backs the
right-hand script viewer."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .core import Session, dict_rowfactory, get_oracle_connection, get_session

router = APIRouter()

OBJECT_TYPES_EXCLUDED = (
    "LOB", "LOB PARTITION", "TABLE PARTITION", "TABLE SUBPARTITION",
    "INDEX PARTITION", "INDEX SUBPARTITION",
)

# DBA_OBJECTS.OBJECT_TYPE -> the type name DBMS_METADATA.GET_DDL expects.
# Not every object type in DBA_OBJECTS has a DDL equivalent (e.g. LOB
# segments, which are already excluded above); anything not listed here
# is reported to the user as unsupported for scripting rather than sent to
# GET_DDL and failing with a cryptic ORA/DBMS_METADATA error.
OBJECT_DDL_TYPE_MAP = {
    "TABLE": "TABLE",
    "VIEW": "VIEW",
    "MATERIALIZED VIEW": "MATERIALIZED_VIEW",
    "PACKAGE": "PACKAGE_SPEC",
    "PACKAGE BODY": "PACKAGE_BODY",
    "PROCEDURE": "PROCEDURE",
    "FUNCTION": "FUNCTION",
    "TRIGGER": "TRIGGER",
    "TYPE": "TYPE_SPEC",
    "TYPE BODY": "TYPE_BODY",
    "SEQUENCE": "SEQUENCE",
    "INDEX": "INDEX",
    "SYNONYM": "SYNONYM",
}


@router.get("/api/object-list")
async def object_list(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    owner = (request.query_params.get("owner") or "").strip()
    if not owner:
        return JSONResponse({"success": False, "message": "An owner parameter is required."}, status_code=400)

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        excluded_binds = {f"excl{i}": t for i, t in enumerate(OBJECT_TYPES_EXCLUDED)}
        excluded_list = ", ".join(f":{k}" for k in excluded_binds)
        await cursor.execute(
            f"""SELECT object_name, object_type, status,
                       TO_CHAR(last_ddl_time, 'YYYY-MM-DD HH24:MI:SS') AS last_ddl_time
                  FROM (
                    SELECT object_name, object_type, status, last_ddl_time
                      FROM dba_objects
                     WHERE owner = :owner
                       AND object_type NOT IN ({excluded_list})
                     ORDER BY object_type ASC, object_name ASC
                  ) WHERE ROWNUM <= 3000""",
            {"owner": owner, **excluded_binds},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()

        cursor2 = connection.cursor()
        await cursor2.execute(
            f"""SELECT COUNT(*) AS cnt FROM dba_objects
                 WHERE owner = :owner AND object_type NOT IN ({excluded_list})""",
            {"owner": owner, **excluded_binds},
        )
        dict_rowfactory(cursor2)
        total_count = (await cursor2.fetchall())[0]["CNT"]

        return {
            "success": True,
            "data": rows,
            "totalCount": total_count,
            "truncated": total_count > len(rows),
        }
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


@router.get("/api/object-ddl")
async def object_ddl(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    owner = (request.query_params.get("owner") or "").strip()
    object_name = (request.query_params.get("objectName") or "").strip()
    object_type = (request.query_params.get("objectType") or "").strip().upper()
    if not owner or not object_name or not object_type:
        return JSONResponse(
            {"success": False, "message": "owner, objectName and objectType parameters are required."},
            status_code=400,
        )

    ddl_type = OBJECT_DDL_TYPE_MAP.get(object_type)
    if not ddl_type:
        return {
            "success": False,
            "message": f"Viewing the script for object type '{object_type}' is not supported.",
        }

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        # Best-effort: trims storage/tablespace/segment-attribute clauses
        # from the generated DDL so a table/index script reads like source
        # code rather than a verbose physical-storage dump. Not fatal if
        # the account can't call this (older DB, restricted privileges) --
        # GET_DDL still runs below, just with the fuller default output.
        try:
            await cursor.execute(
                """BEGIN
                     DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'STORAGE', FALSE);
                     DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'TABLESPACE', FALSE);
                     DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SEGMENT_ATTRIBUTES', FALSE);
                   END;"""
            )
        except Exception:
            pass
        await cursor.execute(
            "SELECT DBMS_METADATA.GET_DDL(:ddlType, :objectName, :owner) AS ddl FROM dual",
            {"ddlType": ddl_type, "objectName": object_name, "owner": owner},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        ddl = rows[0]["DDL"] if rows else None
        if not ddl:
            return {"success": False, "message": "No DDL was returned for this object."}
        return {"success": True, "ddl": str(ddl).strip()}
    except Exception as err:
        return {
            "success": False,
            "message": f"Failed to retrieve the script for this object. ({err})",
        }
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")
