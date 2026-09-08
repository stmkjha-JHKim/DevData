// tuning.js -- rule-based tuning advisor for the "Tuning" dashboard tab.
// Node port of tuning.py -- see that file's own top-of-file comment for
// the full reasoning (license-free views only, statspack-style interval
// deltas for rate-based rules, structured findings rendered client-side).
// Kept self-contained (own encryption, own connection handling) rather
// than importing from report.js/favorites.js, same reasoning as those
// modules already document.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const oracledb = require('oracledb');

const DATA_DIR = path.join(__dirname, 'data');
const SNAPSHOT_FILE = path.join(DATA_DIR, 'tuning-last-snapshot.enc');
const KEY_FILE = path.join(DATA_DIR, '.tuning-key');

// Below this many elapsed seconds since the previous snapshot, rate-based
// ratios are considered too noisy to be meaningful and are reported as
// "not enough history yet" instead, the same as having no previous
// snapshot at all.
const MIN_INTERVAL_SECONDS = 5;

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
}

let cachedKey = null;
function getEncryptionKey() {
  if (cachedKey) return cachedKey;
  ensureDataDir();
  if (fs.existsSync(KEY_FILE)) {
    cachedKey = Buffer.from(fs.readFileSync(KEY_FILE, 'utf8').trim(), 'hex');
  } else {
    cachedKey = crypto.randomBytes(32);
    fs.writeFileSync(KEY_FILE, cachedKey.toString('hex'), { mode: 0o600 });
  }
  return cachedKey;
}

function encrypt(value) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', getEncryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString('base64');
}

function decrypt(base64) {
  const raw = Buffer.from(base64, 'base64');
  const iv = raw.subarray(0, 12);
  const authTag = raw.subarray(12, 28);
  const ciphertext = raw.subarray(28);
  const decipher = crypto.createDecipheriv('aes-256-gcm', getEncryptionKey(), iv);
  decipher.setAuthTag(authTag);
  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return JSON.parse(plaintext.toString('utf8'));
}

function loadLastSnapshot() {
  ensureDataDir();
  if (!fs.existsSync(SNAPSHOT_FILE)) return null;
  try {
    const raw = fs.readFileSync(SNAPSHOT_FILE, 'utf8').trim();
    return raw ? decrypt(raw) : null;
  } catch (err) {
    console.error('[tuning] could not decrypt last snapshot, treating as none:', err.message);
    return null;
  }
}

function saveSnapshot(snapshot) {
  ensureDataDir();
  fs.writeFileSync(SNAPSHOT_FILE, encrypt(snapshot), 'utf8');
}

function sameTarget(a, b) {
  return a && b && a.ip === b.ip && String(a.port) === String(b.port) && a.sid === b.sid;
}

function num(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

// Short, actionable hints for the wait events most likely to show up in a
// license-free health check. Anything not listed falls back to a generic
// "look into this event's sessions/SQL" hint rather than showing nothing.
const WAIT_EVENT_HINTS = {
  'db file sequential read': 'wait_hint_seq_read',
  'db file scattered read': 'wait_hint_scattered_read',
  'log file sync': 'wait_hint_log_file_sync',
  'log file parallel write': 'wait_hint_log_file_parallel_write',
  'buffer busy waits': 'wait_hint_buffer_busy',
  'latch free': 'wait_hint_latch_free',
  'latch: cache buffers chains': 'wait_hint_latch_free',
  'direct path read': 'wait_hint_direct_path',
  'direct path write': 'wait_hint_direct_path',
  'enq: TX - row lock contention': 'wait_hint_row_lock',
  'free buffer waits': 'wait_hint_free_buffer',
  'read by other session': 'wait_hint_seq_read'
};
const WAIT_EVENT_HINT_DEFAULT = 'wait_hint_default';

async function run(connection, sql, mapRow, binds = {}) {
  try {
    const r = await connection.execute(sql, binds, { outFormat: oracledb.OUT_FORMAT_OBJECT });
    return { ok: true, data: mapRow(r.rows) };
  } catch (err) {
    return { ok: false, message: err.message };
  }
}

async function gatherCurrent(connection) {
  const sections = {};

  sections.counters = await run(
    connection,
    `SELECT
       (SELECT value FROM v$sysstat WHERE name = 'physical reads') AS physical_reads,
       (SELECT value FROM v$sysstat WHERE name = 'db block gets') AS db_block_gets,
       (SELECT value FROM v$sysstat WHERE name = 'consistent gets') AS consistent_gets,
       (SELECT value FROM v$sysstat WHERE name = 'parse count (total)') AS parse_count_total,
       (SELECT value FROM v$sysstat WHERE name = 'parse count (hard)') AS parse_count_hard,
       (SELECT value FROM v$sysstat WHERE name = 'sorts (disk)') AS sorts_disk
     FROM dual`,
    rows => rows[0] || {}
  );

  sections.libcache = await run(
    connection,
    `SELECT SUM(pins) AS pins, SUM(reloads) AS reloads FROM v$librarycache`,
    rows => rows[0] || {}
  );

  sections.waitEvents = await run(
    connection,
    `SELECT event, time_waited FROM (
       SELECT event, time_waited FROM v$system_event WHERE wait_class != 'Idle' ORDER BY time_waited DESC
     ) WHERE ROWNUM <= 15`,
    rows => {
      const map = {};
      rows.forEach(r => { map[r.EVENT] = num(r.TIME_WAITED); });
      return map;
    }
  );

  sections.tablespaceUsage = await run(
    connection,
    `SELECT t.tablespace_name,
            ROUND((1 - NVL(f.free_bytes, 0) / t.total_bytes) * 100, 2) AS used_pct
       FROM (SELECT tablespace_name, SUM(bytes) AS total_bytes
               FROM dba_data_files GROUP BY tablespace_name) t
       LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS free_bytes
                    FROM dba_free_space GROUP BY tablespace_name) f
         ON f.tablespace_name = t.tablespace_name
      WHERE t.total_bytes > 0
      ORDER BY used_pct DESC`,
    rows => rows
  );

  sections.invalidObjects = await run(
    connection,
    `SELECT owner, object_name, object_type FROM (
       SELECT owner, object_name, object_type FROM dba_objects
        WHERE status = 'INVALID'
        ORDER BY owner, object_name
     ) WHERE ROWNUM <= 50`,
    rows => rows
  );

  sections.invalidObjectsCount = await run(
    connection,
    `SELECT COUNT(*) AS cnt FROM dba_objects WHERE status = 'INVALID'`,
    rows => Number(rows[0].CNT)
  );

  sections.blockingSessions = await run(
    connection,
    `SELECT waiter.sid AS waiter_sid, waiter.serial# AS waiter_serial,
            waiter.username AS waiter_user, blocker.sid AS blocker_sid,
            blocker.username AS blocker_user, waiter.seconds_in_wait AS wait_seconds
       FROM v$session waiter
       JOIN v$session blocker ON waiter.blocking_session = blocker.sid
      WHERE waiter.blocking_session IS NOT NULL
      ORDER BY waiter.seconds_in_wait DESC`,
    rows => rows
  );

  sections.slowSql = await run(
    connection,
    `SELECT sql_id, ROUND(elapsed_time / 1000000 / executions, 3) AS avg_elapsed_sec, executions
       FROM v$sql
      WHERE executions > 0 AND elapsed_time / executions > 1000000
      ORDER BY elapsed_time / executions DESC
      FETCH FIRST 3 ROWS ONLY`,
    rows => rows
  );

  return sections;
}

function severityByThreshold(value, warnAt, critAt, higherIsWorse = true) {
  if (value == null) return null;
  if (higherIsWorse) {
    if (value >= critAt) return 'critical';
    if (value >= warnAt) return 'warning';
  } else {
    if (value <= critAt) return 'critical';
    if (value <= warnAt) return 'warning';
  }
  return null;
}

function evaluate(current, previous) {
  const findings = [];
  const insufficientHistory = new Set();

  let elapsedSeconds = null;
  let canDiff = false;
  if (previous) {
    elapsedSeconds = (current.ts - previous.ts) / 1000;
    canDiff = elapsedSeconds >= MIN_INTERVAL_SECONDS;
  }

  function counterDelta(section, key) {
    if (!canDiff) return null;
    const curVal = current[section] && current[section].data ? current[section].data[key] : undefined;
    const prevOk = previous[section] && previous[section].ok;
    const prevVal = prevOk ? previous[section].data[key] : undefined;
    if (curVal == null || prevVal == null) return null;
    const delta = num(curVal) - num(prevVal);
    return delta >= 0 ? delta : null; // negative => instance restarted meanwhile; skip
  }

  if (current.counters.ok) {
    const dbBlockGetsD = counterDelta('counters', 'DB_BLOCK_GETS');
    const consistentGetsD = counterDelta('counters', 'CONSISTENT_GETS');
    const physicalReadsD = counterDelta('counters', 'PHYSICAL_READS');
    if (dbBlockGetsD != null && consistentGetsD != null && physicalReadsD != null) {
      const logicalReadsD = dbBlockGetsD + consistentGetsD;
      if (logicalReadsD > 0) {
        const hitRatio = Math.round((1 - physicalReadsD / logicalReadsD) * 1000) / 10;
        const sev = severityByThreshold(hitRatio, 90, 75, false);
        if (sev) findings.push({ ruleId: 'buffer_cache_hit_ratio', category: 'memory', severity: sev, value: hitRatio });
      }
    } else {
      insufficientHistory.add('buffer_cache_hit_ratio');
    }

    const parseTotalD = counterDelta('counters', 'PARSE_COUNT_TOTAL');
    const parseHardD = counterDelta('counters', 'PARSE_COUNT_HARD');
    if (parseTotalD != null && parseHardD != null) {
      if (parseTotalD > 0) {
        const hardPct = Math.round((parseHardD / parseTotalD) * 1000) / 10;
        const sev = severityByThreshold(hardPct, 10, 30);
        if (sev) findings.push({ ruleId: 'hard_parse_ratio', category: 'sql', severity: sev, value: hardPct });
      }
    } else {
      insufficientHistory.add('hard_parse_ratio');
    }

    const sortsDiskD = counterDelta('counters', 'SORTS_DISK');
    if (sortsDiskD != null) {
      if (sortsDiskD > 0) findings.push({ ruleId: 'disk_sort', category: 'memory', severity: 'info', count: Math.round(sortsDiskD) });
    } else {
      insufficientHistory.add('disk_sort');
    }
  } else {
    ['buffer_cache_hit_ratio', 'hard_parse_ratio', 'disk_sort'].forEach(id => insufficientHistory.add(id));
  }

  if (current.libcache.ok) {
    const pinsD = counterDelta('libcache', 'PINS');
    const reloadsD = counterDelta('libcache', 'RELOADS');
    if (pinsD != null && reloadsD != null) {
      if (pinsD > 0) {
        const libRatio = Math.round((1 - reloadsD / pinsD) * 1000) / 10;
        const sev = severityByThreshold(libRatio, 99, 95, false);
        if (sev) findings.push({ ruleId: 'library_cache_hit_ratio', category: 'memory', severity: sev, value: libRatio });
      }
    } else {
      insufficientHistory.add('library_cache_hit_ratio');
    }
  } else {
    insufficientHistory.add('library_cache_hit_ratio');
  }

  if (current.waitEvents.ok && canDiff && previous.waitEvents && previous.waitEvents.ok) {
    const curEvents = current.waitEvents.data;
    const prevEvents = previous.waitEvents.data;
    const increases = [];
    Object.keys(curEvents).forEach(event => {
      const delta = num(curEvents[event]) - num(prevEvents[event] || 0);
      if (delta > 0) increases.push([event, delta]);
    });
    increases.sort((a, b) => b[1] - a[1]);
    if (increases.length) {
      findings.push({
        ruleId: 'wait_event_top',
        category: 'wait_event',
        severity: 'info',
        rows: increases.slice(0, 3).map(([event, deltaCs], idx) => ({
          rank: idx + 1,
          event,
          hintKey: WAIT_EVENT_HINTS[event] || WAIT_EVENT_HINT_DEFAULT,
          seconds: Math.round((deltaCs / 100) * 10) / 10 // v$system_event.time_waited is in centiseconds
        }))
      });
    }
  } else if (current.waitEvents.ok) {
    insufficientHistory.add('wait_event_top');
  }

  // --- Current-state rules (no history needed) -- each grouped into one
  // finding with a `rows` table rather than one finding per row, so e.g.
  // 3 nearly-full tablespaces show up as a single "Tablespace Usage" item
  // instead of 3 separate cards.
  if (current.tablespaceUsage.ok) {
    const rows = [];
    current.tablespaceUsage.data.forEach(row => {
      const pct = num(row.USED_PCT);
      const sev = severityByThreshold(pct, 90, 95);
      if (sev) rows.push({ tablespaceName: row.TABLESPACE_NAME, value: pct, severity: sev });
    });
    if (rows.length) {
      const worst = rows.some(r => r.severity === 'critical') ? 'critical' : 'warning';
      findings.push({ ruleId: 'tablespace_usage', category: 'storage', severity: worst, rows });
    }
  }

  if (current.invalidObjects.ok && current.invalidObjectsCount.ok) {
    const cnt = current.invalidObjectsCount.data;
    if (cnt > 0) {
      findings.push({
        ruleId: 'invalid_objects', category: 'object', severity: 'warning', count: cnt,
        rows: current.invalidObjects.data.map(r => ({ owner: r.OWNER, objectName: r.OBJECT_NAME, objectType: r.OBJECT_TYPE })),
        truncated: cnt > current.invalidObjects.data.length
      });
    }
  }

  if (current.blockingSessions.ok) {
    const rows = current.blockingSessions.data;
    if (rows.length) {
      findings.push({
        ruleId: 'blocking_session', category: 'lock', severity: 'critical', count: rows.length,
        rows: rows.map(r => ({
          waiterSid: r.WAITER_SID, waiterUser: r.WAITER_USER,
          blockerSid: r.BLOCKER_SID, blockerUser: r.BLOCKER_USER, waitSeconds: num(r.WAIT_SECONDS)
        }))
      });
    }
  }

  if (current.slowSql.ok && current.slowSql.data.length) {
    findings.push({
      ruleId: 'slow_sql', category: 'sql', severity: 'info',
      rows: current.slowSql.data.map(r => ({
        sqlId: r.SQL_ID, avgElapsedSec: num(r.AVG_ELAPSED_SEC), executions: Math.round(num(r.EXECUTIONS))
      }))
    });
  }

  const severityOrder = { critical: 0, warning: 1, info: 2 };
  findings.sort((a, b) => (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3));

  return { findings, insufficientHistory: Array.from(insufficientHistory).sort(), elapsedSeconds };
}

// Runs every check and returns the structured result the
// /api/tuning-check endpoint hands back as JSON. `connection` is an
// already-open connection for `creds` (the caller owns opening/closing
// it, same convention as every other endpoint in this app).
async function runTuningCheck(connection, creds) {
  const target = { ip: creds.ip, port: creds.port, sid: creds.sid };
  const currentSections = await gatherCurrent(connection);
  const nowMs = Date.now();

  const previous = loadLastSnapshot();
  const previousMatches = previous && sameTarget(previous.target, target);
  const usablePrevious = previousMatches ? previous : null;

  const evaluation = evaluate({ ...currentSections, ts: nowMs }, usablePrevious);

  saveSnapshot({ target, ts: nowMs, ...currentSections });

  return {
    success: true,
    checkedAt: nowMs,
    previousCheckedAt: usablePrevious ? usablePrevious.ts : null,
    findings: evaluation.findings,
    insufficientHistory: evaluation.insufficientHistory,
    elapsedSeconds: evaluation.elapsedSeconds
  };
}

module.exports = { runTuningCheck };
