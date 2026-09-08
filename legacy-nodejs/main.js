// OraPulse backend — a small standalone Express + Oracle server, meant to
// be run locally by each user (npm install && npm start, then open
// http://127.0.0.1:3000 in a browser), the same way you'd run a desktop DB
// client. It is not a hosted/shared service: every user runs their own
// instance of this process, against their own Oracle credentials.
//
// Because of that, all the internet-facing hardening a real multi-user
// hosted web app would need (app-level login/sign-up, JWT, rate limiting,
// CORS, helmet) is intentionally left out here -- it doesn't apply to this
// deployment model. This Express server is bound to 127.0.0.1 and only
// ever reached by a browser on this same machine -- there is no network
// path for anyone else to reach it. The Oracle DB account/password entered
// on the connect screen is the only "login" needed, exactly like a normal
// desktop DB client. (If you do want to run one shared instance that
// multiple people connect to remotely instead, see the "Running as a
// shared server instead of per-user" note in README.md first -- that
// changes this security model and needs the HOST binding below revisited.)
//
// Only Oracle Database 12.1 or later is supported (node-oracledb's pure-JS
// "thin mode" -- no Oracle Instant Client / thick-mode install required).
// See README.md in the project root for how to add thick-mode support if a
// specific environment needs it (e.g. Oracle Wallet, advanced security
// options).
const express = require('express');
const session = require('express-session');
const path = require('path');
const http = require('http');
const fs = require('fs');
const oracledb = require('oracledb');
const report = require('./report');
const favorites = require('./favorites');
const tuning = require('./tuning');

const app = express();
// 127.0.0.1 only: this must never be reachable from the network or from
// another machine, only from a browser on this same computer. See the
// top-of-file comment above if you're deliberately setting this up as a
// shared server instead.
const HOST = '127.0.0.1';
const PORT = process.env.PORT || 3000;

// Version scheme: 1.NNNN, where NNNN is a zero-padded counter bumped by
// one for every change (1.0000 -> 1.0001 -> 1.0002 -> ...), not decimal
// arithmetic. VERSION is a plain text file at the project root, shared
// with the Python port (main.py reads the same file) so both report the
// same version regardless of which backend is actually running.
let APP_VERSION = 'unknown';
try {
  APP_VERSION = fs.readFileSync(path.join(__dirname, 'VERSION'), 'utf8').trim();
} catch (err) {
  console.error('Could not read VERSION file:', err.message);
}

app.use(express.json());

// A session cookie is still the simplest way to remember "which Oracle DB
// is this browser tab currently connected to" between requests, even
// though there's only ever one real user of this particular server
// process.
app.use(session({
  secret: 'orapulse-local-session', // Never leaves this machine; does not need to be secret from anyone but this process itself.
  resave: false,
  saveUninitialized: false,
  cookie: {
    httpOnly: true,
    maxAge: 30 * 60 * 1000 // 30 minutes
  }
}));

app.use(express.static(path.join(__dirname, 'public')));

// --- End the DB session when the browser actually closes ---
//
// dashboard.html sends a `navigator.sendBeacon('/api/browser-closing')` from
// a `pagehide` handler. There's no reliable way to tell "the tab was closed"
// apart from "the page is about to reload/navigate" at the moment the event
// fires (both fire the same pagehide/beforeunload events) -- so instead of
// disconnecting immediately, this only *schedules* a disconnect a few
// seconds out. Any other request from this browser (the reloaded page
// re-fetching /api/db-status, a normal navigation within the app, etc.)
// cancels it via the middleware below. Only a gap with no follow-up request
// at all -- an actual close -- lets the timer fire.
const BROWSER_CLOSE_GRACE_MS = 5000;
let pendingDisconnectTimer = null;

app.use((req, res, next) => {
  if (req.path !== '/api/browser-closing' && pendingDisconnectTimer) {
    clearTimeout(pendingDisconnectTimer);
    pendingDisconnectTimer = null;
  }
  next();
});

app.post('/api/browser-closing', (req, res) => {
  if (pendingDisconnectTimer) clearTimeout(pendingDisconnectTimer);
  pendingDisconnectTimer = setTimeout(() => {
    pendingDisconnectTimer = null;
    // Ends both the dashboard's login session and the Weekly DB Health
    // Report's background collector (see lastConnectedCreds below) -- a
    // full stop, not just a logout, per explicit request: unlike the
    // Disconnect button, closing the browser is meant to leave nothing
    // still polling this DB. req.session.destroy() (not just clearing
    // dbCreds) because by now the original request/response cycle that
    // handed us this `req` is long finished -- express-session only
    // auto-persists changes at the end of a request's response, which
    // already happened, so a plain property change here would silently
    // never reach the session store. destroy() writes through immediately.
    if (req.session) req.session.destroy(() => {});
    lastConnectedCreds = null;
  }, BROWSER_CLOSE_GRACE_MS);
  res.sendStatus(204);
});

function buildConnectString(ip, port, sid) {
  // Full TNS connect descriptor based on SID.
  // For a DB that uses a Service Name instead, change this to the
  // `${ip}:${port}/${serviceName}` form.
  return `(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=${ip})(PORT=${port}))` +
         `(CONNECT_DATA=(SID=${sid})))`;
}

// Used only by the ad-hoc SQL Query Runner (/api/run-query), since that
// endpoint executes whatever SELECT the user typed and can't rely on every
// DATE/TIMESTAMP column already being wrapped in TO_CHAR(...) the way the
// rest of this file's own queries are. node-oracledb returns those columns
// as JS Date objects; JSON.stringify (and therefore res.json()) would
// otherwise serialize them as a raw ISO 8601 UTC string (e.g.
// "2026-08-30T17:44:40.000Z") -- the same bug already fixed for the Recent
// DML / SQL Text views above. This reformats any Date value to the same
// 'YYYY-MM-DD HH24:MI:SS' shape used everywhere else in the app, reading it
// with the UTC getters (which line up with what TO_CHAR would produce for
// the same column, confirmed via that earlier fix). Non-Date values pass
// through unchanged.
function formatDbValue(v) {
  if (v instanceof Date) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${v.getUTCFullYear()}-${pad(v.getUTCMonth() + 1)}-${pad(v.getUTCDate())} ` +
           `${pad(v.getUTCHours())}:${pad(v.getUTCMinutes())}:${pad(v.getUTCSeconds())}`;
  }
  return v;
}

// The most recently successful /api/connect credentials, kept at module
// scope (outside any one session) so the background "Weekly DB Health
// Report" snapshot collector in report.js can keep running against the
// right DB even after the browser tab that connected is closed or the
// session cookie expires -- see report.js's own top-of-file comment for why
// that's the whole point of the feature. Overwritten by the next successful
// connect; never read back by anything except report.js's collector.
let lastConnectedCreds = null;

// The ad-hoc SQL Query Runner (see /api/run-query below) lets the user
// SELECT from arbitrary tables/views, including ones that happen to have
// CLOB columns. Without this, node-oracledb returns CLOB columns as Lob
// stream objects that can't be serialized straight into a JSON response;
// fetching them as plain JS strings instead means the runner works for any
// query without needing per-query column-type awareness. (BLOB is
// deliberately left alone -- there's no sensible plain-text rendering for
// arbitrary binary data, so a query selecting a BLOB column will still come
// back as an unusable object; this is a known, documented limitation.)
oracledb.fetchAsString = [oracledb.CLOB];

app.post('/api/connect', async (req, res) => {
  const { ip, port, sid, account, password } = req.body || {};

  if (!ip || !port || !sid || !account || !password) {
    return res.status(400).json({
      success: false,
      message: 'Please fill in all fields (IP, Port, SID, Account, Password).'
    });
  }

  const connectString = buildConnectString(ip, port, sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: account,
      password: password,
      connectString: connectString
    });

    // Simple query to confirm the connection
    await connection.execute('SELECT 1 FROM dual');

    // Store the connection info in the session so it can be reused on the
    // main screen (DB status lookup)
    req.session.dbCreds = { ip, port, sid, account, password };

    // Also cache it at module scope and kick off an immediate background
    // snapshot (fire-and-forget) for the Weekly DB Health Report feature --
    // see report.js and the lastConnectedCreds comment above.
    lastConnectedCreds = { ip, port, sid, account, password };
    report.triggerImmediateCollection(lastConnectedCreds);

    return res.json({
      success: true,
      message: `Connected successfully to ${account}@${ip}:${port}:${sid}.`
    });
  } catch (err) {
    req.session.dbCreds = null;
    let message = `Connection failed: ${err.message}`;

    if (err.message && err.message.includes('NJS-138')) {
      message +=
        '\n\nThis DB server version (older than Oracle 12.1) is not supported ' +
        'here, since this app only supports thin-mode connections.';
    }

    return res.json({
      success: false,
      message
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

app.post('/api/logout', (req, res) => {
  req.session.destroy(() => {
    res.json({ success: true });
  });
});

app.get('/api/version', (req, res) => {
  res.json({ success: true, version: APP_VERSION });
});

// Favorites (saved connection details on the connect screen) -- see
// favorites.js for the encrypted-file storage this reads/writes. No login
// gate here (same as everywhere else in this app -- see the top-of-file
// comment): this feature only exists to be usable before any DB
// connection/session exists yet.
app.get('/api/favorites', (req, res) => {
  try {
    res.json({ success: true, favorites: favorites.listFavorites() });
  } catch (err) {
    res.json({ success: false, message: `Failed to load favorites: ${err.message}` });
  }
});

app.post('/api/favorites', (req, res) => {
  const { id, name, ip, port, sid, account, password } = req.body || {};
  if (!name || !ip || !port || !sid || !account || !password) {
    return res.status(400).json({
      success: false,
      message: 'Please fill in all fields (Name, IP, Port, SID, Account, Password).'
    });
  }
  try {
    const saved = favorites.saveFavorite({ id, name, ip, port, sid, account, password });
    res.json({ success: true, favorite: saved });
  } catch (err) {
    res.json({ success: false, message: `Failed to save favorite: ${err.message}` });
  }
});

app.post('/api/favorites-delete', (req, res) => {
  const { id } = req.body || {};
  if (!id) {
    return res.status(400).json({ success: false, message: 'Missing favorite id.' });
  }
  try {
    favorites.deleteFavorite(id);
    res.json({ success: true });
  } catch (err) {
    res.json({ success: false, message: `Failed to delete favorite: ${err.message}` });
  }
});

app.get('/api/db-status', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
  } catch (err) {
    return res.status(500).json({
      success: false,
      message: `Failed to reconnect to the DB: ${err.message}`
    });
  }

  const result = {
    success: true,
    target: { ip: creds.ip, port: creds.port, sid: creds.sid, account: creds.account },
    instance: null,
    sessionCount: null,
    sessionList: null,
    blockingSessions: null,
    longRunningOps: null,
    cpu: null,
    memory: null
  };

  // 1) Basic instance information
  try {
    const r = await connection.execute(
      `SELECT instance_name, status, host_name, version_full AS version,
              TO_CHAR(startup_time, 'YYYY-MM-DD HH24:MI:SS') AS startup_time,
              ROUND((SYSDATE - startup_time) * 86400) AS uptime_seconds
         FROM v$instance`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    if (r.rows.length > 0) {
      result.instance = { ok: true, data: r.rows[0] };
    } else {
      result.instance = { ok: false, message: 'No results found.' };
    }
  } catch (err) {
    result.instance = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 2) Current connected session count (excludes background processes like
  //    PMON/SMON and counts only real user sessions)
  try {
    const r = await connection.execute(
      `SELECT COUNT(*) AS cnt FROM v$session WHERE type = 'USER'`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.sessionCount = { ok: true, data: r.rows[0].CNT };
  } catch (err) {
    result.sessionCount = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 3) Current session list (excludes background processes; type = 'USER',
  //    any status -- ACTIVE and INACTIVE both, so the Status filter on the
  //    dashboard actually has something to filter between, and so idle
  //    INACTIVE sessions can be found and killed from this list). ACTIVE
  //    sessions are shown first, then within each status group sessions
  //    are sorted by logon time, oldest first -- a long-connected ACTIVE
  //    session is usually the one worth looking at first. Capped at 50 rows.
  try {
    const r = await connection.execute(
      `SELECT sid, serial_num, status, machine, program, logon_time_str, sql_id
         FROM (
           SELECT sid, serial# AS serial_num, status, machine, program, sql_id,
                  TO_CHAR(logon_time, 'YYYY-MM-DD HH24:MI:SS') AS logon_time_str
             FROM v$session
            WHERE type = 'USER'
            ORDER BY CASE WHEN status = 'ACTIVE' THEN 0 ELSE 1 END,
                     logon_time ASC,
                     sid
         ) WHERE ROWNUM <= 50`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const r2 = await connection.execute(
      `SELECT COUNT(*) AS cnt FROM v$session WHERE type = 'USER'`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const totalCount = r2.rows[0].CNT;
    result.sessionList = {
      ok: true,
      data: r.rows,
      truncated: totalCount > r.rows.length
    };
  } catch (err) {
    result.sessionList = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 4) Blocking Session - list of sessions that are blocking other sessions
  try {
    const r = await connection.execute(
      `SELECT waiter.sid AS waiter_sid, waiter.serial# AS waiter_serial,
              waiter.username AS waiter_user,
              blocker.sid AS blocker_sid, blocker.serial# AS blocker_serial,
              blocker.username AS blocker_user,
              waiter.machine AS waiter_machine,
              waiter.wait_class AS wait_class,
              waiter.seconds_in_wait AS wait_seconds
         FROM v$session waiter
         JOIN v$session blocker ON waiter.blocking_session = blocker.sid
        WHERE waiter.blocking_session IS NOT NULL
        ORDER BY waiter.seconds_in_wait DESC`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.blockingSessions = { ok: true, data: r.rows };
  } catch (err) {
    result.blockingSessions = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 5) Long Running Session - progress of long-running operations (full
  //    table scans, backups, index creation, etc.)
  try {
    const r = await connection.execute(
      `SELECT sid, serial_num, opname, target, sofar, totalwork,
              ROUND(sofar / totalwork * 100, 1) AS pct_complete,
              elapsed_seconds, time_remaining
         FROM (
           SELECT sid, serial# AS serial_num, opname, target, sofar, totalwork,
                  elapsed_seconds, time_remaining
             FROM v$session_longops
            WHERE totalwork > 0
              AND sofar < totalwork
            ORDER BY start_time DESC
         ) WHERE ROWNUM <= 10`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.longRunningOps = { ok: true, data: r.rows };
  } catch (err) {
    result.longRunningOps = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 6) CPU usage (Host CPU Utilization %)
  try {
    const r = await connection.execute(
      `SELECT value FROM (
         SELECT value FROM v$sysmetric
          WHERE metric_name = 'Host CPU Utilization (%)'
          ORDER BY end_time DESC
       ) WHERE ROWNUM = 1`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    if (r.rows.length > 0) {
      result.cpu = { ok: true, data: { pct: Number(r.rows[0].VALUE) } };
    } else {
      result.cpu = { ok: false, message: 'No results found.' };
    }
  } catch (err) {
    result.cpu = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 7) Memory usage (SGA + PGA usage vs. the configured memory target)
  try {
    const r = await connection.execute(
      `SELECT
         ROUND((SELECT SUM(value) FROM v$sga) / 1024 / 1024, 1) AS sga_mb,
         ROUND((SELECT value FROM v$pgastat WHERE name = 'total PGA allocated') / 1024 / 1024, 1) AS pga_mb,
         ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'sga_max_size'), 0) / 1024 / 1024, 1) AS sga_max_mb,
         ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'pga_aggregate_target'), 0) / 1024 / 1024, 1) AS pga_target_mb,
         ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_target'), 0) / 1024 / 1024, 1) AS memory_target_mb,
         ROUND(NVL((SELECT value FROM v$parameter WHERE name = 'memory_max_target'), 0) / 1024 / 1024, 1) AS memory_max_target_mb
       FROM dual`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const d = r.rows[0];
    const usedMb = Number(d.SGA_MB || 0) + Number(d.PGA_MB || 0);
    const targetMb =
      Number(d.MEMORY_TARGET_MB) > 0 ? Number(d.MEMORY_TARGET_MB) :
      Number(d.MEMORY_MAX_TARGET_MB) > 0 ? Number(d.MEMORY_MAX_TARGET_MB) :
      (Number(d.SGA_MAX_MB || 0) + Number(d.PGA_TARGET_MB || 0));
    const pct = targetMb > 0 ? Math.round((usedMb / targetMb) * 1000) / 10 : null;

    result.memory = {
      ok: true,
      data: {
        sgaMb: Number(d.SGA_MB || 0),
        pgaMb: Number(d.PGA_MB || 0),
        usedMb: Math.round(usedMb * 10) / 10,
        targetMb: targetMb > 0 ? Math.round(targetMb * 10) / 10 : null,
        pct
      }
    };
  } catch (err) {
    result.memory = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  try {
    await connection.close();
  } catch (closeErr) {
    console.error('Error while closing connection:', closeErr.message);
  }

  return res.json(result);
});

// For the Table Statistics Collection card: fetches the list of users (OWNER)
app.get('/api/table-owners', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    const r = await connection.execute(
      `SELECT DISTINCT owner FROM dba_tables ORDER BY owner`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    return res.json({ success: true, data: r.rows.map(row => row.OWNER) });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. DBA privileges are required. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// For the Table Statistics Collection card: per-table statistics for the
// selected user (OWNER)
app.get('/api/table-stats', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const owner = (req.query.owner || '').toString().trim();
  if (!owner) {
    return res.status(400).json({ success: false, message: 'An owner parameter is required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    const r = await connection.execute(
      `SELECT table_name, partition_name, tablespace_name,
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
       ) WHERE ROWNUM <= 200`,
      { owner },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    const r2 = await connection.execute(
      `SELECT COUNT(*) AS cnt
         FROM dba_tab_statistics
        WHERE owner = :owner
          AND object_type IN ('TABLE', 'PARTITION')`,
      { owner },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const totalCount = r2.rows[0].CNT;

    return res.json({
      success: true,
      data: r.rows,
      totalCount,
      truncated: totalCount > r.rows.length
    });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. DBA privileges are required. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Runs DBMS_STATS.GATHER_TABLE_STATS immediately for a specific table (or
// partition) selected via the long-press menu on the Table Statistics
// Collection screen.
app.post('/api/gather-table-stats', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const body = req.body || {};
  const owner = (body.owner || '').toString().trim();
  const tableName = (body.tableName || '').toString().trim();
  const partitionNameRaw = (body.partitionName || '').toString().trim();
  const partitionName = partitionNameRaw ? partitionNameRaw : null;

  // Only allow valid Oracle identifiers (alphanumeric plus _, $, #).
  const IDENT_RE = /^[A-Za-z0-9_$#]+$/;
  if (!IDENT_RE.test(owner) || !IDENT_RE.test(tableName) || (partitionName && !IDENT_RE.test(partitionName))) {
    return res.status(400).json({
      success: false,
      message: 'owner/tableName/partitionName has an invalid format.'
    });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    await connection.execute(
      `BEGIN
         DBMS_STATS.GATHER_TABLE_STATS(
           ownname          => :owner,
           tabname          => :tableName,
           partname         => :partitionName,
           estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
           cascade          => TRUE,
           degree           => DBMS_STATS.AUTO_DEGREE
         );
       END;`,
      { owner, tableName, partitionName },
      { autoCommit: true }
    );

    const target = partitionName
      ? `${owner}.${tableName} (partition ${partitionName})`
      : `${owner}.${tableName}`;
    return res.json({ success: true, message: `Statistics collection completed for ${target}.` });
  } catch (err) {
    return res.json({
      success: false,
      message: `Statistics collection failed. ANALYZE ANY DICTIONARY or the relevant schema privilege is required. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Runs DBMS_STATS.GATHER_TABLE_STATS for several tables/partitions at once,
// selected via checkboxes on the Table Statistics Collection screen. Reuses
// a single connection for the whole batch (rather than one connection per
// item) and keeps going even if an individual item fails, so one bad table
// doesn't block the rest of the batch. Capped at 200 items per request to
// match the table list's own page size.
app.post('/api/gather-table-stats-batch', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const body = req.body || {};
  const owner = (body.owner || '').toString().trim();
  const items = Array.isArray(body.items) ? body.items : [];

  const IDENT_RE = /^[A-Za-z0-9_$#]+$/;
  if (!IDENT_RE.test(owner)) {
    return res.status(400).json({ success: false, message: 'owner has an invalid format.' });
  }
  if (!items.length) {
    return res.status(400).json({ success: false, message: 'At least one table must be selected.' });
  }
  if (items.length > 200) {
    return res.status(400).json({ success: false, message: 'A maximum of 200 tables can be gathered in a single batch.' });
  }

  const normalizedItems = [];
  for (const item of items) {
    const tableName = ((item && item.tableName) || '').toString().trim();
    const partitionNameRaw = ((item && item.partitionName) || '').toString().trim();
    const partitionName = partitionNameRaw ? partitionNameRaw : null;
    if (!IDENT_RE.test(tableName) || (partitionName && !IDENT_RE.test(partitionName))) {
      return res.status(400).json({
        success: false,
        message: `tableName/partitionName has an invalid format: ${tableName || '(empty)'}`
      });
    }
    normalizedItems.push({ tableName, partitionName });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
  } catch (err) {
    return res.json({
      success: false,
      message: `Failed to connect to the DB: ${err.message}`
    });
  }

  const results = [];
  for (const { tableName, partitionName } of normalizedItems) {
    const target = partitionName ? `${owner}.${tableName} (partition ${partitionName})` : `${owner}.${tableName}`;
    try {
      await connection.execute(
        `BEGIN
           DBMS_STATS.GATHER_TABLE_STATS(
             ownname          => :owner,
             tabname          => :tableName,
             partname         => :partitionName,
             estimate_percent => DBMS_STATS.AUTO_SAMPLE_SIZE,
             cascade          => TRUE,
             degree           => DBMS_STATS.AUTO_DEGREE
           );
         END;`,
        { owner, tableName, partitionName },
        { autoCommit: true }
      );
      results.push({ tableName, partitionName, ok: true, message: `Completed for ${target}.` });
    } catch (err) {
      results.push({ tableName, partitionName, ok: false, message: `Failed for ${target}: ${err.message}` });
    }
  }

  try {
    await connection.close();
  } catch (closeErr) {
    console.error('Error while closing connection:', closeErr.message);
  }

  const succeeded = results.filter(r => r.ok).length;
  return res.json({
    success: true,
    results,
    summary: { total: results.length, succeeded, failed: results.length - succeeded }
  });
});

// Backs the "View Table Properties" item in the Table Statistics Collection
// screen's right-click menu: basic table attributes plus its column and
// index lists. Each of the three sections is queried and reported
// independently (ok/message per section, matching the Ops tab's cards) so
// that e.g. missing DBA_INDEXES access doesn't blank out the columns list.
app.get('/api/table-properties', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const owner = (req.query.owner || '').toString().trim();
  const tableName = (req.query.tableName || '').toString().trim();
  if (!owner || !tableName) {
    return res.status(400).json({ success: false, message: 'owner and tableName parameters are required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
  } catch (err) {
    return res.json({ success: false, message: `Failed to connect to the DB: ${err.message}` });
  }

  const result = { success: true, basic: null, columns: null, indexes: null };

  try {
    const r = await connection.execute(
      `SELECT owner, table_name, tablespace_name, partitioned, num_rows, blocks,
              avg_row_len, logging, compression, degree,
              TO_CHAR(last_analyzed, 'YYYY-MM-DD HH24:MI:SS') AS last_analyzed
         FROM dba_tables
        WHERE owner = :owner AND table_name = :tableName`,
      { owner, tableName },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.basic = { ok: true, data: r.rows[0] || null };
  } catch (err) {
    result.basic = { ok: false, message: `Failed to load basic table info: ${err.message}` };
  }

  try {
    const r = await connection.execute(
      `SELECT column_name, data_type, data_length, data_precision, data_scale,
              nullable, column_id
         FROM dba_tab_columns
        WHERE owner = :owner AND table_name = :tableName
        ORDER BY column_id ASC`,
      { owner, tableName },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.columns = { ok: true, data: r.rows };
  } catch (err) {
    result.columns = { ok: false, message: `Failed to load column list: ${err.message}` };
  }

  try {
    const r = await connection.execute(
      `SELECT i.index_name, i.uniqueness, i.status,
              LISTAGG(ic.column_name, ', ') WITHIN GROUP (ORDER BY ic.column_position) AS columns
         FROM dba_indexes i
         JOIN dba_ind_columns ic
           ON ic.index_owner = i.owner AND ic.index_name = i.index_name
        WHERE i.table_owner = :owner AND i.table_name = :tableName
        GROUP BY i.index_name, i.uniqueness, i.status
        ORDER BY i.index_name ASC`,
      { owner, tableName },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.indexes = { ok: true, data: r.rows };
  } catch (err) {
    result.indexes = { ok: false, message: `Failed to load index list: ${err.message}` };
  }

  try {
    await connection.close();
  } catch (closeErr) {
    console.error('Error while closing connection:', closeErr.message);
  }

  return res.json(result);
});

// Object View tab: a small object browser (schema -> list of objects ->
// click one to see its script), similar in spirit to a desktop DB client's
// object explorer. /api/object-list backs the left-hand list;
// /api/object-ddl backs the right-hand script viewer.
const OBJECT_TYPES_EXCLUDED = [
  'LOB', 'LOB PARTITION', 'TABLE PARTITION', 'TABLE SUBPARTITION',
  'INDEX PARTITION', 'INDEX SUBPARTITION'
];

// DBA_OBJECTS.OBJECT_TYPE -> the type name DBMS_METADATA.GET_DDL expects.
// Not every object type in DBA_OBJECTS has a DDL equivalent (e.g. LOB
// segments, which are already excluded above); anything not listed here is
// reported to the user as unsupported for scripting rather than sent to
// GET_DDL and failing with a cryptic ORA/DBMS_METADATA error.
const OBJECT_DDL_TYPE_MAP = {
  TABLE: 'TABLE',
  VIEW: 'VIEW',
  'MATERIALIZED VIEW': 'MATERIALIZED_VIEW',
  PACKAGE: 'PACKAGE_SPEC',
  'PACKAGE BODY': 'PACKAGE_BODY',
  PROCEDURE: 'PROCEDURE',
  FUNCTION: 'FUNCTION',
  TRIGGER: 'TRIGGER',
  TYPE: 'TYPE_SPEC',
  'TYPE BODY': 'TYPE_BODY',
  SEQUENCE: 'SEQUENCE',
  INDEX: 'INDEX',
  SYNONYM: 'SYNONYM'
};

app.get('/api/object-list', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const owner = (req.query.owner || '').toString().trim();
  if (!owner) {
    return res.status(400).json({ success: false, message: 'An owner parameter is required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);
  const excludedList = OBJECT_TYPES_EXCLUDED.map(t => `'${t}'`).join(', ');

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    const r = await connection.execute(
      `SELECT object_name, object_type, status,
              TO_CHAR(last_ddl_time, 'YYYY-MM-DD HH24:MI:SS') AS last_ddl_time
         FROM (
           SELECT object_name, object_type, status, last_ddl_time
             FROM dba_objects
            WHERE owner = :owner
              AND object_type NOT IN (${excludedList})
            ORDER BY object_type ASC, object_name ASC
         ) WHERE ROWNUM <= 3000`,
      { owner },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    const r2 = await connection.execute(
      `SELECT COUNT(*) AS cnt FROM dba_objects
        WHERE owner = :owner AND object_type NOT IN (${excludedList})`,
      { owner },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const totalCount = r2.rows[0].CNT;

    return res.json({
      success: true,
      data: r.rows,
      totalCount,
      truncated: totalCount > r.rows.length
    });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. DBA privileges are required. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

app.get('/api/object-ddl', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const owner = (req.query.owner || '').toString().trim();
  const objectName = (req.query.objectName || '').toString().trim();
  const objectType = (req.query.objectType || '').toString().trim().toUpperCase();
  if (!owner || !objectName || !objectType) {
    return res.status(400).json({
      success: false,
      message: 'owner, objectName and objectType parameters are required.'
    });
  }

  const ddlType = OBJECT_DDL_TYPE_MAP[objectType];
  if (!ddlType) {
    return res.json({
      success: false,
      message: `Viewing the script for object type '${objectType}' is not supported.`
    });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    // Best-effort: trims storage/tablespace/segment-attribute clauses from
    // the generated DDL so a table/index script reads like source code
    // rather than a verbose physical-storage dump. Not fatal if the account
    // can't call this (older DB, restricted privileges) -- GET_DDL still
    // runs below, just with the fuller default output.
    try {
      await connection.execute(
        `BEGIN
           DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'STORAGE', FALSE);
           DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'TABLESPACE', FALSE);
           DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM, 'SEGMENT_ATTRIBUTES', FALSE);
         END;`
      );
    } catch (transformErr) {
      // ignored -- see comment above
    }

    const r = await connection.execute(
      `SELECT DBMS_METADATA.GET_DDL(:ddlType, :objectName, :owner) AS ddl FROM dual`,
      { ddlType, objectName, owner },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    const ddl = r.rows[0] && r.rows[0].DDL;
    if (!ddl) {
      return res.json({ success: false, message: 'No DDL was returned for this object.' });
    }
    return res.json({ success: true, ddl: ddl.toString().trim() });
  } catch (err) {
    return res.json({
      success: false,
      message: `Failed to retrieve the script for this object. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Tuning tab: a rule-based health check that works on any Oracle edition
// or version with no Diagnostics/Tuning Pack license -- see tuning.js's
// own top-of-file comment for the reasoning and what each rule checks.
// Structured findings only (rule id + severity + numeric values); the
// dashboard's own i18n layer renders each one into a localized title and
// message, the same split every other live tab uses.
app.get('/api/tuning-check', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
    const result = await tuning.runTuningCheck(connection, creds);
    return res.json(result);
  } catch (err) {
    return res.json({ success: false, message: `Failed to run the tuning check: ${err.message}` });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// For the Alert Log Analysis card: surfaces noteworthy entries from the
// database alert log via V$DIAG_ALERT_EXT (see the web app's README for why
// this approach is used instead of reading the raw alert log file). Not
// part of the auto-refresh cycle — loaded once on screen open and again via
// its own "Refresh" action.
app.get('/api/alert-log', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  let days = parseInt(req.query.days, 10);
  if (!Number.isInteger(days) || days <= 0) days = 7;
  if (days > 30) days = 30;

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    const r = await connection.execute(
      `SELECT log_time, message_type, message_level, ora_code, message_text FROM (
         SELECT
                TO_CHAR(originating_timestamp, 'YYYY-MM-DD HH24:MI:SS') AS log_time,
                message_type,
                message_level,
                REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') AS ora_code,
                message_text
           FROM v$diag_alert_ext
          WHERE originating_timestamp > SYSDATE - :days
            AND (message_text LIKE '%ORA-%' OR message_type IN (2, 3))
            -- Some background/diagnostic entries end with "Result = ORA-0"
            -- or "Result = ORA-30" -- unpadded, non-error result codes
            -- Oracle also uses for normal/successful completion, not actual
            -- errors -- real error codes are always the full zero-padded
            -- 5-digit form (ORA-00060, ORA-00942, etc.), so matching the
            -- *extracted* code for an exact "ORA-0"/"ORA-30" excludes only
            -- these normal-result markers, never a genuine error whose code
            -- happens to start with "ORA-0..."/"ORA-30...". The IS NULL
            -- branch keeps rows that matched via message_type IN (2, 3) but
            -- don't contain an ORA- code at all. Excluded here (before the
            -- outer ROWNUM <= 30 limit) so this noise doesn't leave a page
            -- of results short a few rows compared to what's actually
            -- available.
            AND (REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') IS NULL
                 OR REGEXP_SUBSTR(message_text, 'ORA-[0-9]+') NOT IN ('ORA-0', 'ORA-30'))
          ORDER BY originating_timestamp DESC
       ) WHERE ROWNUM <= 30`,
      { days },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    return res.json({ success: true, data: r.rows, days });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. Access to V$DIAG_ALERT_EXT is required (typically granted via SELECT_CATALOG_ROLE or the SELECT ANY DICTIONARY privilege). (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Fired when a session is clicked in the current session list: looks up
// wait detail information for that SID.
app.get('/api/session-wait-detail', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const sid = Number(req.query.sid);
  if (!Number.isInteger(sid) || sid <= 0) {
    return res.status(400).json({ success: false, message: 'A valid sid parameter is required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    const r = await connection.execute(
      `SELECT inst_id,
              sid,
              serial# AS serial_num,
              sql_id,
              event,
              state,
              seconds_in_wait,
              p1text,
              p1,
              p2text,
              p2,
              p3text,
              p3,
              row_wait_obj# AS row_wait_obj,
              row_wait_file# AS row_wait_file,
              row_wait_block# AS row_wait_block,
              blocking_instance,
              blocking_session
         FROM gv$session
        WHERE sid = :sid`,
      { sid },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    return res.json({ success: true, data: r.rows });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Looks up the currently-cached SQL text (and a few execution stats) for a
// given SQL_ID, for the "View Running Query" item in the Current Session
// List's right-click/long-press context menu.
app.get('/api/session-sql', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const sqlId = String(req.query.sqlId || '').trim();
  if (!sqlId || !/^[0-9a-zA-Z]+$/.test(sqlId)) {
    return res.status(400).json({ success: false, message: 'A valid sqlId parameter is required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    // sql_fulltext is a CLOB; DBMS_LOB.SUBSTR keeps the result a plain
    // VARCHAR2 (up to 4000 chars) so node-oracledb doesn't need any special
    // CLOB fetch handling. A cursor can have multiple child_number rows for
    // the same sql_id (different bind/plan variants) -- just show the most
    // recently active one.
    const r = await connection.execute(
      `SELECT sql_id,
              child_number,
              parsing_schema_name,
              executions,
              ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
              ROUND(cpu_time / 1000000, 3) AS cpu_sec,
              TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time,
              DBMS_LOB.SUBSTR(sql_fulltext, 4000, 1) AS sql_text
         FROM v$sql
        WHERE sql_id = :sqlId
        ORDER BY last_active_time DESC
        FETCH FIRST 1 ROWS ONLY`,
      { sqlId },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    return res.json({ success: true, data: r.rows });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Uses the P1(FILE_NO) / P2(BLOCK_NO) values from the wait detail info above
// to look up the object (segment) that the actual file/block belongs to.
app.get('/api/block-object', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const fileNo = Number(req.query.fileno);
  const blockNo = Number(req.query.blockno);
  if (!Number.isInteger(fileNo) || fileNo <= 0 || !Number.isInteger(blockNo) || blockNo < 0) {
    return res.status(400).json({ success: false, message: 'A valid fileno/blockno parameter is required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    const r = await connection.execute(
      `SELECT owner,
              segment_name,
              partition_name,
              segment_type,
              tablespace_name,
              relative_fno,
              block_id AS extent_start_block,
              block_id + blocks - 1 AS extent_end_block,
              :blockNo - block_id AS block_offset
         FROM dba_extents
        WHERE relative_fno = :fileNo
          AND :blockNo BETWEEN block_id AND block_id + blocks - 1`,
      { fileNo, blockNo },
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    return res.json({ success: true, data: r.rows });
  } catch (err) {
    return res.json({
      success: false,
      message: `You do not have permission to view this. DBA privileges are required. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Right-clicking a row in the Current Session List opens a context menu
// with "Kill Session (IMMEDIATE)", which calls this endpoint. Runs
// ALTER SYSTEM KILL SESSION '<sid>,<serial#>' IMMEDIATE, requiring the
// connected account to have the ALTER SYSTEM privilege. IMMEDIATE means
// Oracle rolls back the session's transaction and reclaims its resources
// right away rather than waiting for it to reach a safe point on its own --
// this forcibly terminates whatever that session was doing.
//
// ALTER SYSTEM statements don't support bind variables for their target
// (Oracle has no placeholder syntax for this particular DDL-like command),
// so sid/serial are validated as plain positive integers first and then
// interpolated directly -- since only digits can survive that validation,
// there's no injection surface despite the string concatenation.
app.post('/api/kill-session', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const body = req.body || {};
  const sid = Number(body.sid);
  const serial = Number(body.serial);
  if (!Number.isInteger(sid) || sid <= 0 || !Number.isInteger(serial) || serial < 0) {
    return res.status(400).json({ success: false, message: 'A valid sid/serial is required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });

    await connection.execute(`ALTER SYSTEM KILL SESSION '${sid},${serial}' IMMEDIATE`);

    return res.json({
      success: true,
      message: `Kill session (IMMEDIATE) requested for SID ${sid}, SERIAL# ${serial}.`
    });
  } catch (err) {
    return res.json({
      success: false,
      message: `Failed to kill session. The ALTER SYSTEM privilege is required. (${err.message})`
    });
  } finally {
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// For the 운영(Ops) tab: operational/performance-tuning views that don't
// belong on the always-visible Main tab, loosely modeled on a handful of
// AWR report sections that don't need an actual AWR/Statspack snapshot
// (and therefore no Diagnostics Pack license) to produce something useful
// from current v$ views alone:
//   - topQueries / topQueriesCpu / topQueriesBufferGets: "SQL ordered by
//     Elapsed Time / CPU Time / Gets" -- three independent Top-5 rankings
//     over v$sql, since a query can rank high on one metric and not
//     another. Each SQL_ID shown is a link; the full text is fetched on
//     demand via the existing /api/session-sql endpoint (same one used by
//     "View Running Query" and Recovery's Recent DML), not duplicated here.
//   - instanceEfficiency: "Instance Efficiency Percentages" -- Buffer
//     Cache Hit Ratio, Library Cache Hit Ratio, Soft Parse %, Execute to
//     Parse %, using the same formulas AWR uses, from v$sysstat/
//     v$librarycache.
//   - loadProfile: "Load Profile," adapted -- AWR normally averages over
//     one snapshot interval; without snapshot history, this averages the
//     same v$sysstat counters over the whole instance uptime instead (see
//     the comment at that query for why).
//   - tablespaceIo: "Tablespace IO Stats" at the datafile level, from
//     v$filestat, top 10 by total I/O.
// Structured as a `result` object with one section per item (like
// /api/recovery-usage) so more Ops items can be added later without
// changing this endpoint's response shape. Not part of the
// 15-second auto-refresh cycle -- loaded once when the Ops tab is first
// opened, and again via its own "Refresh" button.
app.get('/api/ops-usage', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
  } catch (err) {
    return res.json({ success: false, message: `Failed to connect to the DB: ${err.message}` });
  }

  const result = {
    success: true,
    topQueries: null,
    topQueriesCpu: null,
    topQueriesBufferGets: null,
    topWaitEvents: null,
    instanceEfficiency: null,
    loadProfile: null,
    tablespaceIo: null,
    keyParameters: null,
    tempTablespaceUsage: null,
    tempSessionUsage: null,
    datafileAutoextend: null,
    redoLogStatus: null,
    undoConfig: null,
    undoStatus: null
  };

  // Top 5 by elapsed_time (cumulative across all executions of that cursor
  // since it entered the shared pool, not a single-execution time) -- the
  // standard "top SQL by elapsed time" view most DBA tools lead with. Note:
  // v$sql can hold more than one child cursor (child_number) per SQL_ID
  // (different bind values/plans); this intentionally does not aggregate
  // across child cursors, so in rare cases the same SQL_ID could in theory
  // appear more than once in the Top 5 -- consistent with how this file's
  // other v$sql-based views (Recent DML, View Running Query) already treat
  // v$sql as flat rows rather than grouping by SQL_ID.
  try {
    const r = await connection.execute(
      `SELECT sql_id,
              parsing_schema_name,
              executions,
              ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
              ROUND(cpu_time / 1000000, 3) AS cpu_sec,
              TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time
         FROM (
                SELECT sql_id, parsing_schema_name, executions, elapsed_time, cpu_time, last_active_time
                  FROM v$sql
                 WHERE elapsed_time > 0
                 ORDER BY elapsed_time DESC
              )
        WHERE ROWNUM <= 5`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.topQueries = { ok: true, data: r.rows };
  } catch (err) {
    result.topQueries = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Top 5 by cpu_time -- AWR's "SQL ordered by CPU Time". Same
  // cumulative-since-shared-pool-entry caveat and same
  // not-grouped-by-sql_id caveat as topQueries above, just ranked by a
  // different column: a query can rank high here without ranking high on
  // elapsed_time (e.g. it's CPU-bound rather than wait-bound), so this
  // catches queries the elapsed-time ranking above would miss.
  try {
    const r = await connection.execute(
      `SELECT sql_id,
              parsing_schema_name,
              executions,
              ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
              ROUND(cpu_time / 1000000, 3) AS cpu_sec,
              TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time
         FROM (
                SELECT sql_id, parsing_schema_name, executions, elapsed_time, cpu_time, last_active_time
                  FROM v$sql
                 WHERE cpu_time > 0
                 ORDER BY cpu_time DESC
              )
        WHERE ROWNUM <= 5`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.topQueriesCpu = { ok: true, data: r.rows };
  } catch (err) {
    result.topQueriesCpu = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Top 5 by buffer_gets -- AWR's "SQL ordered by Gets" (logical reads).
  // Catches queries that are logically inefficient (scanning far more
  // blocks than necessary via a missing index, say) even if they aren't
  // currently the slowest in wall-clock or CPU terms.
  try {
    const r = await connection.execute(
      `SELECT sql_id,
              parsing_schema_name,
              executions,
              buffer_gets,
              ROUND(elapsed_time / 1000000, 3) AS elapsed_sec,
              TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time
         FROM (
                SELECT sql_id, parsing_schema_name, executions, buffer_gets, elapsed_time, last_active_time
                  FROM v$sql
                 WHERE buffer_gets > 0
                 ORDER BY buffer_gets DESC
              )
        WHERE ROWNUM <= 5`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.topQueriesBufferGets = { ok: true, data: r.rows };
  } catch (err) {
    result.topQueriesBufferGets = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Top 5 Wait Events (excludes Idle waits, cumulative since instance startup).
  try {
    const r = await connection.execute(
      `SELECT event, wait_class, total_waits, time_waited, average_wait FROM (
         SELECT event, wait_class, total_waits, time_waited, average_wait
           FROM v$system_event
          WHERE wait_class != 'Idle'
          ORDER BY time_waited DESC
       ) WHERE ROWNUM <= 5`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.topWaitEvents = { ok: true, data: r.rows };
  } catch (err) {
    result.topWaitEvents = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Instance Efficiency Percentages -- the same summary ratios AWR reports
  // near the top of every report. Standard formulas, all from v$sysstat /
  // v$librarycache (cumulative since instance startup, like everything
  // else derived from v$sysstat in this app -- there's no snapshot-to-
  // snapshot delta without an actual AWR/Statspack snapshot, which needs
  // the Diagnostics Pack license this app deliberately doesn't assume).
  // NULLIF guards against a divide-by-zero on a freshly-started instance
  // with no activity yet.
  try {
    const r = await connection.execute(
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
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.instanceEfficiency = { ok: true, data: r.rows[0] || {} };
  } catch (err) {
    result.instanceEfficiency = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Load Profile -- AWR's "Load Profile" section, adapted for a tool with
  // no snapshot interval: instead of "per second, averaged over the AWR
  // snapshot window," this is "per second, averaged over the entire
  // instance uptime" (same UPTIME_SECONDS approach as the Main tab's
  // Instance Information card). It's a coarser number that smooths out
  // any recent spike or lull, but needs no snapshot history to compute --
  // clearly labeled as such in the UI/README so it isn't mistaken for a
  // real AWR Load Profile.
  try {
    const r = await connection.execute(
      `SELECT ROUND(redo_size / NULLIF(uptime_seconds, 0), 2) AS redo_size_per_sec,
              ROUND(logical_reads / NULLIF(uptime_seconds, 0), 2) AS logical_reads_per_sec,
              ROUND(physical_reads / NULLIF(uptime_seconds, 0), 2) AS physical_reads_per_sec,
              ROUND(user_calls / NULLIF(uptime_seconds, 0), 2) AS user_calls_per_sec,
              ROUND(executes / NULLIF(uptime_seconds, 0), 2) AS executes_per_sec,
              ROUND((user_commits + user_rollbacks) / NULLIF(uptime_seconds, 0), 2) AS transactions_per_sec,
              uptime_seconds
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
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.loadProfile = { ok: true, data: r.rows[0] || {} };
  } catch (err) {
    result.loadProfile = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Tablespace I/O Stats -- AWR's "Tablespace IO Stats" section, at the
  // datafile level (joined up to its tablespace name), top 10 by physical
  // reads -- read-heavy datafiles are usually the ones worth investigating
  // first. READTIM/WRITETIM on v$filestat are in milliseconds on the Oracle
  // versions this app supports (12.1+; see the Oracle-version note at the
  // top of this file), so the average times below are already in
  // milliseconds, no unit conversion needed.
  try {
    const r = await connection.execute(
      `SELECT tablespace_name, file_name, physical_reads, physical_writes, avg_read_ms, avg_write_ms
         FROM (
                SELECT ts.name AS tablespace_name,
                       df.name AS file_name,
                       fs.phyrds AS physical_reads,
                       fs.phywrts AS physical_writes,
                       ROUND(fs.readtim / NULLIF(fs.phyrds, 0), 2) AS avg_read_ms,
                       ROUND(fs.writetim / NULLIF(fs.phywrts, 0), 2) AS avg_write_ms
                  FROM v$filestat fs
                  JOIN v$datafile df ON fs.file# = df.file#
                  JOIN v$tablespace ts ON df.ts# = ts.ts#
                 ORDER BY fs.phyrds DESC
              )
        WHERE ROWNUM <= 10`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.tablespaceIo = { ok: true, data: r.rows };
  } catch (err) {
    result.tablespaceIo = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Key Instance Parameters -- a handful of initialization parameters DBAs
  // commonly want at a glance: password expiration policy, whether the
  // instance is using an SPFILE (vs. a plain PFILE, which won't persist an
  // ALTER SYSTEM change across a restart), auditing, the process/session/
  // cursor/datafile limits, undo retention, the optimizer mode, the redo
  // log buffer size, and archiving mode. All scalar values, so pulled
  // together as one row of subqueries (same style as the Main tab's Memory
  // card and this file's own Load Profile query above) rather than one
  // round trip per parameter. PASSWORD_LIFE_TIME is a DBA_PROFILES setting
  // (not a v$parameter) -- read from the DEFAULT profile, since that's what
  // an account gets unless explicitly assigned a different profile.
  try {
    const r = await connection.execute(
      `SELECT
         (SELECT limit FROM dba_profiles WHERE profile = 'DEFAULT' AND resource_name = 'PASSWORD_LIFE_TIME') AS password_life_time,
         (SELECT value FROM v$parameter WHERE name = 'spfile') AS spfile,
         (SELECT value FROM v$parameter WHERE name = 'audit_trail') AS audit_trail,
         (SELECT value FROM v$parameter WHERE name = 'processes') AS processes,
         (SELECT value FROM v$parameter WHERE name = 'sessions') AS sessions,
         (SELECT value FROM v$parameter WHERE name = 'open_cursors') AS open_cursors,
         (SELECT value FROM v$parameter WHERE name = 'db_files') AS db_files,
         (SELECT value FROM v$parameter WHERE name = 'undo_retention') AS undo_retention,
         (SELECT value FROM v$parameter WHERE name = 'optimizer_mode') AS optimizer_mode,
         (SELECT value FROM v$parameter WHERE name = 'log_buffer') AS log_buffer,
         (SELECT log_mode FROM v$database) AS archive_mode
       FROM dual`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.keyParameters = { ok: true, data: r.rows[0] || {} };
  } catch (err) {
    result.keyParameters = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // TEMP Tablespace Usage / TEMP Usage by Session -- moved here from the
  // now-removed Temp tab (formerly its own /api/temp-usage endpoint), so
  // it refreshes along with the rest of the Ops tab instead of needing its
  // own separate lazy-load/refresh cycle.
  try {
    const r = await connection.execute(
      `SELECT tablespace_name,
              ROUND(SUM(bytes_used) / 1024 / 1024 / 1024, 2) AS used_gb,
              ROUND(SUM(bytes_free) / 1024 / 1024 / 1024, 2) AS free_gb,
              ROUND(SUM(bytes_used + bytes_free) / 1024 / 1024 / 1024, 2) AS total_gb,
              ROUND(SUM(bytes_used) / SUM(bytes_used + bytes_free) * 100, 2) AS used_pct
         FROM v$temp_space_header
        GROUP BY tablespace_name`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.tempTablespaceUsage = { ok: true, data: r.rows };
  } catch (err) {
    result.tempTablespaceUsage = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  try {
    const r = await connection.execute(
      `SELECT s.sid,
              s.serial# AS serial_num,
              s.username,
              s.machine,
              s.program,
              s.sql_id,
              ROUND(SUM(u.blocks * t.block_size) / 1024 / 1024, 2) AS temp_mb
         FROM v$tempseg_usage u
         JOIN v$session s ON u.session_addr = s.saddr
         JOIN dba_tablespaces t ON u.tablespace = t.tablespace_name
        GROUP BY s.sid, s.serial#, s.username, s.machine, s.program, s.sql_id
        ORDER BY temp_mb DESC`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.tempSessionUsage = { ok: true, data: r.rows };
  } catch (err) {
    result.tempSessionUsage = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Datafile Autoextend Status -- for each datafile, whether AUTOEXTEND is
  // enabled and (if so) how close it is to hitting MAXSIZE. A datafile
  // with autoextend off simply fails with "ORA-01653: unable to extend"
  // once its tablespace fills up, so this is an early-warning list, with
  // the files closest to their max size (or without autoextend at all)
  // surfaced first, capped at 20 rows.
  try {
    const r = await connection.execute(
      `SELECT * FROM (
         SELECT tablespace_name,
                file_name,
                autoextensible,
                ROUND(bytes / 1024 / 1024, 2) AS current_mb,
                CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                     THEN ROUND(maxbytes / 1024 / 1024 / 1024, 2) END AS max_gb,
                CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                     THEN ROUND(bytes / maxbytes * 100, 2) END AS used_pct_of_max
           FROM dba_data_files
          ORDER BY CASE WHEN autoextensible = 'YES' AND maxbytes > 0
                         THEN bytes / maxbytes ELSE -1 END DESC
       ) WHERE ROWNUM <= 20`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.datafileAutoextend = { ok: true, data: r.rows };
  } catch (err) {
    result.datafileAutoextend = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Redo Log Status -- one row per redo log group, straight from V$LOG
  // (MEMBERS, ARCHIVED and STATUS are already columns on this view, so no
  // join against V$LOGFILE is needed for a group-level summary). ARCHIVED
  // only means something in ARCHIVELOG mode (see the Archive Mode value in
  // Key Instance Parameters above) -- in NOARCHIVELOG mode every group
  // shows 'YES' since there's nothing pending archival.
  try {
    const r = await connection.execute(
      `SELECT group#,
              status,
              members,
              ROUND(bytes / 1024 / 1024) AS size_mb,
              archived,
              TO_CHAR(first_time, 'YYYY-MM-DD HH24:MI:SS') AS first_time
         FROM v$log
        ORDER BY group#`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.redoLogStatus = { ok: true, data: r.rows };
  } catch (err) {
    result.redoLogStatus = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Undo Configuration -- the instance-level settings that decide how undo
  // works: automatic vs. manual undo management, which tablespace it's
  // stored in, how long expired undo is kept before it can be overwritten,
  // and whether that retention is actually enforced (RETENTION GUARANTEE,
  // from DBA_TABLESPACES for the current undo tablespace) or just a
  // best-effort target Oracle can ignore under space pressure.
  try {
    const r = await connection.execute(
      `SELECT
         (SELECT value FROM v$parameter WHERE name = 'undo_management') AS undo_management,
         (SELECT value FROM v$parameter WHERE name = 'undo_tablespace') AS undo_tablespace,
         (SELECT value FROM v$parameter WHERE name = 'undo_retention') AS undo_retention,
         (SELECT retention FROM dba_tablespaces
           WHERE tablespace_name = (SELECT value FROM v$parameter WHERE name = 'undo_tablespace')) AS retention_guarantee
       FROM dual`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.undoConfig = { ok: true, data: r.rows[0] || {} };
  } catch (err) {
    result.undoConfig = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // Undo Status -- how full the undo tablespace actually is (from
  // DBA_DATA_FILES / DBA_FREE_SPACE, same used/total% approach as the Temp
  // tab's tablespace usage card, just for a permanent tablespace instead of
  // a TEMP one), plus TUNED_UNDORETENTION from V$UNDOSTAT: what Oracle is
  // actually achieving right now, worth comparing against the configured
  // UNDO_RETENTION above -- if the tuned value is well below the
  // configured one, this undo tablespace is undersized for its retention
  // target. V$UNDOSTAT keeps one row per 10-minute interval; only the most
  // recent is used here (a full trend isn't worth a dedicated endpoint).
  try {
    const r = await connection.execute(
      `WITH ut AS (
         SELECT value AS tablespace_name FROM v$parameter WHERE name = 'undo_tablespace'
       )
       SELECT
         ut.tablespace_name AS undo_tablespace,
         ROUND(df.total_bytes / 1024 / 1024) AS total_mb,
         ROUND((df.total_bytes - NVL(fsp.free_bytes, 0)) / 1024 / 1024) AS used_mb,
         ROUND((1 - NVL(fsp.free_bytes, 0) / NULLIF(df.total_bytes, 0)) * 100, 2) AS used_pct,
         (SELECT tuned_undoretention FROM (
            SELECT tuned_undoretention FROM v$undostat ORDER BY end_time DESC
          ) WHERE ROWNUM = 1) AS tuned_undo_retention_sec
       FROM ut
       LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS total_bytes FROM dba_data_files GROUP BY tablespace_name) df
         ON df.tablespace_name = ut.tablespace_name
       LEFT JOIN (SELECT tablespace_name, SUM(bytes) AS free_bytes FROM dba_free_space GROUP BY tablespace_name) fsp
         ON fsp.tablespace_name = ut.tablespace_name`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.undoStatus = { ok: true, data: r.rows[0] || {} };
  } catch (err) {
    result.undoStatus = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  try {
    await connection.close();
  } catch (closeErr) {
    console.error('Error while closing connection:', closeErr.message);
  }

  return res.json(result);
});

// For the Recovery tab: Fast Recovery Area (FRA) space usage overview, and
// a breakdown of that usage by file type (archived logs, backup pieces,
// image copies, etc.). Not part of the 15-second auto-refresh cycle --
// loaded once when the Recovery tab is first opened, and again via its own
// "Refresh" button.
app.get('/api/recovery-usage', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
  } catch (err) {
    return res.json({ success: false, message: `Failed to connect to the DB: ${err.message}` });
  }

  const result = { success: true, destUsage: null, typeUsage: null, recentDml: null };

  // 1) Overall FRA configuration and usage (one row per configured
  //    recovery file destination -- normally just one).
  try {
    const r = await connection.execute(
      `SELECT name,
              ROUND(space_limit / 1024 / 1024 / 1024, 2) AS space_limit_gb,
              ROUND(space_used / 1024 / 1024 / 1024, 2) AS space_used_gb,
              ROUND(space_reclaimable / 1024 / 1024 / 1024, 2) AS space_reclaimable_gb,
              ROUND((space_used - space_reclaimable) / NULLIF(space_limit, 0) * 100, 2) AS used_pct_net,
              number_of_files
         FROM v$recovery_file_dest`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.destUsage = { ok: true, data: r.rows };
  } catch (err) {
    result.destUsage = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 2) FRA usage broken down by file type (CONTROLFILE, REDOLOG,
  //    ARCHIVEDLOG, BACKUPPIECE, IMAGECOPY, FLASHBACKLOG, etc.).
  try {
    const r = await connection.execute(
      `SELECT file_type,
              ROUND(percent_space_used, 2) AS percent_space_used,
              ROUND(percent_space_reclaimable, 2) AS percent_space_reclaimable,
              number_of_files
         FROM v$flash_recovery_area_usage
        ORDER BY percent_space_used DESC`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.typeUsage = { ok: true, data: r.rows };
  } catch (err) {
    result.typeUsage = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  // 3) Recent DML (INSERT/UPDATE/DELETE/MERGE), top 50, most recently
  //    active first. Sourced from v$sql (the shared pool's SQL cursor
  //    cache) via COMMAND_TYPE, same approach as the "View Running Query"
  //    session context menu feature. command_type: 2=INSERT, 6=UPDATE,
  //    7=DELETE, 189=MERGE.
  try {
    const r = await connection.execute(
      `SELECT sql_id,
              CASE command_type
                WHEN 2 THEN 'INSERT'
                WHEN 6 THEN 'UPDATE'
                WHEN 7 THEN 'DELETE'
                WHEN 189 THEN 'MERGE'
                ELSE TO_CHAR(command_type)
              END AS command_name,
              parsing_schema_name,
              executions,
              TO_CHAR(last_active_time, 'YYYY-MM-DD HH24:MI:SS') AS last_active_time,
              DBMS_LOB.SUBSTR(sql_fulltext, 500, 1) AS sql_text
         FROM v$sql
        WHERE command_type IN (2, 6, 7, 189)
        ORDER BY last_active_time DESC
        FETCH FIRST 50 ROWS ONLY`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );
    result.recentDml = { ok: true, data: r.rows };
  } catch (err) {
    result.recentDml = { ok: false, message: `You do not have permission to view this. (${err.message})` };
  }

  try {
    await connection.close();
  } catch (closeErr) {
    console.error('Error while closing connection:', closeErr.message);
  }

  return res.json(result);
});

// --- Ad-hoc SQL Query Runner (SQL tab) ---
// Lets the user type an arbitrary query and see its results directly, for
// the cases none of the built-in cards happen to cover. Regardless of which
// account this connection is using, this endpoint is deliberately locked
// down to read-only, single-statement SELECTs -- a mistyped/pasted query in
// a quick ad-hoc box is exactly the kind of place a destructive statement
// slips through by accident:
//   - Only a statement starting with SELECT (case-insensitive) is
//     accepted -- no INSERT/UPDATE/DELETE/DDL/PL-SQL block, so a mistyped
//     or malicious query can't affect the instance, only read from it.
//   - A single trailing semicolon is stripped (common copy-paste habit);
//     any semicolon still embedded after that is rejected, as a guard
//     against multi-statement input.
//   - The statement is wrapped as a subquery capped at 200 rows via
//     ROWNUM (`SELECT * FROM (<user sql>) WHERE ROWNUM <= 200`), the same
//     pattern already used for Table Stats elsewhere in
//     this file, rather than node-oracledb's `maxRows` execute option --
//     this keeps the cap enforced by the query itself.
// Known limitation: there's no bind-variable UI here -- the query is a
// single opaque string, so if it needs a bind variable, the literal value
// has to be inlined by the user.
//
// Registry of in-flight SQL Query Runner connections, keyed by a per-query
// id the client generates (crypto.randomUUID()) before firing the request.
// A normal request/response can't interrupt a query that's already blocked
// inside execute(), so the Cancel button instead reaches this exact
// connection object from a separate, concurrent /api/cancel-query request
// and calls connection.break() (an out-of-band break, same mechanism a
// desktop DB client's own Cancel button uses) on it. cancelledQueries
// tracks which ids were deliberately cancelled so this handler can tell
// that apart from a genuine query error once break() makes execute()
// reject. Entries are removed as soon as the query finishes, however it
// finishes, so a stale id never lingers or gets confused with a later one.
const runningQueries = new Map();
const cancelledQueries = new Set();

app.post('/api/run-query', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  let sql = String((req.body || {}).sql || '').trim();
  const queryId = (req.body || {}).queryId || null;
  if (!sql) {
    return res.status(400).json({ success: false, message: 'Please enter a query to run.' });
  }

  if (sql.endsWith(';')) {
    sql = sql.slice(0, -1).trim();
  }
  if (sql.includes(';')) {
    return res.status(400).json({
      success: false,
      message: 'Only a single SQL statement is allowed (remove the embedded semicolon).'
    });
  }
  if (!/^select\b/i.test(sql)) {
    return res.status(400).json({ success: false, message: 'Only SELECT statements are allowed here.' });
  }

  const connectString = buildConnectString(creds.ip, creds.port, creds.sid);

  let connection;
  try {
    connection = await oracledb.getConnection({
      user: creds.account,
      password: creds.password,
      connectString: connectString
    });
    if (queryId) {
      runningQueries.set(queryId, connection);
    }

    const r = await connection.execute(
      `SELECT * FROM (${sql}) WHERE ROWNUM <= 200`,
      [],
      { outFormat: oracledb.OUT_FORMAT_OBJECT }
    );

    // node-oracledb's execute() result exposes column metadata as
    // `metaData` (capital D) -- NOT `metadata` -- which is an easy typo to
    // make and one that fails at runtime rather than at lint/syntax-check
    // time (a plain JS property-name typo, not a case-sensitivity issue
    // with the user's own SQL). This was the actual root cause of "Query
    // failed: Cannot read properties of undefined (reading 'map')" showing
    // up for every query, regardless of how the SELECT keyword was cased.
    const columns = r.metaData.map(m => m.name);
    const rows = r.rows.map(row => {
      const formatted = {};
      columns.forEach(col => {
        formatted[col] = formatDbValue(row[col]);
      });
      return formatted;
    });

    return res.json({ success: true, columns, rows });
  } catch (err) {
    if (queryId && cancelledQueries.has(queryId)) {
      return res.json({ success: false, cancelled: true, message: 'Query cancelled.' });
    }
    return res.json({ success: false, message: `Query failed: ${err.message}` });
  } finally {
    if (queryId) {
      runningQueries.delete(queryId);
      cancelledQueries.delete(queryId);
    }
    if (connection) {
      try {
        await connection.close();
      } catch (closeErr) {
        console.error('Error while closing connection:', closeErr.message);
      }
    }
  }
});

// Cancel button next to Run: breaks a still-running /api/run-query call by
// id. Not an error if the id is no longer running (it may have just
// finished on its own) -- that's a normal race, not a failure.
app.post('/api/cancel-query', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  const queryId = String((req.body || {}).queryId || '');
  const connection = runningQueries.get(queryId);
  if (!connection) {
    return res.json({ success: false, message: 'That query is no longer running.' });
  }

  cancelledQueries.add(queryId);
  try {
    await connection.break();
    return res.json({ success: true, message: 'Cancel requested.' });
  } catch (err) {
    return res.json({ success: false, message: `Failed to cancel: ${err.message}` });
  }
});

// --- Weekly DB Health Report (Report button, next to Refresh) ---
// Renders a self-contained HTML report covering the trailing `days` days
// (default/typical 7), built from report.js: a fresh on-demand snapshot for
// "right now," the locally-collected snapshot history for the trend
// sections, and a live Alert Log query. See report.js's top-of-file comment
// for why this needs its own local snapshot history instead of just
// querying Oracle for "the last week" directly (no AWR/Diagnostics Pack
// license assumed).
//
// Unlike every other endpoint here, this one doesn't hand its result back
// to the browser to download -- it saves the generated HTML straight to
// disk next to main.js (__dirname), under report/<YYYY-MM-DD>/. That
// folder is created if missing (and reused if it already exists) so a
// day's worth of reports land together regardless of how many are
// generated. This replaced a client-side "download the response as a
// Blob" flow that depended on the browser's own download/Save-As handling
// actually completing -- saving server-side works the same way regardless
// of browser download settings.
const REPORT_FILENAME_SANITIZE_RE = /[\\/:*?"<>|]/g;

function todayDateFolder() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

app.post('/api/generate-report', async (req, res) => {
  const creds = req.session.dbCreds;
  if (!creds) {
    return res.status(401).json({ success: false, message: 'Login required.' });
  }

  let days = parseInt((req.body || {}).days, 10);
  if (!Number.isInteger(days) || days <= 0) days = 7;
  if (days > 30) days = 30;

  const lang = (req.body || {}).lang === 'ko' ? 'ko' : 'en';

  // Only the base name is ever used -- a client-supplied path (or "..")
  // must never be able to steer where this gets written on disk.
  let filename = path.basename(((req.body || {}).filename || '').toString().trim());
  filename = filename.replace(REPORT_FILENAME_SANITIZE_RE, '_');
  if (!filename || filename === '.' || filename === '..') {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    filename = `orapulse-report-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}.html`;
  }
  if (!/\.html?$/i.test(filename)) filename += '.html';

  let html;
  try {
    html = await report.generateReport(creds, days, lang);
  } catch (err) {
    console.error('[report] failed to generate report:', err);
    return res.status(500).json({ success: false, message: `Failed to generate report: ${err.message}` });
  }

  const dateFolder = todayDateFolder();
  const reportDir = path.join(__dirname, 'report', dateFolder);
  try {
    fs.mkdirSync(reportDir, { recursive: true });
    fs.writeFileSync(path.join(reportDir, filename), html, 'utf8');
  } catch (err) {
    console.error('[report] failed to save report file:', err);
    return res.status(500).json({ success: false, message: `Failed to save report file: ${err.message}` });
  }

  const relPath = `report/${dateFolder}/${filename}`;
  return res.json({ success: true, message: `Report saved to ${relPath}`, path: relPath });
});

http.createServer(app).listen(PORT, HOST, () => {
  console.log(`OraPulse is running at http://${HOST}:${PORT} -- open that address in your browser.`);
  // Background collector for the Weekly DB Health Report feature -- a
  // no-op tick whenever nothing has connected yet (see report.js).
  report.startCollector(() => lastConnectedCreds);
});
