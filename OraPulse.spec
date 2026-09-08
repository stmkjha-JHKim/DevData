# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for OraPulse -- produces a single dist/OraPulse.exe
# that bundles the Python runtime, all dependencies (FastAPI, uvicorn,
# oracledb, cryptography), and the public/ frontend, so it runs on a
# machine with no Python installed. Rebuild with: .\build.ps1 (or directly:
# venv\Scripts\python.exe -m PyInstaller OraPulse.spec).
#
# public/ is bundled as read-only data (datas=[('public','public')]) --
# extracted at runtime to sys._MEIPASS, which paths.py's resource_dir()
# resolves to. data/ (favorites, snapshot history) is deliberately NOT
# bundled here -- it's created next to the .exe at runtime instead (see
# paths.py's app_dir()), since it has to persist across runs and reinstalls,
# unlike sys._MEIPASS which is wiped after every launch.
#
# collect_all('cryptography') is required, not optional: python-oracledb's
# thin mode imports cryptography.x509 (and other submodules) lazily, from
# inside its own connect code path -- PyInstaller's static import scan
# doesn't see that reference, and the bundled_cryptography hook alone
# wasn't enough (confirmed by hitting "DPY-3016: ... cannot import name
# x509" when actually connecting from the packaged .exe, even though the
# app itself imports cryptography directly and that part worked fine).
# collect_all() forces every submodule/binary/data file cryptography ships
# into the bundle regardless of what static analysis can trace.

from PyInstaller.utils.hooks import collect_all

crypto_datas, crypto_binaries, crypto_hiddenimports = collect_all("cryptography")

# pystray picks its backend at runtime via `from . import _win32 as backend`
# inside a function (see pystray/__init__.py's backend()), based on
# sys.platform -- PyInstaller's static import scan can't see that, so the
# actual backend module has to be listed explicitly or the packaged .exe
# fails with "this platform is not supported" the moment tray.py runs.
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=crypto_binaries,
    datas=[('public', 'public')] + crypto_datas,
    hiddenimports=crypto_hiddenimports + ['pystray._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OraPulse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # No console window: the app now runs as a system tray icon instead
    # (see tray.py) -- Exit is via the tray icon's own menu, not
    # closing/Ctrl+C on a console.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='favicon.ico',
)
