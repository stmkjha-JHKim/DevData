# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for OraPulse Backup -- produces a single
# dist\OraPulseBackup.exe bundling the Python runtime, all dependencies
# (FastAPI, uvicorn, oracledb, SQLAlchemy, APScheduler, cryptography) and
# the public/ frontend, so it runs on a machine with no Python installed.
# Rebuild with: .\build.ps1 (which also handles the dist\<version>\
# folder and version bump -- see that script's own comment).
#
# Same shape as OraPulse's own OraPulse.spec, minus the tray-icon/browser-
# launch pieces this project doesn't have (yet -- see README).
#
# public/ is bundled as read-only data -- extracted at runtime to
# sys._MEIPASS, which paths.py's resource_dir() resolves to. data/
# (registered DBs, policy/history SQLite) is deliberately NOT bundled --
# it's created next to the .exe at runtime instead (paths.py's app_dir()),
# since it has to persist across runs, unlike sys._MEIPASS which is wiped
# after every launch.
#
# collect_all('cryptography') is required, not optional: python-oracledb's
# thin mode imports cryptography.x509 lazily from inside its own connect
# code path, which PyInstaller's static import scan doesn't see (same
# issue OraPulse.spec documents hitting) -- and this app's own
# crypto_store.py uses cryptography.hazmat directly too.

from PyInstaller.utils.hooks import collect_all

crypto_datas, crypto_binaries, crypto_hiddenimports = collect_all("cryptography")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=crypto_binaries,
    datas=[('public', 'public')] + crypto_datas,
    hiddenimports=crypto_hiddenimports,
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
    name='OraPulseBackup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # A visible console window for now (unlike OraPulse's tray-only build)
    # -- there's no system tray icon or auto-opened browser yet, so the
    # console showing "Uvicorn running on http://127.0.0.1:PORT" is
    # currently the only way to see the app started and find its address.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='favicon.ico',
)
