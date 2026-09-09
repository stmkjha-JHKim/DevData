# Builds demo\OraPulse_Demo_ver_<version>\ -- the exact same folder
# distribution build-folder.ps1 produces, tagged with the *next* version
# number (current VERSION + 1) without ever touching the real VERSION
# file, plus a DEMO marker file dropped next to the exe.
#
# That marker is all backend/core.py's IS_DEMO_MODE checks for at startup
# -- its mere presence flips the running app into demo mode, which (see
# app-shell.js's applyDemoModeUi() and switchTab(), and the server-side
# guards in routes_session.py/routes_table_stats.py/routes_report.py/
# routes_connect.py) disables:
#   - the Current Session List's right-click/long-press context menu
#     (both "View Running Query" and "Kill Session (IMMEDIATE)") entirely
#   - the Table Statistics Collection card's gather-stats actions (the
#     per-row context menu item and the "Gather Statistics for Selected"
#     batch button)
#   - every tab except DashBoard and Ops
#   - the Report button (Weekly DB Health Report generation)
#   - the Scheduler/Job Failures and Account Security cards (hidden
#     outright, query skipped server-side too)
#   - Alert Log Analysis (card stays, but shows a "not supported in the
#     demo version" note instead of actually querying V$DIAG_ALERT_EXT)
#   - four Ops tab cards: TEMP Tablespace Usage, TEMP Usage by Session,
#     Datafile Autoextend Status, Tablespace I/O Stats (hidden outright,
#     query skipped server-side too)
#   - Favorites on the connect screen, capped at 1 saved entry
# A normal build.ps1/build-folder.ps1/build-installer.ps1 run never
# creates this file, so the regular release build is never affected.
#
# A demo build isn't an officially numbered release, so it doesn't consume
# a version number the way a normal build does -- the real VERSION file on
# disk is restored immediately after, even if the build fails partway.
#
# Usage: .\build-demo.ps1
# Output: demo\OraPulse_Demo_ver_<version>\ -- e.g.
# demo\OraPulse_Demo_ver_1.0051\, if the real VERSION file currently reads
# 1.0050.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$originalVersion = Get-Content ".\VERSION" -Raw
$currentVersion = $originalVersion.Trim()
if ($currentVersion -notmatch '^(\d+)\.(\d+)$') {
    throw "Unexpected VERSION format: '$currentVersion' (expected e.g. 1.0050)"
}
$major = $Matches[1]
$minorWidth = $Matches[2].Length
$nextMinor = ([int]$Matches[2] + 1).ToString().PadLeft($minorWidth, '0')
$demoVersion = "$major.$nextMinor"

Write-Host "Current VERSION: $currentVersion -- building demo as $demoVersion (real VERSION file left untouched)"

# build-folder.ps1 always reads VERSION fresh off disk, so this is the only
# way to hand it a different version number without duplicating its whole
# PyInstaller build step here -- restored in `finally` no matter what
# happens, so a failed/interrupted demo build can never leave the real
# VERSION file pointing at a version that was never actually released.
Set-Content ".\VERSION" $demoVersion -NoNewline
try {
    .\build-folder.ps1
} finally {
    Set-Content ".\VERSION" $originalVersion -NoNewline
}

$builtDir = ".\dist\OraPulse_ver_$demoVersion"
if (-not (Test-Path $builtDir)) {
    throw "Expected build output not found at $builtDir"
}

New-Item -ItemType Directory -Force -Path ".\demo" | Out-Null
$demoDir = ".\demo\OraPulse_Demo_ver_$demoVersion"
Remove-Item $demoDir -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $demoDir) {
    $demoDir = "$demoDir`_$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "WARNING: $($demoDir -replace '_\d{14}$', '') already exists and could not be replaced. Using $demoDir instead."
}
Move-Item $builtDir $demoDir

# The marker backend/core.py's IS_DEMO_MODE looks for -- see this script's
# own top-of-file comment for exactly what it disables at runtime.
New-Item -ItemType File -Path "$demoDir\DEMO" -Force | Out-Null

$demoDirFull = (Resolve-Path $demoDir).Path
Write-Host ""
Write-Host "Built demo: $demoDirFull\ (run $demoDirFull\OraPulse.exe)"
