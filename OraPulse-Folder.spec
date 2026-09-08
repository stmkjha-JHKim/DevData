# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for OraPulse's FOLDER distribution: produces
# dist/OraPulse/OraPulse.exe plus a dist/OraPulse/lib/ folder holding the
# Python runtime and most dependencies -- the "installed program" look
# (a folder with an .exe and its supporting files) rather than one single
# opaque .exe. Functionally identical to OraPulse.spec (same Analysis, same
# app code) -- this only changes how the build is packaged (COLLECT/onedir
# vs. EXE/onefile).
#
# contents_directory='lib' below renames PyInstaller's default '_internal'
# to 'lib'. That's the only reshaping PyInstaller itself supports: its
# COLLECT step hard-rejects any TOC destination containing '..' (tried and
# confirmed -- it raises "attempting to store file outside of the dist
# directory" and aborts the build), so public/, oracledb/, and a handful of
# core DLLs can't be pulled out to the top level *during* this build step.
# build-folder.ps1 does that relocation as a POST-build step instead (plain
# file moves after PyInstaller is done) -- see the comments there for why
# each piece is safe to move (Windows' DLL search order always includes the
# directory the .exe loaded from, for every LoadLibrary call in the
# process, not just the .exe's own direct dependencies; oracledb/ is
# additionally made importable again via a sys.path entry added in
# paths.py, since Python's import system needs sys.path to find it wherever
# it physically ends up).
#
# Rebuild with: .\build-folder.ps1 (running the .spec directly with
# `python -m PyInstaller` skips that post-build relocation).
#
# To distribute: zip the whole dist/OraPulse/ folder and hand that over --
# the .exe alone won't run without its sibling files.
#
# Same data/ placement as the single-exe build: created next to OraPulse.exe
# at runtime -- see paths.py's app_dir(), which resolves off sys.executable's
# own directory regardless of onefile vs. onedir packaging or this
# relocation.
#
# See OraPulse.spec for why collect_all('cryptography') is required (not
# just the bundled hook) -- same reasoning applies here unchanged.

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
    [],
    exclude_binaries=True,
    name='OraPulse',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    # NOTE: COLLECT (below) reads its own contents_directory straight off
    # this EXE instance's attribute -- passing it to COLLECT()'s kwargs
    # instead (as an earlier version of this spec did) is silently ignored.
    contents_directory='lib',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OraPulse',
)
