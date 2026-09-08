"""backend/routes_table_stats.py -- Table Statistics Collection card: the
owner list, per-table stats, single/batch DBMS_STATS.GATHER_TABLE_STATS
runs, and the "View Table Properties" detail lookup."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .core import IDENT_RE, Session, dict_rowfactory, get_oracle_connection, get_session

router = APIRouter()


# For the Table Statistics Collection card: fetches the list of users (OWNER)
@router.get("/api/table-owners")
async def table_owners(session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute("SELECT DISTINCT owner FROM dba_tables ORDER BY owner")
        rows = await cursor.fetchall()
        return {"success": True, "data": [row[0] for row in rows]}
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


# For the Table Statistics Collection card: per-table statistics for the
# selected user (OWNER)
@router.get("/api/table-stats")
async def table_stats(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    owner = (request.query_params.get("owner") or "").strip()
    if not owner:
        return JSONResponse(
            {"success": False, "message": "An owner parameter is required."}, status_code=400
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT table_name, partition_name, tablespace_name,
                      num_rows, blocks, chain_cnt, last_analyzed
                 FROM (
                 SELECT s.table_name,
                        s.partition_name,
                        COALESCE(p.tablespace_name, t.tablespace_name) AS tablespace_name,
                        s.num_rows, s.blocks, s.chain_cnt,
                        TO_CHAR(s.last_analyzed, 'YYYY-MM-DD HH24:MI:SS') AS last_analyzed
                   FROM dba_tab_statistics s
                   JOIN dba_tables t
                     ON t.owner = s.owner AND t.table_name = s.table_name
                   LEFT JOIN dba_tab_partitions p
                     ON p.table_owner = s.owner AND p.table_name = s.table_name
                    AND p.partition_name = s.partition_name
                  WHERE s.owner = :owner
                    AND s.object_type IN ('TABLE', 'PARTITION')
                  ORDER BY s.last_analyzed ASC NULLS FIRST, s.table_name ASC, s.partition_name ASC NULLS FIRST
               ) WHERE ROWNUM <= 200""",
            {"owner": owner},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()

        cursor2 = connection.cursor()
        await cursor2.execute(
            """SELECT COUNT(*) AS cnt
                 FROM dba_tab_statistics
                WHERE owner = :owner
                  AND object_type IN ('TABLE', 'PARTITION')""",
            {"owner": owner},
        )
        dict_rowfactory(cursor2)
        total_count = (await cursor2.fetchall())[0]["CNT"]

        return {"success": True, "data": rows, "totalCount": total_count, "truncated": total_count > len(rows)}
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


# Runs DBMS_STATS.GATHER_TABLE_STATS immediately for a specific table (or
# partition) selected via the long-press menu on the Table Statistics
# Collection screen.
@router.post("/api/gather-table-stats")
async def gather_table_stats(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    owner = str(body.get("owner") or "").strip()
    table_name = str(body.get("tableName") or "").strip()
    partition_name_raw = str(body.get("partitionName") or "").strip()
    partition_name = partition_name_raw or None

    if not IDENT_RE.match(owner) or not IDENT_RE.match(table_name) or (
        partition_name and not IDENT_RE.match(partition_name)
    ):
        return JSONResponse(
            {"success": False, "message": "owner/tableName/partitionName has an invalid format."},
            status_code=400,
        )

    connection = None
    try:
        connection = await get_oracle_connection(creds)
        cursor = connection.cursor()
        await cursor.execute(
            """BEGIN
                 DBMS_STATS.GATHER_TABLE_STATS(
                   ownname          => :owner,
                   tabname          => :tableName,
                   partname         => :partitionName,
                   estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
                   cascade          => TRUE,
                   degree           => DBMS_STATS.AUTO_DEGREE
                 );
               END;""",
            {"owner": owner, "tableName": table_name, "partitionName": partition_name},
        )
        await connection.commit()

        target = f"{owner}.{table_name} (partition {partition_name})" if partition_name else f"{owner}.{table_name}"
        return {"success": True, "message": f"Statistics collection completed for {target}."}
    except Exception as err:
        return {
            "success": False,
            "message": f"Statistics collection failed. ANALYZE ANY DICTIONARY or the relevant schema privilege is required. ({err})",
        }
    finally:
        if connection:
            try:
                await connection.close()
            except Exception as close_err:
                print(f"Error while closing connection: {close_err}")


# Runs DBMS_STATS.GATHER_TABLE_STATS for several tables/partitions at once,
# selected via checkboxes on the Table Statistics Collection screen. Reuses
# a single connection for the whole batch (rather than one connection per
# item) and keeps going even if an individual item fails, so one bad table
# doesn't block the rest of the batch. Capped at 200 items per request to
# match the table list's own page size.
@router.post("/api/gather-table-stats-batch")
async def gather_table_stats_batch(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    body = await request.json()
    owner = str(body.get("owner") or "").strip()
    items = body.get("items") if isinstance(body.get("items"), list) else []

    if not IDENT_RE.match(owner):
        return JSONResponse({"success": False, "message": "owner has an invalid format."}, status_code=400)
    if not items:
        return JSONResponse(
            {"success": False, "message": "At least one table must be selected."}, status_code=400
        )
    if len(items) > 200:
        return JSONResponse(
            {"success": False, "message": "A maximum of 200 tables can be gathered in a single batch."},
            status_code=400,
        )

    normalized_items = []
    for item in items:
        table_name = str((item or {}).get("tableName") or "").strip()
        partition_name_raw = str((item or {}).get("partitionName") or "").strip()
        partition_name = partition_name_raw or None
        if not IDENT_RE.match(table_name) or (partition_name and not IDENT_RE.match(partition_name)):
            return JSONResponse(
                {
                    "success": False,
                    "message": f"tableName/partitionName has an invalid format: {table_name or '(empty)'}",
                },
                status_code=400,
            )
        normalized_items.append((table_name, partition_name))

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return {"success": False, "message": f"Failed to connect to the DB: {err}"}

    results = []
    for table_name, partition_name in normalized_items:
        target = f"{owner}.{table_name} (partition {partition_name})" if partition_name else f"{owner}.{table_name}"
        try:
            cursor = connection.cursor()
            await cursor.execute(
                """BEGIN
                     DBMS_STATS.GATHER_TABLE_STATS(
                       ownname          => :owner,
                       tabname          => :tableName,
                       partname         => :partitionName,
                       estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
                       cascade          => TRUE,
                       degree           => DBMS_STATS.AUTO_DEGREE
                     );
                   END;""",
                {"owner": owner, "tableName": table_name, "partitionName": partition_name},
            )
            await connection.commit()
            results.append({"tableName": table_name, "partitionName": partition_name, "ok": True, "message": f"Completed for {target}."})
        except Exception as err:
            results.append({"tableName": table_name, "partitionName": partition_name, "ok": False, "message": f"Failed for {target}: {err}"})

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    succeeded = sum(1 for r in results if r["ok"])
    return {
        "success": True,
        "results": results,
        "summary": {"total": len(results), "succeeded": succeeded, "failed": len(results) - succeeded},
    }


# Backs the "View Table Properties" item in the Table Statistics Collection
# screen's right-click menu: basic table attributes plus its column and
# index lists. Each of the three sections is queried and reported
# independently (ok/message per section, matching the Ops tab's cards) so
# that e.g. missing DBA_INDEXES access doesn't blank out the columns list.
@router.get("/api/table-properties")
async def table_properties(request: Request, session: Session = Depends(get_session)):
    creds = session.get("db_creds")
    if not creds:
        return JSONResponse({"success": False, "message": "Login required."}, status_code=401)

    owner = (request.query_params.get("owner") or "").strip()
    table_name = (request.query_params.get("tableName") or "").strip()
    if not owner or not table_name:
        return JSONResponse(
            {"success": False, "message": "owner and tableName parameters are required."}, status_code=400
        )

    try:
        connection = await get_oracle_connection(creds)
    except Exception as err:
        return {"success": False, "message": f"Failed to connect to the DB: {err}"}

    result = {"success": True, "basic": None, "columns": None, "indexes": None}

    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT owner, table_name, tablespace_name, partitioned, num_rows, blocks,
                      avg_row_len, logging, compression, degree,
                      TO_CHAR(last_analyzed, 'YYYY-MM-DD HH24:MI:SS') AS last_analyzed
                 FROM dba_tables
                WHERE owner = :owner AND table_name = :tableName""",
            {"owner": owner, "tableName": table_name},
        )
        dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        result["basic"] = {"ok": True, "data": rows[0] if rows else None}
    except Exception as err:
        result["basic"] = {"ok": False, "message": f"Failed to load basic table info: {err}"}

    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT column_name, data_type, data_length, data_precision, data_scale,
                      nullable, column_id
                 FROM dba_tab_columns
                WHERE owner = :owner AND table_name = :tableName
                ORDER BY column_id ASC""",
            {"owner": owner, "tableName": table_name},
        )
        dict_rowfactory(cursor)
        result["columns"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["columns"] = {"ok": False, "message": f"Failed to load column list: {err}"}

    try:
        cursor = connection.cursor()
        await cursor.execute(
            """SELECT i.index_name, i.uniqueness, i.status,
                      LISTAGG(ic.column_name, ', ') WITHIN GROUP (ORDER BY ic.column_position) AS columns
                 FROM dba_indexes i
                 JOIN dba_ind_columns ic
                   ON ic.index_owner = i.owner AND ic.index_name = i.index_name
                WHERE i.table_owner = :owner AND i.table_name = :tableName
                GROUP BY i.index_name, i.uniqueness, i.status
                ORDER BY i.index_name ASC""",
            {"owner": owner, "tableName": table_name},
        )
        dict_rowfactory(cursor)
        result["indexes"] = {"ok": True, "data": await cursor.fetchall()}
    except Exception as err:
        result["indexes"] = {"ok": False, "message": f"Failed to load index list: {err}"}

    try:
        await connection.close()
    except Exception as close_err:
        print(f"Error while closing connection: {close_err}")

    return result
