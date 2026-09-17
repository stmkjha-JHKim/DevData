"""backend/datapump.py -- runs an actual Oracle Data Pump EXPORT job using
only the DBMS_DATAPUMP PL/SQL API over an ordinary DB connection. This is
the one deliberate architectural choice worth calling out: it does NOT
shell out to expdp.exe and does NOT require an Oracle Instant Client on
the machine running this app -- exactly the same "agentless, thin-mode
python-oracledb only" philosophy OraPulse itself is built on (see that
project's README: "No Oracle Instant Client install needed -- thin mode
is used exclusively"). Everything -- starting the job, waiting for it to
finish, reading its log, checking the resulting dump file's size -- is
driven by PL/SQL blocks run over the connection; the dump/log files
themselves are written directly on the *database server's* filesystem
under the target Directory Object, which this app never needs to reach.

DBMS_DATAPUMP.WAIT_FOR_JOB blocks, at the database side, for the whole
duration of the job -- so every function in this module is plain
synchronous code, meant to be run off the asyncio event loop: from a
route handler via `asyncio.to_thread(...)`, or straight from an
APScheduler job (which already runs in its own worker thread). Never call
any of these directly from an `async def` route.

Starting a job and waiting for it to finish are split into two separate
functions (start_export_job/wait_export_job) instead of one, so a caller
that shouldn't block for the job's whole duration (the "메뉴얼 백업" tab's
"지금 백업" button) can run the fast start step, return a job name to the
browser right away, and let a background thread do the (possibly long)
wait separately -- see backend/jobs.py's run_manual_sync. Data Pump jobs
are server-side objects identified by job name, not tied to one client
connection, so attaching from a different connection later (or from a
different query_job_progress() call while it's still running) is exactly
how Oracle expects this to be used, not a workaround.
run_export_job() below just chains the two for callers that DO want to
block for the whole job (the scheduled-policy path, which already runs on
its own APScheduler thread and has no one polling it in real time)."""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import oracledb

from oracle_dsn import dsn_from_creds

ORACLE_CLIENT_PROGRAM = "OraVaultBackup-DataPump"

# DBMS_DATAPUMP job names are plain Oracle identifiers -- keep it short,
# uppercase, and unique per run so two policies (or two runs of the same
# policy) never collide on an in-progress job name.
_IDENT_STRIP_RE = re.compile(r"[^A-Z0-9_]")


def _job_name(policy_name: str) -> str:
    base = _IDENT_STRIP_RE.sub("_", policy_name.upper())[:14].strip("_") or "POLICY"
    return f"OPB_{base}_{int(time.time())}"[:30]


def _substitute_filename(pattern: str, policy_name: str, run_ts: str) -> str:
    name = (pattern or "%POLICY%_%DATE%.dmp").replace("%POLICY%", policy_name).replace("%DATE%", run_ts)
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)
    return name if name.lower().endswith(".dmp") else f"{name}.dmp"


@dataclass
class ExportSpec:
    policy_name: str
    directory: str
    dump_file_pattern: str
    scope: str  # FULL / SCHEMA / TABLE
    scope_value: Optional[str]
    compression: str
    parallel_degree: int
    content: str


@dataclass
class StartResult:
    job_name: str
    dump_file: str
    log_file: str
    script_text: str


@dataclass
class ExportResult:
    success: bool
    job_state: str
    job_name: str
    dump_file: str
    log_file: str
    dump_size_bytes: Optional[int] = None
    log_text: str = ""
    error_text: str = ""
    script_text: str = ""


class DataPumpError(Exception):
    def __init__(self, message: str, job_name: str = "", dump_file: str = "", log_file: str = ""):
        super().__init__(message)
        self.job_name = job_name
        self.dump_file = dump_file
        self.log_file = log_file


def _job_mode_and_filter(scope: str, scope_value: Optional[str]):
    """Maps this app's SCOPE/scope_value onto DBMS_DATAPUMP's job_mode and
    an optional METADATA_FILTER call.

    TABLE mode is a known simplification: scope_value must be
    "SCHEMA:TABLE1,TABLE2" (a single owning schema) -- DBMS_DATAPUMP's
    NAME_EXPR filters table names within the export's schema context, so
    exporting specific tables spanning *several* schemas in one policy
    isn't supported; split those into separate policies instead."""
    scope = (scope or "FULL").upper()
    if scope == "FULL":
        return "FULL", None, None
    if scope == "SCHEMA":
        schemas = [s.strip() for s in (scope_value or "").split(",") if s.strip()]
        if not schemas:
            raise DataPumpError("SCHEMA 범위에는 스키마를 1개 이상 지정해야 합니다.")
        quoted = ",".join(f"'{s.upper()}'" for s in schemas)
        return "SCHEMA", ("SCHEMA_EXPR", f"IN ({quoted})")
    if scope == "TABLE":
        if not scope_value or ":" not in scope_value:
            raise DataPumpError("TABLE 범위는 'SCHEMA:TABLE1,TABLE2' 형식으로 지정해야 합니다.")
        schema, tables_part = scope_value.split(":", 1)
        tables = [t.strip() for t in tables_part.split(",") if t.strip()]
        if not schema.strip() or not tables:
            raise DataPumpError("TABLE 범위는 'SCHEMA:TABLE1,TABLE2' 형식으로 지정해야 합니다.")
        quoted = ",".join(f"'{t.upper()}'" for t in tables)
        # SCHEMAS param scopes TABLE mode to the one owning schema; NAME_EXPR
        # then narrows it to the listed table names.
        return "TABLE", ("NAME_EXPR", f"IN ({quoted})"), schema.strip().upper()
    raise DataPumpError(f"알 수 없는 백업 범위입니다: {scope}")


# DBMS_DATAPUMP.SET_PARAMETER's actual accepted values for these two
# parameter names -- NOT the BASIC/LOW/MEDIUM/HIGH scale, which is the
# separate, Advanced-Compression-licensed COMPRESSION_ALGORITHM parameter
# this app never sets. Passing one of those as COMPRESSION is exactly what
# raises ORA-39207 (or ORA-39001 from the same internal validation, in
# some Oracle versions/contexts) -- validated here, before ever reaching
# Oracle, so a stale/bad value (an old saved policy from before this was
# fixed, a hand-edited row, ...) fails with a clear message immediately
# instead of a cryptic multi-line ORA-* stack.
_VALID_COMPRESSION = {"NONE", "DATA_ONLY", "METADATA_ONLY", "ALL"}
_VALID_CONTENT = {"ALL", "DATA_ONLY", "METADATA_ONLY"}


def _validate_enum_params(compression: str, content: str) -> None:
    compression = (compression or "NONE").upper()
    content = (content or "ALL").upper()
    if compression not in _VALID_COMPRESSION:
        raise DataPumpError(
            f"COMPRESSION 값이 잘못됐습니다: '{compression}' -- "
            f"{'/'.join(sorted(_VALID_COMPRESSION))} 중 하나여야 합니다 "
            "(BASIC/LOW/MEDIUM/HIGH는 COMPRESSION이 아니라 별도의, "
            "Advanced Compression 라이선스가 필요한 COMPRESSION_ALGORITHM 값입니다)."
        )
    if content not in _VALID_CONTENT:
        raise DataPumpError(
            f"CONTENT 값이 잘못됐습니다: '{content}' -- {'/'.join(sorted(_VALID_CONTENT))} 중 하나여야 합니다."
        )


def _sql_literal(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _render_script(
    job_name: str, job_mode: str, directory: str, dump_file: str, log_file: str,
    parallel: int, compression: str, content: str,
    table_schema: Optional[str], filter_name: Optional[str], filter_value: Optional[str],
) -> str:
    """Renders the PL/SQL block run_export_job() is about to run, with the
    actual values that will be bound spelled out as literals -- purely for
    display in the UI (the "실행 스크립트" panel), so the operator can see
    exactly what ran against their DB. The real execution below still uses
    bind variables; this is never re-parsed or re-executed."""
    lines = [
        "DECLARE",
        "  h1 NUMBER;",
        "BEGIN",
        f"  h1 := DBMS_DATAPUMP.OPEN(operation => 'EXPORT', job_mode => {_sql_literal(job_mode)}, job_name => {_sql_literal(job_name)});",
        f"  DBMS_DATAPUMP.ADD_FILE(handle => h1, filename => {_sql_literal(dump_file)}, directory => {_sql_literal(directory)},",
        "                         filetype => DBMS_DATAPUMP.KU$_FILE_TYPE_DUMP_FILE, reusefile => 1);",
        f"  DBMS_DATAPUMP.ADD_FILE(handle => h1, filename => {_sql_literal(log_file)}, directory => {_sql_literal(directory)},",
        "                         filetype => DBMS_DATAPUMP.KU$_FILE_TYPE_LOG_FILE, reusefile => 1);",
    ]
    if parallel and parallel > 1:
        lines.append(f"  DBMS_DATAPUMP.SET_PARALLEL(handle => h1, degree => {parallel});")
    lines.append(f"  DBMS_DATAPUMP.SET_PARAMETER(handle => h1, name => 'COMPRESSION', value => {_sql_literal(compression or 'NONE')});")
    # CONTENT isn't a SET_PARAMETER name at the DBMS_DATAPUMP level -- that's
    # only expdp's own CLI option, which expdp itself maps to this pair of
    # calls internally (INCLUDE_METADATA=0 for DATA_ONLY, an EXCLUDE_PATH_EXPR
    # metadata filter dropping TABLE_DATA for METADATA_ONLY). Passing the
    # literal string 'CONTENT' to SET_PARAMETER raises ORA-39049 (invalid
    # parameter name), which aborts the block before START_JOB ever runs --
    # the already-OPENed job is then abandoned, which Data Pump logs as
    # ORA-39012 ("client detached before the job started").
    content = (content or "ALL").upper()
    if content == "DATA_ONLY":
        lines.append("  DBMS_DATAPUMP.SET_PARAMETER(handle => h1, name => 'INCLUDE_METADATA', value => 0);")
    elif content == "METADATA_ONLY":
        lines.append("  DBMS_DATAPUMP.METADATA_FILTER(handle => h1, name => 'EXCLUDE_PATH_EXPR', value => 'IN (''TABLE_DATA'')');")
    if table_schema:
        # Mirrors the real call's runtime-concatenated value string
        # ("'IN (''' || :table_schema || ''')'" -> IN ('MES')) -- reproduced
        # here as a literal, then SQL-escaped for display like any other value.
        schema_filter_value = "IN ('" + table_schema + "')"
        lines.append(
            "  DBMS_DATAPUMP.METADATA_FILTER(handle => h1, name => 'SCHEMA_EXPR', value => "
            + _sql_literal(schema_filter_value) + ");"
        )
    if filter_name:
        lines.append(f"  DBMS_DATAPUMP.METADATA_FILTER(handle => h1, name => {_sql_literal(filter_name)}, value => {_sql_literal(filter_value)});")
    lines.append("  DBMS_DATAPUMP.START_JOB(handle => h1);")
    lines.append("  DBMS_DATAPUMP.DETACH(handle => h1);")
    lines.append("END;")
    lines.append("/")
    return "\n".join(lines)


def _read_remote_file_text(cursor, directory: str, filename: str, max_chars: int = 200_000) -> str:
    """Reads a text file (the Data Pump log) that only exists on the DB
    server's filesystem, entirely via UTL_FILE over the same connection --
    no filesystem access from this app's own machine required."""
    out_clob = cursor.var(oracledb.DB_TYPE_CLOB)
    cursor.execute(
        """
        DECLARE
          l_file UTL_FILE.FILE_TYPE;
          l_line VARCHAR2(32767);
          l_clob CLOB;
        BEGIN
          DBMS_LOB.CREATETEMPORARY(l_clob, TRUE);
          l_file := UTL_FILE.FOPEN(:directory, :filename, 'r', 32767);
          LOOP
            BEGIN
              UTL_FILE.GET_LINE(l_file, l_line);
            EXCEPTION WHEN NO_DATA_FOUND THEN
              EXIT;
            END;
            DBMS_LOB.WRITEAPPEND(l_clob, LENGTH(l_line) + 1, l_line || CHR(10));
          END LOOP;
          UTL_FILE.FCLOSE(l_file);
          :out_clob := l_clob;
        EXCEPTION WHEN OTHERS THEN
          IF UTL_FILE.IS_OPEN(l_file) THEN
            UTL_FILE.FCLOSE(l_file);
          END IF;
          :out_clob := '(log을 읽지 못했습니다: ' || SQLERRM || ')';
        END;
        """,
        directory=directory,
        filename=filename,
        out_clob=out_clob,
    )
    text = out_clob.getvalue()
    text = text.read() if hasattr(text, "read") else (text or "")
    return text[:max_chars]


def _remote_file_size(cursor, directory: str, filename: str) -> Optional[int]:
    out_len = cursor.var(int)
    cursor.execute(
        """
        DECLARE
          b BOOLEAN;
          flen NUMBER;
          bsz NUMBER;
        BEGIN
          UTL_FILE.FGETATTR(:directory, :filename, b, flen, bsz);
          IF b THEN
            :out_len := flen;
          ELSE
            :out_len := -1;
          END IF;
        EXCEPTION WHEN OTHERS THEN
          :out_len := -2;
        END;
        """,
        directory=directory,
        filename=filename,
        out_len=out_len,
    )
    value = out_len.getvalue()
    return value if value is not None and value >= 0 else None


def start_export_job(creds: dict, spec: ExportSpec, run_ts: str) -> StartResult:
    """OPEN/ADD_FILE/SET_PARAMETER/METADATA_FILTER/START_JOB/DETACH -- a
    quick, bounded round-trip (unlike WAIT_FOR_JOB, this returns as soon as
    the job is accepted and running, not when it finishes) that either
    raises DataPumpError with the real ORA-* text (bad scope/schema/table
    name, invalid COMPRESSION value, etc.) or hands back the job name to
    wait on later."""
    job_name = _job_name(spec.policy_name)
    dump_file = _substitute_filename(spec.dump_file_pattern, spec.policy_name, run_ts)
    log_file = dump_file[:-4] + ".log" if dump_file.lower().endswith(".dmp") else dump_file + ".log"

    try:
        _validate_enum_params(spec.compression, spec.content)
    except DataPumpError as err:
        raise DataPumpError(str(err), job_name=job_name, dump_file=dump_file, log_file=log_file) from err

    mode_info = _job_mode_and_filter(spec.scope, spec.scope_value)
    job_mode = mode_info[0]
    filter_clause = mode_info[1]
    table_schema = mode_info[2] if len(mode_info) > 2 else None

    script_text = _render_script(
        job_name=job_name, job_mode=job_mode, directory=spec.directory,
        dump_file=dump_file, log_file=log_file, parallel=spec.parallel_degree or 1,
        compression=spec.compression or "NONE", content=spec.content or "ALL",
        table_schema=table_schema,
        filter_name=(filter_clause[0] if filter_clause else None),
        filter_value=(filter_clause[1] if filter_clause else None),
    )

    content_upper = (spec.content or "ALL").upper()
    include_metadata = 0 if content_upper == "DATA_ONLY" else 1
    exclude_table_data = 1 if content_upper == "METADATA_ONLY" else 0

    conn = oracledb.connect(
        user=creds["account"], password=creds["password"], dsn=dsn_from_creds(creds),
        program=ORACLE_CLIENT_PROGRAM,
    )
    cur = conn.cursor()
    try:
        try:
            cur.execute(
                """
                DECLARE
                  h1 NUMBER;
                BEGIN
                  h1 := DBMS_DATAPUMP.OPEN(operation => 'EXPORT', job_mode => :job_mode, job_name => :job_name);
                  DBMS_DATAPUMP.ADD_FILE(handle => h1, filename => :dump_file, directory => :directory,
                                         filetype => DBMS_DATAPUMP.KU$_FILE_TYPE_DUMP_FILE, reusefile => 1);
                  DBMS_DATAPUMP.ADD_FILE(handle => h1, filename => :log_file, directory => :directory,
                                         filetype => DBMS_DATAPUMP.KU$_FILE_TYPE_LOG_FILE, reusefile => 1);
                  IF :parallel > 1 THEN
                    DBMS_DATAPUMP.SET_PARALLEL(handle => h1, degree => :parallel);
                  END IF;
                  DBMS_DATAPUMP.SET_PARAMETER(handle => h1, name => 'COMPRESSION', value => :compression);
                  IF :include_metadata = 0 THEN
                    DBMS_DATAPUMP.SET_PARAMETER(handle => h1, name => 'INCLUDE_METADATA', value => 0);
                  END IF;
                  IF :exclude_table_data = 1 THEN
                    DBMS_DATAPUMP.METADATA_FILTER(handle => h1, name => 'EXCLUDE_PATH_EXPR', value => 'IN (''TABLE_DATA'')');
                  END IF;
                  IF :table_schema IS NOT NULL THEN
                    DBMS_DATAPUMP.METADATA_FILTER(handle => h1, name => 'SCHEMA_EXPR',
                                                   value => 'IN (''' || :table_schema || ''')');
                  END IF;
                  IF :filter_name IS NOT NULL THEN
                    DBMS_DATAPUMP.METADATA_FILTER(handle => h1, name => :filter_name, value => :filter_value);
                  END IF;
                  DBMS_DATAPUMP.START_JOB(handle => h1);
                  DBMS_DATAPUMP.DETACH(handle => h1);
                END;
                """,
                job_mode=job_mode,
                job_name=job_name,
                directory=spec.directory,
                dump_file=dump_file,
                log_file=log_file,
                parallel=spec.parallel_degree or 1,
                compression=spec.compression or "NONE",
                include_metadata=include_metadata,
                exclude_table_data=exclude_table_data,
                table_schema=table_schema,
                filter_name=(filter_clause[0] if filter_clause else None),
                filter_value=(filter_clause[1] if filter_clause else None),
            )
        except oracledb.DatabaseError as err:
            raise DataPumpError(_ora_message(err), job_name=job_name, dump_file=dump_file, log_file=log_file) from err

        return StartResult(job_name=job_name, dump_file=dump_file, log_file=log_file, script_text=script_text)
    finally:
        cur.close()
        conn.close()


def wait_export_job(creds: dict, directory: str, job_name: str, dump_file: str, log_file: str) -> ExportResult:
    """ATTACH/WAIT_FOR_JOB on a job start_export_job() already started (a
    fresh connection is fine -- Data Pump jobs are server-side objects
    identified by job_name, not tied to one client connection). Blocks for
    the whole remaining duration of the job; always call this off the
    event loop (a background thread for a "지금 백업" run, or an
    APScheduler job for a scheduled one)."""
    conn = oracledb.connect(
        user=creds["account"], password=creds["password"], dsn=dsn_from_creds(creds),
        program=ORACLE_CLIENT_PROGRAM,
    )
    cur = conn.cursor()
    try:
        state_var = cur.var(str)
        try:
            cur.execute(
                """
                DECLARE
                  h1 NUMBER;
                  job_state VARCHAR2(30);
                BEGIN
                  h1 := DBMS_DATAPUMP.ATTACH(job_name => :job_name);
                  DBMS_DATAPUMP.WAIT_FOR_JOB(handle => h1, job_state => job_state);
                  :out_state := job_state;
                END;
                """,
                job_name=job_name,
                out_state=state_var,
            )
            final_state = state_var.getvalue() or "UNKNOWN"
        except oracledb.DatabaseError as err:
            raise DataPumpError(_ora_message(err), job_name=job_name, dump_file=dump_file, log_file=log_file) from err

        log_text = _read_remote_file_text(cur, directory, log_file)
        dump_size = _remote_file_size(cur, directory, dump_file) if final_state == "COMPLETED" else None

        return ExportResult(
            success=(final_state == "COMPLETED"),
            job_state=final_state,
            job_name=job_name,
            dump_file=dump_file,
            log_file=log_file,
            dump_size_bytes=dump_size,
            log_text=log_text,
            error_text="" if final_state == "COMPLETED" else f"Data Pump job ended in state {final_state}. 로그를 확인하세요.",
        )
    except DataPumpError as err:
        return ExportResult(
            success=False, job_state="FAILED_TO_START", job_name=job_name,
            dump_file=dump_file, log_file=log_file, error_text=str(err),
        )
    finally:
        cur.close()
        conn.close()


def run_export_job(creds: dict, spec: ExportSpec, run_ts: str) -> ExportResult:
    """start_export_job() + wait_export_job() chained -- for the
    scheduled-policy path (backend/jobs.py's run_policy_sync), which
    already runs on its own APScheduler thread and has no one polling it,
    so there's no reason to split the two steps there. The manual-backup
    path calls start_export_job()/wait_export_job() separately instead --
    see backend/jobs.py's run_manual_sync."""
    try:
        started = start_export_job(creds, spec, run_ts)
    except DataPumpError as err:
        return ExportResult(
            success=False, job_state="FAILED_TO_START", job_name=err.job_name,
            dump_file=err.dump_file, log_file=err.log_file, error_text=str(err),
        )
    result = wait_export_job(creds, spec.directory, started.job_name, started.dump_file, started.log_file)
    result.script_text = started.script_text
    return result


def query_job_progress(creds: dict, job_name: str) -> dict:
    """Best-effort live status straight from Oracle's own Data Pump
    catalog, for the "메뉴얼 백업" tab to poll while the JobRun row it
    already owns still says RUNNING (see backend/routes_manual.py's
    /runs/{run_id}/progress). USER_DATAPUMP_JOBS needs no privilege beyond
    what running Data Pump already requires -- it only lists jobs the
    connected account owns, and the row disappears once the job's master
    table is dropped (i.e. once it's actually finished either way).
    SOFAR/TOTALWORK percentage additionally needs V$SESSION_LONGOPS/
    DBA_DATAPUMP_SESSIONS visibility, which a minimally-privileged backup
    account (per README) may not have -- that part is best-effort and
    silently omitted (not an error) if it isn't granted."""
    conn = oracledb.connect(
        user=creds["account"], password=creds["password"], dsn=dsn_from_creds(creds),
        program=ORACLE_CLIENT_PROGRAM,
    )
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT state, degree FROM user_datapump_jobs WHERE job_name = :job_name",
            job_name=job_name,
        )
        row = cur.fetchone()
        if row is None:
            return {"found": False, "state": None, "percentDone": None}
        state, degree = row

        percent_done = None
        try:
            cur.execute(
                """
                SELECT ROUND(s.sofar / s.totalwork * 100, 1)
                FROM dba_datapump_sessions ds
                JOIN v$session vs ON vs.saddr = ds.saddr
                JOIN v$session_longops s ON s.sid = vs.sid AND s.serial# = vs.serial#
                WHERE ds.job_name = :job_name AND s.totalwork > 0
                ORDER BY s.last_update_time DESC
                FETCH FIRST 1 ROW ONLY
                """,
                job_name=job_name,
            )
            prow = cur.fetchone()
            if prow and prow[0] is not None:
                percent_done = float(prow[0])
        except oracledb.DatabaseError:
            pass  # no catalog-view privilege for the percentage -- state alone is still useful

        return {"found": True, "state": state, "degree": degree, "percentDone": percent_done}
    finally:
        cur.close()
        conn.close()


def _ora_message(err: oracledb.DatabaseError) -> str:
    if err.args:
        return getattr(err.args[0], "message", str(err))
    return str(err)
