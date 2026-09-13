"""main.py -- AtlasStudio entry point.

A small standalone FastAPI + Uvicorn server, meant to be run locally by
each user (pip install -r requirements.txt && python main.py, then open
the printed http://127.0.0.1:<port> address in a browser -- or just let it
open its own app window automatically), the same way you'd run a desktop
app. It is not a hosted/shared service: every user runs their own instance
of this process, and it only ever serves the frontend under public/.

This is the runtime skeleton only (see the project README's "이번 개발
범위") -- adapted from OraPulse's own main.py
(D:\\STMKJHA\\00.Git\\01.OraPulse\\main.py: single-instance guard via a
port lock file, an OS-assigned free port picked fresh on every launch,
opening a dedicated browser app window once the server is ready, and a
system tray icon with no console window when packaged) with everything
Oracle/DB-specific left out. There are no backend/routes_*.py modules yet
because there is nothing behind "작업 홈" yet -- when a real feature is
implemented, it gets its own route module that this file registers with
`app.include_router(...)`, the same way OraPulse's main.py registers each
of its own tab's routes.

Because of the deployment model above, all the internet-facing hardening
a real multi-user hosted web app would need (app-level login/sign-up,
JWT, rate limiting, CORS) is intentionally left out here -- it doesn't
apply. This server is bound to 127.0.0.1 and only ever reached by a
browser on this same machine.
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

from backend.core import APP_VERSION, HOST, PRODUCT_ID, app

PUBLIC_DIR = resource_dir() / "public"

# Static frontend (public/index.html, styles.css, data.js, icons.js,
# app.js, favicon.*) -- served as-is. Mounted last so any future /api/*
# route registered above always matches first.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


# A random free port is picked fresh on every launch instead of a fixed
# well-known one -- so two independent users on the same machine, or
# AtlasStudio and some unrelated app (OraPulse included), never fight over
# the same port. The actual port in use is written to a small lock file
# next to AtlasStudio's own persistent data/ folder (see paths.py -- this
# is never OraPulse's data/ folder), and a relaunch checks that file and
# asks the port it names whether it's really still a live AtlasStudio
# instance (not just some unrelated process that happens to be listening
# there right now) before treating it as "already running".
INSTANCE_LOCK_FILE = DATA_DIR / ".instance-port"


def _pick_free_port() -> int:
    """Asks the OS for an ephemeral port nothing else is using right now,
    the standard bind-to-0-then-read-it-back idiom."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def _running_instance_url() -> Optional[str]:
    """The URL of an already-running AtlasStudio instance, or None if
    there isn't one. A lock file that names a port nothing answers on (or
    that answers but isn't *this* app -- see the product-id check below)
    is treated as stale and simply ignored; this process then goes on to
    pick its own fresh port and overwrite the file, self-healing without
    any special-casing.

    Deliberately checks `data.get("product") == PRODUCT_ID`, not just
    `data.get("success")`: a bare success flag would also be true for
    OraPulse's own /api/version (or any other locally-running service that
    happens to answer JSON with a "success" key on that port), which could
    otherwise redirect an AtlasStudio launch straight into a different
    app's window. See backend/core.py's PRODUCT_ID for the other half of
    this check.
    """
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
    return url if data.get("success") and data.get("product") == PRODUCT_ID else None


if __name__ == "__main__":
    existing_url = _running_instance_url()
    if existing_url is not None:
        # Launched again while an instance is already up (double-clicked a
        # second time, most commonly): jump to the existing one instead of
        # starting a second server, and -- for the frozen/tray build -- a
        # second, confusing tray icon whose "종료" would only stop this new
        # instance while the real one keeps running.
        browser.open_app_window(existing_url)
        sys.exit(0)

    from backend import core

    if core.PORT == 0:  # not pinned via the PORT env var -- the normal case
        core.PORT = _pick_free_port()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_LOCK_FILE.write_text(str(core.PORT))

    import uvicorn

    config = uvicorn.Config(app, host=HOST, port=core.PORT)
    server = uvicorn.Server(config)

    if getattr(sys, "frozen", False):
        # Packaged .exe: no console window at all (see
        # AtlasStudio-Folder.spec's console=False) -- without a tray icon,
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
            title=f"{PRODUCT_ID} v{APP_VERSION}",
            server=server,
        )
        server_thread.join(timeout=5)
    else:
        # Running from source: a normal console is already there, so keep
        # the plain Ctrl+C flow a developer expects instead of a tray icon.
        print(f"{PRODUCT_ID} (Python) is running at http://{HOST}:{core.PORT} -- open that address in your browser.")
        server.run()
