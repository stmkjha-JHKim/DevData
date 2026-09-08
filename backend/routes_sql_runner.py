"""backend/routes_sql_runner.py -- Obj View/SQL tab's ad-hoc read-only SQL
Query Runner, plus its Cancel button."""

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import oracledb

from .core import Session, dict_rowfactory, format_db_value, get_oracle_connection, get_session

router = APIRouter()

# Registry of in-flight SQL Query Runner connections, keyed by a per-query
# id the client generates (crypto.randomUUID()) before firing the request.
# A normal request/response can't interrupt a query that's already blocked
# inside execute(), so the Cancel button instead reaches this exact
# connection object from a separate, concurrent /api/cancel-query request
# and calls connection.cancel() (an out-of-band break, same mechanism a
# desktop DB client's own Cancel button uses) on it. _cancelled_queries
# tracks which ids were deliberately cancelled so run_query can tell that
# apart from a genuine query error once cancel() makes execute() raise.
# Entries are removed as soon as the query finishes, however it finishes,
# so a stale id never lingers or gets confused with a later query.
_running_queries: dict[str, oracledb.AsyncConnection] = {}
_cancelled_queries: set[str] = set()


# Lets the user type an arbitrary query and see its results directly.
# Regardless of which account this connection is using, this endpoint is
# deliberately locked down to read-only, single-statement SELECTs -- a
# mistyped/pasted query in a quick ad-hoc box is exactly the kind of place
# a destructive statement slips through by accident.
@router.post("/api/run-query")
async def run_query(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    sql = str(body.get("sql") or "").strip()
    query_id = body.get("queryId") or None
    if not sql:
        return JSONResponse({"success": False, "message": "Please enter a query to run."}, status_code=400)

    if sql.endswith(";"):
        sql = sql[:-1].strip()
    if ";" in sql:
        return JSONResponse(
            {
                "success": False,
                "message": "Only a single SQL statement is allowed (remove the embedded semicolon).",
            },
            status_code=400,
        )
    if not re.match(r"(?i)^select\b", sql):
        return JSONResponse(
            {"success": False, "message": "Only SELECT statements are allowed here."}, status_code=400
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        if query_id:
            _running_queries[query_id] = connection
        cursor = connection.cursor()
        await cursor.execute(f"SELECT * FROM ({sql}) WHERE ROWNUM <= 200")
        columns = [d[0] for d in cursor.description]
        dict_rowfactory(cursor)
        raw_rows = await cursor.fetchall()
        rows = [{col: format_db_value(row[col]) for col in columns} for row in raw_rows]
        return {"success": True, "columns": columns, "rows": rows}
    except Exception as err:
        if query_id and query_id in _cancelled_queries:
            return {"success": False, "cancelled": True, "message": "Query cancelled."}
        return {"success": False, "message": f"Query failed: {err}"}
    finally:
        if query_id:
            _running_queries.pop(query_id, None)
            _cancelled_queries.discard(query_id)
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


# Cancel button next to Run: breaks a still-running /api/run-query call by
# id. Not an error if the id is no longer running (it may have just
# finished on its own) -- that's a normal race, not a failure.
@router.post("/api/cancel-query")
async def cancel_query(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    query_id = str(body.get("queryId") or "")
    connection = _running_queries.get(query_id)
    if not connection:
        return {"success": False, "message": "That query is no longer running."}

    _cancelled_queries.add(query_id)
    try:
        connection.cancel()
        return {"success": True, "message": "Cancel requested."}
    except Exception as err:
        return {"success": False, "message": f"Failed to cancel: {err}"}
