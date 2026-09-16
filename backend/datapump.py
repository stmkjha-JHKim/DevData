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
run_export_job() directly from an `async def` route.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import oracledb

from oracle_dsn import dsn_from_creds

ORACLE_CLIENT_PROGRAM = "OraPulseBackup-DataPump"

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
class ExportResult:
    success: bool
    job_state: str
    job_name: str
    dump_file: str
    log_file: str
    dump_size_bytes: Optional[int] = None
    log_text: str = ""
    error_text: str = ""


class DataPumpError(Exception):
    pass


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


def run_export_job(creds: dict, spec: ExportSpec, run_ts: str) -> ExportResult:
    """Synchronous, blocking for the whole duration of the Data Pump job.
    Call via asyncio.to_thread() from a route, or directly from an
    APScheduler job (already off the event loop)."""
    job_name = _job_name(spec.policy_name)
    dump_file = _substitute_filename(spec.dump_file_pattern, spec.policy_name, run_ts)
    log_file = dump_file[:-4] + ".log" if dump_file.lower().endswith(".dmp") else dump_file + ".log"

    mode_info = _job_mode_and_filter(spec.scope, spec.scope_value)
    job_mode = mode_info[0]
    filter_clause = mode_info[1]
    table_schema = mode_info[2] if len(mode_info) > 2 else None

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
                  DBMS_DATAPUMP.SET_PARAMETER(handle => h1, name => 'CONTENT', value => :content);
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
                content=spec.content or "ALL",
                table_schema=table_schema,
                filter_name=(filter_clause[0] if filter_clause else None),
                filter_value=(filter_clause[1] if filter_clause else None),
            )
        except oracledb.DatabaseError as err:
            raise DataPumpError(_ora_message(err)) from err

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
            raise DataPumpError(_ora_message(err)) from err

        log_text = _read_remote_file_text(cur, spec.directory, log_file)
        dump_size = _remote_file_size(cur, spec.directory, dump_file) if final_state == "COMPLETED" else None

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


def _ora_message(err: oracledb.DatabaseError) -> str:
    if err.args:
        return getattr(err.args[0], "message", str(err))
    return str(err)
