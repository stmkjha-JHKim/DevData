"""tuning.py -- rule-based tuning advisor for the "Tuning" dashboard tab.

Deliberately license-free: every query here reads only V$SYSSTAT,
V$LIBRARYCACHE, V$SYSTEM_EVENT, V$SQL, DBA_DATA_FILES, DBA_FREE_SPACE and
DBA_OBJECTS (plus V$SESSION for blocking sessions, already used elsewhere
in this app) -- all available on Standard Edition 2 with no Diagnostics/
Tuning Pack, and on any Oracle version, unlike AWR/ADDM
(DBA_HIST_*/DBA_ADVISOR_*/V$ACTIVE_SESSION_HISTORY), which requires an
Enterprise Edition Diagnostics/Tuning Pack license this app doesn't
assume the connected instance has (same reasoning as report.py and the
Ops tab).

Some of the checks below (buffer cache hit ratio, library cache hit
ratio, hard parse ratio, disk sorts, top wait events) are *rate* checks:
they need the *increase* in a cumulative since-startup counter between
two points in time (the same statspack-style approach real AWR/Statspack
reports use), not the raw cumulative value, since a long-uptime instance
can have decades of old, since-fixed history diluting a fresh problem
into an innocuous-looking cumulative ratio. That requires comparing
against a previous snapshot -- so this module keeps exactly one
("the last check for this DB") on disk, the same encrypted-blob pattern
favorites.py already uses, overwriting it on every check. A rule that
needs a previous snapshot and doesn't have a matching one yet (first-ever
check for this DB, or the DB was switched) is simply reported as
"not enough history yet" rather than guessed at.

The remaining checks (tablespace usage, invalid objects, blocking
sessions, slow SQL) reflect the database's current state directly and
don't need any history.

Findings are returned as structured data (rule id + severity + numeric
values), not pre-rendered text -- the dashboard's own i18n layer turns
each one into a localized title/message, the same "server sends data,
client renders it" split every other live tab in this app already uses
(unlike report.py's Weekly Report, which renders its own bilingual HTML
because it's a standalone downloaded file, not part of the live page).
"""

import base64
import json
import os
import secrets
import time
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from paths import DATA_DIR

SNAPSHOT_FILE = DATA_DIR / "tuning-last-snapshot.enc"
KEY_FILE = DATA_DIR / ".tuning-key"

# Below this many elapsed seconds since the previous snapshot, rate-based
# ratios are considered too noisy to be meaningful (a handful of parses in
# a couple of seconds can swing a "ratio" wildly) and are reported as
# "not enough history yet" instead, the same as having no previous
# snapshot at all.
MIN_INTERVAL_SECONDS = 5

# ---------------------------------------------------------------------
# Encryption -- same AES-256-GCM single-blob pattern as favorites.py,
# with its own key file (each of this app's local stores keeps its own
# key, so removing/rotating one never affects the others).
# ---------------------------------------------------------------------
_cached_key: Optional[bytes] = None


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


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


def _encrypt(value) -> str:
    iv = secrets.token_bytes(12)
    combined = AESGCM(_get_encryption_key()).encrypt(iv, json.dumps(value).encode("utf-8"), None)
    ciphertext, tag = combined[:-16], combined[-16:]
    return base64.b64encode(iv + tag + ciphertext).decode("ascii")


def _decrypt(b64: str):
    raw = base64.b64decode(b64)
    iv, tag, ciphertext = raw[:12], raw[12:28], raw[28:]
    plaintext = AESGCM(_get_encryption_key()).decrypt(iv, ciphertext + tag, None)
    return json.loads(plaintext.decode("utf-8"))


def _load_last_snapshot() -> Optional[dict]:
    if not SNAPSHOT_FILE.exists():
        return None
    try:
        raw = SNAPSHOT_FILE.read_text(encoding="utf-8").strip()
        return _decrypt(raw) if raw else None
    except Exception as err:
        print(f"[tuning] could not decrypt last snapshot, treating as none: {err}")
        return None


def _save_snapshot(snapshot: dict) -> None:
    _ensure_data_dir()
    SNAPSHOT_FILE.write_text(_encrypt(snapshot), encoding="utf-8")


def _same_target(a: dict, b: dict) -> bool:
    return (
        a.get("ip") == b.get("ip")
        and str(a.get("port")) == str(b.get("port"))
        and a.get("sid") == b.get("sid")
    )


def _dict_rowfactory(cursor) -> None:
    columns = [d[0] for d in cursor.description]
    cursor.rowfactory = lambda *args: dict(zip(columns, args))


def _num(v, default=0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# Short, actionable hints for the wait events most likely to show up in a
# license-free health check. Anything not listed falls back to a generic
# "look into this event's sessions/SQL" hint rather than showing nothing.
WAIT_EVENT_HINTS = {
    "db file sequential read": "wait_hint_seq_read",
    "db file scattered read": "wait_hint_scattered_read",
    "log file sync": "wait_hint_log_file_sync",
    "log file parallel write": "wait_hint_log_file_parallel_write",
    "buffer busy waits": "wait_hint_buffer_busy",
    "latch free": "wait_hint_latch_free",
    "latch: cache buffers chains": "wait_hint_latch_free",
    "direct path read": "wait_hint_direct_path",
    "direct path write": "wait_hint_direct_path",
    "enq: TX - row lock contention": "wait_hint_row_lock",
    "free buffer waits": "wait_hint_free_buffer",
    "read by other session": "wait_hint_seq_read",
}
WAIT_EVENT_HINT_DEFAULT = "wait_hint_default"


async def _run(connection, sql, map_row, binds=None):
    try:
        cursor = connection.cursor()
        await cursor.execute(sql, binds or {})
        _dict_rowfactory(cursor)
        rows = await cursor.fetchall()
        return {"ok": True, "data": map_row(rows)}
    except Exception as err:
        return {"ok": False, "message": str(err)}


async def _gather_current(connection) -> dict:
    """Everything needed for every rule below, in one pass: the raw
    cumulative counters the rate-based rules will diff against the
    previous snapshot, plus the current-state checks that stand on their
    own. Each section fails independently (matching this app's usual
    "one missing privilege doesn't blank the rest" convention)."""
    sections = {}

    sections["counters"] = await _run(
        connection,
        """SELECT
             (SELECT value FROM v$sysstat WHERE name = 'physical reads') AS physical_reads,
             (SELECT value FROM v$sysstat WHERE name = 'db block gets') AS db_block_gets,
             (SELECT value FROM v$sysstat WHERE name = 'consistent gets') AS consistent_gets,
             (SELECT value FROM v$sysstat WHERE name = 'parse count (total)') AS parse_count_total,
             (SELECT value FROM v$sysstat WHERE name = 'parse count (hard)') AS parse_count_hard,
             (SELECT value FROM v$sysstat WHERE name = 'sorts (disk)') AS sorts_disk
           FROM dual""",
        lambda rows: rows[0] if rows else {},
    )

    sections["libcache"] = await _run(
        connection,
        "SELECT SUM(pins) AS pins, SUM(reloads) AS reloads FROM v$librarycache",
        lambda rows: rows[0] if rows else {},
    )

    sections["waitEvents"] = await _run(
        connection,
        """SELECT event, time_waited FROM (
             SELECT event, time_waited FROM v$system_event WHERE wait_class != 'Idle' ORDER BY time_waited DESC
           ) WHERE ROWNUM <= 15""",
        lambda rows: {r["EVENT"]: _num(r["TIME_WAITED"]) for r in rows},
    )

    sections["tablespaceUsage"] = await _run(
        connection,
        """SELECT t.tablespace_name,
                  ROUND((1 - NVL(f.free_bytes, 0) / t.total_bytes) * 100, 2) AS used_pct
             FROM (SELECT tablespace_name, SUM(bytes) AS total_bytes
                     FROM dba_data_files GROUP BY tablespace_name) t
             LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS free_bytes
                          FROM dba_free_space GROUP BY tablespace_name) f
               ON f.tablespace_name = t.tablespace_name
            WHERE t.total_bytes > 0
            ORDER BY used_pct DESC""",
        lambda rows: rows,
    )

    sections["invalidObjects"] = await _run(
        connection,
        """SELECT owner, object_name, object_type FROM (
             SELECT owner, object_name, object_type FROM dba_objects
              WHERE status = 'INVALID'
              ORDER BY owner, object_name
           ) WHERE ROWNUM <= 50""",
        lambda rows: rows,
    )

    sections["invalidObjectsCount"] = await _run(
        connection,
        "SELECT COUNT(*) AS cnt FROM dba_objects WHERE status = 'INVALID'",
        lambda rows: int(rows[0]["CNT"]) if rows else 0,
    )

    sections["blockingSessions"] = await _run(
        connection,
        """SELECT waiter.sid AS waiter_sid, waiter.serial# AS waiter_serial,
                  waiter.username AS waiter_user, blocker.sid AS blocker_sid,
                  blocker.username AS blocker_user, waiter.seconds_in_wait AS wait_seconds
             FROM v$session waiter
             JOIN v$session blocker ON waiter.blocking_session = blocker.sid
            WHERE waiter.blocking_session IS NOT NULL
            ORDER BY waiter.seconds_in_wait DESC""",
        lambda rows: rows,
    )

    sections["slowSql"] = await _run(
        connection,
        """SELECT sql_id, ROUND(elapsed_time / 1000000 / executions, 3) AS avg_elapsed_sec, executions
             FROM v$sql
            WHERE executions > 0 AND elapsed_time / executions > 1000000
            ORDER BY elapsed_time / executions DESC
            FETCH FIRST 3 ROWS ONLY""",
        lambda rows: rows,
    )

    return sections


def _severity_by_threshold(value, warn_at, crit_at, higher_is_worse=True):
    if value is None:
        return None
    if higher_is_worse:
        if value >= crit_at:
            return "critical"
        if value >= warn_at:
            return "warning"
    else:
        if value <= crit_at:
            return "critical"
        if value <= warn_at:
            return "warning"
    return None


def _evaluate(current: dict, previous: Optional[dict]) -> dict:
    findings = []
    insufficient_history = []

    elapsed_seconds = None
    can_diff = False
    if previous:
        elapsed_seconds = (current["ts"] - previous["ts"]) / 1000
        can_diff = elapsed_seconds >= MIN_INTERVAL_SECONDS

    def counter_delta(section, key):
        if not can_diff:
            return None
        cur_val = current[section].get("data", {}).get(key)
        prev_val = previous[section].get("data", {}).get(key) if previous.get(section, {}).get("ok") else None
        if cur_val is None or prev_val is None:
            return None
        delta = _num(cur_val) - _num(prev_val)
        return delta if delta >= 0 else None  # negative => instance restarted meanwhile; skip

    # --- Rate-based rules (need a previous snapshot) ---
    if current["counters"]["ok"]:
        db_block_gets_d = counter_delta("counters", "DB_BLOCK_GETS")
        consistent_gets_d = counter_delta("counters", "CONSISTENT_GETS")
        physical_reads_d = counter_delta("counters", "PHYSICAL_READS")
        if db_block_gets_d is not None and consistent_gets_d is not None and physical_reads_d is not None:
            logical_reads_d = db_block_gets_d + consistent_gets_d
            if logical_reads_d > 0:
                hit_ratio = round((1 - physical_reads_d / logical_reads_d) * 100, 1)
                sev = _severity_by_threshold(hit_ratio, warn_at=90, crit_at=75, higher_is_worse=False)
                if sev:
                    findings.append({"ruleId": "buffer_cache_hit_ratio", "category": "memory", "severity": sev, "value": hit_ratio})
        else:
            insufficient_history.append("buffer_cache_hit_ratio")

        parse_total_d = counter_delta("counters", "PARSE_COUNT_TOTAL")
        parse_hard_d = counter_delta("counters", "PARSE_COUNT_HARD")
        if parse_total_d is not None and parse_hard_d is not None:
            if parse_total_d > 0:
                hard_pct = round((parse_hard_d / parse_total_d) * 100, 1)
                sev = _severity_by_threshold(hard_pct, warn_at=10, crit_at=30)
                if sev:
                    findings.append({"ruleId": "hard_parse_ratio", "category": "sql", "severity": sev, "value": hard_pct})
        else:
            insufficient_history.append("hard_parse_ratio")

        sorts_disk_d = counter_delta("counters", "SORTS_DISK")
        if sorts_disk_d is not None:
            if sorts_disk_d > 0:
                findings.append({"ruleId": "disk_sort", "category": "memory", "severity": "info", "count": int(sorts_disk_d)})
        else:
            insufficient_history.append("disk_sort")
    else:
        insufficient_history += ["buffer_cache_hit_ratio", "hard_parse_ratio", "disk_sort"]

    if current["libcache"]["ok"]:
        pins_d = counter_delta("libcache", "PINS")
        reloads_d = counter_delta("libcache", "RELOADS")
        if pins_d is not None and reloads_d is not None:
            if pins_d > 0:
                lib_ratio = round((1 - reloads_d / pins_d) * 100, 1)
                sev = _severity_by_threshold(lib_ratio, warn_at=99, crit_at=95, higher_is_worse=False)
                if sev:
                    findings.append({"ruleId": "library_cache_hit_ratio", "category": "memory", "severity": sev, "value": lib_ratio})
        else:
            insufficient_history.append("library_cache_hit_ratio")
    else:
        insufficient_history.append("library_cache_hit_ratio")

    if current["waitEvents"]["ok"] and can_diff and previous.get("waitEvents", {}).get("ok"):
        cur_events = current["waitEvents"]["data"]
        prev_events = previous["waitEvents"]["data"]
        increases = []
        for event, cur_time in cur_events.items():
            delta = _num(cur_time) - _num(prev_events.get(event, 0))
            if delta > 0:
                increases.append((event, delta))
        increases.sort(key=lambda x: x[1], reverse=True)
        if increases:
            findings.append({
                "ruleId": "wait_event_top",
                "category": "wait_event",
                "severity": "info",
                "rows": [
                    {
                        "rank": rank,
                        "event": event,
                        "hintKey": WAIT_EVENT_HINTS.get(event, WAIT_EVENT_HINT_DEFAULT),
                        "seconds": round(delta_cs / 100, 1),  # v$system_event.time_waited is in centiseconds
                    }
                    for rank, (event, delta_cs) in enumerate(increases[:3], start=1)
                ],
            })
    elif current["waitEvents"]["ok"]:
        insufficient_history.append("wait_event_top")

    # --- Current-state rules (no history needed) -- each grouped into one
    # finding with a `rows` table rather than one finding per row, so e.g.
    # 3 nearly-full tablespaces show up as a single "Tablespace Usage" item
    # instead of 3 separate cards.
    if current["tablespaceUsage"]["ok"]:
        rows = []
        for row in current["tablespaceUsage"]["data"]:
            pct = _num(row.get("USED_PCT"))
            sev = _severity_by_threshold(pct, warn_at=90, crit_at=95)
            if sev:
                rows.append({"tablespaceName": row.get("TABLESPACE_NAME"), "value": pct, "severity": sev})
        if rows:
            worst = "critical" if any(r["severity"] == "critical" for r in rows) else "warning"
            findings.append({"ruleId": "tablespace_usage", "category": "storage", "severity": worst, "rows": rows})

    if current["invalidObjects"]["ok"] and current.get("invalidObjectsCount", {}).get("ok"):
        cnt = current["invalidObjectsCount"]["data"]
        if cnt > 0:
            findings.append({
                "ruleId": "invalid_objects", "category": "object", "severity": "warning", "count": cnt,
                "rows": [
                    {"owner": r.get("OWNER"), "objectName": r.get("OBJECT_NAME"), "objectType": r.get("OBJECT_TYPE")}
                    for r in current["invalidObjects"]["data"]
                ],
                "truncated": cnt > len(current["invalidObjects"]["data"]),
            })

    if current["blockingSessions"]["ok"]:
        rows = current["blockingSessions"]["data"]
        if rows:
            findings.append({
                "ruleId": "blocking_session", "category": "lock", "severity": "critical", "count": len(rows),
                "rows": [
                    {
                        "waiterSid": r.get("WAITER_SID"), "waiterUser": r.get("WAITER_USER"),
                        "blockerSid": r.get("BLOCKER_SID"), "blockerUser": r.get("BLOCKER_USER"),
                        "waitSeconds": _num(r.get("WAIT_SECONDS")),
                    }
                    for r in rows
                ],
            })

    if current["slowSql"]["ok"] and current["slowSql"]["data"]:
        findings.append({
            "ruleId": "slow_sql", "category": "sql", "severity": "info",
            "rows": [
                {
                    "sqlId": r.get("SQL_ID"), "avgElapsedSec": _num(r.get("AVG_ELAPSED_SEC")),
                    "executions": int(_num(r.get("EXECUTIONS"))),
                }
                for r in current["slowSql"]["data"]
            ],
        })

    severity_order = {"critical": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: severity_order.get(f["severity"], 3))

    return {
        "findings": findings,
        "insufficientHistory": sorted(set(insufficient_history)),
        "elapsedSeconds": elapsed_seconds,
    }


async def run_tuning_check(connection, creds: dict) -> dict:
    """Runs every check and returns the structured result the
    /api/tuning-check endpoint hands back as JSON. `connection` is an
    already-open connection for `creds` (the caller owns opening/closing
    it, same convention as every other endpoint in this app)."""
    target = {"ip": creds["ip"], "port": creds["port"], "sid": creds["sid"]}
    current_sections = await _gather_current(connection)
    now_ms = time.time() * 1000

    previous = _load_last_snapshot()
    previous_matches = bool(previous) and _same_target(previous.get("target", {}), target)
    usable_previous = previous if previous_matches else None

    evaluation = _evaluate({**current_sections, "ts": now_ms}, usable_previous)

    _save_snapshot({"target": target, "ts": now_ms, **current_sections})

    return {
        "success": True,
        "checkedAt": now_ms,
        "previousCheckedAt": usable_previous["ts"] if usable_previous else None,
        "findings": evaluation["findings"],
        "insufficientHistory": evaluation["insufficientHistory"],
        "elapsedSeconds": evaluation["elapsedSeconds"],
    }
