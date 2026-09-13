"""backend/core.py -- the FastAPI app instance and the one thing every
other part of this project depends on: PRODUCT_ID/APP_VERSION and the
`/api/version` endpoint.

This is a UI-only skeleton (see main.py's own top-of-file comment for the
full picture) -- there is deliberately no DB driver, no session store, no
result cache, no route modules here yet. When a real feature (schema
compare, data diff, ...) is eventually implemented, it gets its own
backend/routes_<feature>.py (one module per tab, matching OraPulse's own
convention) that main.py registers with `app.include_router(...)` -- see
that file's own comment. Nothing about that requires touching this file
beyond adding the import/include line.

Split out of main.py the same way OraPulse's own backend/core.py is split
out of its main.py, so main.py can stay focused on process launch
(single-instance guard, static mount, tray) while this stays focused on
"what the app *is*".
"""

import os
import sys
from contextlib import asynccontextmanager

# The packaged .exe runs with no console at all (AtlasStudio-Folder.spec's
# console=False -- it's a tray-icon app, see tray.py), which means
# sys.stdout/sys.stderr are None, not just non-a-tty. uvicorn's default
# logging setup calls sys.stdout.isatty() unconditionally while configuring
# its formatter; against None that raises AttributeError, which crashes the
# process before the server ever starts -- silently, since there's no
# console to show the traceback on. Standard fix for windowed PyInstaller
# apps: give stdout/stderr a harmless writable/isatty-able stand-in before
# anything (uvicorn, or our own stray print()) can touch them. Only None
# when actually windowed with no console (running from source always has a
# real console here). Carried over verbatim from OraPulse's own
# backend/core.py, which hit this exact crash first.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import browser
from paths import app_dir

from fastapi import FastAPI

# 127.0.0.1 only: this must never be reachable from the network or from
# another machine, only from a browser on this same computer.
HOST = "127.0.0.1"
# 0 is a sentinel meaning "not decided yet": main.py replaces this with a
# fresh OS-assigned free port right before starting uvicorn (see
# main.py's _pick_free_port()), unless PORT is set explicitly here via the
# environment. Read as a plain module attribute (core.PORT), not imported
# by name, by anything that needs the *final* value -- see main.py's own
# comment on why.
PORT = int(os.environ.get("PORT", 0))

# Checked by main.py's _running_instance_url() -- and by anyone else's
# tooling that wants to tell AtlasStudio apart from any other local
# service -- so a lock file pointing at a stale/foreign port is never
# mistaken for an already-running AtlasStudio just because it happens to
# answer with a generically similar-shaped {"success": true} response.
# OraPulse's own /api/version has no such field, and vice versa: neither
# app can ever redirect into the other's window this way, even if both
# happen to be running on this same machine at once.
PRODUCT_ID = "AtlasStudio"

# Version scheme: plain semantic-ish "0.1.0" text, bumped by hand.
# VERSION is a plain text file at the project root (also copied next to
# the .exe by build-folder.ps1) so it reads the same way whether running
# from source or packaged. "unknown" is only a defensive fallback -- it
# should never actually show up outside of a broken build.
try:
    APP_VERSION = (app_dir() / "VERSION").read_text(encoding="utf-8").strip()
except OSError:
    APP_VERSION = "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Opens the app window once the server is actually listening (this
    # fires after uvicorn has bound the socket, right before it starts
    # accepting requests) -- so double-clicking the packaged .exe takes the
    # user straight to the main screen instead of leaving them to find the
    # right address themselves. Reads the bare module global PORT (not a
    # value captured earlier), since by the time this actually runs
    # main.py has already replaced it with this launch's real, freshly
    # picked port -- see main.py's _pick_free_port().
    browser.open_app_window(f"http://{HOST}:{PORT}")
    yield


app = FastAPI(lifespan=lifespan, title=PRODUCT_ID, version=APP_VERSION)


@app.get("/api/version")
async def get_version():
    return {"success": True, "product": PRODUCT_ID, "version": APP_VERSION}
