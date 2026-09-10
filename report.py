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
rather than importing from main.py/backend.core, matching report.js's own
reasoning: this module could be dropped into another project largely
unchanged. The one shared piece is oracle_dsn.py (turning ip/port/sid+
connectType into a TNS connect descriptor) -- a zero-dependency leaf
module, kept in sync with backend/core.py's own connection helper rather
than duplicated a second time, since the SID-vs-Service-Name connect type
has to behave identically everywhere a connection is opened.
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

from oracle_dsn import dsn_from_creds
from paths import DATA_DIR

SNAPSHOT_FILE = DATA_DIR / "snapshot-history.jsonl"
KEY_FILE = DATA_DIR / ".snapshot-key"

SNAPSHOT_INTERVAL_SECONDS = 15 * 60  # 15 minutes
RETENTION_SECONDS = 7 * 24 * 60 * 60  # 7 days -- matches the report's own window


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
                # A stored snapshot predating this field defaults to "sid",
                # exactly matching its only previous behavior -- a SID and
                # a Service Name that happen to spell the same identifier
                # are still not the same database and must not match.
                and t.get("connectType", "sid") == target.get("connectType", "sid")
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
        target_source = "MEMORY_TARGET"
    elif memory_max_target_mb > 0:
        target_mb = memory_max_target_mb
        target_source = "MEMORY_MAX_TARGET"
    else:
        target_mb = _num(d.get("SGA_MAX_MB"), 0) + _num(d.get("PGA_TARGET_MB"), 0)
        target_source = "SGA_MAX_SIZE+PGA_AGGREGATE_TARGET" if target_mb > 0 else None
    pct = round((used_mb / target_mb) * 1000) / 10 if target_mb > 0 else None
    return {
        "ok": True,
        "data": {
            "usedMb": round(used_mb * 10) / 10,
            "targetMb": target_mb if target_mb > 0 else None,
            "targetSource": target_source if target_mb > 0 else None,
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
    connect_string = dsn_from_creds(creds)
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
        "target": encrypt_target({
            "ip": creds["ip"], "port": creds["port"], "sid": creds["sid"],
            "connectType": creds.get("connectType", "sid"),
        }),
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
    connect_string = dsn_from_creds(creds)
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


def fmt_date_time(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


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


# ============================================================================
# Point-in-time Inspection Report ("점검레포트" / Check Report)
# ============================================================================
# A single-moment checklist report generated exactly once, the instant the
# Report button is clicked -- opens one connection to the *currently
# connected* DB and runs a fixed checklist of read-only queries against
# it, modeled on a standard Oracle periodic-inspection checklist (basic
# info / errors / capacity / backup / performance / session / security /
# objects·stats / archive·FRA, plus RAC / ASM / Data Guard / CDB-PDB items
# that only apply to some environments). Every check is independent and
# never raises: one that fails (missing privilege, view not present on
# this edition, etc.) is recorded as "collection failed" with the
# driver's own error text via _q() below, and every other check still
# runs. Nothing here fabricates a pass/fail judgement without a real
# measurement -- an item with no automatable judgement (no org-defined
# baseline, no historical record this app can reach, not applicable to
# this environment) is marked info/unavailable/N-A instead, never "ok".
# AWR/ASH/ADDM are never queried (Diagnostics/Tuning Pack license is never
# assumed -- see tuning.py's own top-of-file comment); nothing here
# executes DDL/DML or changes any instance/database setting.
#
# The rendered HTML opens with a summary dashboard (priority-review/CPU/
# session/tablespace cards, a status-distribution donut, current-limit and
# max-size usage meters, a dynamic priority-review list of whatever this
# run's own danger/warn items are, and a Top SQL bar chart) built from the
# same `items` list and a parallel `metrics` dict that _collect_checks()
# fills in alongside `items` -- the raw numbers behind a handful of checks,
# captured at the same point those checks compute them. The dashboard never
# re-parses the detail table's rendered text and never fabricates a number:
# a metric with no computable value (unlimited limit, zero denominator, no
# memory target configured, a failed query) renders as an explicit
# "unavailable"/reason string instead of a 0 or 0%.

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_DANGER = "danger"
STATUS_INFO = "info"
STATUS_NA = "na"                    # 해당없음 -- doesn't apply to this environment
STATUS_UNAVAILABLE = "unavailable"  # 확인불가 -- no way to check this from here, by design
STATUS_FAILED = "failed"            # 수집실패 -- the check itself raised

_STATUS_LABEL = {
    "ko": {STATUS_OK: "정상", STATUS_WARN: "주의", STATUS_DANGER: "위험", STATUS_INFO: "정보",
           STATUS_NA: "해당없음", STATUS_UNAVAILABLE: "확인불가", STATUS_FAILED: "수집실패"},
    "en": {STATUS_OK: "OK", STATUS_WARN: "Warning", STATUS_DANGER: "Critical", STATUS_INFO: "Info",
           STATUS_NA: "N/A", STATUS_UNAVAILABLE: "Unavailable", STATUS_FAILED: "Collection Failed"},
}
_STATUS_CLASS = {
    STATUS_OK: "ok", STATUS_WARN: "warn", STATUS_DANGER: "danger", STATUS_INFO: "info",
    STATUS_NA: "na", STATUS_UNAVAILABLE: "na", STATUS_FAILED: "danger",
}

_CATEGORY_ORDER = [
    "basic", "error", "capacity", "backup", "performance", "session",
    "security", "objstats", "archive_fra", "rac", "asm", "dataguard", "cdbpdb", "deepperf",
]
_CATEGORY_LABEL = {
    "ko": {
        "basic": "기본정보", "error": "오류", "capacity": "용량", "backup": "백업",
        "performance": "성능", "session": "세션", "security": "보안", "objstats": "객체·통계",
        "archive_fra": "아카이브·FRA", "rac": "RAC", "asm": "ASM", "dataguard": "Data Guard",
        "cdbpdb": "CDB/PDB", "deepperf": "심화 성능",
    },
    "en": {
        "basic": "Basic Info", "error": "Errors", "capacity": "Capacity", "backup": "Backup",
        "performance": "Performance", "session": "Session", "security": "Security", "objstats": "Objects/Stats",
        "archive_fra": "Archive/FRA", "rac": "RAC", "asm": "ASM", "dataguard": "Data Guard",
        "cdbpdb": "CDB/PDB", "deepperf": "Deep Performance",
    },
}


async def _q(connection, sql, params=None):
    """One read-only check. Never raises: returns (rows, None) on success,
    or (None, "<driver's own error text>") on failure."""
    try:
        cursor = connection.cursor()
        await cursor.execute(sql, params or {})
        _dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        return rows, None
    except Exception as err:
        return None, str(err)


def _pct_status(pct, warn_at=75, danger_at=90):
    if pct is None:
        return STATUS_INFO
    if pct >= danger_at:
        return STATUS_DANGER
    if pct >= warn_at:
        return STATUS_WARN
    return STATUS_OK


# A handful of checks below (TEMP/UNDO, CPU/memory, accounts, scheduler)
# run two independent sub-queries and must report ONE combined status --
# the bug this exists to prevent: naively requiring BOTH sub-queries to
# fail before calling the item "failed" means a single failed sub-query
# silently reads as "clean" whenever the other sub-query's own data
# happens to show no risk (a missing value must never be treated as a
# measured zero). _worse_status() combines two independently-judged
# per-sub-query statuses so that:
#   - a real danger/warning found in whichever half DID collect always
#     wins over a mere collection failure in the other half (a real risk
#     is never hidden just because something else couldn't be read), and
#   - a collection failure is never itself silently downgraded to ok/info
#     just because the other half happened to look fine.
_STATUS_SEVERITY = {
    STATUS_DANGER: 4, STATUS_WARN: 3, STATUS_FAILED: 2,
    STATUS_INFO: 1, STATUS_OK: 0, STATUS_UNAVAILABLE: 0, STATUS_NA: 0,
}


def _worse_status(a, b):
    return a if _STATUS_SEVERITY.get(a, 0) >= _STATUS_SEVERITY.get(b, 0) else b


# V$RMAN_BACKUP_JOB_DETAILS.STATUS's own documented values (Oracle only
# ever writes one of these five) -- matched by exact value, not by a loose
# "contains FAIL" substring, which silently let "COMPLETED WITH WARNINGS"
# (and any future/unrecognized status string) read as a clean success.
_BACKUP_STATUS_MAP = {
    "COMPLETED": "completed",
    "COMPLETED WITH WARNINGS": "warned",
    "COMPLETED WITH ERRORS": "errored",
    "FAILED": "failed",
    "RUNNING": "running",
}


def _classify_backup_status(raw_status):
    return _BACKUP_STATUS_MAP.get((raw_status or "").strip().upper(), "unknown")


async def _collect_checks(connection, creds: dict, lang: str):
    def L(ko, en):
        return ko if lang == "ko" else en

    items = []
    counter = {"n": 0}

    def add(category, title, method, criteria, status, measured, note="", period=None):
        counter["n"] += 1
        items.append({
            "category": category, "no": counter["n"], "title": title, "method": method,
            "criteria": criteria, "status": status, "measured": measured, "note": note, "period": period,
        })

    # Raw structured numbers behind a handful of checks below, captured at
    # the same time (from the same already-fetched rows) as the human-
    # readable "measured" text those checks add to `items`. The dashboard
    # summary (cards/donut/meters/SQL chart) renders from this dict plus
    # `items`'s own status counts -- never by re-parsing the rendered HTML
    # or inventing a number that has no query behind it. Each entry is
    # either the real value(s) or {"error": "<reason>"} / a None value
    # when there's genuinely nothing to show (a missing metric renders as
    # "unavailable" text, never as a fabricated 0 or 0%).
    metrics = {}

    log_mode = None  # filled in by check 01, gates check 19 (archive dest)
    is_cdb = None     # filled in by check 01, gates check 24 (CDB/PDB)

    # ---- 01. Instance / service up ----
    rows, err = await _q(
        connection,
        "SELECT i.instance_name, i.status, i.host_name, i.version_full, "
        "d.open_mode, d.log_mode, d.database_role, d.cdb "
        "FROM v$instance i, v$database d",
    )
    if err:
        add("basic", L("인스턴스·서비스 가동", "Instance/Service Up"),
            L("V$INSTANCE, V$DATABASE 조회", "Query V$INSTANCE, V$DATABASE"),
            L("계획된 역할·OPEN_MODE와 일치, 비계획 재시작 없음", "Matches the planned role/OPEN_MODE; no unplanned restart"),
            STATUS_FAILED, "-", err)
    else:
        r = rows[0] if rows else {}
        log_mode = r.get("LOG_MODE")
        is_cdb = r.get("CDB") == "YES"
        ok = r.get("STATUS") == "OPEN" and r.get("OPEN_MODE") in ("READ WRITE", "READ ONLY")
        add("basic", L("인스턴스·서비스 가동", "Instance/Service Up"),
            L("V$INSTANCE, V$DATABASE 조회", "Query V$INSTANCE, V$DATABASE"),
            L("계획된 역할·OPEN_MODE와 일치, 비계획 재시작 없음", "Matches the planned role/OPEN_MODE; no unplanned restart"),
            STATUS_OK if ok else STATUS_WARN,
            f"{r.get('INSTANCE_NAME')} / {r.get('STATUS')} / {r.get('OPEN_MODE')} / {r.get('VERSION_FULL') or '-'}",
            f"{L('호스트','Host')}: {r.get('HOST_NAME')} / {L('역할','Role')}: {r.get('DATABASE_ROLE')}")

    # ---- 02. Version / patch level ----
    rows, err = await _q(
        connection,
        "SELECT patch_id, description, TO_CHAR(action_time, 'YYYY-MM-DD') AS action_time "
        "FROM (SELECT patch_id, description, action_time FROM dba_registry_sqlpatch ORDER BY action_time DESC) "
        "WHERE ROWNUM <= 5",
    )
    if err:
        add("basic", L("버전·패치·지원 기준", "Version/Patch Baseline"),
            L("DBA_REGISTRY_SQLPATCH 조회", "Query DBA_REGISTRY_SQLPATCH"),
            L("조직의 승인 패치 기준 충족 (조직 정책과 대조 필요)", "Meets the organization's approved patch baseline (compare against org policy)"),
            STATUS_FAILED, "-", err)
    else:
        latest = rows[0] if rows else None
        measured = f"{latest['PATCH_ID']} ({latest['ACTION_TIME']}) -- {(latest['DESCRIPTION'] or '')[:80]}" if latest else L("패치 이력 없음", "No patch history found")
        add("basic", L("버전·패치·지원 기준", "Version/Patch Baseline"),
            L("DBA_REGISTRY_SQLPATCH 조회", "Query DBA_REGISTRY_SQLPATCH"),
            L("조직의 승인 패치 기준 충족 (조직 정책과 대조 필요)", "Meets the organization's approved patch baseline (compare against org policy)"),
            STATUS_INFO, measured,
            L("자동 판정 불가 -- 조직 정책 기준선 대조 필요", "Cannot auto-judge -- compare against your organization's own baseline"))

    # ---- 03. Alert log (fetch_alert_summary manages its own connection --
    #      v$diag_alert_ext already has its own history, unlike the other
    #      checks here) ----
    alert_days = 7
    alert = await fetch_alert_summary(creds, alert_days)
    if not alert.get("ok"):
        add("error", L("Alert·진단 로그", "Alert/Diagnostic Log"),
            L("V$DIAG_ALERT_EXT 조회", "Query V$DIAG_ALERT_EXT"),
            L("신규 심각 오류·반복 오류 없음", "No new severe/recurring errors"),
            STATUS_FAILED, "-", alert.get("message", ""), period=L(f"최근 {alert_days}일", f"last {alert_days} days"))
    else:
        total = alert.get("totalCount", 0)
        by_code = alert.get("byCode") or []
        top_codes = ", ".join(f"{r['ORA_CODE']}×{r['CNT']}" for r in by_code[:3]) if by_code else "-"
        add("error", L("Alert·진단 로그", "Alert/Diagnostic Log"),
            L("V$DIAG_ALERT_EXT 조회", "Query V$DIAG_ALERT_EXT"),
            L("신규 심각 오류·반복 오류 없음", "No new severe/recurring errors"),
            STATUS_OK if total == 0 else (STATUS_DANGER if total >= 20 else STATUS_WARN),
            L(f"{total}건 ({top_codes})", f"{total} entries ({top_codes})"),
            L("ORA 코드/오류·경고성 항목 집계", "Count of ORA-coded error/warning entries"),
            period=L(f"최근 {alert_days}일", f"last {alert_days} days"))

    # ---- 04. Tablespace / datafile usage -- against each datafile's own
    #      max size (autoextend MAXBYTES when autoextensible, else its
    #      current size), not the currently allocated total: a tablespace
    #      that's mostly-full today but can still autoextend to its
    #      MAXBYTES ceiling shouldn't read as "danger" when it's really
    #      nowhere near its actual limit. ----
    rows, err = await _q(
        connection,
        """SELECT t.tablespace_name,
                  ROUND((t.total_bytes - NVL(f.free_bytes, 0)) / t.max_bytes * 100, 2) AS used_pct
             FROM (SELECT tablespace_name, SUM(bytes) AS total_bytes,
                          SUM(CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                                   THEN maxbytes ELSE bytes END) AS max_bytes
                     FROM dba_data_files GROUP BY tablespace_name) t
             LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS free_bytes
                          FROM dba_free_space GROUP BY tablespace_name) f
               ON f.tablespace_name = t.tablespace_name
            WHERE t.max_bytes > 0
            ORDER BY used_pct DESC""",
    )
    if err:
        add("capacity", L("테이블스페이스·데이터파일", "Tablespace/Datafile"),
            L("DBA_DATA_FILES, DBA_FREE_SPACE 조회 (최대 크기 대비)", "Query DBA_DATA_FILES, DBA_FREE_SPACE (vs. max size)"),
            L("최대 크기 대비 사용률 80% 주의·90% 위험", "Usage vs. max size 80% warning / 90% critical"),
            STATUS_FAILED, "-", err)
        metrics["tablespace"] = {"error": err}
    else:
        worst = rows[0] if rows else None
        worst_pct = _num(worst.get("USED_PCT")) if worst else None
        over_warn = [r for r in rows if _num(r.get("USED_PCT"), 0) >= 80]
        measured = (L(f"최대 크기 대비 최고 사용률 {fmt_num(worst_pct,1)}% ({worst.get('TABLESPACE_NAME')}), 80%↑ {len(over_warn)}건",
                       f"peak {fmt_num(worst_pct,1)}% of max ({worst.get('TABLESPACE_NAME')}), {len(over_warn)} tablespace(s) ≥80%")
                    if worst else L("테이블스페이스 없음", "No tablespaces found"))
        add("capacity", L("테이블스페이스·데이터파일", "Tablespace/Datafile"),
            L("DBA_DATA_FILES, DBA_FREE_SPACE 조회 (최대 크기 대비)", "Query DBA_DATA_FILES, DBA_FREE_SPACE (vs. max size)"),
            L("최대 크기 대비 사용률 80% 주의·90% 위험", "Usage vs. max size 80% warning / 90% critical"),
            _pct_status(worst_pct, 80, 90), measured)
        metrics["tablespace"] = (
            {"worstPct": worst_pct, "worstName": worst.get("TABLESPACE_NAME"), "overWarnCount": len(over_warn)}
            if worst else {"worstPct": None, "worstName": None, "overWarnCount": 0}
        )

    # ---- 05. TEMP / UNDO -- TEMP is also measured against each tempfile's
    #      own max size (autoextend MAXBYTES, else current size), same
    #      reasoning as check 04. ----
    rows, err = await _q(
        connection,
        """SELECT tu.tablespace_name,
                  ROUND(tu.used_bytes / NULLIF(tm.max_bytes, 0) * 100, 2) AS used_pct
             FROM (SELECT tablespace_name, SUM(bytes_used) AS used_bytes
                     FROM v$temp_space_header GROUP BY tablespace_name) tu
             LEFT JOIN (SELECT tablespace_name,
                               SUM(CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                                        THEN maxbytes ELSE bytes END) AS max_bytes
                          FROM dba_temp_files GROUP BY tablespace_name) tm
               ON tm.tablespace_name = tu.tablespace_name""",
    )
    undo_rows, undo_err = await _q(
        connection,
        """SELECT (SELECT value FROM v$parameter WHERE name='undo_tablespace') AS undo_tablespace,
                  (SELECT tuned_undoretention FROM (SELECT tuned_undoretention FROM v$undostat ORDER BY end_time DESC) WHERE ROWNUM=1) AS tuned_retention_sec
             FROM dual""",
    )
    temp_worst_row = None
    for r in (rows or []):
        p = _num(r.get("USED_PCT"))
        if p is not None and (temp_worst_row is None or p > _num(temp_worst_row.get("USED_PCT"), -1)):
            temp_worst_row = r
    temp_worst = _num(temp_worst_row.get("USED_PCT")) if temp_worst_row else None
    undo_sec = _num(undo_rows[0].get("TUNED_RETENTION_SEC")) if (undo_rows and not undo_err) else None

    if err:
        temp_status = STATUS_FAILED
        temp_text = L(f"TEMP 조회 실패 ({err})", f"TEMP query failed ({err})")
    elif temp_worst is not None:
        temp_status = _pct_status(temp_worst, 85, 95)
        temp_text = L(f"TEMP 최대 크기 대비 최고사용률 {fmt_num(temp_worst,1)}%", f"TEMP peak {fmt_num(temp_worst,1)}% of max")
    else:
        temp_status = STATUS_INFO
        temp_text = L("TEMP 테이블스페이스 없음", "No TEMP tablespace found")

    if undo_err:
        undo_status = STATUS_FAILED
        undo_text = L(f"UNDO 조회 실패 ({undo_err})", f"UNDO query failed ({undo_err})")
    else:
        # Retention itself isn't judged against a threshold in this check --
        # only TEMP capacity is -- so a successful UNDO query never
        # contributes anything worse than STATUS_OK on its own.
        undo_status = STATUS_OK
        undo_text = (L(f"UNDO 보존 {fmt_num(undo_sec,0)}초", f"UNDO retention {fmt_num(undo_sec,0)}s")
                     if undo_sec is not None else L("UNDO 보존시간 확인 불가", "UNDO retention unavailable"))

    status = _worse_status(temp_status, undo_status)
    measured = f"{temp_text} / {undo_text}"
    note = ""
    if err or undo_err:
        note = L("일부 항목 조회 실패 -- 위 측정값은 실제로 수집된 부분만 반영합니다", "Some sub-checks failed to collect -- the measured value above reflects only what was actually collected")

    metrics["temp"] = (
        {"error": err} if err
        else {"worstPct": temp_worst, "worstName": temp_worst_row.get("TABLESPACE_NAME") if temp_worst_row else None}
    )
    add("capacity", "TEMP·UNDO", L("V$TEMP_SPACE_HEADER, DBA_TEMP_FILES, V$UNDOSTAT 조회", "Query V$TEMP_SPACE_HEADER, DBA_TEMP_FILES, V$UNDOSTAT"),
        L("TEMP 최대 크기 대비 여유 확인, UNDO 보존시간 확보", "TEMP has free space vs. its max size; UNDO retention is adequate"),
        status, measured, note)

    # ---- 06. Backup success / gaps -- V$RMAN_BACKUP_JOB_DETAILS has no
    #      date filter here (just "last 10 jobs"), so a failure surfaced
    #      below may be old news, not something from this check's own
    #      moment. The period text and each job's own START/END timestamp
    #      (already in `measured`) are shown explicitly instead of implying
    #      "this just failed now". ----
    rows, err = await _q(
        connection,
        """SELECT input_type, status, TO_CHAR(start_time,'YYYY-MM-DD HH24:MI') AS start_time,
                  TO_CHAR(end_time,'YYYY-MM-DD HH24:MI') AS end_time
             FROM (SELECT input_type, status, start_time, end_time FROM v$rman_backup_job_details
                    ORDER BY start_time DESC) WHERE ROWNUM <= 10""",
    )
    backup_period = L("최근 10건, 기간 제한 없음 (건별 시각 확인)", "last 10 job(s), no date filter (check each job's own timestamp)")
    if err:
        add("backup", L("백업 성공·누락", "Backup Success/Gaps"),
            L("V$RMAN_BACKUP_JOB_DETAILS 조회", "Query V$RMAN_BACKUP_JOB_DETAILS"),
            L("계획된 백업 모두 완료, 경고·실패·누락 없음", "All scheduled backups completed; no warning/failure/gap"),
            STATUS_FAILED, "-", err)
    elif not rows:
        add("backup", L("백업 성공·누락", "Backup Success/Gaps"),
            L("V$RMAN_BACKUP_JOB_DETAILS 조회", "Query V$RMAN_BACKUP_JOB_DETAILS"),
            L("백업 작업 이력 존재 여부만 확인 (예정된 백업의 존재·누락 여부는 이 조회만으로 판단하지 않음)",
              "Only confirms whether any backup job history exists (this query alone does not judge whether a backup was scheduled or missed)"),
            STATUS_UNAVAILABLE, L("이력 없음", "No history found"),
            L("RMAN 백업 이력이 없거나 보존 기간이 지났습니다 (미수집)", "No RMAN backup history found, or it has aged out (not collected)"),
            period=backup_period)
    else:
        buckets = {"completed": 0, "warned": 0, "errored": 0, "failed": 0, "running": 0, "unknown": 0}
        for r in rows:
            buckets[_classify_backup_status(r.get("STATUS"))] += 1
        latest = rows[0]

        hard_fail_cnt = buckets["failed"] + buckets["errored"]
        attention_cnt = buckets["warned"] + buckets["unknown"]
        if hard_fail_cnt > 0:
            status = STATUS_DANGER
        elif attention_cnt > 0:
            status = STATUS_WARN
        elif buckets["completed"] > 0:
            status = STATUS_OK
        else:
            # Nothing in this window has actually finished yet (e.g. every
            # row is still RUNNING) -- there's genuinely nothing to judge
            # as clean or not yet, so this is not a confirmed success.
            status = STATUS_INFO

        breakdown_parts = []
        if buckets["completed"]:
            breakdown_parts.append(L(f"완료 {buckets['completed']}", f"completed {buckets['completed']}"))
        if buckets["warned"]:
            breakdown_parts.append(L(f"경고 포함 완료 {buckets['warned']}", f"completed with warnings {buckets['warned']}"))
        if buckets["errored"]:
            breakdown_parts.append(L(f"오류 포함 완료 {buckets['errored']}", f"completed with errors {buckets['errored']}"))
        if buckets["failed"]:
            breakdown_parts.append(L(f"실패 {buckets['failed']}", f"failed {buckets['failed']}"))
        if buckets["running"]:
            breakdown_parts.append(L(f"진행 중 {buckets['running']}", f"running {buckets['running']}"))
        if buckets["unknown"]:
            breakdown_parts.append(L(f"알 수 없는 상태 {buckets['unknown']}", f"unrecognized status {buckets['unknown']}"))
        breakdown = ", ".join(breakdown_parts)

        measured = L(
            f"최근 {len(rows)}건 -- {breakdown} (최신: {latest.get('INPUT_TYPE')} {latest.get('STATUS')} {latest.get('END_TIME')})",
            f"last {len(rows)} -- {breakdown} (latest: {latest.get('INPUT_TYPE')} {latest.get('STATUS')} {latest.get('END_TIME')})",
        )
        note = (L("이 앱이 인식하지 못하는 상태값이 있어 정상으로 단정하지 않았습니다", "Includes a status value this app doesn't recognize -- not assumed to be a clean success")
                if buckets["unknown"] else "")
        add("backup", L("백업 성공·누락", "Backup Success/Gaps"),
            L("V$RMAN_BACKUP_JOB_DETAILS 조회", "Query V$RMAN_BACKUP_JOB_DETAILS"),
            L("계획된 백업 모두 완료, 경고·실패·누락 없음", "All scheduled backups completed; no warning/failure/gap"),
            status, measured, note,
            period=backup_period)

    # ---- 07. CPU / memory ----
    cpu_rows, cpu_err = await _q(
        connection,
        "SELECT value FROM (SELECT value FROM v$sysmetric WHERE metric_name='Host CPU Utilization (%)' "
        "ORDER BY end_time DESC) WHERE ROWNUM=1",
    )
    mem_rows, mem_err = await _q(
        connection,
        """SELECT ROUND((SELECT SUM(value) FROM v$sga)/1024/1024,1) AS sga_mb,
                  ROUND((SELECT value FROM v$pgastat WHERE name='total PGA allocated')/1024/1024,1) AS pga_mb,
                  ROUND(NVL((SELECT value FROM v$parameter WHERE name='memory_target'),0)/1024/1024,1) AS memory_target_mb,
                  ROUND(NVL((SELECT value FROM v$parameter WHERE name='memory_max_target'),0)/1024/1024,1) AS memory_max_target_mb,
                  ROUND(NVL((SELECT value FROM v$parameter WHERE name='sga_max_size'),0)/1024/1024,1) AS sga_max_mb,
                  ROUND(NVL((SELECT value FROM v$parameter WHERE name='pga_aggregate_target'),0)/1024/1024,1) AS pga_target_mb
             FROM dual""",
    )
    cpu_pct = _num(cpu_rows[0]["VALUE"]) if (cpu_rows and not cpu_err) else None
    mem_info = _map_memory(mem_rows or [])["data"] if not mem_err else {}
    mem_pct = mem_info.get("pct")
    measured = L(
        f"CPU {fmt_num(cpu_pct,1) if cpu_pct is not None else '확인불가'}% / 메모리 {fmt_num(mem_pct,1) if mem_pct is not None else '확인불가'}%",
        f"CPU {fmt_num(cpu_pct,1) if cpu_pct is not None else 'unavailable'}% / Memory {fmt_num(mem_pct,1) if mem_pct is not None else 'unavailable'}%",
    )
    cpu_status = STATUS_FAILED if cpu_err else (_pct_status(cpu_pct, 75, 90) if cpu_pct is not None else STATUS_INFO)
    mem_status = STATUS_FAILED if mem_err else (_pct_status(mem_pct, 75, 90) if mem_pct is not None else STATUS_INFO)
    status = _worse_status(cpu_status, mem_status)
    note = L("응답시간(p95)은 이 앱에서 별도 이력화하지 않아 비교자료없음", "Response-time (p95) history isn't tracked by this app -- no comparison data")
    partial_errs = [e for e in (cpu_err, mem_err) if e]
    if partial_errs:
        note = L(f"{note} / 일부 조회 실패: {'; '.join(partial_errs)}", f"{note} / partial collection failure: {'; '.join(partial_errs)}")
    add("performance", L("CPU·메모리·응답시간", "CPU/Memory/Response Time"),
        L("V$SYSMETRIC, V$SGA, V$PGASTAT 조회", "Query V$SYSMETRIC, V$SGA, V$PGASTAT"),
        L("동일 업무 기준 대비 CPU/메모리 정상 범위", "CPU/memory within normal range for equivalent workload"),
        status, measured, note)
    metrics["cpu"] = {"error": cpu_err} if cpu_err else {"pct": cpu_pct}
    metrics["memory"] = (
        {"error": mem_err} if mem_err
        else {"pct": mem_pct, "usedMb": mem_info.get("usedMb"), "targetMb": mem_info.get("targetMb"),
              "targetSource": mem_info.get("targetSource")}
    )

    # ---- 08. Wait events (cumulative since instance startup -- a single
    #      reading, no baseline to auto-judge against) ----
    rows, err = await _q(
        connection,
        """SELECT event, time_waited FROM (SELECT event, time_waited FROM v$system_event
             WHERE wait_class != 'Idle' ORDER BY time_waited DESC) WHERE ROWNUM <= 5""",
    )
    if err:
        add("performance", L("대기 이벤트", "Wait Events"),
            L("V$SYSTEM_EVENT 조회", "Query V$SYSTEM_EVENT"),
            L("특정 이벤트 편중 없음 (구간 비교 필요)", "No single event dominates (needs interval comparison)"),
            STATUS_FAILED, "-", err)
    else:
        top = ", ".join(f"{r['EVENT']}" for r in rows[:3]) if rows else "-"
        add("performance", L("대기 이벤트", "Wait Events"),
            L("V$SYSTEM_EVENT 조회", "Query V$SYSTEM_EVENT"),
            L("특정 이벤트 편중 없음 (구간 비교 필요)", "No single event dominates (needs interval comparison)"),
            STATUS_INFO, L(f"누적 상위: {top}", f"top cumulative: {top}"),
            L("인스턴스 시작 이후 누적값이라 이번 조회만으로는 판정 불가", "Cumulative since startup -- a single reading alone can't be judged"))

    # ---- 09. Top SQL (informational -- same reasoning as wait events) ----
    rows, err = await _q(
        connection,
        """SELECT sql_id, ROUND(elapsed_time/1000000,3) AS elapsed_sec FROM (
             SELECT sql_id, elapsed_time FROM v$sql WHERE elapsed_time > 0 ORDER BY elapsed_time DESC
           ) WHERE ROWNUM <= 5""",
    )
    if err:
        add("performance", L("주요 SQL", "Top SQL"),
            L("V$SQL 조회", "Query V$SQL"),
            L("동일 SQL 대비 이상 급증 없음", "No abnormal jump vs. the same SQL's own history"),
            STATUS_FAILED, "-", err)
        metrics["topSql"] = {"error": err}
    else:
        top = ", ".join(f"{r['SQL_ID']}({fmt_num(r['ELAPSED_SEC'],1)}s)" for r in rows[:3]) if rows else "-"
        add("performance", L("주요 SQL", "Top SQL"),
            L("V$SQL 조회", "Query V$SQL"),
            L("동일 SQL 대비 이상 급증 없음", "No abnormal jump vs. the same SQL's own history"),
            STATUS_INFO, top,
            L("공유 풀에 남아있는 누적 실행시간 기준, 계획 변경 이력은 비교자료없음", "Cumulative elapsed time still in the shared pool -- no plan-change history to compare"))
        metrics["topSql"] = [
            {"sqlId": r.get("SQL_ID"), "elapsedSec": _num(r.get("ELAPSED_SEC"))} for r in (rows or [])
        ]

    # ---- 10. Session / process limits ----
    rows, err = await _q(
        connection,
        "SELECT resource_name, current_utilization, max_utilization, limit_value "
        "FROM v$resource_limit WHERE resource_name IN ('processes','sessions')",
    )
    if err:
        add("session", L("세션·프로세스 한도", "Session/Process Limits"),
            L("V$RESOURCE_LIMIT 조회", "Query V$RESOURCE_LIMIT"),
            L("사용률 80% 주의·90% 위험", "Usage 80% warning / 90% critical"),
            STATUS_FAILED, "-", err)
        metrics["resourceLimits"] = {"error": err}
    else:
        worst_pct, worst_line = None, []
        by_resource = {}
        for r in rows or []:
            limit_raw = r.get("LIMIT_VALUE")
            cur = _num(r.get("CURRENT_UTILIZATION"))
            limit_val = _num(limit_raw) if limit_raw not in (None, "UNLIMITED") else None
            pct = round(cur / limit_val * 100, 1) if (cur is not None and limit_val and limit_val > 0) else None
            worst_line.append(f"{r.get('RESOURCE_NAME')} {fmt_num(cur,0)}/{limit_raw}")
            by_resource[r.get("RESOURCE_NAME")] = {
                "used": cur, "limit": limit_val,
                "unlimited": limit_raw == "UNLIMITED", "pct": pct,
            }
            if pct is not None and (worst_pct is None or pct > worst_pct):
                worst_pct = pct
        add("session", L("세션·프로세스 한도", "Session/Process Limits"),
            L("V$RESOURCE_LIMIT 조회", "Query V$RESOURCE_LIMIT"),
            L("사용률 80% 주의·90% 위험", "Usage 80% warning / 90% critical"),
            _pct_status(worst_pct, 80, 90), " / ".join(worst_line) or "-")
        metrics["resourceLimits"] = by_resource

    # ---- 11. Locks / long-running transactions ----
    rows, err = await _q(
        connection,
        """SELECT waiter.sid AS waiter_sid, waiter.seconds_in_wait AS wait_seconds
             FROM v$session waiter JOIN v$session blocker ON waiter.blocking_session = blocker.sid
            WHERE waiter.blocking_session IS NOT NULL ORDER BY waiter.seconds_in_wait DESC""",
    )
    if err:
        add("session", L("잠금·장기 트랜잭션", "Locks/Long-Running Transactions"),
            L("V$SESSION, V$TRANSACTION 조회", "Query V$SESSION, V$TRANSACTION"),
            L("업무 허용 시간 초과 차단 없음", "No blocking beyond the business-allowed duration"),
            STATUS_FAILED, "-", err)
    else:
        cnt = len(rows or [])
        max_wait = max((r.get("WAIT_SECONDS") or 0) for r in rows) if rows else 0
        add("session", L("잠금·장기 트랜잭션", "Locks/Long-Running Transactions"),
            L("V$SESSION, V$TRANSACTION 조회", "Query V$SESSION, V$TRANSACTION"),
            L("업무 허용 시간 초과 차단 없음", "No blocking beyond the business-allowed duration"),
            STATUS_OK if cnt == 0 else (STATUS_DANGER if max_wait >= 300 else STATUS_WARN),
            L(f"차단 세션 {cnt}건 (최대 대기 {max_wait}초)", f"{cnt} blocked session(s) (max wait {max_wait}s)"))

    # ---- 12. Accounts / privileges / profiles ----
    locked_rows, locked_err = await _q(
        connection,
        "SELECT username, account_status, lock_date FROM dba_users WHERE account_status LIKE '%LOCKED%'",
    )
    expiring_rows, expiring_err = await _q(
        connection,
        "SELECT username, expiry_date, ROUND(expiry_date - SYSDATE) AS days_left FROM dba_users "
        "WHERE expiry_date IS NOT NULL AND expiry_date <= SYSDATE + 30",
    )
    # locked_cnt/expiring_cnt stay None (never a fabricated 0) when their own
    # query failed, so a genuine "0 found" (a real, successful empty result)
    # is never confused with "couldn't check" -- see _worse_status() above.
    locked_cnt = len(locked_rows) if (locked_rows is not None and not locked_err) else None
    expiring_cnt = len(expiring_rows) if (expiring_rows is not None and not expiring_err) else None
    locked_status = STATUS_FAILED if locked_err else (STATUS_OK if locked_cnt == 0 else STATUS_WARN)
    expiring_status = STATUS_FAILED if expiring_err else (STATUS_OK if expiring_cnt == 0 else STATUS_WARN)
    status = _worse_status(locked_status, expiring_status)
    locked_text = (L(f"잠긴 계정 {locked_cnt}건", f"{locked_cnt} locked")
                   if locked_cnt is not None else L("잠긴 계정 확인불가", "locked accounts unavailable"))
    expiring_text = (L(f"30일 내 만료 {expiring_cnt}건", f"{expiring_cnt} expiring within 30 days")
                      if expiring_cnt is not None else L("만료 예정 계정 확인불가", "expiring accounts unavailable"))
    note = ""
    partial_errs = [e for e in (locked_err, expiring_err) if e]
    if partial_errs:
        note = L(f"일부 조회 실패: {'; '.join(partial_errs)}", f"partial collection failure: {'; '.join(partial_errs)}")
    add("security", L("계정·권한·프로파일", "Accounts/Privileges/Profiles"),
        L("DBA_USERS 조회", "Query DBA_USERS"),
        L("승인 목록과 일치, 사용 안 하는 계정 만료 임박 시 주의", "Matches the approved list; unused accounts nearing expiry are flagged"),
        status, f"{locked_text}, {expiring_text}", note)

    # ---- 13. Audit / access history ----
    rows, err = await _q(connection, "SELECT value FROM v$parameter WHERE name = 'audit_trail'")
    if err:
        add("security", L("감사·접근 이력", "Audit/Access History"),
            L("AUDIT_TRAIL 파라미터 조회", "Query the AUDIT_TRAIL parameter"),
            L("필수 감사 정책·보관 기간 준수", "Meets the required audit policy/retention"),
            STATUS_FAILED, "-", err)
    else:
        val = rows[0]["VALUE"] if rows else None
        add("security", L("감사·접근 이력", "Audit/Access History"),
            L("AUDIT_TRAIL 파라미터 조회", "Query the AUDIT_TRAIL parameter"),
            L("필수 감사 정책·보관 기간 준수", "Meets the required audit policy/retention"),
            STATUS_INFO, L(f"AUDIT_TRAIL = {val}", f"AUDIT_TRAIL = {val}"),
            L("감사 정책·보관 이력 자체의 조회·판정은 이 앱의 범위 밖입니다", "Reviewing the actual audit trail/policy content is outside this app's scope"))

    # ---- 14. Invalid objects ----
    rows, err = await _q(connection, "SELECT COUNT(*) AS cnt FROM dba_objects WHERE status = 'INVALID'")
    if err:
        add("objstats", L("무효 객체·구성요소", "Invalid Objects/Components"),
            L("DBA_OBJECTS 조회", "Query DBA_OBJECTS"),
            L("신규 INVALID·비정상 구성요소 없음", "No new INVALID objects/abnormal components"),
            STATUS_FAILED, "-", err)
    else:
        cnt = int(rows[0]["CNT"]) if rows else 0
        add("objstats", L("무효 객체·구성요소", "Invalid Objects/Components"),
            L("DBA_OBJECTS 조회", "Query DBA_OBJECTS"),
            L("신규 INVALID·비정상 구성요소 없음", "No new INVALID objects/abnormal components"),
            STATUS_OK if cnt == 0 else STATUS_WARN, L(f"INVALID {cnt}건", f"{cnt} INVALID object(s)"))

    # ---- 15. Statistics freshness ----
    rows, err = await _q(
        connection,
        """SELECT COUNT(*) AS cnt FROM dba_tab_statistics s
            WHERE s.object_type = 'TABLE' AND (s.last_analyzed IS NULL OR s.last_analyzed < SYSDATE - 30)
              AND s.owner NOT IN (SELECT username FROM dba_users WHERE oracle_maintained = 'Y')""",
    )
    if err:
        add("objstats", L("통계정보", "Optimizer Statistics"),
            L("DBA_TAB_STATISTICS 조회", "Query DBA_TAB_STATISTICS"),
            L("핵심 테이블 stale·누락·수집 실패 없음", "No stale/missing/failed statistics on key tables"),
            STATUS_FAILED, "-", err)
    else:
        cnt = int(rows[0]["CNT"]) if rows else 0
        add("objstats", L("통계정보", "Optimizer Statistics"),
            L("DBA_TAB_STATISTICS 조회", "Query DBA_TAB_STATISTICS"),
            L("핵심 테이블 stale·누락·수집 실패 없음", "No stale/missing/failed statistics on key tables"),
            STATUS_OK if cnt == 0 else STATUS_WARN,
            L(f"30일 초과·미수집 테이블 {cnt}건 (사용자 스키마)", f"{cnt} user-schema table(s) stale (>30d) or never analyzed"))

    # ---- 16. Scheduler / batch jobs ----
    sched_rows, sched_err = await _q(
        connection,
        """SELECT owner, job_name, status FROM (SELECT owner, job_name, status FROM dba_scheduler_job_run_details
             WHERE status != 'SUCCEEDED' AND log_date > SYSDATE - 7 ORDER BY log_date DESC) WHERE ROWNUM <= 20""",
    )
    legacy_rows, legacy_err = await _q(
        connection, "SELECT job FROM dba_jobs WHERE broken = 'Y' OR failures > 0",
    )
    sched_cnt = len(sched_rows) if (sched_rows is not None and not sched_err) else None
    legacy_cnt = len(legacy_rows) if (legacy_rows is not None and not legacy_err) else None
    sched_status = STATUS_FAILED if sched_err else (STATUS_OK if sched_cnt == 0 else STATUS_WARN)
    legacy_status = STATUS_FAILED if legacy_err else (STATUS_OK if legacy_cnt == 0 else STATUS_WARN)
    status = _worse_status(sched_status, legacy_status)
    sched_text = (L(f"실패 이력 {sched_cnt}건", f"{sched_cnt} failed run(s)")
                  if sched_cnt is not None else L("스케줄러 실패 이력 확인불가", "scheduler failure history unavailable"))
    legacy_text = (L(f"고장난 legacy job {legacy_cnt}건", f"{legacy_cnt} broken legacy job(s)")
                   if legacy_cnt is not None else L("legacy job 상태 확인불가", "legacy job status unavailable"))
    note = ""
    partial_errs = [e for e in (sched_err, legacy_err) if e]
    if partial_errs:
        note = L(f"일부 조회 실패: {'; '.join(partial_errs)}", f"partial collection failure: {'; '.join(partial_errs)}")
    add("objstats", L("스케줄러·배치", "Scheduler/Batch Jobs"),
        L("DBA_SCHEDULER_JOB_RUN_DETAILS, DBA_JOBS 조회", "Query DBA_SCHEDULER_JOB_RUN_DETAILS, DBA_JOBS"),
        L("필수 배치 누락·실패 없음", "No missing/failed required batch job"),
        status, f"{sched_text}, {legacy_text}", note,
        period=L("최근 7일 (스케줄러), 현재 스냅샷 (legacy)", "last 7 days (scheduler), current snapshot (legacy)"))

    # ---- 17. Archive log generation / transport ----
    if log_mode != "ARCHIVELOG":
        add("archive_fra", L("아카이브 생성·전송", "Archive Log Generation/Transport"),
            L("V$ARCHIVE_DEST_STATUS 조회", "Query V$ARCHIVE_DEST_STATUS"),
            L("목적지 오류 없음, 일·피크 생성량 대비 여유 확보", "No destination error; ample headroom vs. daily/peak generation"),
            STATUS_NA, "-", L("NOARCHIVELOG 모드", "NOARCHIVELOG mode"))
    else:
        rows, err = await _q(
            connection,
            "SELECT dest_id, status, error FROM v$archive_dest_status WHERE status != 'INACTIVE'",
        )
        if err:
            add("archive_fra", L("아카이브 생성·전송", "Archive Log Generation/Transport"),
                L("V$ARCHIVE_DEST_STATUS 조회", "Query V$ARCHIVE_DEST_STATUS"),
                L("목적지 오류 없음, 일·피크 생성량 대비 여유 확보", "No destination error; ample headroom vs. daily/peak generation"),
                STATUS_FAILED, "-", err)
        else:
            errored = [r for r in (rows or []) if r.get("ERROR")]
            add("archive_fra", L("아카이브 생성·전송", "Archive Log Generation/Transport"),
                L("V$ARCHIVE_DEST_STATUS 조회", "Query V$ARCHIVE_DEST_STATUS"),
                L("목적지 오류 없음, 일·피크 생성량 대비 여유 확보", "No destination error; ample headroom vs. daily/peak generation"),
                STATUS_OK if not errored else STATUS_DANGER,
                L(f"활성 목적지 {len(rows or [])}건, 오류 {len(errored)}건", f"{len(rows or [])} active destination(s), {len(errored)} error(s)"))

    # ---- 18. FRA usage ----
    rows, err = await _q(
        connection,
        """SELECT ROUND(space_limit/1024/1024/1024,2) AS space_limit_gb,
                  ROUND((space_used - space_reclaimable)/NULLIF(space_limit,0)*100,2) AS used_pct_net
             FROM v$recovery_file_dest""",
    )
    if err:
        add("archive_fra", "FRA " + L("사용률", "Usage"),
            L("V$RECOVERY_FILE_DEST 조회", "Query V$RECOVERY_FILE_DEST"),
            L("사용률 80% 주의·90% 위험 (재사용 가능 공간 제외)", "Usage 80% warning / 90% critical (net of reclaimable space)"),
            STATUS_FAILED, "-", err)
    elif not rows:
        add("archive_fra", "FRA " + L("사용률", "Usage"),
            L("V$RECOVERY_FILE_DEST 조회", "Query V$RECOVERY_FILE_DEST"),
            L("사용률 80% 주의·90% 위험 (재사용 가능 공간 제외)", "Usage 80% warning / 90% critical (net of reclaimable space)"),
            STATUS_NA, "-", L("FRA 미구성", "FRA not configured"))
    else:
        pct = _num(rows[0].get("USED_PCT_NET"))
        add("archive_fra", "FRA " + L("사용률", "Usage"),
            L("V$RECOVERY_FILE_DEST 조회", "Query V$RECOVERY_FILE_DEST"),
            L("사용률 80% 주의·90% 위험 (재사용 가능 공간 제외)", "Usage 80% warning / 90% critical (net of reclaimable space)"),
            _pct_status(pct, 80, 90), L(f"순사용률 {fmt_num(pct,1)}%", f"net usage {fmt_num(pct,1)}%"))

    # ---- 19. RAC ----
    rows, err = await _q(connection, "SELECT COUNT(*) AS cnt FROM gv$instance")
    if err:
        add("rac", L("노드·서비스·인터커넥트", "Nodes/Services/Interconnect"),
            L("GV$INSTANCE 조회", "Query GV$INSTANCE"),
            L("계획된 노드·서비스 상태 일치, 비계획 eviction 없음", "Matches planned node/service state; no unplanned eviction"),
            STATUS_FAILED, "-", err)
    else:
        node_cnt = int(rows[0]["CNT"]) if rows else 1
        if node_cnt <= 1:
            add("rac", L("노드·서비스·인터커넥트", "Nodes/Services/Interconnect"),
                L("GV$INSTANCE 조회", "Query GV$INSTANCE"),
                L("계획된 노드·서비스 상태 일치, 비계획 eviction 없음", "Matches planned node/service state; no unplanned eviction"),
                STATUS_NA, "-", L("단일 인스턴스 (RAC 아님)", "Single instance (not RAC)"))
        else:
            add("rac", L("노드·서비스·인터커넥트", "Nodes/Services/Interconnect"),
                L("GV$INSTANCE 조회", "Query GV$INSTANCE"),
                L("계획된 노드·서비스 상태 일치, 비계획 eviction 없음", "Matches planned node/service state; no unplanned eviction"),
                STATUS_UNAVAILABLE, L(f"{node_cnt}노드 RAC 감지됨", f"RAC detected: {node_cnt} node(s)"),
                L("RAC 상세 점검(부하 편차·통신 지연 등)은 아직 구현되어 있지 않습니다", "Detailed RAC checks (load skew, interconnect latency, etc.) aren't implemented yet"))

    # ---- 20. ASM -- a query failure (no privilege, view absent on this
    #      edition, etc.) and "genuinely no ASM disk groups" are different
    #      facts and must not collapse into one ambiguous label: the former
    #      is 수집실패 (something couldn't be checked), the latter is
    #      해당없음 (checked, and ASM simply isn't in use here). ----
    rows, err = await _q(connection, "SELECT name, state, total_mb, free_mb FROM v$asm_diskgroup")
    if err:
        add("asm", L("디스크그룹·디스크", "Disk Groups/Disks"),
            L("V$ASM_DISKGROUP_STAT, V$ASM_DISK_STAT 조회", "Query V$ASM_DISKGROUP_STAT, V$ASM_DISK_STAT"),
            L("중복성·failgroup 기준 충족", "Meets redundancy/failgroup requirements"),
            STATUS_FAILED, "-", err)
    elif not rows:
        add("asm", L("디스크그룹·디스크", "Disk Groups/Disks"),
            L("V$ASM_DISKGROUP_STAT, V$ASM_DISK_STAT 조회", "Query V$ASM_DISKGROUP_STAT, V$ASM_DISK_STAT"),
            L("중복성·failgroup 기준 충족", "Meets redundancy/failgroup requirements"),
            STATUS_NA, "-", L("조회 결과 디스크그룹 없음 (ASM 미사용)", "Query succeeded with no disk groups (ASM not in use)"))
    else:
        worst_pct = None
        for r in rows:
            total = _num(r.get("TOTAL_MB"))
            free = _num(r.get("FREE_MB"))
            if total and total > 0:
                used_pct = round((1 - (free or 0) / total) * 100, 1)
                if worst_pct is None or used_pct > worst_pct:
                    worst_pct = used_pct
        add("asm", L("디스크그룹·디스크", "Disk Groups/Disks"),
            L("V$ASM_DISKGROUP_STAT, V$ASM_DISK_STAT 조회", "Query V$ASM_DISKGROUP_STAT, V$ASM_DISK_STAT"),
            L("중복성·failgroup 기준 충족", "Meets redundancy/failgroup requirements"),
            _pct_status(worst_pct, 80, 90), L(f"디스크그룹 {len(rows)}개, 최고 사용률 {fmt_num(worst_pct,1)}%", f"{len(rows)} disk group(s), peak usage {fmt_num(worst_pct,1)}%"),
            L("중복성 상세 점검은 이 앱 범위 밖입니다", "Detailed redundancy checks are outside this app's scope"))

    # ---- 21. Data Guard -- a PRIMARY role with no V$DATAGUARD_STATS rows
    #      does not, by itself, prove Data Guard is unconfigured (the view
    #      can simply have no recent stats yet); that's "확인불가"
    #      (insufficient basis to confirm), not a confident 해당없음. A
    #      failed role/stats query is 수집실패, and an actual STANDBY role
    #      is definite proof Data Guard IS configured, so it's shown as
    #      info regardless of whether lag stats happen to be present. ----
    role_rows, role_err = await _q(connection, "SELECT database_role FROM v$database")
    dg_rows, dg_err = await _q(connection, "SELECT transport_lag, apply_lag FROM v$dataguard_stats")
    role = role_rows[0]["DATABASE_ROLE"] if (role_rows and not role_err) else None
    lag_line = ", ".join(f"{r.get('TRANSPORT_LAG') or '-'} / {r.get('APPLY_LAG') or '-'}" for r in (dg_rows or [])) or "-"
    if role_err or role is None:
        add("dataguard", L("전송·적용·역할", "Transport/Apply/Role"),
            L("V$DATAGUARD_STATS, V$DATABASE 조회", "Query V$DATAGUARD_STATS, V$DATABASE"),
            L("전송·적용 지연이 목표 이내, DATUM_TIME 최신", "Transport/apply lag within target; DATUM_TIME current"),
            STATUS_FAILED, "-", role_err or L("V$DATABASE에서 역할을 확인하지 못했습니다", "Could not read a role from V$DATABASE"))
    elif dg_err:
        add("dataguard", L("전송·적용·역할", "Transport/Apply/Role"),
            L("V$DATAGUARD_STATS, V$DATABASE 조회", "Query V$DATAGUARD_STATS, V$DATABASE"),
            L("전송·적용 지연이 목표 이내, DATUM_TIME 최신", "Transport/apply lag within target; DATUM_TIME current"),
            STATUS_FAILED, "-", dg_err)
    elif role == "PRIMARY" and not dg_rows:
        add("dataguard", L("전송·적용·역할", "Transport/Apply/Role"),
            L("V$DATAGUARD_STATS, V$DATABASE 조회", "Query V$DATAGUARD_STATS, V$DATABASE"),
            L("전송·적용 지연이 목표 이내, DATUM_TIME 최신", "Transport/apply lag within target; DATUM_TIME current"),
            STATUS_UNAVAILABLE, "-",
            L("PRIMARY 역할이며 V$DATAGUARD_STATS에 조회된 행이 없어 Data Guard 구성 여부를 이 조회만으로 확정할 수 없습니다",
              "Role is PRIMARY with no V$DATAGUARD_STATS rows -- this alone can't confirm whether Data Guard is configured"))
    else:
        add("dataguard", L("전송·적용·역할", "Transport/Apply/Role"),
            L("V$DATAGUARD_STATS, V$DATABASE 조회", "Query V$DATAGUARD_STATS, V$DATABASE"),
            L("전송·적용 지연이 목표 이내, DATUM_TIME 최신", "Transport/apply lag within target; DATUM_TIME current"),
            STATUS_INFO, L(f"역할 {role} / 전송·적용 지연 {lag_line}", f"role {role} / transport·apply lag {lag_line}"),
            L("목표 지연 시간은 조직 정책에 따라 별도 판정 필요", "Judging against a lag target requires your own organization's policy"))

    # ---- 22. CDB / PDB ----
    if not is_cdb:
        add("cdbpdb", L("컨테이너 상태·점검 범위", "Container State/Scope"),
            L("V$PDBS 조회", "Query V$PDBS"),
            L("대상 PDB의 OPEN_MODE가 계획과 일치", "Target PDB's OPEN_MODE matches the plan"),
            STATUS_NA, "-", L("Non-CDB 구성", "Non-CDB architecture"))
    else:
        rows, err = await _q(connection, "SELECT con_id, name, open_mode FROM v$pdbs")
        if err:
            add("cdbpdb", L("컨테이너 상태·점검 범위", "Container State/Scope"),
                L("V$PDBS 조회", "Query V$PDBS"),
                L("대상 PDB의 OPEN_MODE가 계획과 일치", "Target PDB's OPEN_MODE matches the plan"),
                STATUS_FAILED, "-", err)
        else:
            not_open = [r for r in (rows or []) if r.get("OPEN_MODE") != "READ WRITE"]
            add("cdbpdb", L("컨테이너 상태·점검 범위", "Container State/Scope"),
                L("V$PDBS 조회", "Query V$PDBS"),
                L("대상 PDB의 OPEN_MODE가 계획과 일치", "Target PDB's OPEN_MODE matches the plan"),
                STATUS_OK if not not_open else STATUS_WARN,
                L(f"PDB {len(rows or [])}개, READ WRITE 아님 {len(not_open)}개", f"{len(rows or [])} PDB(s), {len(not_open)} not READ WRITE"))

    # ---- 23. AWR / ASH / ADDM ----
    add("deepperf", "AWR·ASH·ADDM",
        L("Diagnostics/Tuning Pack 사용 권한 확인 필요", "Requires confirmed Diagnostics/Tuning Pack license"),
        L("계약·라이선스상 사용 권한이 확인된 경우에만 사용", "Only usable when contract/license permission is confirmed"),
        STATUS_UNAVAILABLE, "-",
        L("이 앱은 라이선스 보유 여부를 확인할 수 없어 AWR/ASH/ADDM을 조회하지 않습니다 (기존 V$/DBA_ 뷰 기반 항목으로 대체)",
          "This app can't confirm license status, so AWR/ASH/ADDM are never queried (replaced above by plain V$/DBA_ view checks)"))

    return items, metrics, {"logMode": log_mode, "isCdb": is_cdb}


_DONUT_ORDER = (STATUS_OK, STATUS_WARN, STATUS_DANGER, STATUS_FAILED, STATUS_UNAVAILABLE, STATUS_NA, STATUS_INFO)
_DONUT_COLOR = {
    STATUS_OK: "#299f83", STATUS_WARN: "#e7ad43", STATUS_DANGER: "#cb514b", STATUS_FAILED: "#b5541f",
    STATUS_UNAVAILABLE: "#9167af", STATUS_NA: "#c3ccd8", STATUS_INFO: "#6084bb",
}


def _meter_color(pct, warn_at, danger_at):
    if pct is None:
        return "#c3ccd8"
    if pct >= danger_at:
        return "#c14d45"
    if pct >= warn_at:
        return "#d4a040"
    return "#2c9f98"


def _render_check_report_html(meta: dict, items: list, metrics: dict, lang: str) -> str:
    L = lambda ko, en: ko if lang == "ko" else en
    lk = "ko" if lang == "ko" else "en"

    counts = {}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    overall = STATUS_OK
    if counts.get(STATUS_DANGER) or counts.get(STATUS_FAILED):
        overall = STATUS_DANGER
    elif counts.get(STATUS_WARN):
        overall = STATUS_WARN

    def status_badge(status):
        cls = _STATUS_CLASS.get(status, "info")
        label = _STATUS_LABEL[lang if lang in ("ko", "en") else "en"].get(status, status)
        return f'<span class="badge {cls}">{escape_html(label)}</span>'

    counts_line = " · ".join(
        f"{_STATUS_LABEL['ko' if lang=='ko' else 'en'][s]} {counts.get(s, 0)}"
        for s in (STATUS_OK, STATUS_WARN, STATUS_DANGER, STATUS_FAILED, STATUS_UNAVAILABLE, STATUS_NA, STATUS_INFO)
    )

    # ---- Dashboard: cards / donut / usage meters / priority / SQL chart --
    # all built from `items`'s own status counts and the raw `metrics`
    # captured inline by the checks above (see _collect_checks) -- never by
    # re-parsing the detail table's rendered text. A missing/uncomputable
    # number always renders as an explicit "unavailable" reason, never a
    # fabricated 0 or 0%. ----
    def meter_row(label_html, pct, warn_at, danger_at, reason_html=None):
        if pct is None:
            shown = reason_html if reason_html else escape_html(L("확인불가", "Unavailable"))
            return (f'<div class="meter"><div class="meter-label"><span>{label_html}</span>'
                     f'<b>{shown}</b></div><div class="track">'
                     f'<div class="fill" style="width:0%;background:#c3ccd8"></div></div></div>')
        clamped = max(0.0, min(100.0, pct))
        color = _meter_color(pct, warn_at, danger_at)
        return (f'<div class="meter"><div class="meter-label"><span>{label_html}</span>'
                f'<b>{fmt_num(pct,1)}%</b></div><div class="track">'
                f'<div class="fill" style="width:{clamped:.2f}%;background:{color}"></div></div></div>')

    danger_count = counts.get(STATUS_DANGER, 0)
    warn_count = counts.get(STATUS_WARN, 0)
    total_items = len(items)

    # -- Card 1: priority review count (danger + warn among all items) --
    review_count = danger_count + warn_count
    card1_value = f'{review_count}<span style="font-size:14px">{escape_html(L("건",""))}</span>'
    card1_note = escape_html(L(f"위험 {danger_count} · 주의 {warn_count}", f"Critical {danger_count} · Warning {warn_count}"))

    # -- Card 2: CPU usage (V$SYSMETRIC instantaneous reading) --
    cpu_metric = metrics.get("cpu") or {}
    cpu_pct = cpu_metric.get("pct") if not cpu_metric.get("error") else None
    if cpu_metric.get("error"):
        card2_value, card2_note = "-", escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
    elif cpu_pct is None:
        card2_value, card2_note = "-", escape_html(L("확인불가", "Unavailable"))
    else:
        card2_value = f'{fmt_num(cpu_pct,1)}<span style="font-size:14px">%</span>'
        card2_note = escape_html(L("V$SYSMETRIC 순간값 · 평균 구간 미기재", "V$SYSMETRIC instantaneous reading -- no averaging window recorded"))

    # -- Card 3: session usage vs. its own current limit --
    res_metric = metrics.get("resourceLimits") or {}
    sessions = res_metric.get("sessions") if not res_metric.get("error") else None
    if res_metric.get("error"):
        card3_value, card3_note = "-", escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
    elif not sessions:
        card3_value, card3_note = "-", escape_html(L("확인불가", "Unavailable"))
    else:
        used, limit, pct, unlimited = sessions.get("used"), sessions.get("limit"), sessions.get("pct"), sessions.get("unlimited")
        limit_text = escape_html(L("무제한", "Unlimited")) if (unlimited or limit is None) else fmt_num(limit, 0)
        card3_value = f'{fmt_num(used,0)}<span style="font-size:14px"> / {limit_text}</span>'
        card3_note = (escape_html(L(f"한도 대비 {fmt_num(pct,1)}%", f"{fmt_num(pct,1)}% of limit")) if pct is not None
                       else escape_html(L("한도 UNLIMITED -- 사용률 미계산", "Limit is UNLIMITED -- % not computed")))

    # -- Card 4: peak tablespace usage vs. its own max size --
    ts_metric = metrics.get("tablespace") or {}
    ts_pct = ts_metric.get("worstPct") if not ts_metric.get("error") else None
    if ts_metric.get("error"):
        card4_value, card4_note = "-", escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
    elif ts_pct is None:
        card4_value, card4_note = "-", escape_html(L("확인불가 (대상 테이블스페이스 없음)", "Unavailable (no tablespace found)"))
    else:
        card4_value = f'{fmt_num(ts_pct,1)}<span style="font-size:14px">%</span>'
        card4_note = escape_html(f"{ts_metric.get('worstName')} · " + L("최대 크기 대비", "vs. max size"))

    cards_html = "".join([
        f'<div class="card{" alert" if review_count > 0 else ""}"><div class="label">{escape_html(L("우선 검토 항목","Priority Review Items"))}</div><strong>{card1_value}</strong><small>{card1_note}</small></div>',
        f'<div class="card"><div class="label">{escape_html(L("CPU 사용률","CPU Usage"))}</div><strong>{card2_value}</strong><small>{card2_note}</small></div>',
        f'<div class="card"><div class="label">{escape_html(L("세션 사용 / 한도","Sessions Used / Limit"))}</div><strong>{card3_value}</strong><small>{card3_note}</small></div>',
        f'<div class="card"><div class="label">{escape_html(L("테이블스페이스 최고 사용률","Peak Tablespace Usage"))}</div><strong>{card4_value}</strong><small>{card4_note}</small></div>',
    ])

    # -- Donut: status distribution, drawn with the SVG stroke-dasharray/
    #    pathLength trick so counts (not angles eyeballed by hand) drive
    #    the arcs; total always equals sum(counts) since counts come
    #    straight from `items`. --
    offset = 0
    circle_parts = []
    for s in _DONUT_ORDER:
        c = counts.get(s, 0)
        if c <= 0:
            continue
        gap = total_items - c
        off_attr = f' stroke-dashoffset="-{offset}"' if offset else ""
        circle_parts.append(
            f'<circle cx="70" cy="70" r="52" pathLength="{total_items}" stroke="{_DONUT_COLOR[s]}" '
            f'stroke-dasharray="{c} {gap}"{off_attr}/>'
        )
        offset += c
    donut_aria = ", ".join(f"{_STATUS_LABEL[lk][s]} {counts.get(s,0)}" for s in _DONUT_ORDER)
    donut_key = "".join(
        f'<div><i class="dot" style="background:{_DONUT_COLOR[s]}"></i>{escape_html(_STATUS_LABEL[lk][s])}<b>{counts.get(s,0)}</b></div>'
        for s in _DONUT_ORDER
    )
    donut_panel_html = f'''<div class="panel"><h3>{escape_html(L(f"전체 {total_items}개 항목의 상태 분포", f"Status distribution across all {total_items} items"))}</h3><div class="distribution">
<svg viewBox="0 0 140 140" role="img" aria-label="{escape_html(L(f"{total_items}개 점검항목: {donut_aria}", f"{total_items} check items: {donut_aria}"))}">
<circle cx="70" cy="70" r="52" fill="none" stroke="#eef2f6" stroke-width="15"/>
<g transform="rotate(-90 70 70)" fill="none" stroke-width="15">{"".join(circle_parts)}</g>
<text x="70" y="68" text-anchor="middle" font-size="29" font-weight="bold" fill="#213b59">{total_items}</text>
<text x="70" y="87" text-anchor="middle" font-size="10" fill="#697b90">{escape_html(L("전체 점검항목","Total items"))}</text>
</svg>
<div class="key">{donut_key}</div></div>
<p class="metric-note">{escape_html(L("상태 건수의 합은 전체 점검항목 수와 같습니다. 정상 비율을 별도의 건강 점수로 환산하지 않았습니다.","Status counts sum to the total item count. The OK ratio is not converted into a separate health score."))}</p></div>'''

    # -- Usage meters: memory, processes, sessions, worst tablespace, TEMP.
    #    Each label states its own denominator (current limit vs. max
    #    extend size) so the two are never conflated; a None pct always
    #    means "not computed" (unlimited/zero denominator/no basis), never
    #    a 0% bar. --
    mem_metric = metrics.get("memory") or {}
    mem_pct = mem_metric.get("pct") if not mem_metric.get("error") else None
    mem_source_label = {
        "MEMORY_TARGET": L("MEMORY_TARGET 대비", "vs. MEMORY_TARGET"),
        "MEMORY_MAX_TARGET": L("MEMORY_MAX_TARGET 대비", "vs. MEMORY_MAX_TARGET"),
        "SGA_MAX_SIZE+PGA_AGGREGATE_TARGET": L("SGA_MAX_SIZE+PGA_TARGET 대비", "vs. SGA_MAX_SIZE+PGA_TARGET"),
    }.get(mem_metric.get("targetSource"))
    mem_label = escape_html(L("메모리(SGA+PGA)", "Memory (SGA+PGA)")) + (f" · {escape_html(mem_source_label)}" if mem_source_label else "")
    if mem_metric.get("error"):
        mem_reason = escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
    elif mem_pct is None:
        mem_reason = escape_html(L("확인불가 (목표 메모리 값 없음)", "Unavailable (no target value)"))
    else:
        mem_reason = None

    def resource_row(res_dict, res_error, name_ko, name_en):
        name = escape_html(L(name_ko, name_en))
        if res_error:
            return f"{name} · {escape_html(L('한도 대비','vs. limit'))}", None, escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
        if not res_dict:
            return f"{name} · {escape_html(L('한도 대비','vs. limit'))}", None, escape_html(L("확인불가", "Unavailable"))
        used, limit, pct, unlimited = res_dict.get("used"), res_dict.get("limit"), res_dict.get("pct"), res_dict.get("unlimited")
        limit_text = escape_html(L("무제한", "Unlimited")) if (unlimited or limit is None) else fmt_num(limit, 0)
        label = f"{name} · {fmt_num(used,0)}/{limit_text}"
        if pct is not None:
            return label, pct, None
        reason = escape_html(L("한도 UNLIMITED -- 사용률 미계산", "Limit is UNLIMITED -- % not computed")) if unlimited else escape_html(L("확인불가 (한도 값 없음)", "Unavailable (no limit value)"))
        return label, None, reason

    proc_label, proc_pct, proc_reason = resource_row(
        (res_metric.get("processes") if not res_metric.get("error") else None), res_metric.get("error"),
        "프로세스", "Processes")
    sess_label, sess_pct, sess_reason = resource_row(
        (res_metric.get("sessions") if not res_metric.get("error") else None), res_metric.get("error"),
        "세션", "Sessions")

    ts_label_base = escape_html(ts_metric.get("worstName")) if (ts_metric.get("worstName") and not ts_metric.get("error")) else escape_html(L("테이블스페이스","Tablespace"))
    ts_label = f"{ts_label_base} · {escape_html(L('최대 크기 대비','vs. max size'))}"
    if ts_metric.get("error"):
        ts_reason = escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
    elif ts_pct is None:
        ts_reason = escape_html(L("확인불가 (대상 없음)", "Unavailable (none found)"))
    else:
        ts_reason = None

    temp_metric = metrics.get("temp") or {}
    temp_pct = temp_metric.get("worstPct") if not temp_metric.get("error") else None
    temp_label_base = escape_html(temp_metric.get("worstName")) if (temp_metric.get("worstName") and not temp_metric.get("error")) else "TEMP"
    temp_label = f"{temp_label_base} · {escape_html(L('최대 크기 대비','vs. max size'))}"
    if temp_metric.get("error"):
        temp_reason = escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))
    elif temp_pct is None:
        temp_reason = escape_html(L("확인불가 (대상 없음)", "Unavailable (none found)"))
    else:
        temp_reason = None

    meters_html = "".join([
        meter_row(mem_label, mem_pct, 75, 90, mem_reason),
        meter_row(proc_label, proc_pct, 80, 90, proc_reason),
        meter_row(sess_label, sess_pct, 80, 90, sess_reason),
        meter_row(ts_label, ts_pct, 80, 90, ts_reason),
        meter_row(temp_label, temp_pct, 85, 95, temp_reason),
    ])
    meters_panel_html = f'''<div class="panel"><h3>{escape_html(L("용량·자원 현황","Capacity/Resource Usage"))} <small style="font-weight:normal;color:#74849a">0-100%</small></h3>{meters_html}
<p class="metric-note">{escape_html(L("각 막대의 분모가 다릅니다. 메모리는 목표 메모리 설정값이 없으면 계산하지 않습니다. 프로세스·세션은 현재 한도 대비, 테이블스페이스·TEMP는 최대 확장 크기 대비이며 실제 스토리지 여유를 보장하지 않습니다.","Each bar's denominator differs. Memory is skipped when no target value is set. Processes/sessions are vs. their current limit; tablespace/TEMP are vs. max extend size, which doesn't guarantee actual storage headroom."))}</p></div>'''

    # -- Priority review: the actual danger/warn items, most severe first
    #    -- never a fixed single topic (e.g. backup) hardcoded regardless
    #    of what this check actually found. --
    danger_items = sorted([it for it in items if it["status"] == STATUS_DANGER], key=lambda it: it["no"])
    warn_items = sorted([it for it in items if it["status"] == STATUS_WARN], key=lambda it: it["no"])
    ordered_priority = danger_items + warn_items
    top_priority = ordered_priority[:5]
    if not top_priority:
        priority_html = (
            f'<div class="priority ok"><strong>{escape_html(L("우선 확인 · 위험·주의 항목 없음","Priority Review · No critical/warning items"))}</strong>'
            f'<p>{escape_html(L("이번 점검에서 위험 또는 주의로 판정된 항목이 없습니다.","No items were judged critical or warning in this check."))}</p></div>'
        )
    else:
        entry_parts = []
        for it in top_priority:
            period_suffix = f" ({escape_html(it['period'])})" if it.get("period") else ""
            note_text = escape_html(it["note"] or L("담당 DBA 검토 필요", "Needs DBA review"))
            entry_parts.append(
                f'<p>{status_badge(it["status"])} <b>{escape_html(it["title"])}</b> -- {escape_html(it["measured"])}{period_suffix}'
                f'<br><small>{note_text}</small></p>'
            )
        more_note = ""
        if len(ordered_priority) > len(top_priority):
            more_note = (f'<p class="metric-note">{escape_html(L(f"상위 {len(top_priority)}건만 표시 (전체 {len(ordered_priority)}건은 상세 표·이슈 표에서 확인)", f"Showing top {len(top_priority)} of {len(ordered_priority)} -- see the detail/issues tables below for the rest"))}</p>')
        priority_html = (
            f'<div class="priority"><strong>{escape_html(L(f"우선 확인 · 위험 {len(danger_items)}건 · 주의 {len(warn_items)}건", f"Priority Review · Critical {len(danger_items)} · Warning {len(warn_items)}"))}</strong>'
            f'{"".join(entry_parts)}{more_note}</div>'
        )

    # -- Top SQL bar chart: one common linear scale (0 -> the slowest
    #    query's own cumulative elapsed time), same cumulative-since-
    #    startup figure the detail table already shows for check 09 --
    #    never a single execution's time or this check's own window. --
    top_sql = metrics.get("topSql")
    sql_error = top_sql.get("error") if isinstance(top_sql, dict) else None
    sql_list = top_sql if isinstance(top_sql, list) else []
    if sql_error:
        sql_body = f'<p class="metric-note">{escape_html(L("확인불가 (조회 실패)", "Unavailable (query failed)"))}</p>'
    elif not sql_list:
        sql_body = f'<p class="metric-note">{escape_html(L("조회된 SQL이 없습니다.","No SQL found."))}</p>'
    else:
        max_sec = max((s.get("elapsedSec") or 0) for s in sql_list)
        sql_rows = []
        for s in sql_list:
            sec = s.get("elapsedSec")
            width = (sec / max_sec * 100) if (max_sec and max_sec > 0 and sec is not None) else 0
            sql_rows.append(
                f'<div class="sql-row"><code>{escape_html(s.get("sqlId") or "-")}</code>'
                f'<div class="track"><div class="fill" style="width:{width:.3f}%"></div></div>'
                f'<b>{fmt_num(sec,1)} s</b></div>'
            )
        sql_body = "".join(sql_rows) + (
            f'<p class="metric-note">{escape_html(L(f"0에서 시작하는 공통 선형 척도 · 최댓값 {fmt_num(max_sec,1)}초. 공유 풀에 남은 SQL의 누적 실행시간이며, 단일 실행이나 이번 점검 구간만의 실행시간이 아닙니다.", f"Common linear scale starting at 0 · max {fmt_num(max_sec,1)}s. Cumulative elapsed time still in the shared pool -- not a single execution or this check window alone."))}</p>'
        )
    sql_panel_html = f'<div class="panel" style="margin-top:16px"><h3>{escape_html(L("조회된 주요 SQL · 누적 실행시간","Top SQL Found · Cumulative Elapsed Time"))}</h3>{sql_body}</div>'

    dashboard_html = f'''<section class="dashboard" aria-label="{escape_html(L("점검 요약 대시보드","Check summary dashboard"))}">
<div class="dashboard-head"><h2>{escape_html(L("점검 요약","Check Summary"))}</h2><p>{escape_html(L(f"이번 점검 결과 기준 · {meta['refTimeStr']}", f"From this check's own results · {meta['refTimeStr']}"))}</p></div>
<div class="cards">{cards_html}</div>
<div class="panels">{donut_panel_html}{meters_panel_html}</div>
{priority_html}
{sql_panel_html}
</section>'''

    rows_by_cat = {}
    for it in items:
        rows_by_cat.setdefault(it["category"], []).append(it)

    section_html = []
    for cat in _CATEGORY_ORDER:
        cat_items = rows_by_cat.get(cat)
        if not cat_items:
            continue
        body_rows = "".join(
            f"""<tr>
              <td>{it['no']}</td>
              <td><b>{escape_html(it['title'])}</b><small>{escape_html(it['method'])}</small></td>
              <td>{escape_html(it['criteria'])}</td>
              <td>{escape_html(it['measured'])}{f'<small>{escape_html(it["period"])}</small>' if it.get('period') else ''}</td>
              <td>{status_badge(it['status'])}</td>
              <td>{escape_html(it['note'])}</td>
            </tr>"""
            for it in cat_items
        )
        section_html.append(f"""
        <div class="table-wrap"><table class="detail">
          <thead><tr><th>#</th><th>{escape_html(L('점검항목 / 확인방법','Item / Method'))}</th>
            <th>{escape_html(L('판단 기준','Criteria'))}</th><th>{escape_html(L('측정값·결과','Measured / Result'))}</th>
            <th>{escape_html(L('상태','Status'))}</th><th>{escape_html(L('비고','Notes'))}</th></tr></thead>
          <tbody>{body_rows}</tbody>
        </table></div>""")

    issues = [it for it in items if it["status"] in (STATUS_WARN, STATUS_DANGER, STATUS_FAILED)]
    if issues:
        issue_rows = "".join(
            f"""<tr><td>{it['no']}</td><td>{escape_html(_CATEGORY_LABEL['ko' if lang=='ko' else 'en'][it['category']])}</td>
              <td>{escape_html(it['title'])}</td><td>{status_badge(it['status'])}</td>
              <td>{escape_html(it['measured'])}</td><td>{escape_html(it['note'] or L('담당 DBA 검토 필요','Needs DBA review'))}</td></tr>"""
            for it in issues
        )
        issues_html = f"""<table class="detail"><thead><tr><th>#</th><th>{escape_html(L('영역','Area'))}</th>
          <th>{escape_html(L('항목','Item'))}</th><th>{escape_html(L('상태','Status'))}</th>
          <th>{escape_html(L('측정값','Measured'))}</th><th>{escape_html(L('권장 조치','Recommended Action'))}</th></tr></thead>
          <tbody>{issue_rows}</tbody></table>"""
    else:
        issues_html = f'<p class="note">{escape_html(L("발견된 이슈가 없습니다 (주의·위험·수집실패 항목 없음).","No issues found (no warning/critical/failed items)."))}</p>'

    title = L("Oracle Database 점검레포트", "Oracle Database Check Report")
    html_lang = "ko" if lang == "ko" else "en"
    return f"""<!doctype html>
<html lang="{html_lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape_html(title)}</title>
<style>
:root{{--ink:#172b40;--muted:#607185;--line:#d8e0e8;--accent:#126b75}}
*{{box-sizing:border-box}}body{{margin:0;background:#edf1f5;color:var(--ink);font:14px/1.6 "Malgun Gothic","Segoe UI",sans-serif}}
main{{max-width:1120px;margin:28px auto;background:#fff;padding:40px;box-shadow:0 6px 30px #172b4010}}
header{{border-top:6px solid var(--accent);padding-top:20px}}.eyebrow{{letter-spacing:2px;color:var(--accent);font-size:11px;font-weight:700}}
h1{{font-size:26px;margin:8px 0}}h2{{font-size:18px;margin:28px 0 10px}}h2 span{{color:var(--accent);font-size:13px;margin-right:8px}}
.sub,.note{{color:var(--muted);font-size:12px}}
.meta-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}}
.meta-field{{border:1px solid var(--line);padding:9px 11px}}.meta-label{{font-size:11px;color:var(--muted);font-weight:bold}}
.summary{{display:flex;align-items:center;gap:16px;border:1px solid var(--line);padding:14px 16px;margin:16px 0;flex-wrap:wrap}}
.overall-badge{{font-size:15px;font-weight:800;padding:6px 14px;border-radius:6px}}
table.detail{{width:100%;border-collapse:collapse;table-layout:fixed;margin:8px 0 18px;font-size:12.5px}}
table.detail th{{background:#edf3f5;color:#234653;text-align:left;padding:8px 7px;border:1px solid var(--line)}}
table.detail td{{vertical-align:top;padding:9px 7px;border:1px solid var(--line);overflow-wrap:anywhere}}
table.detail td small{{display:block;color:var(--muted);font-size:10.5px;margin-top:3px}}
.badge{{display:inline-block;font-size:11px;font-weight:700;border-radius:4px;padding:3px 8px;white-space:nowrap}}
.badge.ok{{background:#e4f4ec;color:#17643b}}.badge.warn{{background:#fff2cf;color:#795700}}
.badge.danger{{background:#fde6e6;color:#a22424}}.badge.na{{background:#f3f3f3;color:#777}}.badge.info{{background:#e7eef8;color:#2c527a}}
.callout{{padding:12px 15px;background:#f0f7f8;border-left:3px solid var(--accent);font-size:12px;margin:14px 0}}
.table-wrap{{overflow-x:auto}}
footer{{border-top:1px solid var(--line);margin-top:24px;padding-top:12px;font-size:11px;color:var(--muted)}}
@media print{{body{{background:#fff}}main{{box-shadow:none;margin:0}}}}
</style><style>
body{{background:#e9eef5;color:#1c3049}}main{{max-width:1200px;padding:44px;border-radius:16px}}header{{border:0;background:#142b48;color:#fff;margin:-44px -44px 28px;padding:32px 44px;border-radius:16px 16px 0 0;position:relative}}header .eyebrow{{color:#7ce0d0}}header .sub,header .note{{color:#d2deee}}header .meta-field{{border-color:#3a4e68;background:#203955;border-radius:8px}}header .meta-label{{color:#b3c8dd}}header .summary{{border-color:#3a4e68;border-radius:8px}}header .callout{{background:#233e5a;color:#d4e3f4;border-color:#6bd4c5}}h1{{font-size:30px}}h2{{margin-top:32px}}h2 span{{font-weight:bold}}.dashboard{{margin:22px 0 32px}}.dashboard-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.dashboard-head p{{color:#67798e;font-size:12px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.card,.panel{{border:1px solid #dde5ef;border-radius:12px;padding:18px;background:white}}.card .label{{font-size:12px;color:#63758c}}.card strong{{display:block;font-size:30px;line-height:1.4;color:#1b3554}}.card small{{font-size:11px;color:#6c7e92}}.card.alert{{background:#fff5f4;border-color:#efc9c3}}.card.alert strong{{color:#b43935}}.panels{{display:grid;grid-template-columns:1fr 1.4fr;gap:16px;margin:16px 0}}.panel h3{{font-size:15px;margin:0 0 14px}}.distribution{{display:flex;align-items:center;gap:22px}}.distribution svg{{width:148px;flex-shrink:0}}.key{{font-size:12px;display:grid;gap:7px;width:100%}}.key div{{display:flex;align-items:center;gap:8px}}.key b{{margin-left:auto}}.dot{{width:9px;height:9px;border-radius:50%;display:inline-block}}.meter{{margin:13px 0}}.meter-label{{display:flex;justify-content:space-between;font-size:12px;margin-bottom:5px}}.track{{height:9px;border-radius:5px;background:#ecf1f7;overflow:hidden}}.fill{{height:100%;background:#2c9f98;border-radius:5px}}.metric-note{{font-size:11px;color:#66778a;line-height:1.7;margin:12px 0 0}}.priority{{border-left:4px solid #c14d45;background:#fff5f3;border-radius:8px;padding:16px 20px}}.priority strong{{color:#9d332e}}.priority p{{font-size:12px;margin:6px 0}}.priority.ok{{border-left-color:#2c9f98;background:#f2faf8}}.priority.ok strong{{color:#1c7d6d}}.sql-row{{display:grid;grid-template-columns:140px 1fr 75px;gap:12px;align-items:center;margin:12px 0;font-size:12px}}.sql-row code{{font-size:11px}}.sql-row .fill{{background:#657ab2}}.print-tools{{max-width:1200px;margin:16px auto;display:flex;justify-content:space-between;align-items:center;font-size:12px;color:#607185}}.print-tools button{{background:#193c5a;color:white;border:0;padding:9px 18px;border-radius:6px;cursor:pointer}}table.detail{{font-size:12px}}table.detail th{{background:#eef3f9;border:0;border-bottom:2px solid #ced9e6}}table.detail td{{border:0;border-bottom:1px solid #e0e7ef}}table.detail th:nth-child(1){{width:5%}}table.detail th:nth-child(2){{width:22%}}table.detail th:nth-child(3){{width:21%}}table.detail th:nth-child(4){{width:25%}}table.detail th:nth-child(5){{width:9%}}table.detail th:nth-child(6){{width:18%}}table.detail tbody tr:nth-child(even){{background:#f8fafd}}.table-wrap{{border:1px solid #e0e7ef;border-radius:8px;margin:10px 0 16px}}.table-wrap table{{margin:0}}.badge{{white-space:normal}}thead{{display:table-header-group}}tr{{break-inside:avoid}}h2,h3{{break-after:avoid}}.panel,.card,.priority{{break-inside:avoid}}footer{{line-height:1.8}}@page{{size:A4 portrait;margin:12mm}}@media print{{.print-tools{{display:none}}body{{background:#fff}}main{{padding:0;border-radius:0;max-width:none;margin:0}}header{{margin:0 0 18px;padding:18px;border-radius:0}}h1{{font-size:23px}}h2{{font-size:16px}}.cards{{gap:7px}}.card{{padding:10px}}.card strong{{font-size:24px}}.panel{{padding:12px}}.distribution{{gap:10px}}.distribution svg{{width:105px}}.key{{font-size:10px}}.panels{{gap:10px}}table.detail{{font-size:9px}}table.detail td small{{font-size:8px}}table.detail th,table.detail td{{padding:6px 4px}}.badge{{font-size:9px;padding:2px 4px}}.table-wrap{{overflow:visible;border-radius:0}}.sql-row{{font-size:10px}}.meta-grid{{gap:6px}}.meta-field{{font-size:10px}}*{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}@media screen and (max-width:800px){{main{{padding:20px;margin:12px;border-radius:12px}}header{{margin:-20px -20px 20px;padding:22px;border-radius:12px 12px 0 0}}.cards{{grid-template-columns:repeat(2,1fr)}}.panels{{grid-template-columns:1fr}}.meta-grid{{grid-template-columns:1fr}}.table-wrap{{overflow-x:auto}}table.detail{{min-width:760px}}.print-tools{{margin:12px}}.sql-row{{grid-template-columns:125px 1fr 65px}}}}
</style></head>
<body><div class="print-tools"><span>{escape_html(L("OraPulse · 점검레포트","OraPulse · Check Report"))}</span><button onclick="window.print()">{escape_html(L("인쇄 / PDF 저장","Print / Save as PDF"))}</button></div><main>
<header>
  <div class="eyebrow">ORAPULSE &middot; DATABASE CHECK REPORT</div>
  <h1>{escape_html(title)}</h1>
  <p class="sub">{escape_html(meta['instanceTarget'])}</p>
  <div class="meta-grid">
    <div class="meta-field"><div class="meta-label">{escape_html(L('점검 기준시각','Reference Time'))}</div>{escape_html(meta['refTimeStr'])}</div>
    <div class="meta-field"><div class="meta-label">{escape_html(L('수집 시작·종료','Collection Start/End'))}</div>{escape_html(meta['collectStartStr'])} &rarr; {escape_html(meta['collectEndStr'])}</div>
    <div class="meta-field"><div class="meta-label">{escape_html(L('시간대','Timezone'))}</div>{escape_html(meta['tzStr'])}</div>
  </div>
  <div class="summary">
    <span class="overall-badge badge {_STATUS_CLASS.get(overall,'info')}">{escape_html(L('종합상태','Overall'))}: {escape_html(_STATUS_LABEL['ko' if lang=='ko' else 'en'][overall])}</span>
    <span class="note">{escape_html(counts_line)}</span>
  </div>
  <div class="callout">{escape_html(L(
    '전월 대비: 비교 자료 없음 (이전 보고서가 보관되어 있지 않아 추세 비교를 제공하지 않습니다).',
    'Vs. last month: no comparison data (no prior report is stored, so no trend comparison is shown).'
  ))}</div>
</header>
{dashboard_html}
<section><h2><span>01</span>{escape_html(L('영역별 상세 점검 결과','Detailed Results by Area'))}</h2>
{''.join(section_html)}
</section>

<section><h2><span>02</span>{escape_html(L('발견 이슈 및 권장 조치','Issues Found & Recommended Actions'))}</h2>
{issues_html}
</section>

<footer>
  <p>{escape_html(L(
    'AWR·ASH·ADDM 등 Diagnostics/Tuning Pack 기능은 라이선스 보유 여부가 확인되지 않아 포함하지 않았습니다. '
    '"확인불가"/"해당없음" 항목은 결함이 아니라, 이 앱의 DB 접속만으로는 판단할 수 없거나 이 환경에 해당하지 않는 항목입니다.',
    'Diagnostics/Tuning Pack features (AWR/ASH/ADDM) are excluded because license status cannot be confirmed. '
    '"Unavailable"/"N/A" items are not defects -- they simply cannot be judged from a DB connection alone, or do not apply to this environment.'
  ))}</p>
  <p>OraPulse &middot; {escape_html(L('생성','Generated'))} {escape_html(meta['generatedStr'])}</p>
</footer>
</main></body></html>"""


# Ties everything together for the /api/generate-report endpoint. Opens
# exactly one connection at click_dt (the moment the button was clicked --
# see routes_report.py), runs the fixed checklist above against it, and
# renders the result. Never raises for an individual check's own failure
# (see _q()); only a failure to connect at all aborts the whole report.
async def generate_check_report(creds: dict, click_dt: datetime, lang: str) -> str:
    connect_string = dsn_from_creds(creds)
    connection = await oracledb.connect_async(
        user=creds["account"], password=creds["password"], dsn=connect_string
    )
    collect_start = datetime.now()
    try:
        items, metrics, _ctx = await _collect_checks(connection, creds, lang)
    finally:
        try:
            await connection.close()
        except Exception as close_err:
            print(f"[report] error while closing check-report connection: {close_err}")
    collect_end = datetime.now()

    tz_str = click_dt.astimezone().strftime("%Z (UTC%z)") if click_dt.tzinfo is None else click_dt.strftime("%Z (UTC%z)")
    # "SID"/"Service Name" are used as-is in both languages, matching how
    # the connect screen and Help tab already refer to them untranslated.
    connect_type_label = "Service Name" if creds.get("connectType") == "service_name" else "SID"
    meta = {
        "instanceTarget": f"{creds['account']}@{creds['ip']}:{creds['port']}:{creds['sid']} ({connect_type_label})",
        "refTimeStr": fmt_date_time(click_dt),
        "collectStartStr": fmt_date_time(collect_start),
        "collectEndStr": fmt_date_time(collect_end),
        "tzStr": tz_str,
        "generatedStr": fmt_date_time(datetime.now()),
    }
    return _render_check_report_html(meta, items, metrics, lang)
