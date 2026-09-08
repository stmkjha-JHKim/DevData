// report.js -- Weekly DB Health Report feature for OraPulse (the "Report"
// button next to Refresh on the dashboard).
//
// Why this needs its own local snapshot history at all: a real AWR report
// needs the Oracle Diagnostics Pack license (DBMS_WORKLOAD_REPOSITORY /
// dba_hist_* views), which this app deliberately doesn't assume the
// connecting instance has -- same reasoning as the Ops tab (see main.js and
// README.md). Most of what a "last 7 days" report needs -- CPU/memory %,
// session counts, Top SQL, instance efficiency, TEMP/FRA usage -- comes
// from v$ views that only ever expose the *current* value, with no history
// behind them, so there's no query that can answer "what was this over the
// last week" without AWR. Instead, this module has main.js take its own
// lightweight snapshot on a timer (see startCollector below) and appends it
// to a plain JSON-lines file on disk -- effectively a tiny, license-free,
// dependency-free stand-in for an AWR repository (no sqlite/DB driver
// needed, just fs).
//
// The one exception is the Alert Log: v$diag_alert_ext already holds
// entries going back further than any single poll (as far as the DB's own
// alert log retention allows), so the report's Alert Log section queries
// that view live, directly, for the requested window -- no local collection
// needed for that part.
//
// Practical caveat, documented in README.md too: trend data only exists
// from the moment this feature first ran onward, so a brand new install's
// first "weekly" report will show a partial week that fills in over the
// next 7 days. The collector is a plain `setInterval` inside this same
// `node main.js` process -- there is no OS-level scheduler -- so it only
// collects while that process is running. Restarting the process does NOT
// lose already-collected history (it's a plain file on disk), but nothing
// is collected while the process is down. Disconnecting from the dashboard
// UI does NOT stop collection either: the whole point is a trend that
// survives closed browser tabs, so collection keeps running against the
// last successful connection's credentials until a new connection replaces
// them or the process exits.

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const oracledb = require('oracledb');

const DATA_DIR = path.join(__dirname, 'data');
const SNAPSHOT_FILE = path.join(DATA_DIR, 'snapshot-history.jsonl');
const KEY_FILE = path.join(DATA_DIR, '.snapshot-key');

const SNAPSHOT_INTERVAL_MS = 15 * 60 * 1000; // 15 minutes
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000; // 7 days -- matches the report's own window

// Duplicated from main.js on purpose (it's three lines) rather than
// imported, so this module has no dependency on main.js's internals and
// could be dropped into another project unchanged.
function buildConnectString(ip, port, sid) {
  return `(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=${ip})(PORT=${port}))` +
         `(CONNECT_DATA=(SID=${sid})))`;
}

function ensureDataDir() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }
}

// snapshot-history.jsonl is a plain file on disk (see the top-of-file
// comment), so the DB connection target (ip/port/sid) each row was
// collected against is encrypted before it's written, rather than sitting
// there in plain text for anyone who opens the file directly. The key
// lives next to it (data/.snapshot-key, generated on first use) -- this
// doesn't defend against someone who already has full access to this
// app's own data/ folder, but it does mean the history file on its own
// (copied out, attached to a support ticket, etc.) no longer discloses
// which DB servers this app has been pointed at.
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

// AES-256-GCM: a random IV per value plus an auth tag, so a corrupted/
// tampered value is detected (decrypt throws) rather than silently
// producing garbage. Encrypted target values are only ever compared for
// equality (see readSnapshots below) -- nothing in this app displays a
// snapshot's stored target back to the user, it's only used to keep one
// DB's history from blending into another's.
function encryptTarget(target) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', getEncryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(target), 'utf8'), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), ciphertext]).toString('base64');
}

// Snapshots collected before this encryption was added stored `target` as
// a plain { ip, port, sid } object -- passed through unchanged here rather
// than erroring out and losing that older history. A value that fails to
// decrypt (wrong/rotated key, corrupted line) returns null, which simply
// excludes that row from target-matching rather than crashing the report.
function decryptTarget(value) {
  if (value && typeof value === 'object') return value;
  if (typeof value !== 'string') return null;
  try {
    const raw = Buffer.from(value, 'base64');
    const iv = raw.subarray(0, 12);
    const authTag = raw.subarray(12, 28);
    const ciphertext = raw.subarray(28);
    const decipher = crypto.createDecipheriv('aes-256-gcm', getEncryptionKey(), iv);
    decipher.setAuthTag(authTag);
    const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    return JSON.parse(plaintext.toString('utf8'));
  } catch (err) {
    return null;
  }
}

// One-time migration for a history file that already has plain-text
// targets from before this encryption existed (run once at collector
// startup -- see startCollector below). Leaves everything else about each
// snapshot untouched.
function migrateLegacyTargets() {
  const all = readAllSnapshots();
  let changed = false;
  for (const s of all) {
    if (s.target && typeof s.target === 'object') {
      s.target = encryptTarget(s.target);
      changed = true;
    }
  }
  if (!changed) return;
  ensureDataDir();
  const body = all.map(s => JSON.stringify(s)).join('\n') + (all.length ? '\n' : '');
  fs.writeFileSync(SNAPSHOT_FILE, body, 'utf8');
}

function readAllSnapshots() {
  ensureDataDir();
  if (!fs.existsSync(SNAPSHOT_FILE)) return [];
  const raw = fs.readFileSync(SNAPSHOT_FILE, 'utf8');
  const out = [];
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue;
    try {
      out.push(JSON.parse(line));
    } catch (err) {
      // A partial/corrupted line (e.g. the process was killed mid-write) is
      // skipped rather than allowed to take down the whole report.
    }
  }
  return out;
}

// `target`, if given, restricts to snapshots collected against that same
// DB (ip/port/sid) -- so switching which DB you're connected to over time
// doesn't mix two different instances' history into one report.
function readSnapshots(days, target) {
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return readAllSnapshots()
    .filter(s => s.ts >= cutoff)
    .filter(s => {
      if (!target) return true;
      const t = decryptTarget(s.target);
      return t && t.ip === target.ip && String(t.port) === String(target.port) && t.sid === target.sid;
    })
    .sort((a, b) => a.ts - b.ts);
}

function persistSnapshot(snapshot) {
  ensureDataDir();
  const cutoff = Date.now() - RETENTION_MS;
  const kept = readAllSnapshots().filter(s => s.ts >= cutoff);
  kept.push(snapshot);
  const body = kept.map(s => JSON.stringify(s)).join('\n') + '\n';
  fs.writeFileSync(SNAPSHOT_FILE, body, 'utf8');
}

// Opens its own short-lived connection (same pattern as every endpoint in
// main.js) and gathers a compact snapshot -- enough to redraw the Main
// tab's core numbers, the Ops tab's cards, and Temp/Recovery usage as a
// trend later, without pulling in the heavier per-row detail those live
// endpoints return (full session lists, Recent DML text, etc. don't belong
// in a once-every-15-minutes history file). Never throws -- a failed
// section is recorded as { ok: false, message }, same convention as
// main.js's own endpoints, and a failed connection just skips the whole
// snapshot (logged, not thrown) so one bad tick doesn't stop the timer.
async function gatherSnapshot(creds) {
  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);
  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString
    });
  } catch (err) {
    console.error('[report] snapshot skipped -- could not connect:', err.message);
    return null;
  }

  const run = async (sql, mapRow, binds = []) => {
    try {
      const r = await connection.execute(sql, binds, { outFormat: oracledb.OUT_FORMAT_OBJECT });
      return mapRow(r.rows);
    } catch (err) {
      return { ok: false, message: err.message };
    }
  };

  const snapshot = {
    ts: Date.now(),
    iso: new Date().toISOString(),
    target: encryptTarget({ ip: creds.ip, port: creds.port, sid: creds.sid }),
    main: {},
    ops: {},
    usage: {}
  };

  snapshot.main.instance = await run(
    `SELECT instance_name, host_name, version FROM v$instance`,
    rows => (rows[0] ? { ok: true, data: rows[0] } : { ok: false, message: 'No results found.' })
  );

  snapshot.main.cpuPct = await run(
    `SELECT value FROM (
       SELECT value FROM v$sysmetric WHERE metric_name = 'Host CPU Utilization (%)' ORDER BY end_time DESC
     ) WHERE ROWNUM = 1`,
    rows => (rows[0] ? { ok: true, data: Number(rows[0].VALUE) } : { ok: false, message: 'No results found.' })
  );

  snapshot.main.memory = await run(
    `SELECT
       ROUND((SELECT SUM(value) FROM v$sga) / 1024 / 1024, 1) AS sga_mb,
       ROUND((SELECT value FROM v$pgastat WHERE name = 'total PGA allocated') / 1024 / 1024, 1) AS pga_mb,
       ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_target'), 0) / 1024 / 1024, 1) AS memory_target_mb,
       ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_max_target'), 0) / 1024 / 1024, 1) AS memory_max_target_mb,
       ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'sga_max_size'), 0) / 1024 / 1024, 1) AS sga_max_mb,
       ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'pga_aggregate_target'), 0) / 1024 / 1024, 1) AS pga_target_mb
     FROM dual`,
    rows => {
      const d = rows[0] || {};
      const usedMb = Number(d.SGA_MB || 0) + Number(d.PGA_MB || 0);
      const targetMb =
        Number(d.MEMORY_TARGET_MB) > 0 ? Number(d.MEMORY_TARGET_MB) :
        Number(d.MEMORY_MAX_TARGET_MB) > 0 ? Number(d.MEMORY_MAX_TARGET_MB) :
        (Number(d.SGA_MAX_MB || 0) + Number(d.PGA_TARGET_MB || 0));
      const pct = targetMb > 0 ? Math.round((usedMb / targetMb) * 1000) / 10 : null;
      return { ok: true, data: { usedMb: Math.round(usedMb * 10) / 10, targetMb: targetMb > 0 ? targetMb : null, pct } };
    }
  );

  snapshot.main.sessionCount = await run(
    `SELECT COUNT(*) AS cnt FROM v$session WHERE type = 'USER'`,
    rows => ({ ok: true, data: Number(rows[0].CNT) })
  );

  snapshot.main.invalidObjectsCount = await run(
    `SELECT COUNT(*) AS cnt FROM dba_objects WHERE status = 'INVALID'`,
    rows => ({ ok: true, data: Number(rows[0].CNT) })
  );

  snapshot.main.topWaitEvents = await run(
    `SELECT event, time_waited FROM (
       SELECT event, time_waited FROM v$system_event WHERE wait_class != 'Idle' ORDER BY time_waited DESC
     ) WHERE ROWNUM <= 3`,
    rows => ({ ok: true, data: rows })
  );

  snapshot.ops.topQueries = await run(
    `SELECT sql_id, ROUND(elapsed_time / 1000000, 3) AS elapsed_sec FROM (
       SELECT sql_id, elapsed_time FROM v$sql WHERE elapsed_time > 0 ORDER BY elapsed_time DESC
     ) WHERE ROWNUM <= 3`,
    rows => ({ ok: true, data: rows })
  );

  snapshot.ops.topQueriesCpu = await run(
    `SELECT sql_id, ROUND(cpu_time / 1000000, 3) AS cpu_sec FROM (
       SELECT sql_id, cpu_time FROM v$sql WHERE cpu_time > 0 ORDER BY cpu_time DESC
     ) WHERE ROWNUM <= 3`,
    rows => ({ ok: true, data: rows })
  );

  snapshot.ops.topQueriesBufferGets = await run(
    `SELECT sql_id, buffer_gets FROM (
       SELECT sql_id, buffer_gets FROM v$sql WHERE buffer_gets > 0 ORDER BY buffer_gets DESC
     ) WHERE ROWNUM <= 3`,
    rows => ({ ok: true, data: rows })
  );

  snapshot.ops.instanceEfficiency = await run(
    `SELECT
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
     FROM dual`,
    rows => ({ ok: true, data: rows[0] || {} })
  );

  snapshot.ops.loadProfile = await run(
    `SELECT ROUND(redo_size / NULLIF(uptime_seconds, 0), 2) AS redo_size_per_sec,
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
            )`,
    rows => ({ ok: true, data: rows[0] || {} })
  );

  snapshot.usage.temp = await run(
    `SELECT tablespace_name, ROUND(SUM(bytes_used) / SUM(bytes_used + bytes_free) * 100, 2) AS used_pct
       FROM v$temp_space_header
      GROUP BY tablespace_name`,
    rows => ({ ok: true, data: rows })
  );

  snapshot.usage.recovery = await run(
    `SELECT ROUND((space_used - space_reclaimable) / NULLIF(space_limit, 0) * 100, 2) AS used_pct_net
       FROM v$recovery_file_dest`,
    rows => ({ ok: true, data: rows })
  );

  snapshot.ops.tablespaceIo = await run(
    `SELECT tablespace_name, physical_reads, physical_writes FROM (
       SELECT ts.name AS tablespace_name,
              SUM(fs.phyrds) AS physical_reads,
              SUM(fs.phywrts) AS physical_writes
         FROM v$filestat fs
         JOIN v$datafile df ON fs.file# = df.file#
         JOIN v$tablespace ts ON df.ts# = ts.ts#
        GROUP BY ts.name
        ORDER BY SUM(fs.phyrds + fs.phywrts) DESC
     ) WHERE ROWNUM <= 10`,
    rows => ({ ok: true, data: rows })
  );

  try {
    await connection.close();
  } catch (closeErr) {
    console.error('[report] error while closing snapshot connection:', closeErr.message);
  }

  persistSnapshot(snapshot);
  return snapshot;
}

// Starts the recurring background collector. `getCreds` is a function
// (rather than a fixed value) because the credentials it should use change
// every time someone connects -- main.js passes `() => lastConnectedCreds`
// so this always picks up the most recent connection without needing to be
// restarted.
function startCollector(getCreds) {
  try {
    migrateLegacyTargets();
  } catch (err) {
    console.error('[report] legacy target migration failed:', err.message);
  }
  setInterval(() => {
    const creds = getCreds();
    if (!creds) return; // Nothing has ever connected yet -- nothing to snapshot.
    gatherSnapshot(creds).catch(err => console.error('[report] snapshot collection failed:', err.message));
  }, SNAPSHOT_INTERVAL_MS);
}

// Fire-and-forget: called right after a successful /api/connect so the
// history starts filling in immediately rather than waiting up to 15
// minutes for the first tick.
function triggerImmediateCollection(creds) {
  gatherSnapshot(creds).catch(err => console.error('[report] initial snapshot failed:', err.message));
}

// Queries v$diag_alert_ext directly for the requested window -- unlike
// everything else in this file, the alert log already has its own history
// built in, so there's no need to have been polling it ourselves. Mirrors
// the exact filtering logic already used by /api/alert-log in main.js
// (see the comment there for why "ORA-0"/"ORA-30" are excluded).
async function fetchAlertSummary(creds, days) {
  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);
  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString
    });
  } catch (err) {
    return { ok: false, message: `Failed to connect to the DB: ${err.message}` };
  }

  const WHERE_CLAUSE = `
    WHERE originating_timestamp > SYSDATE - :days
      AND (message_text LIKE '%ORA-%' OR message_type IN (2, 3))
      AND (REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') IS NULL
           OR REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') NOT IN ('ORA-0', 'ORA-30'))`;

  try {
    const totalR = await connection.execute(
      `SELECT COUNT(*) AS cnt FROM v$diag_alert_ext ${WHERE_CLAUSE}`,
      { days }, { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const byCodeR = await connection.execute(
      `SELECT ora_code, COUNT(*) AS cnt FROM (
         SELECT REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') AS ora_code
           FROM v$diag_alert_ext ${WHERE_CLAUSE}
       )
       WHERE ora_code IS NOT NULL
       GROUP BY ora_code
       ORDER BY COUNT(*) DESC
       FETCH FIRST 10 ROWS ONLY`,
      { days }, { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const recentR = await connection.execute(
      `SELECT log_time, ora_code, message_text FROM (
         SELECT TO_CHAR(originating_timestamp, 'YYYY-MM-DD HH24:MI:SS') AS log_time,
                REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') AS ora_code,
                message_text
           FROM v$diag_alert_ext ${WHERE_CLAUSE}
          ORDER BY originating_timestamp DESC
       ) WHERE ROWNUM <= 15`,
      { days }, { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    return {
      ok: true,
      totalCount: totalR.rows[0].CNT,
      byCode: byCodeR.rows,
      recent: recentR.rows
    };
  } catch (err) {
    return {
      ok: false,
      message: `You do not have permission to view this. Access to V$DIAG_ALERT_EXT is required (typically granted via SELECT_CATALOG_ROLE or the SELECT ANY DICTIONARY privilege). (${err.message})`
    };
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('[report] error while closing alert-summary connection:', closeErr.message);
      }
    }
  }
}

// ---------------------------------------------------------------------
// HTML report rendering. Self-contained (inline CSS, hand-drawn inline SVG
// charts -- no external CDN/font/script dependency, same "works with no
// internet access" posture as the rest of this app), styled to match the
// dashboard's own dark color palette so a downloaded report doesn't look
// like a different product.
// ---------------------------------------------------------------------

const REPORT_I18N = {
  en: {
    title: 'OraPulse Weekly DB Health Report',
    periodLabel: 'Report Period', generatedLabel: 'Generated At', dataPointsLabel: 'Data Points Collected',
    partialDataNote: (fromStr) => `Note: local snapshot collection for this DB only goes back to ${fromStr} so far -- the trend sections below cover less than the full ${'{days}'}-day window until more history accumulates.`,
    sectionGlance: 'At a Glance (Latest Snapshot)',
    statCpu: 'CPU Utilization', statMemory: 'Memory Usage', statSessions: 'Active Sessions', statInvalid: 'Invalid Objects',
    sectionTrend: '7-Day Trend',
    chartCpu: 'CPU Utilization (%)', chartMemory: 'Memory Usage (%)', chartSessions: 'Active Sessions', chartInvalid: 'Invalid Objects',
    sectionEfficiency: 'Instance Efficiency (%)',
    effBuffer: 'Buffer Cache Hit Ratio', effLibrary: 'Library Cache Hit Ratio', effSoftParse: 'Soft Parse %', effExecParse: 'Execute to Parse %',
    sectionLoadProfile: 'Load Profile (per second, since instance startup)',
    lpRedo: 'Redo Size/sec', lpLogical: 'Logical Reads/sec', lpPhysical: 'Physical Reads/sec',
    lpUserCalls: 'User Calls/sec', lpExecutes: 'Executes/sec', lpTx: 'Transactions/sec',
    sectionTopSql: 'Top SQL (Latest Snapshot)',
    topSqlElapsed: 'By Elapsed Time', topSqlCpu: 'By CPU Time', topSqlGets: 'By Buffer Gets',
    colSqlId: 'SQL_ID', colElapsedSec: 'Elapsed (sec)', colCpuSec: 'CPU (sec)', colBufferGets: 'Buffer Gets',
    sectionUsage: 'Storage Usage Trend',
    chartTemp: 'TEMP Tablespace Usage -- Worst Tablespace (%)', chartRecovery: 'Fast Recovery Area Usage, Net of Reclaimable (%)',
    sectionTablespaceIo: 'Tablespace I/O (Latest Snapshot)',
    colTablespace: 'Tablespace', colReads: 'Physical Reads', colWrites: 'Physical Writes',
    sectionAlertLog: 'Alert Log Summary',
    alertTotal: 'Noteworthy entries in period', alertByCode: 'Most Frequent ORA Codes', alertRecent: 'Most Recent Entries',
    colOraCode: 'ORA Code', colCount: 'Count', colTime: 'Time', colMessage: 'Message',
    noData: 'No data available.',
    footerNote: 'Generated by OraPulse. Trend data comes from locally collected snapshots (~15-minute interval); this is not an Oracle AWR/Diagnostics Pack report.'
  },
  ko: {
    title: 'OraPulse 주간 DB 상태 리포트',
    periodLabel: '리포트 기간', generatedLabel: '생성 시각', dataPointsLabel: '수집된 데이터 포인트',
    partialDataNote: (fromStr) => `참고: 이 DB에 대한 로컬 스냅샷 수집이 아직 ${fromStr}부터만 쌓여 있어, 데이터가 더 쌓이기 전까지는 아래 추이 항목들이 전체 ${'{days}'}일 구간을 다 채우지 못합니다.`,
    sectionGlance: '한눈에 보기 (최신 스냅샷 기준)',
    statCpu: 'CPU 사용률', statMemory: '메모리 사용률', statSessions: '활성 세션 수', statInvalid: 'Invalid 객체 수',
    sectionTrend: '최근 7일 추이',
    chartCpu: 'CPU 사용률 (%)', chartMemory: '메모리 사용률 (%)', chartSessions: '활성 세션 수', chartInvalid: 'Invalid 객체 수',
    sectionEfficiency: '인스턴스 효율 (%)',
    effBuffer: '버퍼 캐시 히트율', effLibrary: '라이브러리 캐시 히트율', effSoftParse: '소프트 파스 비율', effExecParse: '실행 대비 파스 비율',
    sectionLoadProfile: 'Load Profile (초당, 인스턴스 시작 이후 누적 평균)',
    lpRedo: 'Redo Size/초', lpLogical: 'Logical Reads/초', lpPhysical: 'Physical Reads/초',
    lpUserCalls: 'User Calls/초', lpExecutes: 'Executes/초', lpTx: 'Transactions/초',
    sectionTopSql: 'Top SQL (최신 스냅샷 기준)',
    topSqlElapsed: '실행시간 기준', topSqlCpu: 'CPU 시간 기준', topSqlGets: 'Buffer Gets 기준',
    colSqlId: 'SQL_ID', colElapsedSec: '실행시간(초)', colCpuSec: 'CPU(초)', colBufferGets: 'Buffer Gets',
    sectionUsage: '스토리지 사용률 추이',
    chartTemp: 'TEMP 테이블스페이스 사용률 -- 최고치 기준 (%)', chartRecovery: 'FRA(Fast Recovery Area) 순사용률 (%)',
    sectionTablespaceIo: '테이블스페이스 I/O (최신 스냅샷 기준)',
    colTablespace: '테이블스페이스', colReads: 'Physical Reads', colWrites: 'Physical Writes',
    sectionAlertLog: 'Alert Log 요약',
    alertTotal: '기간 내 주요 항목 수', alertByCode: '가장 빈번한 ORA 코드', alertRecent: '최근 항목',
    colOraCode: 'ORA 코드', colCount: '건수', colTime: '시각', colMessage: '메시지',
    noData: '데이터가 없습니다.',
    footerNote: 'OraPulse가 생성한 리포트입니다. 추이 데이터는 로컬에서 수집한 스냅샷(약 15분 간격) 기준이며, Oracle AWR/Diagnostics Pack 리포트가 아닙니다.'
  }
};

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function fmtNum(v, digits) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '-';
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits == null ? 2 : digits, minimumFractionDigits: 0 });
}

function fmtDateTime(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtDateShort(ts) {
  const d = new Date(ts);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// High-is-bad thresholds (CPU/memory/usage-%): matches the dashboard's own
// pctClass() helper (90/75).
function badgeClassHighBad(pct) {
  if (pct == null) return '';
  if (pct >= 90) return 'danger';
  if (pct >= 75) return 'warn';
  return 'ok';
}

// High-is-good thresholds (hit ratios / efficiency %): matches the
// dashboard's own efficiencyPctClass() helper -- inverted from the above.
function badgeClassHighGood(pct) {
  if (pct == null) return '';
  if (pct < 75) return 'danger';
  if (pct < 90) return 'warn';
  return 'ok';
}

function badge(pct, cls) {
  if (pct == null) return '<span class="badge">-</span>';
  return `<span class="badge ${cls}">${fmtNum(pct, 1)}%</span>`;
}

// Hand-rolled inline line/area chart -- no charting library, so the report
// stays a single self-contained file with no external request of any kind.
// `points`: [{ ts, value }] in chronological order; a null/undefined value
// renders as a gap in the line rather than a drop to zero.
function lineChartSvg(points, opts = {}) {
  const width = opts.width || 620;
  const height = opts.height || 160;
  const padL = 42, padR = 14, padT = 14, padB = 26;
  const plotW = width - padL - padR;
  const plotH = height - padT - padB;
  const color = opts.color || '#4f7cff';
  const unit = opts.unit || '';

  const valid = points.filter(p => typeof p.value === 'number' && isFinite(p.value));
  if (valid.length < 2) {
    return `<svg viewBox="0 0 ${width} ${height}" class="chart-svg" role="img">
      <rect x="0" y="0" width="${width}" height="${height}" rx="8" fill="#111a30" />
      <text x="${width / 2}" y="${height / 2}" text-anchor="middle" fill="#8b96b3" font-size="13">Not enough data yet</text>
    </svg>`;
  }

  const xs = points.map(p => p.ts);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const vs = valid.map(p => p.value);
  let minY = opts.minY != null ? opts.minY : Math.min(...vs);
  let maxY = opts.maxY != null ? opts.maxY : Math.max(...vs);
  if (minY === maxY) { minY -= 1; maxY += 1; }
  const yPad = (maxY - minY) * 0.15;
  minY -= yPad;
  maxY += yPad;
  if (opts.forceMinZero) minY = Math.min(minY, 0);
  if (opts.maxY == null && opts.capMax != null) maxY = Math.min(maxY, opts.capMax);

  const xScale = ts => padL + ((ts - minX) / (maxX - minX || 1)) * plotW;
  const yScale = v => padT + plotH - ((Math.max(minY, Math.min(maxY, v)) - minY) / (maxY - minY || 1)) * plotH;

  // Build one or more polylines, breaking wherever the data has a gap.
  const segments = [];
  let cur = [];
  for (const p of points) {
    if (typeof p.value === 'number' && isFinite(p.value)) {
      cur.push([xScale(p.ts), yScale(p.value)]);
    } else if (cur.length) {
      segments.push(cur);
      cur = [];
    }
  }
  if (cur.length) segments.push(cur);

  const gradId = `grad-${Math.random().toString(36).slice(2, 9)}`;
  const baseY = (padT + plotH).toFixed(1);
  const linesSvg = segments.map(seg =>
    `<polyline points="${seg.map(pt => `${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />`
  ).join('');
  const areasSvg = segments.map(seg => {
    const first = seg[0], last = seg[seg.length - 1];
    return `<polygon points="${first[0].toFixed(1)},${baseY} ${seg.map(pt => `${pt[0].toFixed(1)},${pt[1].toFixed(1)}`).join(' ')} ${last[0].toFixed(1)},${baseY}" fill="url(#${gradId})" opacity="0.35" />`;
  }).join('');

  const gridLines = [0, 0.5, 1].map(t => {
    const y = padT + plotH * t;
    const val = maxY - (maxY - minY) * t;
    return `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${width - padR}" y2="${y.toFixed(1)}" stroke="#26314d" stroke-width="1" stroke-dasharray="3,3" />
      <text x="${padL - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="#8b96b3">${fmtNum(val, 0)}${unit}</text>`;
  }).join('');

  return `<svg viewBox="0 0 ${width} ${height}" class="chart-svg" role="img">
    <defs>
      <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${color}" stop-opacity="0.55" />
        <stop offset="100%" stop-color="${color}" stop-opacity="0" />
      </linearGradient>
    </defs>
    <rect x="0" y="0" width="${width}" height="${height}" rx="8" fill="#111a30" />
    ${gridLines}
    ${areasSvg}
    ${linesSvg}
    <text x="${padL}" y="${height - 6}" font-size="10" fill="#8b96b3">${escapeHtml(fmtDateShort(minX))}</text>
    <text x="${width - padR}" y="${height - 6}" text-anchor="end" font-size="10" fill="#8b96b3">${escapeHtml(fmtDateShort(maxX))}</text>
  </svg>`;
}

function chartCard(title, points, opts) {
  const vals = points.filter(p => typeof p.value === 'number' && isFinite(p.value)).map(p => p.value);
  const latest = vals.length ? vals[vals.length - 1] : null;
  const min = vals.length ? Math.min(...vals) : null;
  const max = vals.length ? Math.max(...vals) : null;
  const unit = opts.unit || '';
  const statsLine = vals.length
    ? `latest ${fmtNum(latest, 1)}${unit} &middot; min ${fmtNum(min, 1)}${unit} &middot; max ${fmtNum(max, 1)}${unit}`
    : '';
  return `<div class="chart-card">
    <div class="chart-title"><span>${escapeHtml(title)}</span><span class="chart-stats">${statsLine}</span></div>
    ${lineChartSvg(points, opts)}
  </div>`;
}

function tableOrEmpty(rows, colDefs, i18n) {
  if (!rows || !rows.length) {
    return `<div class="empty-msg">${escapeHtml(i18n.noData)}</div>`;
  }
  const head = colDefs.map(c => `<th>${escapeHtml(c.label)}</th>`).join('');
  const body = rows.map(row => `<tr>${colDefs.map(c => `<td>${escapeHtml(c.render ? c.render(row) : row[c.key])}</td>`).join('')}</tr>`).join('');
  return `<table class="report-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function buildReportHtml({ meta, snapshots, alertSummary, lang }) {
  const t = REPORT_I18N[lang === 'ko' ? 'ko' : 'en'];
  const latest = snapshots.length ? snapshots[snapshots.length - 1] : null;

  const coverageStartMs = snapshots.length ? snapshots[0].ts : null;
  const requestedFromMs = meta.periodFrom.getTime();
  const isPartial = !coverageStartMs || coverageStartMs > requestedFromMs + 6 * 60 * 60 * 1000; // >6h short of the full window

  // --- At a Glance ---
  const cpuPct = latest && latest.main.cpuPct && latest.main.cpuPct.ok ? latest.main.cpuPct.data : null;
  const memPct = latest && latest.main.memory && latest.main.memory.ok ? latest.main.memory.data.pct : null;
  const sessionCount = latest && latest.main.sessionCount && latest.main.sessionCount.ok ? latest.main.sessionCount.data : null;
  const invalidCount = latest && latest.main.invalidObjectsCount && latest.main.invalidObjectsCount.ok ? latest.main.invalidObjectsCount.data : null;

  const glanceCards = [
    { label: t.statCpu, value: cpuPct, unit: '%', cls: badgeClassHighBad(cpuPct) },
    { label: t.statMemory, value: memPct, unit: '%', cls: badgeClassHighBad(memPct) },
    { label: t.statSessions, value: sessionCount, unit: '', cls: '' },
    { label: t.statInvalid, value: invalidCount, unit: '', cls: invalidCount > 0 ? 'warn' : 'ok' }
  ].map(c => `
    <div class="stat-card">
      <div class="stat-label">${escapeHtml(c.label)}</div>
      <div class="stat-value">${c.value == null ? '-' : fmtNum(c.value, c.unit === '%' ? 1 : 0)}${c.unit}</div>
      ${c.cls ? `<div class="stat-sub"><span class="badge ${c.cls}">&nbsp;</span></div>` : ''}
    </div>`).join('');

  // --- Trend series ---
  const cpuSeries = snapshots.map(s => ({ ts: s.ts, value: s.main.cpuPct && s.main.cpuPct.ok ? s.main.cpuPct.data : null }));
  const memSeries = snapshots.map(s => ({ ts: s.ts, value: s.main.memory && s.main.memory.ok ? s.main.memory.data.pct : null }));
  const sessionSeries = snapshots.map(s => ({ ts: s.ts, value: s.main.sessionCount && s.main.sessionCount.ok ? s.main.sessionCount.data : null }));
  const invalidSeries = snapshots.map(s => ({ ts: s.ts, value: s.main.invalidObjectsCount && s.main.invalidObjectsCount.ok ? s.main.invalidObjectsCount.data : null }));

  const trendCharts = [
    chartCard(t.chartCpu, cpuSeries, { color: '#4f7cff', unit: '%', forceMinZero: true, capMax: 100 }),
    chartCard(t.chartMemory, memSeries, { color: '#7c93ff', unit: '%', forceMinZero: true, capMax: 100 }),
    chartCard(t.chartSessions, sessionSeries, { color: '#4fe3a3', unit: '', forceMinZero: true }),
    chartCard(t.chartInvalid, invalidSeries, { color: '#f2c14e', unit: '', forceMinZero: true })
  ].join('');

  // --- Instance Efficiency ---
  const eff = latest && latest.ops.instanceEfficiency && latest.ops.instanceEfficiency.ok ? latest.ops.instanceEfficiency.data : {};
  const effRows = [
    [t.effBuffer, eff.BUFFER_HIT_RATIO],
    [t.effLibrary, eff.LIBRARY_HIT_RATIO],
    [t.effSoftParse, eff.SOFT_PARSE_PCT],
    [t.effExecParse, eff.EXECUTE_TO_PARSE_PCT]
  ].map(([label, val]) => `
    <div class="stat-card">
      <div class="stat-label">${escapeHtml(label)}</div>
      <div class="stat-value">${val == null ? '-' : fmtNum(val, 1) + '%'}</div>
      <div class="stat-sub">${badge(val, badgeClassHighGood(val))}</div>
    </div>`).join('');

  // --- Load Profile ---
  const lp = latest && latest.ops.loadProfile && latest.ops.loadProfile.ok ? latest.ops.loadProfile.data : {};
  const lpRows = [
    [t.lpRedo, lp.REDO_SIZE_PER_SEC], [t.lpLogical, lp.LOGICAL_READS_PER_SEC], [t.lpPhysical, lp.PHYSICAL_READS_PER_SEC],
    [t.lpUserCalls, lp.USER_CALLS_PER_SEC], [t.lpExecutes, lp.EXECUTES_PER_SEC], [t.lpTx, lp.TRANSACTIONS_PER_SEC]
  ].map(([label, val]) => `
    <div class="stat-card">
      <div class="stat-label">${escapeHtml(label)}</div>
      <div class="stat-value">${fmtNum(val, 2)}</div>
    </div>`).join('');

  // --- Top SQL (latest snapshot) ---
  const topElapsed = latest && latest.ops.topQueries && latest.ops.topQueries.ok ? latest.ops.topQueries.data : [];
  const topCpu = latest && latest.ops.topQueriesCpu && latest.ops.topQueriesCpu.ok ? latest.ops.topQueriesCpu.data : [];
  const topGets = latest && latest.ops.topQueriesBufferGets && latest.ops.topQueriesBufferGets.ok ? latest.ops.topQueriesBufferGets.data : [];

  const topSqlHtml = `
    <div class="card-grid">
      <div class="table-card">
        <div class="chart-title"><span>${escapeHtml(t.topSqlElapsed)}</span></div>
        ${tableOrEmpty(topElapsed, [{ key: 'SQL_ID', label: t.colSqlId }, { key: 'ELAPSED_SEC', label: t.colElapsedSec }], t)}
      </div>
      <div class="table-card">
        <div class="chart-title"><span>${escapeHtml(t.topSqlCpu)}</span></div>
        ${tableOrEmpty(topCpu, [{ key: 'SQL_ID', label: t.colSqlId }, { key: 'CPU_SEC', label: t.colCpuSec }], t)}
      </div>
      <div class="table-card">
        <div class="chart-title"><span>${escapeHtml(t.topSqlGets)}</span></div>
        ${tableOrEmpty(topGets, [{ key: 'SQL_ID', label: t.colSqlId }, { key: 'BUFFER_GETS', label: t.colBufferGets, render: r => fmtNum(r.BUFFER_GETS, 0) }], t)}
      </div>
    </div>`;

  // --- Storage usage trend (TEMP worst-tablespace %, FRA net %) ---
  const tempSeries = snapshots.map(s => {
    const rows = s.usage.temp && s.usage.temp.ok ? s.usage.temp.data : [];
    const pcts = rows.map(r => Number(r.USED_PCT)).filter(v => isFinite(v));
    return { ts: s.ts, value: pcts.length ? Math.max(...pcts) : null };
  });
  const recoverySeries = snapshots.map(s => {
    const rows = s.usage.recovery && s.usage.recovery.ok ? s.usage.recovery.data : [];
    const v = rows.length ? Number(rows[0].USED_PCT_NET) : null;
    return { ts: s.ts, value: isFinite(v) ? v : null };
  });
  const usageCharts = [
    chartCard(t.chartTemp, tempSeries, { color: '#f2c14e', unit: '%', forceMinZero: true, capMax: 100 }),
    chartCard(t.chartRecovery, recoverySeries, { color: '#ff9f6b', unit: '%', forceMinZero: true, capMax: 100 })
  ].join('');

  // --- Tablespace I/O (latest snapshot) ---
  const tsIo = latest && latest.ops.tablespaceIo && latest.ops.tablespaceIo.ok ? latest.ops.tablespaceIo.data : [];
  const tsIoHtml = tableOrEmpty(tsIo, [
    { key: 'TABLESPACE_NAME', label: t.colTablespace },
    { key: 'PHYSICAL_READS', label: t.colReads, render: r => fmtNum(r.PHYSICAL_READS, 0) },
    { key: 'PHYSICAL_WRITES', label: t.colWrites, render: r => fmtNum(r.PHYSICAL_WRITES, 0) }
  ], t);

  // --- Alert Log summary ---
  let alertHtml;
  if (!alertSummary || !alertSummary.ok) {
    alertHtml = `<div class="empty-msg">${escapeHtml((alertSummary && alertSummary.message) || t.noData)}</div>`;
  } else {
    const byCodeHtml = tableOrEmpty(alertSummary.byCode, [
      { key: 'ORA_CODE', label: t.colOraCode },
      { key: 'CNT', label: t.colCount }
    ], t);
    const recentHtml = tableOrEmpty(alertSummary.recent, [
      { key: 'LOG_TIME', label: t.colTime },
      { key: 'ORA_CODE', label: t.colOraCode, render: r => r.ORA_CODE || '-' },
      { key: 'MESSAGE_TEXT', label: t.colMessage, render: r => (r.MESSAGE_TEXT || '').slice(0, 140) }
    ], t);
    alertHtml = `
      <div class="stat-card" style="margin-bottom:16px; max-width:260px;">
        <div class="stat-label">${escapeHtml(t.alertTotal)}</div>
        <div class="stat-value">${fmtNum(alertSummary.totalCount, 0)}</div>
      </div>
      <div class="card-grid">
        <div class="table-card"><div class="chart-title"><span>${escapeHtml(t.alertByCode)}</span></div>${byCodeHtml}</div>
        <div class="table-card"><div class="chart-title"><span>${escapeHtml(t.alertRecent)}</span></div>${recentHtml}</div>
      </div>`;
  }

  const partialNoteHtml = isPartial && coverageStartMs
    ? `<div class="note">⚠️ ${escapeHtml(t.partialDataNote(fmtDateTime(new Date(coverageStartMs))).replace('{days}', String(meta.periodDays)))}</div>`
    : '';

  return `<!doctype html>
<html lang="${lang === 'ko' ? 'ko' : 'en'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(t.title)}</title>
<style>
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
</style>
</head>
<body>
<div class="wrap">
  <header class="report-header">
    <h1>📊 ${escapeHtml(t.title)}</h1>
    <div class="meta-row">${escapeHtml(meta.instanceTarget)}</div>
    <div class="meta-grid">
      <div><span class="label">${escapeHtml(t.periodLabel)}</span><span class="value">${escapeHtml(fmtDateTime(meta.periodFrom))} &rarr; ${escapeHtml(fmtDateTime(meta.periodTo))}</span></div>
      <div><span class="label">${escapeHtml(t.generatedLabel)}</span><span class="value">${escapeHtml(fmtDateTime(meta.generatedAt))}</span></div>
      <div><span class="label">${escapeHtml(t.dataPointsLabel)}</span><span class="value">${snapshots.length}</span></div>
    </div>
    ${partialNoteHtml}
  </header>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionGlance)}</h2>
    <div class="card-grid">${glanceCards}</div>
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionTrend)}</h2>
    ${trendCharts}
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionEfficiency)}</h2>
    <div class="card-grid">${effRows}</div>
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionLoadProfile)}</h2>
    <div class="card-grid">${lpRows}</div>
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionTopSql)}</h2>
    ${topSqlHtml}
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionUsage)}</h2>
    ${usageCharts}
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionTablespaceIo)}</h2>
    <div class="table-card">${tsIoHtml}</div>
  </section>

  <section class="report-section">
    <h2>${escapeHtml(t.sectionAlertLog)}</h2>
    ${alertHtml}
  </section>

  <footer class="report-footer">${escapeHtml(t.footerNote)}</footer>
</div>
</body>
</html>`;
}

// Ties everything together for the /api/generate-report endpoint: takes a
// fresh snapshot right now (so the report's "latest" numbers are current,
// not up to 15 minutes stale), reads the trailing `days` of history for
// this same DB, fetches the Alert Log summary live, and renders the HTML.
async function generateReport(creds, days, lang) {
  await gatherSnapshot(creds).catch(err => {
    console.error('[report] on-demand snapshot failed (continuing with existing history):', err.message);
    return null;
  });

  const target = { ip: creds.ip, port: creds.port, sid: creds.sid };
  const snapshots = readSnapshots(days, target);
  const alertSummary = await fetchAlertSummary(creds, days);

  const meta = {
    instanceTarget: `${creds.account}@${creds.ip}:${creds.port}:${creds.sid}`,
    generatedAt: new Date(),
    periodDays: days,
    periodFrom: new Date(Date.now() - days * 24 * 60 * 60 * 1000),
    periodTo: new Date()
  };

  return buildReportHtml({ meta, snapshots, alertSummary, lang });
}

module.exports = {
  SNAPSHOT_INTERVAL_MS,
  startCollector,
  triggerImmediateCollection,
  generateReport,
  // Exported for tests / troubleshooting only:
  readSnapshots,
  gatherSnapshot
};
