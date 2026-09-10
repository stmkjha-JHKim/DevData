"""tests/test_connect_type.py -- regression tests for SID vs. Service Name
connect-type support (see oracle_dsn.py, backend/routes_connect.py,
favorites.py, backend/core.py's cache_key(), report.py's read_snapshots(),
and tuning.py's _same_target()).

IMPORTANT -- test nature disclosure: this environment has no reachable
Oracle Database. Every check below that exercises DB-connection code paths
does so against a mocked oracledb.connect_async (a FakeConnection/
FakeCursor pair patched into the real `oracledb` module for the duration
of this run -- see MockedOracle below), never a real instance. This is
MOCK-BASED verification only: it proves the app builds the correct TNS
connect string (SID= vs SERVICE_NAME=) and keeps SID/Service Name targets
from cross-contaminating cache keys, favorites, and snapshot/tuning
history -- not that a real Oracle listener accepts either connect string.
There is no REAL-DB test in this file, and none exists anywhere in this
project for the same reason (see tests/test_favorites_security.py's own
check #9, which hits a real python-oracledb call against an intentionally
unreachable target for the same disclosed reason).

Runs entirely in-process (imports the app's own modules directly and calls
their functions/coroutines) rather than spawning main.py as a subprocess --
unlike test_favorites_security.py, several of these checks need to inspect
the exact DSN string handed to oracledb.connect_async, which isn't
observable from outside a real server process without adding an HTTP
client/mocking dependency this project doesn't otherwise use.

Isolation: temporarily moves aside data/favorites.enc, data/.favorites-key,
data/snapshot-history.jsonl, data/.snapshot-key, data/tuning-last-snapshot.enc,
and data/.tuning-key for the run (same reasoning as
test_favorites_security.py's own isolation block) and restores them
afterwards in a finally block.

Run directly with:

    .\\venv\\Scripts\\python.exe tests\\test_connect_type.py

from the repo root. Exits non-zero with a list of failed checks, or prints
"ALL TESTS PASSED" on success.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
ISOLATED_FILES = [
    DATA_DIR / "favorites.enc",
    DATA_DIR / ".favorites-key",
    DATA_DIR / "snapshot-history.jsonl",
    DATA_DIR / ".snapshot-key",
    DATA_DIR / "tuning-last-snapshot.enc",
    DATA_DIR / ".tuning-key",
]

failures = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {description}")
    if not condition:
        failures.append(description)


# --- Mocked Oracle connection (no real DB reachable in this environment) ---
# Records every DSN handed to oracledb.connect_async() so tests can assert
# on the exact TNS connect string built for a given creds dict, and answers
# just enough SQL (by substring match, same pattern used elsewhere in this
# project's own mock-based experiments) for the connect flow and a couple
# of DB-status endpoints to complete successfully.
class FakeCursor:
    def __init__(self):
        self.description = None
        self.rowfactory = None
        self._rows = []

    async def execute(self, sql, params=None):
        u = sql.upper()
        if "V$INSTANCE" in u:
            self.description = [("INSTANCE_NAME",), ("STATUS",), ("HOST_NAME",), ("VERSION",), ("STARTUP_TIME",), ("UPTIME_SECONDS",)]
            self._rows = [("MOCKDB", "OPEN", "mockhost", "19.0.0.0.0", "2026-01-01 00:00:00", 12345)]
        elif "DUAL" in u:
            self.description = [("DUMMY",)]
            self._rows = [(1,)]
        else:
            self.description = []
            self._rows = []

    async def fetchall(self):
        if self.rowfactory:
            return [self.rowfactory(*r) for r in self._rows]
        return list(self._rows)


class FakeConnection:
    def __init__(self, dsn):
        self.dsn = dsn

    def cursor(self):
        return FakeCursor()

    async def close(self):
        pass


class MockedOracle:
    """Context manager: patches oracledb.connect_async for its duration,
    recording every dsn it was called with in self.dsns. Restores the real
    attribute afterwards regardless of outcome."""

    def __init__(self, fail_predicate=None):
        self.dsns = []
        self._fail_predicate = fail_predicate
        self._real = None

    def __enter__(self):
        import oracledb

        self._real = oracledb.connect_async

        async def fake_connect_async(user=None, password=None, dsn=None, program=None):
            self.dsns.append(dsn)
            if self._fail_predicate and self._fail_predicate(dsn):
                raise Exception("ORA-12154: TNS:could not resolve the connect identifier specified (mocked failure)")
            return FakeConnection(dsn)

        oracledb.connect_async = fake_connect_async
        return self

    def __exit__(self, *exc):
        import oracledb

        oracledb.connect_async = self._real
        return False


def backup_data_files():
    backups = {}
    for f in ISOLATED_FILES:
        backups[f] = f.read_bytes() if f.exists() else None
        if f.exists():
            f.unlink()
    return backups


def restore_data_files(backups):
    for f in ISOLATED_FILES:
        if f.exists():
            f.unlink()
    for f, content in backups.items():
        if content is not None:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content)


class FakeRequestCookies:
    def __init__(self, cookies):
        self._cookies = cookies

    def get(self, key, default=None):
        return self._cookies.get(key, default)


class FakeRequest:
    def __init__(self, cookies=None):
        self.cookies = FakeRequestCookies(cookies or {})


class FakeResponse:
    """Just enough of Starlette's Response for backend.core.Session.set() to
    call set_cookie() on without error -- the cookie itself is never
    inspected by these tests (no real browser involved)."""

    def set_cookie(self, *args, **kwargs):
        pass


def run(coro):
    return asyncio.run(coro)


class NoBackgroundCollection:
    """A successful /api/connect fires an async fire-and-forget background
    snapshot (report.trigger_immediate_collection) as a side effect -- see
    backend/routes_connect.py's _connect_and_store_session(). Left enabled,
    that background task can race the test's own event-loop shutdown (it
    may get scheduled a moment before asyncio.run() tears the loop down)
    and issue its own extra, nondeterministic oracledb.connect_async() call
    on top of the one this test means to observe. Patched out for the
    duration of these connect-flow checks so DSN capture stays
    deterministic; the background collector itself is exercised separately
    (report.gather_snapshot() is called directly in
    test_report_and_tuning_target_matching())."""

    def __enter__(self):
        import report

        self._real = report.trigger_immediate_collection
        report.trigger_immediate_collection = lambda creds: None
        return self

    def __exit__(self, *exc):
        import report

        report.trigger_immediate_collection = self._real
        return False


def test_oracle_dsn_unit():
    print("1) oracle_dsn.py unit checks")
    import oracle_dsn

    check(oracle_dsn.normalize_connect_type(None) == "sid", "missing connectType normalizes to 'sid'")
    check(oracle_dsn.normalize_connect_type("") == "sid", "empty connectType normalizes to 'sid'")
    check(oracle_dsn.normalize_connect_type("SID") == "sid", "'SID' normalizes to lowercase 'sid'")
    check(oracle_dsn.normalize_connect_type("Service_Name") == "service_name", "'Service_Name' normalizes to 'service_name'")
    check(oracle_dsn.normalize_connect_type("bogus") is None, "an unrecognized explicit value returns None (caller must reject)")

    check(oracle_dsn.validate_identifier("ORCL", "sid") is None, "a plain SID passes validation")
    check(oracle_dsn.validate_identifier("orcl.pdb1", "sid") is not None, "a dotted name is rejected for SID mode")
    check(oracle_dsn.validate_identifier("orclpdb1.example.com", "service_name") is None, "a dotted service name passes validation")
    check(oracle_dsn.validate_identifier("bad name!", "service_name") is not None, "a space/! in a service name is rejected")
    check(oracle_dsn.validate_identifier("", "sid") is not None, "an empty identifier is rejected")
    check(oracle_dsn.validate_identifier(None, "service_name") is not None, "a None identifier is rejected")

    sid_dsn = oracle_dsn.build_connect_string("10.0.0.1", "1521", "ORCL", "sid")
    check("(SID=ORCL)" in sid_dsn and "SERVICE_NAME" not in sid_dsn, "SID mode builds a SID= connect descriptor")

    svc_dsn = oracle_dsn.build_connect_string("10.0.0.1", "1521", "orclpdb1.example.com", "service_name")
    check("(SERVICE_NAME=orclpdb1.example.com)" in svc_dsn and "(SID=" not in svc_dsn, "Service Name mode builds a SERVICE_NAME= connect descriptor")

    legacy_creds = {"ip": "10.0.0.1", "port": "1521", "sid": "ORCL"}  # no connectType key at all
    check("(SID=ORCL)" in oracle_dsn.dsn_from_creds(legacy_creds), "creds dict missing connectType still builds a SID= DSN (backward compatibility)")


def test_favorites():
    print("2) favorites.py checks (isolated store)")
    import favorites as favorites_store

    sid_fav = favorites_store.save_favorite({
        "name": "SID Favorite", "ip": "10.0.0.1", "port": "1521",
        "sid": "ORCL", "connectType": "sid", "account": "system", "password": "pw1",
    })
    check(sid_fav["connectType"] == "sid", "SID favorite stores connectType='sid'")

    svc_fav = favorites_store.save_favorite({
        "name": "Service Name Favorite", "ip": "10.0.0.2", "port": "1521",
        "sid": "orclpdb1.example.com", "connectType": "service_name", "account": "system", "password": "pw2",
    })
    check(svc_fav["connectType"] == "service_name", "Service Name favorite stores connectType='service_name'")
    check(svc_fav["sid"] == "orclpdb1.example.com", "Service Name favorite keeps the dotted identifier verbatim")

    try:
        favorites_store.save_favorite({
            "name": "Bad Type", "ip": "10.0.0.3", "port": "1521",
            "sid": "ORCL", "connectType": "not_a_real_type", "account": "system", "password": "pw3",
        })
        check(False, "an invalid explicit connectType is rejected")
    except ValueError:
        check(True, "an invalid explicit connectType is rejected")

    try:
        favorites_store.save_favorite({
            "name": "Bad SID Chars", "ip": "10.0.0.4", "port": "1521",
            "sid": "orcl.pdb1", "connectType": "sid", "account": "system", "password": "pw4",
        })
        check(False, "a dotted identifier is rejected in SID mode at save time")
    except ValueError:
        check(True, "a dotted identifier is rejected in SID mode at save time")

    # Simulate a favorite saved before this feature existed: written straight
    # via _write_all(), bypassing save_favorite()'s own connectType handling.
    legacy_list = favorites_store._read_all()
    legacy_list.append({
        "id": "fav_legacy_no_connect_type", "name": "Legacy Favorite",
        "ip": "10.0.0.9", "port": "1521", "sid": "OLDORCL",
        "account": "system", "password": "legacy_pw",
    })
    favorites_store._write_all(legacy_list)
    legacy = favorites_store.get_favorite("fav_legacy_no_connect_type")
    check(legacy is not None and "connectType" not in legacy, "a pre-feature favorite record genuinely has no connectType key")
    view = favorites_store.public_view(legacy)
    check(view.get("connectType") is None, "public_view() surfaces the missing key as None, not a default")
    import oracle_dsn
    check(oracle_dsn.normalize_connect_type(view.get("connectType")) == "sid", "downstream normalization treats that None as 'sid', preserving old behavior")


def test_cache_key():
    print("3) backend.core.cache_key() checks")
    from backend import core

    base = {"ip": "10.0.0.1", "port": "1521", "sid": "ORCL", "account": "system"}
    sid_creds = {**base, "connectType": "sid"}
    svc_creds = {**base, "connectType": "service_name"}  # same literal identifier, different meaning
    legacy_creds = dict(base)  # no connectType key at all

    key_sid = core.cache_key("db-status-instance", sid_creds)
    key_svc = core.cache_key("db-status-instance", svc_creds)
    key_legacy = core.cache_key("db-status-instance", legacy_creds)

    check(key_sid != key_svc, "a SID target and a Service Name target sharing the same identifier get different cache keys")
    check(key_sid == key_legacy, "a creds dict missing connectType produces the same cache key as an explicit 'sid' (backward compatibility)")


def test_report_and_tuning_target_matching():
    print("4) report.py read_snapshots() / tuning.py _same_target() checks")
    import report
    import tuning

    now_ms = time.time() * 1000
    sid_target = {"ip": "10.0.0.1", "port": "1521", "sid": "ORCL", "connectType": "sid"}
    svc_target = {"ip": "10.0.0.1", "port": "1521", "sid": "ORCL", "connectType": "service_name"}
    legacy_target = {"ip": "10.0.0.1", "port": "1521", "sid": "ORCL"}  # predates connectType

    snapshots = [
        {"ts": now_ms, "target": report.encrypt_target(sid_target), "marker": "sid-snapshot"},
        {"ts": now_ms, "target": report.encrypt_target(svc_target), "marker": "service-name-snapshot"},
    ]
    body = "\n".join(json.dumps(s) for s in snapshots) + "\n"
    report.SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    report.SNAPSHOT_FILE.write_text(body, encoding="utf-8")

    sid_matches = report.read_snapshots(7, target=sid_target)
    check(len(sid_matches) == 1 and sid_matches[0]["marker"] == "sid-snapshot", "read_snapshots() for a SID target only returns the SID snapshot")

    svc_matches = report.read_snapshots(7, target=svc_target)
    check(len(svc_matches) == 1 and svc_matches[0]["marker"] == "service-name-snapshot", "read_snapshots() for a Service Name target only returns the Service Name snapshot")

    legacy_matches = report.read_snapshots(7, target=legacy_target)
    check(len(legacy_matches) == 1 and legacy_matches[0]["marker"] == "sid-snapshot", "a target lookup with no connectType key matches the SID snapshot, not the Service Name one")

    check(tuning._same_target(sid_target, legacy_target), "tuning._same_target(): explicit 'sid' matches a target with no connectType key")
    check(not tuning._same_target(sid_target, svc_target), "tuning._same_target(): SID and Service Name targets with the same identifier do not match")


def test_connect_endpoint_validation():
    print("5) POST /api/connect validation checks (no DB connection reached)")
    from backend import routes_connect

    from backend.core import Session

    async def call(body):
        request = FakeRequest()
        response = FakeResponse()
        session = Session(FakeRequest(), response)

        async def _json():
            return body

        request.json = _json
        return await routes_connect.connect(request, session=session)

    resp = run(call({"ip": "10.0.0.1", "port": "1521", "sid": "ORCL", "connectType": "not_a_real_type", "account": "system", "password": "pw"}))
    check(resp.status_code == 400, "an invalid explicit connectType is rejected with 400")

    resp = run(call({"ip": "10.0.0.1", "port": "1521", "sid": "orcl.pdb1", "connectType": "sid", "account": "system", "password": "pw"}))
    check(resp.status_code == 400, "a dotted identifier is rejected with 400 in SID mode")

    resp = run(call({"ip": "10.0.0.1", "port": "1521", "sid": "bad name!", "connectType": "service_name", "account": "system", "password": "pw"}))
    check(resp.status_code == 400, "a space/! identifier is rejected with 400 in Service Name mode")

    resp = run(call({"ip": "10.0.0.1", "port": "1521", "account": "system", "password": "pw"}))
    check(resp.status_code == 400, "a missing sid/service name value is rejected with 400")


def test_connect_flow_mocked():
    print("6) Mocked end-to-end connect flow (MOCK ONLY -- no real Oracle DB involved)")
    from backend import routes_connect
    from backend.core import Session

    async def do_connect(body):
        response = FakeResponse()
        session = Session(FakeRequest(), response)
        request = FakeRequest()

        async def _json():
            return body

        request.json = _json
        result = await routes_connect.connect(request, session=session)
        return result, session

    with MockedOracle() as mock:
        result, session = run(do_connect({
            "ip": "10.0.0.1", "port": "1521", "sid": "ORCL",
            "connectType": "sid", "account": "system", "password": "pw",
        }))
        check(result.get("success") is True, "mocked SID connect succeeds")
        check(any("(SID=ORCL)" in d for d in mock.dsns), "mocked SID connect built a SID= DSN")
        check(session.get("db_creds", {}).get("connectType") == "sid", "session stores connectType='sid' after a SID connect")

    with MockedOracle() as mock:
        result, session = run(do_connect({
            "ip": "10.0.0.2", "port": "1521", "sid": "orclpdb1.example.com",
            "connectType": "service_name", "account": "system", "password": "pw",
        }))
        check(result.get("success") is True, "mocked Service Name connect (with a dotted name) succeeds")
        check(any("(SERVICE_NAME=orclpdb1.example.com)" in d for d in mock.dsns), "mocked Service Name connect built a SERVICE_NAME= DSN")
        check(session.get("db_creds", {}).get("connectType") == "service_name", "session stores connectType='service_name' after a Service Name connect")

        # Requirement 7: connecting with an explicit connectType never falls
        # back to trying the other mode -- exactly one connect_async call
        # was made for this attempt, using exactly the chosen mode's DSN.
        check(len(mock.dsns) == 1, "exactly one connect attempt is made -- no automatic SID<->Service Name retry")

    # Reconnect path (dashboard reload / db-status-* polling): a session's
    # stored creds (including connectType) is reused to open a fresh
    # connection, and it must still honor the Service Name mode.
    with MockedOracle() as mock:
        creds = {"ip": "10.0.0.2", "port": "1521", "sid": "orclpdb1.example.com", "connectType": "service_name", "account": "system", "password": "pw"}
        from backend.core import get_oracle_connection

        run(get_oracle_connection(creds))
        check(any("(SERVICE_NAME=orclpdb1.example.com)" in d for d in mock.dsns), "reconnecting from stored session creds still builds a SERVICE_NAME= DSN")


def test_connect_favorite_flow_mocked():
    print("7) Mocked /api/connect-favorite flow, including a legacy (no connectType) favorite")
    import favorites as favorites_store
    from backend import routes_connect
    from backend.core import Session

    svc_fav = favorites_store.save_favorite({
        "name": "Fixture Service Name Favorite", "ip": "10.0.0.5", "port": "1521",
        "sid": "orclpdb1.example.com", "connectType": "service_name", "account": "system", "password": "pw",
    })

    legacy_list = favorites_store._read_all()
    legacy_list.append({
        "id": "fav_legacy_connect_test", "name": "Legacy Connect Favorite",
        "ip": "10.0.0.6", "port": "1521", "sid": "LEGACYSID",
        "account": "system", "password": "pw",
    })
    favorites_store._write_all(legacy_list)

    async def do_connect_favorite(fav_id):
        response = FakeResponse()
        session = Session(FakeRequest(), response)
        request = FakeRequest()

        async def _json():
            return {"favoriteId": fav_id}

        request.json = _json
        result = await routes_connect.connect_favorite(request, session=session)
        return result, session

    with MockedOracle() as mock:
        result, session = run(do_connect_favorite(svc_fav["id"]))
        check(result.get("success") is True, "connect-favorite succeeds for the Service Name favorite")
        check(any("(SERVICE_NAME=orclpdb1.example.com)" in d for d in mock.dsns), "connect-favorite for a Service Name favorite builds a SERVICE_NAME= DSN")

    with MockedOracle() as mock:
        result, session = run(do_connect_favorite("fav_legacy_connect_test"))
        check(result.get("success") is True, "connect-favorite succeeds for the legacy (no connectType) favorite")
        check(any("(SID=LEGACYSID)" in d for d in mock.dsns), "connect-favorite for a legacy favorite (no connectType key) falls back to a SID= DSN")


def main():
    backups = backup_data_files()
    try:
        test_oracle_dsn_unit()
        test_favorites()
        test_cache_key()
        test_report_and_tuning_target_matching()
        test_connect_endpoint_validation()
        with NoBackgroundCollection():
            test_connect_flow_mocked()
            test_connect_favorite_flow_mocked()
    finally:
        restore_data_files(backups)

    print()
    print("NOTE: every DB-connection check above ran against a mocked oracledb.connect_async")
    print("(see MockedOracle) -- there is no reachable Oracle Database in this environment,")
    print("so no REAL-DB verification was performed or is claimed here.")
    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL TESTS PASSED (mock-based only -- see NOTE above)")


if __name__ == "__main__":
    main()
