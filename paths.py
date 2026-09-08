"""paths.py -- shared path helpers so persistent data and bundled static
assets resolve correctly both when running from source (python main.py)
and when running as a PyInstaller-frozen .exe.

PyInstaller's --onefile mode extracts the whole app into a fresh temporary
directory (sys._MEIPASS) on every launch and discards it on exit --
__file__-relative paths inside a frozen build point there, not somewhere
persistent. So:

- Persistent, read/write data (data/favorites.enc, data/.favorites-key,
  data/snapshot-history.jsonl, data/.snapshot-key) must live next to the
  actual .exe, mirroring exactly where data/ already lives relative to
  main.py when running from source -- see app_dir()/DATA_DIR.
- Bundled, read-only resources (public/*.html, favicon.svg) come from
  wherever PyInstaller actually extracted them to -- see resource_dir().
"""

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory the persistent data/ folder lives under: next to the
    .exe when frozen, next to this source file's project root otherwise."""
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


DATA_DIR = app_dir() / "data"
