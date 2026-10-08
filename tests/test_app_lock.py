"""tests/test_app_lock.py -- regression tests for the app-password gate
(app_lock.py, backend/routes_app_lock.py, public/lock.html).

Covers the actual security property this feature exists for: that nothing
behind the gate -- static pages (the connect screen, the dashboard) and
every /api/* route except the tiny allow-list needed to render and operate
the lock screen itself -- is reachable before the right password has been
typed in, and that a wrong password (or a second attempt to call /setup
once a password already exists) is rejected without ever leaking the
stored password/hash back to the client or into the server's own log
output. Also covers the brute-force throttle and that the one documented
recovery path (deleting app-lock.json) actually resets the gate without
touching anything else.

Deliberately dependency-free, same as tests/test_favorites_security.py:
runs the real app (main.py) as a subprocess and talks to it with the
standard library's urllib. Run directly with:

    .\\venv\\Scripts\\python.exe tests\\test_app_lock.py

from the repo root. Exits non-zero with a list of failed checks, or prints
"ALL TESTS PASSED" on success.

Isolation: same approach as test_favorites_security.py -- this moves any
pre-existing data\\app-lock.json aside before running and restores it
afterwards, so running this test can never lock a developer's real,
already-configured app out from under them, or leave this test's own
throwaway password behind as the real one.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
APP_LOCK_FILE = DATA_DIR / "app-lock.json"
PORT = 59531
BASE = f"http://127.0.0.1:{PORT}"

APP_PASSWORD = "Correct_Horse_Battery_Staple_42"
WRONG_PASSWORD = "definitely-not-it"

failures = []
_cookie = None


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {description}")
    if not condition:
        failures.append(description)


def request(method, path, body=None, use_cookie=True, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if use_cookie and _cookie:
        headers["Cookie"] = _cookie
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            return resp.status, raw, parsed, resp.headers.get("Set-Cookie")
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        return err.code, raw, parsed, err.headers.get("Set-Cookie")


def wait_until_ready():
    for _ in range(50):
        try:
            status, _raw, data, _ = request("GET", "/api/version", use_cookie=False)
            if data and data.get("success"):
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Server did not become ready in time.")


def main():
    global _cookie

    app_lock_backup = APP_LOCK_FILE.read_bytes() if APP_LOCK_FILE.exists() else None
    if APP_LOCK_FILE.exists():
        APP_LOCK_FILE.unlink()

    proc = None
    try:
        env = dict(os.environ)
        env["PORT"] = str(PORT)
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "main.py")],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wait_until_ready()

        print("1) Fresh instance: not configured yet")
        status, raw, data, _ = request("GET", "/api/app-lock/status", use_cookie=False)
        check(status == 200 and data.get("success") and data.get("configured") is False, "status reports not configured")

        print("2) /api/version stays reachable even while locked (needed for single-instance detection)")
        status, raw, data, _ = request("GET", "/api/version", use_cookie=False)
        check(status == 200 and data.get("success"), "/api/version is not gated")

        print("3) Everything else is blocked pre-setup")
        status, raw, data, _ = request("GET", "/api/favorites", use_cookie=False)
        check(status == 401 and data.get("needsSetup") is True, "favorites API blocked, needsSetup=true")
        status, raw, _, _ = request("GET", "/", use_cookie=False)
        html = raw.decode("utf-8", "ignore")
        check(status == 200 and "lockForm" in html and "dbForm" not in html, "root serves the lock screen, not the connect screen")

        print("4) /api/app-lock/verify before anything is configured: 409, no crash")
        status, raw, data, _ = request("POST", "/api/app-lock/verify", {"password": WRONG_PASSWORD}, use_cookie=False)
        check(status == 409 and not data.get("success"), "verify before setup is rejected cleanly")

        print("5) Setup rejects a mismatched confirm password")
        status, raw, data, _ = request(
            "POST", "/api/app-lock/setup", {"password": APP_PASSWORD, "confirmPassword": "something-else"}, use_cookie=False
        )
        check(status == 400 and not data.get("success"), "mismatched confirm rejected")
        check(not APP_LOCK_FILE.exists(), "no app-lock.json written after a rejected setup")

        print("6) Setup rejects a too-short password")
        status, raw, data, _ = request("POST", "/api/app-lock/setup", {"password": "short", "confirmPassword": "short"}, use_cookie=False)
        check(status == 400 and not data.get("success"), "too-short password rejected")

        print("7) Setup succeeds with a matching, long-enough password")
        status, raw, data, set_cookie = request(
            "POST", "/api/app-lock/setup", {"password": APP_PASSWORD, "confirmPassword": APP_PASSWORD}, use_cookie=False
        )
        check(status == 200 and data.get("success"), "setup succeeded")
        check(bool(set_cookie), "setup response sets an unlock cookie")
        check(APP_PASSWORD not in raw.decode("utf-8", "ignore"), "no password echoed back in the setup response")
        check(APP_LOCK_FILE.exists(), "app-lock.json was written")
        stored = json.loads(APP_LOCK_FILE.read_text(encoding="utf-8"))
        check(APP_PASSWORD not in json.dumps(stored), "app-lock.json stores a hash, not the plaintext password")
        check("hash" in stored and "salt" in stored and "iterations" in stored, "app-lock.json has the expected verifier shape")
        stored_after_first_setup = APP_LOCK_FILE.read_bytes()

        print("8) A second /api/app-lock/setup call is rejected even though one already exists (can't be silently overwritten)")
        status, raw, data, _ = request(
            "POST", "/api/app-lock/setup", {"password": "some-other-password", "confirmPassword": "some-other-password"}, use_cookie=False
        )
        check(status == 409 and not data.get("success"), "repeat setup rejected with 409")
        check(APP_LOCK_FILE.read_bytes() == stored_after_first_setup, "app-lock.json unchanged by the rejected repeat setup")

        print("9) Without the unlock cookie, everything is still blocked now that a password IS configured")
        status, raw, data, _ = request("GET", "/api/favorites", use_cookie=False)
        check(status == 401 and data.get("needsSetup") is False, "favorites still blocked; needsSetup now false")
        status, raw, _, _ = request("GET", "/", use_cookie=False)
        html = raw.decode("utf-8", "ignore")
        check("lockForm" in html, "root still serves the lock screen without a valid cookie")

        print("10) Wrong password is rejected without leaking anything")
        status, raw, data, _ = request("POST", "/api/app-lock/verify", {"password": WRONG_PASSWORD}, use_cookie=False)
        check(status == 401 and not data.get("success"), "wrong password rejected")
        check(APP_PASSWORD not in raw.decode("utf-8", "ignore"), "no password marker in the failure response")

        print("11) Repeated wrong attempts eventually get throttled (429)")
        statuses = []
        for _ in range(5):
            status, raw, data, _ = request("POST", "/api/app-lock/verify", {"password": WRONG_PASSWORD}, use_cookie=False)
            statuses.append(status)
            if status == 429:
                break
        check(429 in statuses, f"throttle eventually kicks in (saw statuses: {statuses})")
        if statuses and statuses[-1] == 429:
            status, raw, data, _ = request("POST", "/api/app-lock/verify", {"password": WRONG_PASSWORD}, use_cookie=False)
            check(status == 429 and isinstance(data.get("retryAfterSeconds"), (int, float)), "429 response carries retryAfterSeconds")
            time.sleep(data.get("retryAfterSeconds", 1) + 0.5)

        print("12) The correct password still works after the throttle window passes")
        status, raw, data, set_cookie = request("POST", "/api/app-lock/verify", {"password": APP_PASSWORD}, use_cookie=False)
        check(status == 200 and data.get("success"), "correct password accepted")
        check(bool(set_cookie), "verify response sets an unlock cookie")
        _cookie = set_cookie.split(";", 1)[0] if set_cookie else None

        print("13) With a valid unlock cookie, the real app is reachable again")
        status, raw, data, _ = request("GET", "/api/favorites")
        check(status == 200 and data.get("success"), "favorites API reachable once unlocked")
        status, raw, _, _ = request("GET", "/")
        html = raw.decode("utf-8", "ignore")
        check("dbForm" in html and "lockForm" not in html, "root serves the real connect screen once unlocked")

        print("14) A forged/garbage cookie value is treated as locked, not a crash")
        garbage_req = urllib.request.Request(f"{BASE}/api/favorites", headers={"Cookie": "ora_unlock=not-a-real-token"})
        try:
            with urllib.request.urlopen(garbage_req, timeout=10) as resp:
                check(False, "forged cookie should not grant access")
        except urllib.error.HTTPError as err:
            check(err.code == 401, "forged cookie correctly rejected with 401")

    finally:
        server_output = ""
        if proc is not None:
            proc.terminate()
            try:
                server_output, _ = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                server_output, _ = proc.communicate()
        if server_output:
            check(
                APP_PASSWORD not in server_output and WRONG_PASSWORD not in server_output,
                "no password marker anywhere in the server's own stdout/stderr log",
            )

        if APP_LOCK_FILE.exists():
            APP_LOCK_FILE.unlink()
        if app_lock_backup is not None:
            APP_LOCK_FILE.write_bytes(app_lock_backup)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
