# Builds setup\<MSI_VERSION>\OraPulse_ODM_Setup_ver_<MSI_VERSION>.exe -- an
# Inno Setup EXE installer (Start Menu / optional Desktop shortcut, an
# uninstaller registered in "Add or Remove Programs", upgrade-in-place),
# installing to C:\Program Files (x86)\OraPulse_ODM.
#
# This is a *third* installer artifact alongside the two that already
# exist and are both left completely untouched by this script:
#   - build-installer.ps1 / installer.iss's own default behavior --
#     dist\OraPulse-Setup_ver_<VERSION>.exe, installing to
#     Program Files (x86)\OraPulse_Windows_x86.
#   - build-msi.ps1 -- setup\<MSI_VERSION>\OraPulse_ODM_Setup_ver_
#     <MSI_VERSION>.msi (WiX), installing to Program Files\OraPulse(ODM).
# This script reuses the *same* installer.iss (its behavior is unchanged
# for anyone still calling build-installer.ps1 the old way) but passes it
# three additional /D defines -- InstallDirName, OutputDir,
# OutputBaseFilename -- added to installer.iss specifically so this could
# be layered on without editing that file's actual [Setup] logic per
# variant.
#
# --- Versioning ---
# Uses MSI_VERSION (the same 4-part "installer release" version
# build-msi.ps1 already established -- e.g. 1.0.0.1, 1.0.0.2, ...) as this
# EXE's own AppVersion and as the setup\<version>\ folder name, so a given
# version number's folder can hold either installer format (or, in
# principle, both) for that same release. This is a different number from
# the underlying app's own VERSION file (1.NNNN scheme, e.g. 1.0063) --
# bumping one never requires bumping the other. To release a new version,
# edit MSI_VERSION by hand (same convention build-msi.ps1 already uses)
# before running this script again.
#
# Requires Inno Setup 6 (ISCC.exe) -- install once with:
#   winget install --id JRSoftware.InnoSetup -e
#
# Usage: .\build-installer-odm.ps1 [-SkipFolderBuild]
#   -SkipFolderBuild  Reuse whatever dist\OraPulse_ver_<VERSION>\ already
#                     exists instead of rebuilding it -- only for quickly
#                     iterating on the installer packaging itself; a real
#                     release build should always let this rebuild fresh.
# Output: setup\<MSI_VERSION>\OraPulse_ODM_Setup_ver_<MSI_VERSION>.exe
#         setup\<MSI_VERSION>\OraPulse_ODM_Setup_ver_<MSI_VERSION>.exe.sha256.txt

param(
    [switch]$SkipFolderBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

# --- 1. Locate Inno Setup 6 ---
Write-Step "Locating Inno Setup 6 (ISCC.exe)"

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "Inno Setup 6 (ISCC.exe) not found. Install it first with: winget install --id JRSoftware.InnoSetup -e"
}
Write-Host "Found ISCC at: $iscc"

# --- 2. Versions ---
Write-Step "Reading versions"

if (-not (Test-Path ".\VERSION")) { throw "VERSION file not found at repo root." }
$appVersion = (Get-Content ".\VERSION" -Raw).Trim()
Write-Host "Underlying app build (VERSION): $appVersion"

if (-not (Test-Path ".\MSI_VERSION")) { throw "MSI_VERSION file not found at repo root (expected e.g. 1.0.0.2)." }
$displayVersion = (Get-Content ".\MSI_VERSION" -Raw).Trim()
if ($displayVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw "MSI_VERSION must be exactly 4 numeric parts separated by dots (e.g. 1.0.0.2); found '$displayVersion'."
}
Write-Host "Installer release version (MSI_VERSION): $displayVersion"

$exeName = "OraPulse_ODM_Setup_ver_$displayVersion.exe"

# --- 3. Fresh folder build ---
if ($SkipFolderBuild) {
    Write-Step "Skipping build-folder.ps1 (-SkipFolderBuild) -- reusing existing dist\OraPulse_ver_$appVersion"
} else {
    Write-Step "Building fresh portable folder distribution (build-folder.ps1)"
    .\build-folder.ps1
}
$sourceDir = ".\dist\OraPulse_ver_$appVersion"
if (-not (Test-Path $sourceDir)) {
    throw "Expected folder build not found at $sourceDir -- check VERSION or run build-folder.ps1 first."
}
$sourceDirFull = (Resolve-Path $sourceDir).Path

# --- 4. Output location ---
$setupRoot = ".\setup\$displayVersion"
New-Item -ItemType Directory -Force -Path $setupRoot | Out-Null
$setupRootFull = (Resolve-Path $setupRoot).Path

# --- 5. Compile with Inno Setup ---
Write-Step "Compiling installer with ISCC.exe"

Remove-Item (Join-Path $setupRootFull $exeName) -Force -ErrorAction SilentlyContinue
& $iscc "installer.iss" `
    "/DMyAppVersion=$displayVersion" `
    "/DSourceDir=$sourceDirFull" `
    "/DInstallDirName=OraPulse_ODM" `
    "/DOutputDir=$setupRootFull" `
    "/DOutputBaseFilename=OraPulse_ODM_Setup_ver_$displayVersion"
if ($LASTEXITCODE -ne 0) { throw "ISCC.exe failed (exit $LASTEXITCODE)." }

$exePath = Join-Path $setupRootFull $exeName
if (-not (Test-Path $exePath)) { throw "Expected output not found at $exePath." }
$exeFull = (Resolve-Path $exePath).Path
Write-Host "Built installer: $exeFull"

# --- 6. Hash ---
Write-Step "Computing SHA-256 hash"

$exeHash = (Get-FileHash $exeFull -Algorithm SHA256).Hash
Write-Host "EXE SHA-256: $exeHash"
"$exeHash  $exeName" | Out-File -FilePath "$exeFull.sha256.txt" -Encoding ascii

# --- 7. Summary ---
Write-Step "Summary"
Write-Host "Installer:       $exeFull"
Write-Host "SHA-256:         $exeHash"
Write-Host "Install path:    C:\Program Files (x86)\OraPulse_ODM"
Write-Host "App build:       $appVersion  (installer release: $displayVersion)"
Write-Host ""
Write-Host "NOT done by this script (changes the system -- run only with your own approval):"
Write-Host "  & `"$exeFull`"          (attended install)"
Write-Host "  & `"$exeFull`" /VERYSILENT   (silent install)"
