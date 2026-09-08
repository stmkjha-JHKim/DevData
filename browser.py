"""browser.py -- opens OraPulse's URL in an isolated, dedicated browser
profile with password-saving turned off, instead of the user's normal
default-browser profile/tab.

Why: OraPulse binds to a fresh, randomly-picked port on every launch (see
main.py's _pick_free_port()), so its URL's origin (http://127.0.0.1:<port>)
is different every time. Chrome/Edge remember a "never save passwords for
this site" choice per *origin*, so that choice can never stick across
launches -- to the browser, the same login screen looks like a brand new
site every time, and it asks again. The one setting that isn't defeated
by a changing port is the password manager's own on/off switch, which
applies to a whole browser *profile*, not to one origin -- so this opens
a small, dedicated profile (created once, under this app's own data/
folder) with that switch pre-set to off, instead of touching the user's
real day-to-day browser profile at all.

Opened with --app=<url> (no address bar/tabs, an app-like window) per the
user's own choice of window style.

Falls back to the OS's normal webbrowser.open() (the user's actual
default browser, in their normal profile, normal window) if neither
Chrome nor Edge can be found at any of their usual Windows install
locations -- this is a nice-to-have, not a hard requirement, and every
other browser this app supports (see README) still works fine that way,
just without this specific fix.
"""

import json
import os
import subprocess
import webbrowser
from typing import Optional

from paths import DATA_DIR

PROFILE_DIR = DATA_DIR / "browser-profile"

# Checked in order; the first one that actually exists on disk wins.
# Chrome is preferred over Edge since it's this app's most-tested/primary
# supported browser (see README).
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
    dedicated profile is created, before Chrome/Edge ever touches it.
    credentials_enable_service is a normal (not enterprise-managed) user
    preference -- the exact one the "Offer to save passwords" toggle in
    Settings writes -- so this is indistinguishable from a user having
    flipped that toggle off themselves. Left alone on every later launch
    (this function no-ops once the file exists) so a user who deliberately
    re-enables it inside this profile's own Settings isn't fought."""
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
    # second one -- the same well-known behavior a normal --user-data-dir
    # relaunch has.
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
