"""paths.py -- shared path helpers so persistent data and bundled static
assets resolve correctly both when running from source (python main.py)
and when running as a PyInstaller-frozen .exe.

Adapted from OraPulse's own paths.py (D:\\STMKJHA\\00.Git\\01.OraPulse\\
paths.py) -- same app_dir()/resource_dir()/writable-fallback pattern, but
trimmed to what AtlasStudio actually needs: no REPORT_DIR (no report
feature in this build) and no _migrate_legacy_data() (there is no older
AtlasStudio version to migrate data from yet).

PyInstaller's --onefile mode extracts the whole app into a fresh temporary
directory (sys._MEIPASS) on every launch and discards it on exit --
__file__-relative paths inside a frozen build point there, not somewhere
persistent. So:

- Bundled, read-only resources (public/*.html, favicon.*) come from
  wherever PyInstaller actually extracted them to -- see resource_dir().
- Persistent, read/write data lives next to the .exe (app_dir()) whenever
  that location is actually writable -- a plain "unzip and run" folder
  build keeps creating its own data/ folder right next to itself. Only
  when that location genuinely can't be written to (e.g. installed to a
  Program Files-style location a non-admin user can't write to) does this
  fall back to %LOCALAPPDATA%\\AtlasStudio instead (always writable,
  always per-user). See _writable() and DATA_DIR/LOG_DIR below. The choice
  is made once at import time by actually probing app_dir()/data for write
  access, not by guessing how the build was installed.

  Running from source (python main.py, sys.frozen is False) deliberately
  keeps the plain next-to-main.py data/ folder -- that's this project's
  own working tree, not an installed product.

This module -- and DATA_DIR in particular -- is what keeps AtlasStudio's
storage completely separate from OraPulse's: every path below is rooted
at *this* project's own app_dir()/%LOCALAPPDATA%\\AtlasStudio, never
anything under OraPulse's folder or its %LOCALAPPDATA%\\OraPulse. Nothing
in this file ever reads or writes OraPulse's data/, browser profile, or
build output.
"""

import os
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
    (unused by this project's build-folder.ps1, which only ever produces
    a folder distribution, but kept for parity with OraPulse's paths.py)."""
    candidate = app_dir()
    if (candidate / "public").exists():
        return candidate
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return candidate


def _local_appdata_root() -> Path:
    """%LOCALAPPDATA%\\AtlasStudio -- only ever consulted for a frozen
    build (see module docstring). Falls back to a `local_appdata` folder
    next to the .exe on the vanishingly unlikely chance LOCALAPPDATA isn't
    set (some locked-down service accounts), rather than crashing at
    import time over it."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else app_dir() / "local_appdata"
    return root / "AtlasStudio"


def _writable(dir_path: Path) -> bool:
    """Best-effort probe: can dir_path be created (if missing) and actually
    written to? Creates it eagerly on success -- that's fine, since the
    caller wants exactly that folder to exist when it's usable. Returns
    False (without raising) for anything from a plain missing-permission
    error to a locked-down ACL that lets mkdir succeed but blocks the
    actual file write."""
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        probe = dir_path / f".write_test_{os.getpid()}.tmp"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


if getattr(sys, "frozen", False):
    _portable_data = app_dir() / "data"
    if _writable(_portable_data):
        DATA_DIR = _portable_data
        LOG_DIR = app_dir() / "logs"
    else:
        _APPDATA_ROOT = _local_appdata_root()
        DATA_DIR = _APPDATA_ROOT / "data"
        LOG_DIR = _APPDATA_ROOT / "logs"  # reserved for future use; nothing writes here yet
else:
    DATA_DIR = app_dir() / "data"
    LOG_DIR = app_dir() / "logs"
