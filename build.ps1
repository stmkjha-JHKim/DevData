# Builds dist\OraPulse_ver_<VERSION>.exe -- a single standalone executable
# that runs on a machine with no Python installed. See OraPulse.spec for
# what's bundled.
#
# Usage: .\build.ps1
# Output: dist\OraPulse_ver_<VERSION>.exe -- e.g.
# dist\OraPulse_ver_1.0002.exe. Copy that one file anywhere and run it.
# Named after VERSION (rather than always dist\OraPulse.exe) for the same
# reason build-folder.ps1's output folder is -- see its own comment on
# that -- even though a single file has never actually gotten stuck the
# way that folder did; this just keeps the two build scripts' naming
# consistent.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv and installing dependencies..."
    python -m venv venv
    .\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .\venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller --quiet
}

.\venv\Scripts\python.exe -m PyInstaller OraPulse.spec --noconfirm

$version = (Get-Content ".\VERSION" -Raw).Trim()
$finalExe = ".\dist\OraPulse_ver_$version.exe"
Move-Item ".\dist\OraPulse.exe" $finalExe -Force

# main.py reads VERSION from next to the .exe (app_dir()) -- it isn't
# bundled as PyInstaller data since that would land inside the onefile
# extraction temp dir, not somewhere persistent/discoverable at a fixed
# relative path across both the onefile and folder distributions.
Copy-Item ".\VERSION" ".\dist\VERSION" -Force

$finalExeFull = (Resolve-Path $finalExe).Path
Write-Host ""
Write-Host "Built: $finalExeFull"
