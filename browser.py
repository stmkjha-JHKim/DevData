"""browser.py -- opens AtlasStudio's URL in an isolated, dedicated browser
profile with password-saving turned off, instead of the user's normal
default-browser profile/tab.

Adapted from OraPulse's own browser.py (D:\\STMKJHA\\00.Git\\01.OraPulse\\
browser.py) -- identical logic, but PROFILE_DIR is rooted at *this*
project's own DATA_DIR (see paths.py), so AtlasStudio always gets its own
separate browser profile under its own data/ folder, never OraPulse's.
Running both apps at the same time never shares this profile, and never
opens one app's window from the other's tray icon.

Why a dedicated profile at all: this app binds to a fresh, randomly-picked
port on every launch (see main.py's _pick_free_port()), so its URL's
origin (http://127.0.0.1:<port>) is different every time. Chrome/Edge
remember a "never save passwords for this site" choice per *origin*, so
that choice can never stick across launches -- to the browser, the same
screen looks like a brand new site every time, and it asks again. The one
setting that isn't defeated by a changing port is the password manager's
own on/off switch, which applies to a whole browser *profile*, not to one
origin -- so this opens a small, dedicated profile (created once, under
this app's own data/browser-profile folder) with that switch pre-set to
off, instead of touching the user's real day-to-day browser profile at
all. (This UI-only build has no password field anywhere, but the profile
is still isolated for the same reason a future feature would want it.)

Opened with --app=<url> (no address bar/tabs, an app-like window) -- no
--window-size/--window-position here, matching OraPulse's own real
browser.py exactly: Chrome/Edge decide the new window's size themselves,
and because this always reuses the same dedicated profile (PROFILE_DIR
below), the browser remembers whatever size/position the user last left
that window at and reopens it there next time, the same way it would for
any other app-mode window -- no extra bookkeeping needed here for that.
(An earlier revision of this file computed an explicit --window-size/
--window-position from the primary monitor's resolution instead; it was
removed after comparing this file against OraPulse's real one, which
never had that logic to begin with.)

Falls back to the OS's normal webbrowser.open() (the user's actual
default browser, in their normal profile, normal window) if neither
Chrome nor Edge can be found at any of their usual Windows install
locations -- a nice-to-have, not a hard requirement.
"""

import json
import os
import subprocess
import webbrowser
from typing import Optional

from paths import DATA_DIR

PROFILE_DIR = DATA_DIR / "browser-profile"

# Checked in order; the first one that actually exists on disk wins.
_CANDIDATE_PATHS = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
)


def _find_browser() -> Optional[str]:
    for template in _CANDIDATE_PATHS:
        candidate = os.path.expandvars(template)
        if os.path.isfile(candidate):
            return candidate
    return None


def _ensure_profile_prefs_disable_password_manager() -> None:
    """Pre-seeds "Offer to save passwords: off" the very first time this
    dedicated profile is created, before Chrome/Edge ever touches it."""
    prefs_path = PROFILE_DIR / "Default" / "Preferences"
    if prefs_path.exists():
        return
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps({"credentials_enable_service": False}))


def open_app_window(url: str) -> None:
    browser_path = _find_browser()
    if browser_path is None:
        webbrowser.open(url)
        return

    _ensure_profile_prefs_disable_password_manager()
    # If this profile's browser process is already running (e.g. the
    # single-instance guard in main.py redirecting a second launch to the
    # already-open instance), Chrome/Edge forward this to that existing
    # process and just open a new window there instead of starting a
    # second one.
    subprocess.Popen(
        [
            browser_path,
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            f"--app={url}",
        ],
        close_fds=True,
    )
