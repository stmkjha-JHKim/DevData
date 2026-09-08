"""report.py -- Weekly DB Health Report feature for OraPulse (Python port
of report.js). See report.js's own top-of-file comment for the full
rationale; condensed here:

A real AWR report needs the Oracle Diagnostics Pack license, which this
app deliberately doesn't assume the connecting instance has. Most of what
a "last N days" report needs (CPU/memory %, session counts, Top SQL,
instance efficiency, TEMP/FRA usage) comes from v$ views that only expose
the *current* value, with no history behind them -- so this module takes
its own lightweight snapshot on a timer and appends it to a plain
JSON-lines file on disk (data/snapshot-history.jsonl): a tiny, license-
free, dependency-free stand-in for an AWR repository.

The one exception is the Alert Log: v$diag_alert_ext already holds its
own history, so the report's Alert Log section queries that view live for
the requested window instead.

The collector is a plain asyncio background task started from main.py's
lifespan -- there is no OS-level scheduler, so it only collects while the
server process is running. Restarting the process does not lose
already-collected history (it's a plain file on disk), but nothing is
collected while the process is down. Disconnecting from the dashboard UI
does NOT stop collection either (see main.py's last_connected_creds
comment) -- only closing the browser (or exiting the app) does.

Deliberately self-contained (own encryption, own DB connection, own SQL)
rather than importing from main.py, matching report.js's own reasoning:
this module could be dropped into another project unchanged.
"""

import asyncio
import base64
import json
import os
import random
import secrets
import string
import time
from datetime import datetime
from typing import Optional

import oracledb
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paths import DATA_DIR

SNAPSHOT_FILE = DATA_DIR / "snapshot-history.jsonl"
KEY_FILE = DATA_DIR / ".snapshot-key"

SNAPSHOT_INTERVAL_SECONDS = 15 * 60  # 15 minutes
RETENTION_SECONDS = 7 * 24 * 60 * 60  # 7 days -- matches the report's own window


def build_connect_string(ip, port, sid) -> str:
    return (
        f"(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={ip})(PORT={port}))"
        f"(CONNECT_DATA=(SID={sid})))"
    )


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- Encryption (same AES-256-GCM wire format as favorites.py / favorites.js) ---
_cached_key: Optional[bytes] = None


def _get_encryption_key() -> bytes:
    global _cached_key
    if _cached_key is not None:
        return _cached_key
    _ensure_data_dir()
    if KEY_FILE.exists():
        _cached_key = bytes.fromhex(KEY_FILE.read_text().strip())
    else:
        _cached_key = secrets.token_bytes(32)
        KEY_FILE.write_text(_cached_key.hex())
        try:
            os.chmod(KEY_FILE, 0o600)
        except OSError:
            pass
    return _cached_key


def encrypt_target(target: dict) -> str:
    iv = secrets.token_bytes(12)
    combined = AESGCM(_get_encryption_key()).encrypt(iv, json.dumps(target).encode("utf-8"), None)
    ciphertext, tag = combined[:-16], combined[-16:]
    return base64.b64encode(iv + tag + ciphertext).decode("ascii")


def decrypt_target(value) -> Optional[dict]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        raw = base64.b64decode(value)
        iv, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
        plaintext = AESGCM(_get_encryption_key()).decrypt(iv, ciphertext + tag, None)
        return json.loads(plaintext.decode("utf-8"))
    except Exception:
        return None


def _migrate_legacy_targets() -> None:
    all_snaps = _read_all_snapshots()
    changed = False
    for s in all_snaps:
        if isinstance(s.get("target"), dict):
            s["target"] = encrypt_target(s["target"])
            changed = True
    if not changed:
        return
    _ensure_data_dir()
    body = "\n".join(json.dumps(s) for s in all_snaps)
    if all_snaps:
        body += "\n"
    SNAPSHOT_FILE.write_text(body, encoding="utf-8")


def _read_all_snapshots() -> list:
    _ensure_data_dir()
    if not SNAPSHOT_FILE.exists():
        return []
    raw = SNAPSHOT_FILE.read_text(encoding="utf-8")
    out = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            pass  # a partial/corrupted line (process killed mid-write) is skipped
    return out


def read_snapshots(days: int, target: Optional[dict] = None) -> list:
    cutoff = time.time() * 1000 - days * 24 * 60 * 60 * 1000
    rows = [s for s in _read_all_snapshots() if s.get("ts", 0) >= cutoff]
    if target:
        def matches(s):
            t = decrypt_target(s.get("target"))
            return (
                bool(t)
                and t.get("ip") == target["ip"]
                and str(t.get("port")) == str(target["port"])
                and t.get("sid") == target["sid"]
            )
        rows = [s for s in rows if matches(s)]
    rows.sort(key=lambda s: s.get("ts", 0))
    return rows


def _persist_snapshot(snapshot: dict) -> None:
    _ensure_data_dir()
    cutoff = time.time() * 1000 - RETENTION_SECONDS * 1000
    kept = [s for s in _read_all_snapshots() if s.get("ts", 0) >= cutoff]
    kept.append(snapshot)
    body = "\n".join(json.dumps(s) for s in kept) + "\n"
    SNAPSHOT_FILE.write_text(body, encoding="utf-8")


def _dict_rowfactory(cursor) -> None:
    columns = [d[0] for d in cursor.description]
    cursor.rowfactory = lambda *args: dict(zip(columns, args))


async def _run(connection, sql, map_row, binds=None):
    try:
        cursor = connection.cursor()
        await cursor.execute(sql, binds or {})
        _dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        return map_row(rows)
    except Exception as err:
        return {"ok": False, "message": str(err)}


def _num(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _map_memory(rows):
    d = rows[0] if rows else {}
    sga_mb = _num(d.get("SGA_MB"), 0)
    pga_mb = _num(d.get("PGA_MB"), 0)
    used_mb = sga_mb + pga_mb
    memory_target_mb = _num(d.get("MEMORY_TARGET_MB"), 0)
    memory_max_target_mb = _num(d.get("MEMORY_MAX_TARGET_MB"), 0)
    if memory_target_mb > 0:
        target_mb = memory_target_mb
    elif memory_max_target_mb > 0:
        target_mb = memory_max_target_mb
    else:
        target_mb = _num(d.get("SGA_MAX_MB"), 0) + _num(d.get("PGA_TARGET_MB"), 0)
    pct = round((used_mb / target_mb) * 1000) / 10 if target_mb > 0 else None
    return {
        "ok": True,
        "data": {
            "usedMb": round(used_mb * 10) / 10,
            "targetMb": target_mb if target_mb > 0 else None,
            "pct": pct,
        },
    }


# Opens its own short-lived connection (same pattern as every endpoint in
# main.py) and gathers a compact snapshot -- enough to redraw the Main
# tab's core numbers, the Ops tab's cards, and Temp/Recovery usage as a
# trend later. Never raises -- a failed section is recorded as
# {"ok": False, "message": ...}; a failed connection just skips the whole
# snapshot (logged, not raised) so one bad tick doesn't stop the collector.
async def gather_snapshot(creds: dict) -> Optional[dict]:
    connect_string = build_connect_string(creds["ip"], creds["port"], creds["sid"])
    try:
        connection = await oracledb.connect_async(
            user=creds["account"], password=creds["password"], dsn=connect_string
        )
    except Exception as err:
        print(f"[report] snapshot skipped -- could not connect: {err}")
        return None

    snapshot = {
        "ts": time.time() * 1000,
        "iso": datetime.utcnow().isoformat() + "Z",
        "target": encrypt_target({"ip": creds["ip"], "port": creds["port"], "sid": creds["sid"]}),
        "main": {},
        "ops": {},
        "usage": {},
    }

    snapshot["main"]["instance"] = await _run(
        connection,
        "SELECT instance_name, host_name, version FROM v$instance",
        lambda rows: {"ok": True, "data": rows[0]} if rows else {"ok": False, "message": "No results found."},
    )

    snapshot["main"]["cpuPct"] = await _run(
        connection,
        """SELECT value FROM (
             SELECT value FROM v$sysmetric WHERE metric_name = 'Host CPU Utilization (%)' ORDER BY end_time DESC
           ) WHERE ROWNUM = 1""",
        lambda rows: {"ok": True, "data": _num(rows[0]["VALUE"])} if rows else {"ok": False, "message": "No results found."},
    )

    snapshot["main"]["memory"] = await _run(
        connection,
        """SELECT
             ROUND((SELECT SUM(value) FROM v$sga) / 1024 / 1024, 1) AS sga_mb,
             ROUND((SELECT value FROM v$pgastat WHERE name = 'total PGA allocated') / 1024 / 1024, 1) AS pga_mb,
             ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_target'), 0) / 1024 / 1024, 1) AS memory_target_mb,
             ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_max_target'), 0) / 1024 / 1024, 1) AS memory_max_target_mb,
             ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'sga_max_size'), 0) / 1024 / 1024, 1) AS sga_max_mb,
             ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'pga_aggregate_target'), 0) / 1024 / 1024, 1) AS pga_target_mb
           FROM dual""",
        _map_memory,
    )

    snapshot["main"]["sessionCount"] = await _run(
        connection,
        "SELECT COUNT(*) AS cnt FROM v$session WHERE type = 'USER'",
        lambda rows: {"ok": True, "data": int(rows[0]["CNT"])},
    )

    snapshot["main"]["invalidObjectsCount"] = await _run(
        connection,
        "SELECT COUNT(*) AS cnt FROM dba_objects WHERE status = 'INVALID'",
        lambda rows: {"ok": True, "data": int(rows[0]["CNT"])},
    )

    snapshot["main"]["topWaitEvents"] = await _run(
        connection,
        """SELECT event, time_waited FROM (
             SELECT event, time_waited FROM v$system_event WHERE wait_class != 'Idle' ORDER BY time_waited DESC
           ) WHERE ROWNUM <= 3""",
        lambda rows: {"ok": True, "data": rows},
    )

    snapshot["ops"]["topQueries"] = await _run(
        connection,
        """SELECT sql_id, ROUND(elapsed_time / 1000000, 3) AS elapsed_sec FROM (
             SELECT sql_id, elapsed_time FROM v$sql WHERE elapsed_time > 0 ORDER BY elapsed_time DESC
           ) WHERE ROWNUM <= 3""",
        lambda rows: {"ok": True, "data": rows},
    )

    snapshot["ops"]["topQueriesCpu"] = await _run(
        connection,
        """SELECT sql_id, ROUND(cpu_time / 1000000, 3) AS cpu_sec FROM (
             SELECT sql_id, cpu_time FROM v$sql WHERE cpu_time > 0 ORDER BY cpu_time DESC
           ) WHERE ROWNUM <= 3""",
        lambda rows: {"ok": True, "data": rows},
    )

    snapshot["ops"]["topQueriesBufferGets"] = await _run(
        connection,
        """SELECT sql_id, buffer_gets FROM (
             SELECT sql_id, buffer_gets FROM v$sql WHERE buffer_gets > 0 ORDER BY buffer_gets DESC
           ) WHERE ROWNUM <= 3""",
        lambda rows: {"ok": True, "data": rows},
    )

    snapshot["ops"]["instanceEfficiency"] = await _run(
        connection,
        """SELECT
             ROUND((1 - ((SELECT value FROM v$sysstat WHERE name = 'physical reads') /
                         NULLIF((SELECT value FROM v$sysstat WHERE name = 'db block gets') +
                                (SELECT value FROM v$sysstat WHERE name = 'consistent gets'), 0))) * 100, 2)
               AS buffer_hit_ratio,
             ROUND((1 - ((SELECT SUM(reloads) FROM v$librarycache) /
                         NULLIF((SELECT SUM(pins) FROM v$librarycache), 0))) * 100, 2)
               AS library_hit_ratio,
             ROUND((1 - ((SELECT value FROM v$sysstat WHERE name = 'parse count (hard)') /
                         NULLIF((SELECT value FROM v$sysstat WHERE name = 'parse count (total)'), 0))) * 100, 2)
               AS soft_parse_pct,
             ROUND((1 - ((SELECT value FROM v$sysstat WHERE name = 'parse count (total)') /
                         NULLIF((SELECT value FROM v$sysstat WHERE name = 'execute count'), 0))) * 100, 2)
               AS execute_to_parse_pct
           FROM dual""",
        lambda rows: {"ok": True, "data": rows[0] if rows else {}},
    )

    snapshot["ops"]["loadProfile"] = await _run(
        connection,
        """SELECT ROUND(redo_size / NULLIF(uptime_seconds, 0), 2) AS redo_size_per_sec,
                  ROUND(logical_reads / NULLIF(uptime_seconds, 0), 2) AS logical_reads_per_sec,
                  ROUND(physical_reads / NULLIF(uptime_seconds, 0), 2) AS physical_reads_per_sec,
                  ROUND(user_calls / NULLIF(uptime_seconds, 0), 2) AS user_calls_per_sec,
                  ROUND(executes / NULLIF(uptime_seconds, 0), 2) AS executes_per_sec,
                  ROUND((user_commits + user_rollbacks) / NULLIF(uptime_seconds, 0), 2) AS transactions_per_sec
             FROM (
                    SELECT
                      (SELECT value FROM v$sysstat WHERE name = 'redo size') AS redo_size,
                      (SELECT value FROM v$sysstat WHERE name = 'session logical reads') AS logical_reads,
                      (SELECT value FROM v$sysstat WHERE name = 'physical reads') AS physical_reads,
                      (SELECT value FROM v$sysstat WHERE name = 'user calls') AS user_calls,
                      (SELECT value FROM v$sysstat WHERE name = 'execute count') AS executes,
                      (SELECT value FROM v$sysstat WHERE name = 'user commits') AS user_commits,
                      (SELECT value FROM v$sysstat WHERE name = 'user rollbacks') AS user_rollbacks,
                      ROUND((SYSDATE - i.startup_time) * 86400) AS uptime_seconds
                    FROM v$instance i
                  )""",
        lambda rows: {"ok": True, "data": rows[0] if rows else {}},
    )

    snapshot["usage"]["temp"] = await _run(
        connection,
        """SELECT tablespace_name, ROUND(SUM(bytes_used) / SUM(bytes_used + bytes_free) * 100, 2) AS used_pct
             FROM v$temp_space_header
            GROUP BY tablespace_name""",
        lambda rows: {"ok": True, "data": rows},
    )

    snapshot["usage"]["recovery"] = await _run(
        connection,
        """SELECT ROUND((space_used - space_reclaimable) / NULLIF(space_limit, 0) * 100, 2) AS used_pct_net
             FROM v$recovery_file_dest""",
        lambda rows: {"ok": True, "data": rows},
    )

    snapshot["ops"]["tablespaceIo"] = await _run(
        connection,
        """SELECT tablespace_name, physical_reads, physical_writes FROM (
             SELECT ts.name AS tablespace_name,
                    SUM(fs.phyrds) AS physical_reads,
                    SUM(fs.phywrts) AS physical_writes
               FROM v$filestat fs
               JOIN v$datafile df ON fs.file# = df.file#
               JOIN v$tablespace ts ON df.ts# = ts.ts#
              GROUP BY ts.name
              ORDER BY SUM(fs.phyrds + fs.phywrts) DESC
           ) WHERE ROWNUM <= 10""",
        lambda rows: {"ok": True, "data": rows},
    )

    try:
        await connection.close()
    except Exception as close_err:
        print(f"[report] error while closing snapshot connection: {close_err}")

    _persist_snapshot(snapshot)
    return snapshot


async def _collector_loop(get_creds) -> None:
    try:
        _migrate_legacy_targets()
    except Exception as err:
        print(f"[report] legacy target migration failed: {err}")
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
        creds = get_creds()
        if not creds:
            continue  # Nothing has ever connected yet -- nothing to snapshot.
        try:
            await gather_snapshot(creds)
        except Exception as err:
            print(f"[report] snapshot collection failed: {err}")


# Starts the recurring background collector. `get_creds` is a callable
# (rather than a fixed value) because the credentials it should use change
# every time someone connects -- main.py passes `lambda: last_connected_creds`
# so this always picks up the most recent connection without needing to be
# restarted. Must be called from a running asyncio event loop (main.py's
# lifespan startup).
def start_collector(get_creds) -> None:
    asyncio.create_task(_collector_loop(get_creds))


# Fire-and-forget: called right after a successful /api/connect so the
# history starts filling in immediately rather than waiting up to 15
# minutes for the first tick.
def trigger_immediate_collection(creds: dict) -> None:
    async def _run_once():
        try:
            await gather_snapshot(creds)
        except Exception as err:
            print(f"[report] initial snapshot failed: {err}")

    asyncio.create_task(_run_once())


# Queries v$diag_alert_ext directly for the requested window -- unlike
# everything else in this file, the alert log already has its own history
# built in. Mirrors the exact filtering logic used by /api/alert-log in
# main.py (see the comment there for why "ORA-0"/"ORA-30" are excluded).
async def fetch_alert_summary(creds: dict, days: int) -> dict:
    connect_string = build_connect_string(creds["ip"], creds["port"], creds["sid"])
    try:
        connection = await oracledb.connect_async(
            user=creds["account"], password=creds["password"], dsn=connect_string
        )
    except Exception as err:
        return {"ok": False, "message": f"Failed to connect to the DB: {err}"}

    where_clause = """
        WHERE originating_timestamp > SYSDATE - :days
          AND (message_text LIKE '%ORA-%' OR message_type IN (2, 3))
          AND (REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') IS NULL
               OR REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') NOT IN ('ORA-0', 'ORA-30'))
    """

    try:
        cursor = connection.cursor()
        await cursor.execute(f"SELECT COUNT(*) AS cnt FROM v$diag_alert_ext {where_clause}", {"days": days})
        _dict_rowfactory(cursor)
        total_count = (await cursor.fetchall())[0]["CNT"]

        cursor = connection.cursor()
        await cursor.execute(
            f"""SELECT ora_code, COUNT(*) AS cnt FROM (
                 SELECT REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') AS ora_code
                   FROM v$diag_alert_ext {where_clause}
               )
               WHERE ora_code IS NOT NULL
               GROUP BY ora_code
               ORDER BY COUNT(*) DESC
               FETCH FIRST 10 ROWS ONLY""",
            {"days": days},
        )
        _dict_rowfactory(cursor)
        by_code = await cursor.fetchall()

        cursor = connection.cursor()
        await cursor.execute(
            f"""SELECT log_time, ora_code, message_text FROM (
                 SELECT TO_CHAR(originating_timestamp, 'YYYY-MM-DD HH24:MI:SS') AS log_time,
                        REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') AS ora_code,
                        message_text
                   FROM v$diag_alert_ext {where_clause}
                  ORDER BY originating_timestamp DESC
               ) WHERE ROWNUM <= 15""",
            {"days": days},
        )
        _dict_rowfactory(cursor)
        recent = await cursor.fetchall()

        return {"ok": True, "totalCount": total_count, "byCode": by_code, "recent": recent}
    except Exception as err:
        return {
            "ok": False,
            "message": (
                "You do not have permission to view this. Access to V$DIAG_ALERT_EXT is required "
                f"(typically granted via SELECT_CATALOG_ROLE or the SELECT ANY DICTIONARY privilege). ({err})"
            ),
        }
    finally:
        try:
            await connection.close()
        except Exception as close_err:
            print(f"[report] error while closing alert-summary connection: {close_err}")


# ---------------------------------------------------------------------
# HTML report rendering. Self-contained (inline CSS, hand-drawn inline SVG
# charts -- no external CDN/font/script dependency), styled to match the
# dashboard's own dark color palette.
# ---------------------------------------------------------------------

REPORT_I18N = {
    "en": {
        "title": "OraPulse Weekly DB Health Report",
        "periodLabel": "Report Period", "generatedLabel": "Generated At", "dataPointsLabel": "Data Points Collected",
        "partialDataNote": lambda from_str, days: (
            f"Note: local snapshot collection for this DB only goes back to {from_str} so far -- the trend "
            f"sections below cover less than the full {days}-day window until more history accumulates."
        ),
        "sectionGlance": "At a Glance (Latest Snapshot)",
        "statCpu": "CPU Utilization", "statMemory": "Memory Usage", "statSessions": "Active Sessions", "statInvalid": "Invalid Objects",
        "sectionTrend": "7-Day Trend",
        "chartCpu": "CPU Utilization (%)", "chartMemory": "Memory Usage (%)", "chartSessions": "Active Sessions", "chartInvalid": "Invalid Objects",
        "sectionEfficiency": "Instance Efficiency (%)",
        "effBuffer": "Buffer Cache Hit Ratio", "effLibrary": "Library Cache Hit Ratio", "effSoftParse": "Soft Parse %", "effExecParse": "Execute to Parse %",
        "sectionLoadProfile": "Load Profile (per second, since instance startup)",
        "lpRedo": "Redo Size/sec", "lpLogical": "Logical Reads/sec", "lpPhysical": "Physical Reads/sec",
        "lpUserCalls": "User Calls/sec", "lpExecutes": "Executes/sec", "lpTx": "Transactions/sec",
        "sectionTopSql": "Top SQL (Latest Snapshot)",
        "topSqlElapsed": "By Elapsed Time", "topSqlCpu": "By CPU Time", "topSqlGets": "By Buffer Gets",
        "colSqlId": "SQL_ID", "colElapsedSec": "Elapsed (sec)", "colCpuSec": "CPU (sec)", "colBufferGets": "Buffer Gets",
        "sectionUsage": "Storage Usage Trend",
        "chartTemp": "TEMP Tablespace Usage -- Worst Tablespace (%)", "chartRecovery": "Fast Recovery Area Usage, Net of Reclaimable (%)",
        "sectionTablespaceIo": "Tablespace I/O (Latest Snapshot)",
        "colTablespace": "Tablespace", "colReads": "Physical Reads", "colWrites": "Physical Writes",
        "sectionAlertLog": "Alert Log Summary",
        "alertTotal": "Noteworthy entries in period", "alertByCode": "Most Frequent ORA Codes", "alertRecent": "Most Recent Entries",
        "colOraCode": "ORA Code", "colCount": "Count", "colTime": "Time", "colMessage": "Message",
        "noData": "No data available.",
        "footerNote": "Generated by OraPulse. Trend data comes from locally collected snapshots (~15-minute interval); this is not an Oracle AWR/Diagnostics Pack report.",
    },
    "ko": {
        "title": "OraPulse 주간 DB 상태 리포트",
        "periodLabel": "리포트 기간", "generatedLabel": "생성 시각", "dataPointsLabel": "수집된 데이터 포인트",
        "partialDataNote": lambda from_str, days: (
            f"참고: 이 DB에 대한 로컬 스냅샷 수집이 아직 {from_str}부터만 쌓여 있어, 데이터가 더 쌓이기 전까지는 "
            f"아래 추이 항목들이 전체 {days}일 구간을 다 채우지 못합니다."
        ),
        "sectionGlance": "한눈에 보기 (최신 스냅샷 기준)",
        "statCpu": "CPU 사용률", "statMemory": "메모리 사용률", "statSessions": "활성 세션 수", "statInvalid": "Invalid 객체 수",
        "sectionTrend": "최근 7일 추이",
        "chartCpu": "CPU 사용률 (%)", "chartMemory": "메모리 사용률 (%)", "chartSessions": "활성 세션 수", "chartInvalid": "Invalid 객체 수",
        "sectionEfficiency": "인스턴스 효율 (%)",
        "effBuffer": "버퍼 캐시 히트율", "effLibrary": "라이브러리 캐시 히트율", "effSoftParse": "소프트 파스 비율", "effExecParse": "실행 대비 파스 비율",
        "sectionLoadProfile": "Load Profile (초당, 인스턴스 시작 이후 누적 평균)",
        "lpRedo": "Redo Size/초", "lpLogical": "Logical Reads/초", "lpPhysical": "Physical Reads/초",
        "lpUserCalls": "User Calls/초", "lpExecutes": "Executes/초", "lpTx": "Transactions/초",
        "sectionTopSql": "Top SQL (최신 스냅샷 기준)",
        "topSqlElapsed": "실행시간 기준", "topSqlCpu": "CPU 시간 기준", "topSqlGets": "Buffer Gets 기준",
        "colSqlId": "SQL_ID", "colElapsedSec": "실행시간(초)", "colCpuSec": "CPU(초)", "colBufferGets": "Buffer Gets",
        "sectionUsage": "스토리지 사용률 추이",
        "chartTemp": "TEMP 테이블스페이스 사용률 -- 최고치 기준 (%)", "chartRecovery": "FRA(Fast Recovery Area) 순사용률 (%)",
        "sectionTablespaceIo": "테이블스페이스 I/O (최신 스냅샷 기준)",
        "colTablespace": "테이블스페이스", "colReads": "Physical Reads", "colWrites": "Physical Writes",
        "sectionAlertLog": "Alert Log 요약",
        "alertTotal": "기간 내 주요 항목 수", "alertByCode": "가장 빈번한 ORA 코드", "alertRecent": "최근 항목",
        "colOraCode": "ORA 코드", "colCount": "건수", "colTime": "시각", "colMessage": "메시지",
        "noData": "데이터가 없습니다.",
        "footerNote": "OraPulse가 생성한 리포트입니다. 추이 데이터는 로컬에서 수집한 스냅샷(약 15분 간격) 기준이며, Oracle AWR/Diagnostics Pack 리포트가 아닙니다.",
    },
}


def escape_html(s) -> str:
    if s is None:
        s = ""
    s = str(s)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def fmt_num(v, digits: Optional[int] = 2) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v != v:  # NaN
        return "-"
    d = 2 if digits is None else digits
    s = f"{v:,.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_date_time(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M")


def fmt_date_short(ts_ms) -> str:
    d = datetime.fromtimestamp(ts_ms / 1000)
    return f"{d.month}/{d.day:02d} {d.hour:02d}:{d.minute:02d}"


# High-is-bad thresholds (CPU/memory/usage-%): matches the dashboard's own
# pctClass() helper (90/75).
def badge_class_high_bad(pct) -> str:
    if pct is None:
        return ""
    if pct >= 90:
        return "danger"
    if pct >= 75:
        return "warn"
    return "ok"


# High-is-good thresholds (hit ratios / efficiency %) -- inverted from the above.
def badge_class_high_good(pct) -> str:
    if pct is None:
        return ""
    if pct < 75:
        return "danger"
    if pct < 90:
        return "warn"
    return "ok"


def badge(pct, cls: str) -> str:
    if pct is None:
        return '<span class="badge">-</span>'
    return f'<span class="badge {cls}">{fmt_num(pct, 1)}%</span>'


# Hand-rolled inline line/area chart -- no charting library, so the report
# stays a single self-contained file. `points`: [{"ts", "value"}] in
# chronological order; a None value renders as a gap in the line rather
# than a drop to zero.
def line_chart_svg(points: list, opts: Optional[dict] = None) -> str:
    opts = opts or {}
    width = opts.get("width", 620)
    height = opts.get("height", 160)
    pad_l, pad_r, pad_t, pad_b = 42, 14, 14, 26
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    color = opts.get("color", "#4f7cff")
    unit = opts.get("unit", "")

    valid = [p for p in points if isinstance(p.get("value"), (int, float)) and p["value"] == p["value"]]
    if len(valid) < 2:
        return (
            f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img">'
            f'<rect x="0" y="0" width="{width}" height="{height}" rx="8" fill="#111a30" />'
            f'<text x="{width / 2}" y="{height / 2}" text-anchor="middle" fill="#8b96b3" font-size="13">'
            f"Not enough data yet</text></svg>"
        )

    xs = [p["ts"] for p in points]
    min_x, max_x = min(xs), max(xs)
    vs = [p["value"] for p in valid]
    min_y = opts["minY"] if opts.get("minY") is not None else min(vs)
    max_y = opts["maxY"] if opts.get("maxY") is not None else max(vs)
    if min_y == max_y:
        min_y -= 1
        max_y += 1
    y_pad = (max_y - min_y) * 0.15
    min_y -= y_pad
    max_y += y_pad
    if opts.get("forceMinZero"):
        min_y = min(min_y, 0)
    if opts.get("maxY") is None and opts.get("capMax") is not None:
        max_y = min(max_y, opts["capMax"])

    def x_scale(ts):
        return pad_l + ((ts - min_x) / (max_x - min_x or 1)) * plot_w

    def y_scale(v):
        clamped = max(min_y, min(max_y, v))
        return pad_t + plot_h - ((clamped - min_y) / (max_y - min_y or 1)) * plot_h

    segments = []
    cur = []
    for p in points:
        v = p.get("value")
        if isinstance(v, (int, float)) and v == v:
            cur.append((x_scale(p["ts"]), y_scale(v)))
        elif cur:
            segments.append(cur)
            cur = []
    if cur:
        segments.append(cur)

    grad_id = "grad-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=7))
    base_y = f"{pad_t + plot_h:.1f}"
    lines_svg = "".join(
        '<polyline points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in seg) +
        f'" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />'
        for seg in segments
    )
    areas_svg = "".join(
        '<polygon points="' + f"{seg[0][0]:.1f},{base_y} " +
        " ".join(f"{x:.1f},{y:.1f}" for x, y in seg) +
        f' {seg[-1][0]:.1f},{base_y}" fill="url(#{grad_id})" opacity="0.35" />'
        for seg in segments
    )

    grid_lines = ""
    for t in (0, 0.5, 1):
        y = pad_t + plot_h * t
        val = max_y - (max_y - min_y) * t
        grid_lines += (
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" stroke="#26314d" '
            f'stroke-width="1" stroke-dasharray="3,3" />'
            f'<text x="{pad_l - 6}" y="{y + 3:.1f}" text-anchor="end" font-size="10" fill="#8b96b3">'
            f"{fmt_num(val, 0)}{unit}</text>"
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img">'
        f"<defs><linearGradient id=\"{grad_id}\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">"
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.55" />'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0" /></linearGradient></defs>'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="8" fill="#111a30" />'
        f"{grid_lines}{areas_svg}{lines_svg}"
        f'<text x="{pad_l}" y="{height - 6}" font-size="10" fill="#8b96b3">{escape_html(fmt_date_short(min_x))}</text>'
        f'<text x="{width - pad_r}" y="{height - 6}" text-anchor="end" font-size="10" fill="#8b96b3">'
        f"{escape_html(fmt_date_short(max_x))}</text></svg>"
    )


def chart_card(title: str, points: list, opts: dict) -> str:
    vals = [p["value"] for p in points if isinstance(p.get("value"), (int, float)) and p["value"] == p["value"]]
    latest = vals[-1] if vals else None
    lo = min(vals) if vals else None
    hi = max(vals) if vals else None
    unit = opts.get("unit", "")
    stats_line = (
        f"latest {fmt_num(latest, 1)}{unit} &middot; min {fmt_num(lo, 1)}{unit} &middot; max {fmt_num(hi, 1)}{unit}"
        if vals else ""
    )
    return (
        f'<div class="chart-card"><div class="chart-title"><span>{escape_html(title)}</span>'
        f'<span class="chart-stats">{stats_line}</span></div>{line_chart_svg(points, opts)}</div>'
    )


def table_or_empty(rows: list, col_defs: list, i18n: dict) -> str:
    if not rows:
        return f'<div class="empty-msg">{escape_html(i18n["noData"])}</div>'
    head = "".join(f'<th>{escape_html(c["label"])}</th>' for c in col_defs)
    body = "".join(
        "<tr>" + "".join(
            f'<td>{escape_html(c["render"](row) if c.get("render") else row.get(c["key"]))}</td>' for c in col_defs
        ) + "</tr>"
        for row in rows
    )
    return f'<table class="report-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


REPORT_CSS = """
  :root {
    --bg-1: #0b1220; --panel: #16213a; --panel-border: #26314d;
    --text-main: #e6ebf5; --text-sub: #8b96b3; --accent: #4f7cff;
    --success-text:#4fe3a3; --success-border:#1f8f5f; --success-bg:#0f2e22;
    --error-text:#ff6b7f; --error-border:#8f2b3a; --error-bg:#331419;
    --warn-text:#f2c14e; --warn-border:#8f6f1f; --warn-bg:#332a10;
  }
  * { box-sizing: border-box; }
  body {
    margin:0; padding: 32px 20px 60px;
    background:
      radial-gradient(circle at 15% 10%, rgba(79,124,255,0.10), transparent 40%),
      radial-gradient(circle at 85% 90%, rgba(79,124,255,0.08), transparent 40%),
      var(--bg-1);
    color: var(--text-main);
    font-family: "Segoe UI", "Malgun Gothic", -apple-system, BlinkMacSystemFont, sans-serif;
  }
  .wrap { max-width: 1080px; margin: 0 auto; }
  header.report-header {
    background: linear-gradient(135deg, rgba(79,124,255,0.22), rgba(79,124,255,0.04));
    border: 1px solid var(--panel-border); border-radius: 14px; padding: 26px 30px; margin-bottom: 26px;
  }
  header.report-header h1 { margin: 0 0 6px; font-size: 24px; }
  header.report-header .meta-row { color: var(--text-sub); font-size: 13px; }
  .meta-grid { display:flex; flex-wrap:wrap; gap: 14px 32px; margin-top: 16px; }
  .meta-grid div span.label { display:block; font-size:11px; color:var(--text-sub); text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }
  .meta-grid div span.value { font-size: 15px; font-weight:600; }
  section.report-section { margin-bottom: 30px; }
  section.report-section h2 {
    font-size: 15px; margin: 0 0 14px; padding-bottom: 9px; border-bottom: 1px solid var(--panel-border);
  }
  .card-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(230px,1fr)); gap:16px; }
  .stat-card, .chart-card, .table-card {
    background: var(--panel); border:1px solid var(--panel-border); border-radius:12px; padding:16px 18px;
  }
  .chart-card { margin-bottom: 16px; }
  .stat-card .stat-label { font-size:12px; color:var(--text-sub); margin-bottom:6px; }
  .stat-card .stat-value { font-size:24px; font-weight:700; }
  .stat-card .stat-sub { margin-top:6px; }
  .chart-card .chart-title, .table-card .chart-title {
    font-size:13px; font-weight:600; margin-bottom:10px; display:flex; justify-content:space-between; flex-wrap:wrap; gap:4px 10px;
  }
  .chart-card .chart-title .chart-stats { font-weight:400; color:var(--text-sub); font-size:11px; }
  .chart-svg { width:100%; height:auto; display:block; }
  table.report-table { width:100%; border-collapse: collapse; font-size: 12.5px; }
  table.report-table th, table.report-table td { text-align:left; padding:7px 9px; border-bottom:1px solid var(--panel-border); }
  table.report-table th { color:var(--text-sub); font-weight:600; font-size:10.5px; text-transform:uppercase; letter-spacing:.03em; }
  table.report-table tr:last-child td { border-bottom:none; }
  .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; }
  .badge.ok { background: var(--success-bg); border:1px solid var(--success-border); color:var(--success-text); }
  .badge.warn { background: var(--warn-bg); border:1px solid var(--warn-border); color:var(--warn-text); }
  .badge.danger { background: var(--error-bg); border:1px solid var(--error-border); color:var(--error-text); }
  .empty-msg { color: var(--text-sub); font-size:13px; padding: 10px 0; }
  .note { font-size:11.5px; color: var(--warn-text); background:var(--warn-bg); border:1px solid var(--warn-border); border-radius:8px; padding:10px 14px; margin-top:16px; line-height:1.5; }
  footer.report-footer { text-align:center; color:var(--text-sub); font-size:11px; margin-top: 44px; line-height:1.6; }
  @media (max-width: 620px) { .card-grid { grid-template-columns: 1fr; } }
"""


def build_report_html(meta: dict, snapshots: list, alert_summary: dict, lang: str) -> str:
    t = REPORT_I18N["ko" if lang == "ko" else "en"]
    latest = snapshots[-1] if snapshots else None

    coverage_start_ms = snapshots[0]["ts"] if snapshots else None
    requested_from_ms = meta["periodFrom"].timestamp() * 1000
    is_partial = not coverage_start_ms or coverage_start_ms > requested_from_ms + 6 * 60 * 60 * 1000

    def ok_data(section_path, default=None):
        node = latest
        if node is None:
            return default
        for key in section_path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                return default
        if isinstance(node, dict) and node.get("ok"):
            return node.get("data", default)
        return default

    # --- At a Glance ---
    cpu_pct = ok_data(["main", "cpuPct"])
    mem_data = ok_data(["main", "memory"])
    mem_pct = mem_data.get("pct") if isinstance(mem_data, dict) else None
    session_count = ok_data(["main", "sessionCount"])
    invalid_count = ok_data(["main", "invalidObjectsCount"])

    glance_defs = [
        (t["statCpu"], cpu_pct, "%", badge_class_high_bad(cpu_pct)),
        (t["statMemory"], mem_pct, "%", badge_class_high_bad(mem_pct)),
        (t["statSessions"], session_count, "", ""),
        (t["statInvalid"], invalid_count, "", ("warn" if (invalid_count or 0) > 0 else "ok")),
    ]
    glance_cards = "".join(
        f'<div class="stat-card"><div class="stat-label">{escape_html(label)}</div>'
        f'<div class="stat-value">{"-" if value is None else fmt_num(value, 1 if unit == "%" else 0)}{unit}</div>'
        + (f'<div class="stat-sub"><span class="badge {cls}">&nbsp;</span></div>' if cls else "")
        + "</div>"
        for label, value, unit, cls in glance_defs
    )

    # --- Trend series ---
    def series(section_path):
        out = []
        for s in snapshots:
            node = s
            for key in section_path:
                node = node.get(key, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict) and node.get("ok"):
                out.append({"ts": s["ts"], "value": node.get("data")})
            else:
                out.append({"ts": s["ts"], "value": None})
        return out

    cpu_series = series(["main", "cpuPct"])
    mem_series = [
        {"ts": s["ts"], "value": (s.get("main", {}).get("memory") or {}).get("data", {}).get("pct")
         if (s.get("main", {}).get("memory") or {}).get("ok") else None}
        for s in snapshots
    ]
    session_series = series(["main", "sessionCount"])
    invalid_series = series(["main", "invalidObjectsCount"])

    trend_charts = "".join([
        chart_card(t["chartCpu"], cpu_series, {"color": "#4f7cff", "unit": "%", "forceMinZero": True, "capMax": 100}),
        chart_card(t["chartMemory"], mem_series, {"color": "#7c93ff", "unit": "%", "forceMinZero": True, "capMax": 100}),
        chart_card(t["chartSessions"], session_series, {"color": "#4fe3a3", "unit": "", "forceMinZero": True}),
        chart_card(t["chartInvalid"], invalid_series, {"color": "#f2c14e", "unit": "", "forceMinZero": True}),
    ])

    # --- Instance Efficiency ---
    eff = ok_data(["ops", "instanceEfficiency"], {}) or {}
    eff_rows = "".join(
        f'<div class="stat-card"><div class="stat-label">{escape_html(label)}</div>'
        f'<div class="stat-value">{"-" if val is None else fmt_num(val, 1) + "%"}</div>'
        f'<div class="stat-sub">{badge(val, badge_class_high_good(val))}</div></div>'
        for label, val in [
            (t["effBuffer"], eff.get("BUFFER_HIT_RATIO")),
            (t["effLibrary"], eff.get("LIBRARY_HIT_RATIO")),
            (t["effSoftParse"], eff.get("SOFT_PARSE_PCT")),
            (t["effExecParse"], eff.get("EXECUTE_TO_PARSE_PCT")),
        ]
    )

    # --- Load Profile ---
    lp = ok_data(["ops", "loadProfile"], {}) or {}
    lp_rows = "".join(
        f'<div class="stat-card"><div class="stat-label">{escape_html(label)}</div>'
        f'<div class="stat-value">{fmt_num(val, 2)}</div></div>'
        for label, val in [
            (t["lpRedo"], lp.get("REDO_SIZE_PER_SEC")), (t["lpLogical"], lp.get("LOGICAL_READS_PER_SEC")),
            (t["lpPhysical"], lp.get("PHYSICAL_READS_PER_SEC")), (t["lpUserCalls"], lp.get("USER_CALLS_PER_SEC")),
            (t["lpExecutes"], lp.get("EXECUTES_PER_SEC")), (t["lpTx"], lp.get("TRANSACTIONS_PER_SEC")),
        ]
    )

    # --- Top SQL (latest snapshot) ---
    top_elapsed = ok_data(["ops", "topQueries"], []) or []
    top_cpu = ok_data(["ops", "topQueriesCpu"], []) or []
    top_gets = ok_data(["ops", "topQueriesBufferGets"], []) or []

    top_sql_html = f"""
    <div class="card-grid">
      <div class="table-card">
        <div class="chart-title"><span>{escape_html(t["topSqlElapsed"])}</span></div>
        {table_or_empty(top_elapsed, [{"key": "SQL_ID", "label": t["colSqlId"]}, {"key": "ELAPSED_SEC", "label": t["colElapsedSec"]}], t)}
      </div>
      <div class="table-card">
        <div class="chart-title"><span>{escape_html(t["topSqlCpu"])}</span></div>
        {table_or_empty(top_cpu, [{"key": "SQL_ID", "label": t["colSqlId"]}, {"key": "CPU_SEC", "label": t["colCpuSec"]}], t)}
      </div>
      <div class="table-card">
        <div class="chart-title"><span>{escape_html(t["topSqlGets"])}</span></div>
        {table_or_empty(top_gets, [{"key": "SQL_ID", "label": t["colSqlId"]}, {"key": "BUFFER_GETS", "label": t["colBufferGets"], "render": lambda r: fmt_num(r.get("BUFFER_GETS"), 0)}], t)}
      </div>
    </div>"""

    # --- Storage usage trend ---
    def temp_value(s):
        node = s.get("usage", {}).get("temp")
        rows = node.get("data", []) if isinstance(node, dict) and node.get("ok") else []
        pcts = [r.get("USED_PCT") for r in rows if isinstance(r.get("USED_PCT"), (int, float))]
        return max(pcts) if pcts else None

    def recovery_value(s):
        node = s.get("usage", {}).get("recovery")
        rows = node.get("data", []) if isinstance(node, dict) and node.get("ok") else []
        if not rows:
            return None
        v = rows[0].get("USED_PCT_NET")
        return v if isinstance(v, (int, float)) else None

    temp_series = [{"ts": s["ts"], "value": temp_value(s)} for s in snapshots]
    recovery_series = [{"ts": s["ts"], "value": recovery_value(s)} for s in snapshots]
    usage_charts = "".join([
        chart_card(t["chartTemp"], temp_series, {"color": "#f2c14e", "unit": "%", "forceMinZero": True, "capMax": 100}),
        chart_card(t["chartRecovery"], recovery_series, {"color": "#ff9f6b", "unit": "%", "forceMinZero": True, "capMax": 100}),
    ])

    # --- Tablespace I/O (latest snapshot) ---
    ts_io = ok_data(["ops", "tablespaceIo"], []) or []
    ts_io_html = table_or_empty(ts_io, [
        {"key": "TABLESPACE_NAME", "label": t["colTablespace"]},
        {"key": "PHYSICAL_READS", "label": t["colReads"], "render": lambda r: fmt_num(r.get("PHYSICAL_READS"), 0)},
        {"key": "PHYSICAL_WRITES", "label": t["colWrites"], "render": lambda r: fmt_num(r.get("PHYSICAL_WRITES"), 0)},
    ], t)

    # --- Alert Log summary ---
    if not alert_summary or not alert_summary.get("ok"):
        alert_html = f'<div class="empty-msg">{escape_html((alert_summary or {}).get("message") or t["noData"])}</div>'
    else:
        by_code_html = table_or_empty(alert_summary.get("byCode") or [], [
            {"key": "ORA_CODE", "label": t["colOraCode"]},
            {"key": "CNT", "label": t["colCount"]},
        ], t)
        recent_html = table_or_empty(alert_summary.get("recent") or [], [
            {"key": "LOG_TIME", "label": t["colTime"]},
            {"key": "ORA_CODE", "label": t["colOraCode"], "render": lambda r: r.get("ORA_CODE") or "-"},
            {"key": "MESSAGE_TEXT", "label": t["colMessage"], "render": lambda r: (r.get("MESSAGE_TEXT") or "")[:140]},
        ], t)
        alert_html = f"""
      <div class="stat-card" style="margin-bottom:16px; max-width:260px;">
        <div class="stat-label">{escape_html(t["alertTotal"])}</div>
        <div class="stat-value">{fmt_num(alert_summary.get("totalCount"), 0)}</div>
      </div>
      <div class="card-grid">
        <div class="table-card"><div class="chart-title"><span>{escape_html(t["alertByCode"])}</span></div>{by_code_html}</div>
        <div class="table-card"><div class="chart-title"><span>{escape_html(t["alertRecent"])}</span></div>{recent_html}</div>
      </div>"""

    partial_note_html = ""
    if is_partial and coverage_start_ms:
        note_text = t["partialDataNote"](fmt_date_time(datetime.fromtimestamp(coverage_start_ms / 1000)), meta["periodDays"])
        partial_note_html = f'<div class="note">⚠️ {escape_html(note_text)}</div>'

    html_lang = "ko" if lang == "ko" else "en"
    return f"""<!doctype html>
<html lang="{html_lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape_html(t["title"])}</title>
<style>{REPORT_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="report-header">
    <h1>\U0001F4CA {escape_html(t["title"])}</h1>
    <div class="meta-row">{escape_html(meta["instanceTarget"])}</div>
    <div class="meta-grid">
      <div><span class="label">{escape_html(t["periodLabel"])}</span><span class="value">{escape_html(fmt_date_time(meta["periodFrom"]))} &rarr; {escape_html(fmt_date_time(meta["periodTo"]))}</span></div>
      <div><span class="label">{escape_html(t["generatedLabel"])}</span><span class="value">{escape_html(fmt_date_time(meta["generatedAt"]))}</span></div>
      <div><span class="label">{escape_html(t["dataPointsLabel"])}</span><span class="value">{len(snapshots)}</span></div>
    </div>
    {partial_note_html}
  </header>

  <section class="report-section">
    <h2>{escape_html(t["sectionGlance"])}</h2>
    <div class="card-grid">{glance_cards}</div>
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionTrend"])}</h2>
    {trend_charts}
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionEfficiency"])}</h2>
    <div class="card-grid">{eff_rows}</div>
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionLoadProfile"])}</h2>
    <div class="card-grid">{lp_rows}</div>
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionTopSql"])}</h2>
    {top_sql_html}
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionUsage"])}</h2>
    {usage_charts}
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionTablespaceIo"])}</h2>
    <div class="table-card">{ts_io_html}</div>
  </section>

  <section class="report-section">
    <h2>{escape_html(t["sectionAlertLog"])}</h2>
    {alert_html}
  </section>

  <footer class="report-footer">{escape_html(t["footerNote"])}</footer>
</div>
</body>
</html>"""


# Ties everything together for the /api/generate-report endpoint: takes a
# fresh snapshot right now (so the report's "latest" numbers are current,
# not up to 15 minutes stale), reads the trailing `days` of history for
# this same DB, fetches the Alert Log summary live, and renders the HTML.
async def generate_report(creds: dict, days: int, lang: str) -> str:
    try:
        await gather_snapshot(creds)
    except Exception as err:
        print(f"[report] on-demand snapshot failed (continuing with existing history): {err}")

    target = {"ip": creds["ip"], "port": creds["port"], "sid": creds["sid"]}
    snapshots = read_snapshots(days, target)
    alert_summary = await fetch_alert_summary(creds, days)

    now = datetime.now()
    meta = {
        "instanceTarget": f"{creds['account']}@{creds['ip']}:{creds['port']}:{creds['sid']}",
        "generatedAt": now,
        "periodDays": days,
        "periodFrom": datetime.fromtimestamp(now.timestamp() - days * 86400),
        "periodTo": now,
    }

    return build_report_html(meta, snapshots, alert_summary, lang)
