"""main.py -- entry point: creates the app, registers routes, launches the
server. Same overall shape as OraPulse's own main.py (FastAPI + uvicorn,
static frontend served straight out of public/), extended with the local
SQLite metadata store and the backup scheduler this project adds on top.

Run from source:
    pip install -r requirements.txt
    python main.py
"""

import os
import sys

# The packaged .exe is built windowed (OraVaultBackup.spec's console=False),
# so there's no console and PyInstaller's bootloader sets sys.stdout/stderr
# to None -- any print() or uvicorn's own logging would raise
# AttributeError on first use. Redirect to os.devnull before anything else
# runs. Source runs (python main.py) keep the real console untouched.
if getattr(sys, "frozen", False) and sys.stdout is None:
    _devnull = open(os.devnull, "w")
    sys.stdout = _devnull
    sys.stderr = _devnull

import shutil
import socket
import subprocess
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.core import APP_VERSION, HOST, PORT
from backend.db import init_db
from backend.scheduler import shutdown_scheduler, start_scheduler
from paths import DATA_DIR, PUBLIC_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(title="OraVault Backup", version=APP_VERSION, lifespan=lifespan)

from backend.routes_dashboard import router as dashboard_router
from backend.routes_db import router as dbs_router
from backend.routes_history import router as history_router
from backend.routes_manual import router as manual_router
from backend.routes_policies import router as policies_router
from backend.routes_recovery import router as recovery_router

app.include_router(dbs_router)
app.include_router(policies_router)
app.include_router(manual_router)
app.include_router(history_router)
app.include_router(dashboard_router)
app.include_router(recovery_router)


@app.get("/api/version")
async def version():
    return {"success": True, "version": APP_VERSION}


@app.get("/")
async def root():
    return RedirectResponse(url="/index.html")


# Static frontend -- mounted last so it doesn't shadow the /api/* routes
# above. html=True lets /index.html and /dashboard.html resolve without
# the extension too, matching how OraPulse's own public/ is served.
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")


_CHROMIUM_CANDIDATES = [
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
]


def _find_chromium_browser() -> str | None:
    for candidate in _CHROMIUM_CANDIDATES:
        expanded = os.path.expandvars(candidate)
        if os.path.isfile(expanded):
            return expanded
    return shutil.which("chrome") or shutil.which("msedge")


def _wait_for_server(host: str, port: int, timeout: float = 10.0) -> None:
    """Polls the listening socket instead of a flat sleep -- opens the
    browser the moment the server can actually accept a connection rather
    than guessing a fixed delay (too short races the server on a slow
    machine, too long adds dead time to every launch for no reason)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)


def _open_browser_once_ready():
    # Only for the packaged .exe -- there's no console to show the
    # "Uvicorn running on ..." line anymore (console=False), so this is
    # now the only way the user gets to the UI. Running from source keeps
    # printing the address instead, so it doesn't pop a tab on every dev
    # reload.
    _wait_for_server(HOST, PORT)
    url = f"http://{HOST}:{PORT}/"

    browser = _find_chromium_browser()
    if browser is None:
        webbrowser.open(url)
        return

    # --app opens a chromeless window (no tabs/address bar/bookmarks bar --
    # just the page, with a plain title bar). A dedicated --user-data-dir
    # is what actually makes this launch stand alone: without it, Chrome/Edge
    # forward the request to whatever instance of that browser is already
    # running (reusing its window/profile, ignoring --app) instead of
    # opening a new one, so a separate profile folder is required to get an
    # independent window every time regardless of what's already open.
    profile_dir = DATA_DIR / "browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            [
                browser,
                f"--app={url}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            # A windowed (console=False) build has no console, so its
            # stdin/stdout/stderr handles are invalid -- subprocess.Popen
            # tries to inherit them by default and raises "OSError:
            # [WinError 6] The handle is invalid" unless all three are
            # explicitly redirected here.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        webbrowser.open(url)


def main():
    if getattr(sys, "frozen", False):
        threading.Thread(target=_open_browser_once_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
