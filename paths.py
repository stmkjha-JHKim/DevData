"""paths.py -- where persistent data and bundled static assets live.

Same split OraPulse's own paths.py uses, trimmed to what this project
needs (no report/log folders). PyInstaller's --onefile mode extracts the
whole app into a fresh temporary directory (sys._MEIPASS) on every launch
and discards it on exit -- a plain `__file__`-relative path inside a
frozen build points there, not somewhere persistent, which is exactly the
bug this module exists to avoid: registered DBs, policies and job history
would otherwise vanish every time the packaged .exe restarts.

- Bundled, read-only resources (public/*.html/css/js) come from wherever
  PyInstaller actually extracted them to -- see resource_dir().
- Persistent, read/write data (data/registered_dbs.enc, data/metadata.db)
  lives next to the .exe (app_dir()) whenever that's actually writable --
  a portable/unzipped copy, which is the only distribution shape build.ps1
  produces today. Falls back to %LOCALAPPDATA%\\OraPulseBackup only if
  that ever isn't writable (e.g. a future installer places the .exe under
  Program Files) -- decided by actually probing for write access, not by
  guessing how the build was installed.
- Running from source (python main.py) keeps the old next-to-main.py
  data/ folder, same as always.
"""

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "OraPulseBackup"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    candidate = app_dir()
    if (candidate / "public").exists():
        return candidate
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return candidate


def _local_appdata_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else app_dir() / "local_appdata"
    return root / APP_NAME


def _writable(dir_path: Path) -> bool:
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        probe = dir_path / f".write_test_{os.getpid()}.tmp"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


def _migrate_legacy_data(legacy_dir: Path, new_dir: Path) -> None:
    if new_dir.exists() or not legacy_dir.exists():
        return
    try:
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_dir), str(new_dir))
        print(f"[paths] Migrated existing '{legacy_dir}' to '{new_dir}'.")
    except OSError as err:
        print(f"[paths] Could not migrate '{legacy_dir}' to '{new_dir}': {err}")


APP_DIR = app_dir()
PUBLIC_DIR = resource_dir() / "public"

if getattr(sys, "frozen", False):
    _portable_data = app_dir() / "data"
    if _writable(_portable_data):
        DATA_DIR = _portable_data
    else:
        DATA_DIR = _local_appdata_root() / "data"
        _migrate_legacy_data(app_dir() / "data", DATA_DIR)
else:
    DATA_DIR = app_dir() / "data"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
