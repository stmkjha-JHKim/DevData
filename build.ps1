# Builds dist\<VERSION>\OraPulseBackup.exe -- a single standalone
# executable that runs on a machine with no Python installed. See
# OraPulseBackup.spec for what's bundled.
#
# Usage: .\build.ps1
#
# Versioning: the VERSION file (4-part, e.g. "1.0.0.1") holds the version
# this run is ABOUT to build. Each successful build:
#   1. creates dist\ if it doesn't exist yet,
#   2. builds into dist\<VERSION>\OraPulseBackup.exe (a fresh, version-
#      named folder every time -- old builds are never touched/overwritten),
#   3. bumps VERSION's last segment by 1 and writes it back to .\VERSION,
#      so the *next* run of this script builds the next version
#      automatically -- you never have to edit VERSION by hand.
#
# First run (VERSION starts at 1.0.0.1, as set up for this project) builds
# dist\1.0.0.1\OraPulseBackup.exe and leaves VERSION at 1.0.0.2 for next
# time; the run after that builds dist\1.0.0.2\, and so on.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv and installing dependencies..."
    python -m venv venv
    .\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .\venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller --quiet
}

if (-not (Test-Path ".\dist")) {
    New-Item -ItemType Directory -Path ".\dist" | Out-Null
}

if (-not (Test-Path ".\VERSION")) {
    "1.0.0.1" | Out-File -FilePath ".\VERSION" -Encoding ascii -NoNewline
}
$version = (Get-Content ".\VERSION" -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw "VERSION must be exactly 4 numeric parts separated by dots (e.g. 1.0.0.1); found '$version'."
}

$versionDir = ".\dist\$version"
if (Test-Path $versionDir) {
    Write-Host "WARNING: dist\$version already exists -- rebuilding it (previous contents will be replaced)."
    Remove-Item $versionDir -Recurse -Force
}
New-Item -ItemType Directory -Path $versionDir | Out-Null

.\venv\Scripts\python.exe -m PyInstaller OraPulseBackup.spec --noconfirm --clean

Move-Item ".\dist\OraPulseBackup.exe" "$versionDir\OraPulseBackup.exe" -Force

# main.py reads VERSION from next to the .exe (paths.py's app_dir()) --
# it isn't bundled as PyInstaller data since that would land inside the
# onefile extraction temp dir, not somewhere persistent/discoverable at a
# fixed relative path.
Copy-Item ".\VERSION" "$versionDir\VERSION" -Force

# Bump the last segment for the *next* build. This build's own
# dist\<version>\ folder (and the VERSION copy just written into it) keeps
# the version it was actually built with.
$parts = $version.Split('.')
$parts[3] = [int]$parts[3] + 1
$nextVersion = $parts -join '.'
$nextVersion | Out-File -FilePath ".\VERSION" -Encoding ascii -NoNewline

$finalExeFull = (Resolve-Path "$versionDir\OraPulseBackup.exe").Path
Write-Host ""
Write-Host "Built: $finalExeFull"
Write-Host "Next build will produce version $nextVersion (dist\$nextVersion\)."
