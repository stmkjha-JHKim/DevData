"""tests/test_favorites_security.py -- regression tests for the Favorites
password-exposure fix (see favorites.py's public_view()/get_favorite(),
and backend/routes_connect.py's GET/POST /api/favorites and
POST /api/connect-favorite).

Verifies a saved favorite's plaintext password never appears anywhere a
client (or an attacker with only devtools/Network-tab access) could
observe it: not in a GET /api/favorites response, not in a POST
/api/favorites (save/overwrite) response, not in a failed
POST /api/connect-favorite's error message, and not in the running
server's own stdout/stderr. Also covers the "keep vs. change password"
save semantics and the not-found/forged-id/corrupted-store handling.

Frontend state (favoritesCache, the password input) isn't separately
exercised here -- there's no browser/DOM test harness in this project, and
none is added just for this. It doesn't need one anyway: the frontend can
only ever hold what GET /api/favorites hands it, so proving the API never
sends the password (below) structurally proves the frontend cache can't
contain it either.

Deliberately dependency-free (no pytest/httpx/etc. added to this project
for this): runs the real app (main.py, the exact server every user runs)
as a subprocess and talks to it with the standard library's urllib. Run
directly with:

    .\\venv\\Scripts\\python.exe tests\\test_favorites_security.py

from the repo root. Exits non-zero with a list of failed checks, or
prints "ALL TESTS PASSED" on success.

Isolation: paths.py resolves DATA_DIR relative to this repo's own root
when not frozen (app_dir() uses paths.py's own __file__, not the test's
cwd), so this temporarily moves the real data\\favorites.enc /
data\\.favorites-key aside for the run and restores them afterwards in a
finally block -- including deleting whatever *new* key file favorites.py
generates in their absence first, since leaving that behind would
silently break decryption of the restored (differently-keyed) real
favorites.enc.
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
FAVORITES_FILE = DATA_DIR / "favorites.enc"
KEY_FILE = DATA_DIR / ".favorites-key"
PORT = 59530
BASE = f"http://127.0.0.1:{PORT}"

# Distinctive enough that it can never appear by coincidence in any
# unrelated response text, error message, or log line.
PLAINTEXT_PASSWORD = "S3cr3t_Test_Password_Marker_9f8e"

failures = []


def check(condition, description):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {description}")
    if not condition:
        failures.append(description)


def request(method, path, body=None, timeout=10):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, raw, json.loads(raw)
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, raw, json.loads(raw)


def wait_until_ready():
    for _ in range(50):
        try:
            status, _raw, data = request("GET", "/api/version")
            if data.get("success"):
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError("Server did not become ready in time.")


def main():
    fav_backup = FAVORITES_FILE.read_bytes() if FAVORITES_FILE.exists() else None
    key_backup = KEY_FILE.read_bytes() if KEY_FILE.exists() else None
    if FAVORITES_FILE.exists():
        FAVORITES_FILE.unlink()
    if KEY_FILE.exists():
        KEY_FILE.unlink()

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

        print("1) GET /api/favorites starts empty")
        status, raw, data = request("GET", "/api/favorites")
        check(data.get("success") and data.get("favorites") == [], "empty favorites list")

        print("2) POST /api/favorites (new, with password) never echoes it back")
        status, raw, data = request(
            "POST",
            "/api/favorites",
            {
                "name": "SecTest",
                "ip": "127.0.0.1",
                "port": "1521",
                "sid": "ORCL",
                "account": "scott",
                "password": PLAINTEXT_PASSWORD,
            },
        )
        check(status == 200 and data.get("success"), "save succeeded")
        fav_id = (data.get("favorite") or {}).get("id")
        check(bool(fav_id), "response includes an id")
        check("password" not in (data.get("favorite") or {}), "response has no password key")
        check(PLAINTEXT_PASSWORD not in raw.decode("utf-8", "ignore"), "no password marker anywhere in raw save response")

        print("3) GET /api/favorites lists it without the password")
        status, raw, data = request("GET", "/api/favorites")
        favs = data.get("favorites") or []
        check(len(favs) == 1 and favs[0]["id"] == fav_id, "the saved favorite is listed")
        check("password" not in favs[0], "listed favorite has no password key")
        check(PLAINTEXT_PASSWORD not in raw.decode("utf-8", "ignore"), "no password marker anywhere in raw list response")

        print("4) New favorite with no password is rejected (400), not silently blank")
        status, raw, data = request(
            "POST",
            "/api/favorites",
            {"name": "NoPasswordFavorite", "ip": "1.2.3.4", "port": "1521", "sid": "ORCL", "account": "x"},
        )
        check(status == 400 and not data.get("success"), "rejected with 400")

        print("5) Overwrite by id with no password keeps the old password (checked server-side only)")
        status, raw, data = request(
            "POST",
            "/api/favorites",
            {"id": fav_id, "name": "SecTest", "ip": "10.0.0.5", "port": "1521", "sid": "ORCL", "account": "scott"},
        )
        check(status == 200 and data.get("success"), "overwrite succeeded")
        check("password" not in (data.get("favorite") or {}), "overwrite response still has no password key")
        check(PLAINTEXT_PASSWORD not in raw.decode("utf-8", "ignore"), "no password marker in overwrite response")

        sys.path.insert(0, str(ROOT))
        import favorites as favorites_store  # server isn't holding this file open between requests; safe to read now

        stored = favorites_store.get_favorite(fav_id)
        check(stored is not None and stored["password"] == PLAINTEXT_PASSWORD, "password preserved server-side after no-password overwrite")
        check(stored is not None and stored["ip"] == "10.0.0.5", "other fields still updated")

        print("6) Overwrite WITH a new password changes it")
        status, raw, data = request(
            "POST",
            "/api/favorites",
            {
                "id": fav_id,
                "name": "SecTest",
                "ip": "10.0.0.5",
                "port": "1521",
                "sid": "ORCL",
                "account": "scott",
                "password": "a_different_password",
            },
        )
        check(status == 200 and data.get("success"), "password-changing overwrite succeeded")
        stored = favorites_store.get_favorite(fav_id)
        check(stored is not None and stored["password"] == "a_different_password", "password actually changed")
        check(PLAINTEXT_PASSWORD not in raw.decode("utf-8", "ignore"), "no password marker in response")

        print("7) connect-favorite with a forged/unknown id: safe 404, no leak")
        status, raw, data = request("POST", "/api/connect-favorite", {"favoriteId": "fav_forged_does_not_exist"})
        check(status == 404 and not data.get("success"), "404 for unknown id")

        print("8) connect-favorite with missing favoriteId: 400")
        status, raw, data = request("POST", "/api/connect-favorite", {})
        check(status == 400 and not data.get("success"), "400 for missing favoriteId")

        print("9) connect-favorite with a real id (no Oracle reachable in this test env): no password in the failure")
        # A real (if doomed) connection attempt goes through python-oracledb
        # itself here -- that can legitimately take much longer than a
        # normal API call to time out against an unreachable target, hence
        # the generous timeout (this is the one call in this whole test
        # that isn't answered straight from favorites.enc/a quick 4xx).
        status, raw, data = request("POST", "/api/connect-favorite", {"favoriteId": fav_id}, timeout=90)
        check(not data.get("success"), "connection attempt fails (expected -- no real Oracle DB in this test env)")
        check("a_different_password" not in raw.decode("utf-8", "ignore"), "no password marker in raw connect-favorite failure response")
        check("a_different_password" not in json.dumps(data), "no password marker in parsed JSON either")

        print("10) delete + re-check")
        status, raw, data = request("POST", "/api/favorites-delete", {"id": fav_id})
        check(status == 200 and data.get("success"), "delete succeeded")
        status, raw, data = request("GET", "/api/favorites")
        check(data.get("favorites") == [], "list is empty again")

        print("11) corrupted store is handled safely (no crash, no partial leak)")
        FAVORITES_FILE.write_bytes(b"not a valid encrypted payload")
        status, raw, data = request("GET", "/api/favorites")
        check(status == 200 and data.get("favorites") == [], "corrupted store -> empty list, no crash")
        status, raw, data = request("POST", "/api/connect-favorite", {"favoriteId": "anything"})
        check(status == 404, "corrupted store -> connect-favorite returns a safe 404, not a 500")

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
                PLAINTEXT_PASSWORD not in server_output and "a_different_password" not in server_output,
                "no password marker anywhere in the server's own stdout/stderr log",
            )

        # Clean up whatever this run wrote, then restore the developer's
        # real store exactly as it was -- a freshly generated key must
        # never be left in place ahead of restoring the (differently
        # keyed) real favorites.enc, or it silently fails to decrypt.
        if FAVORITES_FILE.exists():
            FAVORITES_FILE.unlink()
        if KEY_FILE.exists():
            KEY_FILE.unlink()
        if fav_backup is not None:
            FAVORITES_FILE.write_bytes(fav_backup)
        if key_backup is not None:
            KEY_FILE.write_bytes(key_backup)

    print()
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
