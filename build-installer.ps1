# Builds dist\OraPulse-Setup_ver_<VERSION>.exe -- a normal Windows
# installer (Start Menu shortcut, optional Desktop icon, an entry in "Add
# or Remove Programs" with a working uninstaller) wrapping the folder
# distribution that build-folder.ps1 produces. See installer.iss for the
# actual Inno Setup script -- installs to Program Files (x86) and
# therefore requires admin/UAC.
#
# Requires Inno Setup 6 (ISCC.exe) -- install once with:
#   winget install --id JRSoftware.InnoSetup -e
#
# Usage: .\build-installer.ps1
# Output: dist\OraPulse-Setup_ver_<VERSION>.exe

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Inno Setup 6 (ISCC.exe) not found. Install it first with: winget install --id JRSoftware.InnoSetup -e"
}

# Always rebuild the folder distribution first so the installer never
# packages stale binaries left over from a previous version.
.\build-folder.ps1

$version = (Get-Content ".\VERSION" -Raw).Trim()
$sourceDir = (Resolve-Path ".\dist\OraPulse_ver_$version").Path

& $iscc "installer.iss" "/DMyAppVersion=$version" "/DSourceDir=$sourceDir"

$finalExeFull = (Resolve-Path ".\dist\OraPulse-Setup_ver_$version.exe").Path
Write-Host ""
Write-Host "Built: $finalExeFull"
