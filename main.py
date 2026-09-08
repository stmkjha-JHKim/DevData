"""main.py -- OraPulse entry point.

This is a small standalone FastAPI + Oracle server, meant to be run locally
by each user (pip install -r requirements.txt && python main.py, then open
the printed http://127.0.0.1:<port> address in a browser), the same way
you'd run a desktop DB client. It is not a hosted/shared service: every
user runs their own instance of this process, against their own Oracle
credentials.

Because of that, all the internet-facing hardening a real multi-user hosted
web app would need (app-level login/sign-up, JWT, rate limiting, CORS) is
intentionally left out here -- it doesn't apply to this deployment model.
This server is bound to 127.0.0.1 and only ever reached by a browser on this
same machine -- there is no network path for anyone else to reach it. The
Oracle DB account/password entered on the connect screen is the only
"login" needed, exactly like a normal desktop DB client.

Only Oracle Database 12.1 or later is supported (python-oracledb's pure-
Python "thin mode" -- no Oracle Instant Client / thick-mode install
required).

This file itself only wires things together: it creates the FastAPI app
(backend/core.py), registers every feature's routes (backend/routes_*.py,
one module per tab/feature -- see each module's own top-of-file comment),
mounts the static frontend, and handles process launch (single-instance
guard, tray icon when packaged). All actual endpoint logic lives in
backend/.
"""

import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from typing import Optional

from fastapi.staticfiles import StaticFiles

import browser
from paths import DATA_DIR, resource_dir

from backend import core
from backend.core import APP_VERSION, HOST, PUBLIC_DIR, app
from backend import (
    routes_account_security,
    routes_alert_log,
    routes_connect,
    routes_jobs,
    routes_object_view,
    routes_ops,
    routes_recovery,
    routes_report,
    routes_session,
    routes_sql_runner,
    routes_table_stats,
    routes_tuning,
)

for _router_module in (
    routes_connect,
    routes_session,
    routes_table_stats,
    routes_object_view,
    routes_tuning,
    routes_jobs,
    routes_account_security,
    routes_alert_log,
    routes_ops,
    routes_recovery,
    routes_sql_runner,
    routes_report,
):
    app.include_router(_router_module.router)

# Static frontend (public/index.html, dashboard.html, troubleshooting.html,
# favicon.svg) -- served as-is. Mounted last so the /api/* routes above are
# always matched first.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


# A random free port is picked fresh on every launch instead of a fixed
# well-known one (see core.PORT's own comment) -- so two independent users
# on the same machine, or OraPulse and some unrelated app, never fight
# over the same port. That means the old "try to bind the fixed port
# ourselves" trick for detecting an already-running instance no longer
# applies (a fresh launch's own random port essentially never collides
# with a previous one's). Instead, the actual port in use is written to a
# small lock file next to the persistent data/ folder, and a relaunch
# checks that file and asks the port it names whether it's really still a
# live OraPulse instance (not just some unrelated process that happens to
# be listening there right now) before treating it as "already running".
INSTANCE_LOCK_FILE = DATA_DIR / ".instance-port"


def _pick_free_port() -> int:
    """Asks the OS for an ephemeral port nothing else is using right now,
    the standard bind-to-0-then-read-it-back idiom. There's a theoretical
    (and, in practice, vanishingly unlikely) race between closing this
    probe socket and uvicorn binding the same number a moment later."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _running_instance_url() -> Optional[str]:
    """The URL of an already-running OraPulse instance, or None if there
    isn't one. A lock file that names a port nothing answers on (or that
    answers but isn't this app) is treated as stale -- left behind by a
    previous run that crashed or was killed rather than exited cleanly --
    and simply ignored; this process then goes on to pick its own fresh
    port and overwrite the file, self-healing without any special-casing."""
    try:
        port = int(INSTANCE_LOCK_FILE.read_text().strip())
    except (OSError, ValueError):
        return None

    url = f"http://{HOST}:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/version", timeout=1.0) as resp:
            data = json.loads(resp.read())
    except (OSError, urllib.error.URLError, ValueError):
        return None
    return url if data.get("success") else None


if __name__ == "__main__":
    existing_url = _running_instance_url()
    if existing_url is not None:
        # Launched again while an instance is already up (double-clicked
        # a second time, most commonly): jump to the existing one instead
        # of starting a second server, and -- for the frozen/tray build --
        # a second, confusing tray icon whose "Exit" would only stop this
        # new instance while the real one keeps running.
        browser.open_app_window(existing_url)
        sys.exit(0)

    if core.PORT == 0:  # not pinned via the PORT env var -- the normal case
        core.PORT = _pick_free_port()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_LOCK_FILE.write_text(str(core.PORT))

    import uvicorn

    config = uvicorn.Config(app, host=HOST, port=core.PORT)
    server = uvicorn.Server(config)

    if getattr(sys, "frozen", False):
        # Packaged .exe: no console window at all (see OraPulse.spec /
        # OraPulse-Folder.spec's console=False) -- without a tray icon,
        # there would be no way to tell the app is still running or to
        # shut it down short of Task Manager. uvicorn runs on a background
        # thread instead of blocking here so the tray icon's own message
        # loop can have the main thread, which pystray requires on
        # Windows; uvicorn's own signal-handler setup already skips itself
        # gracefully when it isn't running on the main thread.
        import tray

        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        tray.run(
            url=f"http://{HOST}:{core.PORT}",
            icon_path=resource_dir() / "public" / "favicon.ico",
            title=f"OraPulse v{APP_VERSION}",
            server=server,
        )
        server_thread.join(timeout=5)
    else:
        # Running from source: a normal console is already there, so keep
        # the plain Ctrl+C flow a developer expects instead of a tray icon.
        print(f"OraPulse (Python) is running at http://{HOST}:{core.PORT} -- open that address in your browser.")
        server.run()
