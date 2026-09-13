# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for AtlasStudio's FOLDER distribution: produces
# dist/AtlasStudio/AtlasStudio.exe plus a dist/AtlasStudio/lib/ folder
# holding the Python runtime and dependencies -- the "installed program"
# look (a folder with an .exe and its supporting files) rather than one
# single opaque .exe. Single-file (--onefile) and installer (MSI/Inno)
# packaging are out of scope for this build -- see build-folder.ps1.
#
# Adapted from OraPulse's OraPulse-Folder.spec
# (D:\STMKJHA\00.Git\01.OraPulse\OraPulse-Folder.spec), trimmed:
# AtlasStudio has no oracledb/cryptography dependency, so this doesn't
# need collect_all('cryptography') or any DB-driver hidden imports.
#
# contents_directory='lib' renames PyInstaller's default '_internal' to
# 'lib'. That's the only reshaping PyInstaller itself supports: its
# COLLECT step hard-rejects any TOC destination containing '..', so
# public/ can't be pulled out to the top level *during* this build step --
# build-folder.ps1 does that relocation as a POST-build step instead (a
# plain file move after PyInstaller is done; safe because Windows' DLL
# search order always includes the directory the .exe loaded from, and
# public/ is plain data read via paths.py's resource_dir(), not resolved
# through Python's import system at all).
#
# Rebuild with: .\build-folder.ps1 (running the .spec directly with
# `python -m PyInstaller` skips that post-build relocation).
#
# pystray picks its backend at runtime via `from . import _win32 as
# backend` inside a function, based on sys.platform -- PyInstaller's
# static import scan can't see that, so the actual backend module has to
# be listed explicitly or the packaged .exe fails with "this platform is
# not supported" the moment tray.py runs.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('public', 'public')],
    hiddenimports=['pystray._win32'],
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
    name='AtlasStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # No console window: the app runs as a system tray icon instead (see
    # tray.py) -- exit is via the tray icon's own "종료" menu item, not
    # closing/Ctrl+C on a console.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='public/favicon.ico',
    # NOTE: COLLECT (below) reads its own contents_directory straight off
    # this EXE instance's attribute -- passing it to COLLECT()'s kwargs
    # instead is silently ignored.
    contents_directory='lib',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AtlasStudio',
)
