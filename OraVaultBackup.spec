# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for OraVault Backup -- produces dist\OraVaultBackup\
# (a folder: OraVaultBackup.exe plus its DLLs/data alongside it), not a
# single .exe. This is a onedir build, not onefile -- onefile re-extracts
# the entire bundle (Python runtime, FastAPI/uvicorn/oracledb/SQLAlchemy/
# APScheduler/cryptography, public/) into a fresh %TEMP% directory on
# *every single launch*, which was the actual cause of the slow startup
# this replaces. onedir runs directly out of its own folder instead, so
# there's nothing to unpack after the first build. build.ps1 already
# treats dist\<version>\ as "copy this whole folder to deploy it", so this
# doesn't change the distribution story, only what's inside that folder
# (see that script's own comment for how it moves this folder's contents
# into dist\<version>\).
#
# UPX is off (upx=False) for the same reason as onefile: it shrinks the
# DLLs on disk but costs decompression time on every process start -- the
# wrong trade when the goal is a faster launch, not a smaller download.
# (Moot on this build machine specifically -- UPX isn't installed here, so
# upx=True was already a silent no-op -- but explicit is correct either way.)
#
# Windowed build (console=False): no console window pops up when the .exe
# runs. main.py compensates for the two things that depended on a console
# existing -- it redirects sys.stdout/stderr to os.devnull (PyInstaller
# sets them to None in windowed mode, which would crash on first log/print
# line) and opens the default browser itself instead of the user reading
# the address off the console.
#
# public/ is bundled as read-only data, placed directly next to the .exe
# by COLLECT below (not extracted to sys._MEIPASS on every launch the way
# onefile did) -- paths.py's resource_dir() already checks for a `public`
# folder next to the exe first, so it needs no changes for this. data/
# (registered DBs, policy/history SQLite) still isn't bundled -- it's
# created next to the .exe at runtime instead (paths.py's app_dir()),
# since it has to persist across runs and restarts.
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
    [],
    exclude_binaries=True,
    name='OraVaultBackup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='favicon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='OraVaultBackup',
)
