"""paths.py -- shared path helpers so persistent data and bundled static
assets resolve correctly both when running from source (python main.py)
and when running as a PyInstaller-frozen .exe.

PyInstaller's --onefile mode extracts the whole app into a fresh temporary
directory (sys._MEIPASS) on every launch and discards it on exit --
__file__-relative paths inside a frozen build point there, not somewhere
persistent. So:

- Bundled, read-only resources (public/*.html, favicon.svg) come from
  wherever PyInstaller actually extracted them to -- see resource_dir().
- Persistent, read/write data used to live next to the .exe (app_dir()) for
  every packaged flavor -- portable zip, Inno-installed, and (new) the MSI
  install. That stopped working once the MSI started installing to
  Program Files: a non-admin user can't write there at runtime, and per-
  machine data next to a shared Program Files copy would collide between
  Windows accounts anyway. So a *frozen* build now writes its persistent
  data under %LOCALAPPDATA%\\OraPulse instead (always writable, always
  per-user, regardless of install location) -- see DATA_DIR/REPORT_DIR/
  LOG_DIR and _migrate_legacy_data() below.

  Running from source (python main.py, sys.frozen is False) deliberately
  keeps the old next-to-main.py data/ folder -- that's this project's own
  working tree, not an installed product, and every dev/test workflow in
  this repo already assumes data/ sits right there. Nothing under
  %LOCALAPPDATA% is touched in that case.
"""

import shutil
import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory bundled resources and (when not frozen) persistent data
    live under: next to the .exe when frozen, next to this source file's
    project root otherwise."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """Directory bundled read-only resources (public/) live under. Checks,
    in order: next to the .exe/script (where it already sits when running
    from source, and where the folder distribution's post-build step
    relocates it to -- see build-folder.ps1's promotion of public/ out of
    lib/), then PyInstaller's onefile extraction directory as a fallback
    (where public/ stays put, never relocated, for the single-.exe build)."""
    candidate = app_dir()
    if (candidate / "public").exists():
        return candidate
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return candidate


def _local_appdata_root() -> Path:
    """%LOCALAPPDATA%\\OraPulse -- only ever consulted for a frozen build
    (see module docstring). Falls back to a `local_appdata` folder next to
    the .exe on the vanishingly unlikely chance LOCALAPPDATA isn't set
    (some locked-down service accounts), rather than crashing at import
    time over it."""
    import os

    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else app_dir() / "local_appdata"
    return root / "OraPulse"


def _migrate_legacy_data() -> None:
    """One-time move of a pre-existing exe-adjacent data/report folder (from
    an older portable/Inno-installed OraPulse build, or the MSI's own
    Program-Files-adjacent location before this redirect existed) into the
    new %LOCALAPPDATA%\\OraPulse location. Runs exactly once: if the new
    location already has a data/reports folder, a previous run already
    migrated (or this is simply not a fresh-from-old-version machine) and
    nothing further happens. Every failure is swallowed and printed rather
    than raised -- a failed migration should never block the app from
    starting; worst case, the user's old favorites/history stay in the old
    spot and can be moved by hand (see README's "Data storage & privacy")."""
    legacy_root = app_dir()
    moves = (
        (legacy_root / "data", DATA_DIR),
        (legacy_root / "report", REPORT_DIR),
    )
    for old_dir, new_dir in moves:
        if new_dir.exists() or not old_dir.exists():
            continue
        try:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
            print(f"[paths] Migrated existing '{old_dir}' to '{new_dir}'.")
        except OSError as err:
            print(f"[paths] Could not migrate '{old_dir}' to '{new_dir}': {err}")


if getattr(sys, "frozen", False):
    _APPDATA_ROOT = _local_appdata_root()
    DATA_DIR = _APPDATA_ROOT / "data"
    REPORT_DIR = _APPDATA_ROOT / "reports"
    LOG_DIR = _APPDATA_ROOT / "logs"  # reserved for future use; nothing writes here yet
    _migrate_legacy_data()
else:
    DATA_DIR = app_dir() / "data"
    REPORT_DIR = app_dir() / "report"
    LOG_DIR = app_dir() / "logs"
