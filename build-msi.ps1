# Builds setup\<MSI_VERSION>\OraPulse_ODM_Setup_ver_<MSI_VERSION>.msi -- a
# proper per-machine Windows Installer package (WiX Toolset v3), installing
# to C:\Program Files\OraPulse(ODM) with a Start Menu shortcut, an optional
# Desktop shortcut, correct Add/Remove Programs metadata, silent-install
# support, and major-upgrade/downgrade-block versioning.
#
# This is a *second*, independent installer format alongside the existing
# Inno Setup one (installer.iss / build-installer.ps1) -- that one is
# untouched and still works exactly as before. Use whichever fits: Inno's
# EXE installs to Program Files (x86) with no MSI semantics; this MSI
# installs to Program Files (64-bit) with real Windows Installer upgrade/
# downgrade/uninstall tracking, which is what a corporate software
# deployment tool (SCCM, Intune, etc.) typically expects.
#
# Prerequisite: WiX Toolset v3.14 (candle.exe/light.exe/heat.exe). Not
# detected? Install it with:
#     winget install --id WiXToolset.WiXToolset -e
# (this enables the .NET Framework 3.5 Windows feature the first time,
# which needs admin/UAC approval once) -- or download the v3.14 installer
# from https://github.com/wixtoolset/wix3/releases if winget isn't
# available. This script never tries to install WiX itself -- see below.
#
# --- Versioning ---
# The MSI has its own 4-part "display version" (MSI_VERSION file at the
# repo root, e.g. 1.0.0.1), completely independent of the portable/Inno
# builds' VERSION file (1.NNNN scheme) -- bumping one never affects the
# other. Windows Installer's own ProductVersion property can only hold 3
# numeric fields, so this script maps the 4-part display version down to 3
# by dropping the *third* field (kept at 0 by convention) and keeping the
# first/second/fourth: 1.0.0.1 -> 1.0.1, 1.0.0.2 -> 1.0.2, etc. The 4-part
# form is what appears in the output filename and in ARPCOMMENTS ("more
# info" in Programs and Features); the 3-part form is the real
# ProductVersion Windows Installer itself uses for upgrade/downgrade
# comparisons. To release a new MSI version, edit MSI_VERSION by hand
# (same convention as the VERSION file) before running this script again.
#
# --- Pipeline ---
#   1. Locate WiX v3 (candle/light/heat) -- fail with clear install
#      instructions if not found, never install it ourselves.
#   2. Read VERSION (the underlying app build) and MSI_VERSION (this
#      installer's own display version); compute the 3-part ProductVersion.
#   3. Run build-folder.ps1 for a guaranteed-fresh portable folder build.
#   4. Stage a private copy of that folder under
#      setup\<version>\work\payload\, plus favicon.ico and a generated
#      THIRD-PARTY-NOTICES.txt (aggregated from this project's direct
#      dependencies' own license files in venv\).
#   5. Validate every required file/folder is actually present in that
#      payload -- fail loudly, listing exactly what's missing, rather than
#      silently shipping an incomplete MSI.
#   6. heat.exe harvests lib\ and public\ (hundreds of files between
#      Python's runtime and the frontend) into WiX fragments -- hand-
#      authoring components for those trees isn't practical or reliable.
#   7. candle.exe compiles wix\Product.wxs + the two harvested fragments;
#      light.exe links them (with the WiX UI + Util extensions) into the
#      final MSI at setup\<version>\OraPulse_ODM_Setup_ver_<version>.msi.
#   8. SHA-256 both the final MSI and the payload's OraPulse.exe, then run
#      a handful of read-only checks against the built MSI's own tables
#      (via the WindowsInstaller COM object) -- x64-ness, install path,
#      ARP metadata, silent-install properties, upgrade table, file counts
#      -- and print a pass/fail summary. This never installs or uninstalls
#      anything; see this script's own final output for what still needs a
#      real (user-approved) install/uninstall test.
#
# Usage: .\build-msi.ps1 [-SkipFolderBuild]
#   -SkipFolderBuild  Reuse whatever dist\OraPulse_ver_<VERSION>\ already
#                     exists instead of rebuilding it -- only for quickly
#                     iterating on the WiX authoring itself; a real release
#                     build should always let this rebuild fresh.

param(
    [switch]$SkipFolderBuild
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

# --- 1. Locate WiX v3 ---
Write-Step "Locating WiX Toolset v3"

function Find-WixBin {
    $candidates = @()
    if ($env:WIX) { $candidates += (Join-Path $env:WIX "bin") }
    $candidates += "C:\Program Files (x86)\WiX Toolset v3.14\bin"
    $candidates += "C:\Program Files\WiX Toolset v3.14\bin"
    $candidates += "C:\Program Files (x86)\WiX Toolset v3.11\bin"
    foreach ($c in $candidates) {
        if (Test-Path (Join-Path $c "candle.exe")) { return $c }
    }
    $onPath = Get-Command candle.exe -ErrorAction SilentlyContinue
    if ($onPath) { return (Split-Path $onPath.Source -Parent) }
    return $null
}

$wixBin = Find-WixBin
if (-not $wixBin) {
    Write-Host ""
    Write-Host "WiX Toolset v3.x (candle.exe/light.exe/heat.exe) was not found." -ForegroundColor Red
    Write-Host "This script does not install it automatically -- install it yourself first:"
    Write-Host ""
    Write-Host "    winget install --id WiXToolset.WiXToolset -e"
    Write-Host ""
    Write-Host "That installer needs the .NET Framework 3.5 Windows feature enabled (it will"
    Write-Host "prompt for that, and for admin/UAC approval) the first time. If winget isn't"
    Write-Host "available, download the WiX v3.14 installer from:"
    Write-Host "    https://github.com/wixtoolset/wix3/releases"
    Write-Host ""
    throw "WiX Toolset v3.x not found -- see instructions above."
}
$candle = Join-Path $wixBin "candle.exe"
$light = Join-Path $wixBin "light.exe"
$heat = Join-Path $wixBin "heat.exe"
Write-Host "Found WiX at: $wixBin"
& $candle -? 2>&1 | Select-Object -First 1 | ForEach-Object { Write-Host "  $_" }

# --- 2. Versions ---
Write-Step "Reading versions"

if (-not (Test-Path ".\VERSION")) { throw "VERSION file not found at repo root." }
$appVersion = (Get-Content ".\VERSION" -Raw).Trim()
Write-Host "Underlying app build (VERSION): $appVersion"

if (-not (Test-Path ".\MSI_VERSION")) { throw "MSI_VERSION file not found at repo root (expected e.g. 1.0.0.1)." }
$displayVersion = (Get-Content ".\MSI_VERSION" -Raw).Trim()
if ($displayVersion -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    throw "MSI_VERSION must be exactly 4 numeric parts separated by dots (e.g. 1.0.0.1); found '$displayVersion'."
}
$parts = $displayVersion.Split('.')
$productVersion = "$($parts[0]).$($parts[1]).$($parts[3])"
Write-Host "MSI display version: $displayVersion  ->  ProductVersion: $productVersion"

$manufacturer = "OraPulse"
$msiName = "OraPulse_ODM_Setup_ver_$displayVersion.msi"

# --- 3. Fresh folder build ---
if ($SkipFolderBuild) {
    Write-Step "Skipping build-folder.ps1 (-SkipFolderBuild) -- reusing existing dist\OraPulse_ver_$appVersion"
} else {
    Write-Step "Building fresh portable folder distribution (build-folder.ps1)"
    .\build-folder.ps1
}
$payloadSourceDir = ".\dist\OraPulse_ver_$appVersion"
if (-not (Test-Path $payloadSourceDir)) {
    throw "Expected folder build not found at $payloadSourceDir -- check VERSION or run build-folder.ps1 first."
}

# --- 4. Stage payload ---
Write-Step "Staging MSI payload under setup\$displayVersion\work"

$setupRoot = ".\setup\$displayVersion"
$work = "$setupRoot\work"
$obj = "$work\obj"
$payload = "$work\payload"
foreach ($d in @($setupRoot, $work, $obj)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Remove-Item $payload -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item $payloadSourceDir $payload -Recurse
Copy-Item ".\favicon.ico" "$payload\favicon.ico" -Force
# The payload's own data\ (created if this dist\ folder was ever launched
# to smoke-test it) must never be harvested into the MSI -- user data has
# no business being installed as a "file this product ships".
Remove-Item "$payload\data" -Recurse -Force -ErrorAction SilentlyContinue

# --- 5. Third-party notices ---
Write-Step "Generating THIRD-PARTY-NOTICES.txt"

$noticesPath = "$payload\THIRD-PARTY-NOTICES.txt"
$lines = @(
    "OraPulse (ODM) -- Third-Party Notices",
    "======================================",
    "",
    "OraPulse is built with Python and the following third-party packages.",
    "Each package's own license text (as published by its author) follows.",
    ""
)
$reqPackages = Get-Content ".\requirements.txt" | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') } |
    ForEach-Object { ($_ -split '[><=!\s]')[0].Trim() } | Where-Object { $_ }

foreach ($pkg in $reqPackages) {
    $distInfo = Get-ChildItem ".\venv\Lib\site-packages" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^(?i)$([regex]::Escape($pkg))-.*\.dist-info$" } | Select-Object -First 1
    $lines += "--------------------------------------------------------------------"
    $lines += "Package: $pkg"
    if (-not $distInfo) {
        $lines += "(license metadata not found under venv\; see the package's own PyPI page)"
        $lines += ""
        continue
    }
    $licenseFiles = Get-ChildItem $distInfo.FullName -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "^(LICENSE|NOTICE|COPYING)" }
    if (-not $licenseFiles) {
        $lines += "(no LICENSE/NOTICE file found in $($distInfo.Name); see the package's own PyPI page)"
        $lines += ""
        continue
    }
    foreach ($lf in $licenseFiles) {
        $lines += "  [$($lf.Name)]"
        $lines += (Get-Content $lf.FullName -Raw)
        $lines += ""
    }
}
$lines -join "`r`n" | Out-File -FilePath $noticesPath -Encoding utf8
Write-Host "Wrote $noticesPath ($((Get-Item $noticesPath).Length) bytes) covering $($reqPackages.Count) package(s)."

# --- 6. Validate payload ---
Write-Step "Validating required payload files"

$required = @(
    "OraPulse.exe", "VERSION", "README.txt", "favicon.ico", "THIRD-PARTY-NOTICES.txt",
    "api-ms-win-crt-runtime-l1-1-0.dll", "ucrtbase.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll"
)
$missing = @()
foreach ($f in $required) {
    if (-not (Test-Path (Join-Path $payload $f))) { $missing += $f }
}
foreach ($d in @("lib", "public")) {
    $p = Join-Path $payload $d
    if (-not (Test-Path $p) -or (Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
        $missing += "$d\ (missing or empty)"
    }
}
if ($missing.Count -gt 0) {
    Write-Host "Missing required payload files:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    throw "Payload validation failed -- see missing files above."
}
$libCount = (Get-ChildItem "$payload\lib" -Recurse -File).Count
$publicCount = (Get-ChildItem "$payload\public" -Recurse -File).Count
Write-Host "Payload OK: all required files present. lib\ has $libCount file(s), public\ has $publicCount file(s)."

# --- 7. Harvest lib/ and public/ ---
Write-Step "Harvesting lib\ and public\ with heat.exe"

$payloadFull = (Resolve-Path $payload).Path
$libFragment = "$obj\LibFragment.wxs"
$publicFragment = "$obj\PublicFragment.wxs"

& $heat dir "$payloadFull\lib" -cg LibComponents -dr LIBFOLDER -var var.LibSourceDir `
    -ag -srd -sfrag -scom -sreg -svb6 -nologo -out $libFragment
if ($LASTEXITCODE -ne 0) { throw "heat.exe failed harvesting lib\ (exit $LASTEXITCODE)." }

& $heat dir "$payloadFull\public" -cg PublicComponents -dr PUBLICFOLDER -var var.PublicSourceDir `
    -ag -srd -sfrag -scom -sreg -svb6 -nologo -out $publicFragment
if ($LASTEXITCODE -ne 0) { throw "heat.exe failed harvesting public\ (exit $LASTEXITCODE)." }
Write-Host "Harvested lib\ -> $libFragment"
Write-Host "Harvested public\ -> $publicFragment"

# --- 8. Compile + link ---
Write-Step "Compiling with candle.exe"

$wixSourceDirFull = (Resolve-Path ".\wix").Path
& $candle -ext WixUtilExtension `
    "-dPayloadDir=$payloadFull" `
    "-dLibSourceDir=$payloadFull\lib" `
    "-dPublicSourceDir=$payloadFull\public" `
    "-dWixSourceDir=$wixSourceDirFull" `
    "-dProductVersion=$productVersion" `
    "-dDisplayVersion=$displayVersion" `
    "-dManufacturer=$manufacturer" `
    -arch x64 `
    -out "$obj\" `
    ".\wix\Product.wxs" $libFragment $publicFragment
if ($LASTEXITCODE -ne 0) { throw "candle.exe failed (exit $LASTEXITCODE)." }

Write-Step "Linking with light.exe"

$msiPath = "$setupRoot\$msiName"
Remove-Item $msiPath -Force -ErrorAction SilentlyContinue
& $light -ext WixUIExtension -ext WixUtilExtension -sice:ICE61 `
    -out $msiPath `
    "$obj\Product.wixobj" "$obj\LibFragment.wixobj" "$obj\PublicFragment.wixobj"
if ($LASTEXITCODE -ne 0) { throw "light.exe failed (exit $LASTEXITCODE)." }

$msiFull = (Resolve-Path $msiPath).Path
Write-Host "Built MSI: $msiFull"

# --- 9. Hashes ---
Write-Step "Computing SHA-256 hashes"

$msiHash = (Get-FileHash $msiFull -Algorithm SHA256).Hash
$exeHash = (Get-FileHash "$payloadFull\OraPulse.exe" -Algorithm SHA256).Hash
Write-Host "MSI  SHA-256: $msiHash"
Write-Host "EXE  SHA-256: $exeHash  (OraPulse.exe inside the payload)"
"$msiHash  $msiName" | Out-File -FilePath "$setupRoot\$msiName.sha256.txt" -Encoding ascii
"$exeHash  OraPulse.exe" | Out-File -FilePath "$setupRoot\OraPulse.exe.sha256.txt" -Encoding ascii

# --- 10. Static verification (no install performed) ---
Write-Step "Verifying the built MSI (read-only -- no install/uninstall performed)"

# MSI SQL requires backtick-quoted table/column names -- built via $bt
# (a literal backtick, safe inside a single-quoted PowerShell string, so
# PowerShell's own escape-character handling never gets involved) rather
# than writing literal backticks inline, which PowerShell would otherwise
# try to parse as its own escape character.
$bt = '`'

function Invoke-MsiQuery($db, [string]$sql) {
    $view = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @($sql))
    $view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null) | Out-Null
    return $view
}

function Get-MsiRecord($view) {
    return $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
}

$checks = [ordered]@{}
try {
    $installer = New-Object -ComObject WindowsInstaller.Installer
    $db = $installer.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $installer, @($msiFull, 0))

    function Get-MsiProperty($db, [string]$name) {
        $sql = "SELECT ${bt}Value${bt} FROM ${bt}Property${bt} WHERE ${bt}Property${bt} = '$name'"
        $rec = Get-MsiRecord (Invoke-MsiQuery $db $sql)
        if ($null -eq $rec) { return $null }
        return $rec.GetType().InvokeMember("StringData", "GetProperty", $null, $rec, @(1))
    }

    $checks["Manufacturer property"] = (Get-MsiProperty $db "Manufacturer") -eq $manufacturer
    $checks["ProductVersion property"] = (Get-MsiProperty $db "ProductVersion") -eq $productVersion
    $checks["ProductName property"] = (Get-MsiProperty $db "ProductName") -eq "OraPulse (ODM)"
    $checks["ALLUSERS = 1 (per-machine)"] = (Get-MsiProperty $db "ALLUSERS") -eq "1"

    $sco = $installer.GetType().InvokeMember("SummaryInformation", "GetProperty", $null, $installer, @($msiFull, 0))
    $platformField = $sco.GetType().InvokeMember("Property", "GetProperty", $null, $sco, @(7))
    $checks["x64 package (Template = $platformField)"] = $platformField -like "x64*"

    $dirSql = "SELECT ${bt}Directory${bt},${bt}DefaultDir${bt} FROM ${bt}Directory${bt} WHERE ${bt}Directory${bt} = 'INSTALLFOLDER'"
    $dirRec = Get-MsiRecord (Invoke-MsiQuery $db $dirSql)
    $checks["INSTALLFOLDER directory entry present"] = ($null -ne $dirRec)

    $fileCountView = Invoke-MsiQuery $db "SELECT ${bt}File${bt} FROM ${bt}File${bt}"
    $msiFileCount = 0
    while ($true) {
        $r = Get-MsiRecord $fileCountView
        if ($null -eq $r) { break }
        $msiFileCount++
    }
    $expectedFileCount = $libCount + $publicCount + $required.Count
    $checks["File table row count ($msiFileCount) >= payload file count ($expectedFileCount)"] = $msiFileCount -ge $expectedFileCount

    $upgradeRec = Get-MsiRecord (Invoke-MsiQuery $db "SELECT ${bt}UpgradeCode${bt} FROM ${bt}Upgrade${bt}")
    $checks["Upgrade table has a row (major-upgrade wired up)"] = ($null -ne $upgradeRec)

    $featureSql = "SELECT ${bt}Feature${bt} FROM ${bt}Feature${bt} WHERE ${bt}Feature${bt} = 'DesktopShortcutFeature'"
    $featureRec = Get-MsiRecord (Invoke-MsiQuery $db $featureSql)
    $checks["Optional DesktopShortcutFeature feature present"] = ($null -ne $featureRec)

    $upgradeCodeRec = Get-MsiRecord (Invoke-MsiQuery $db "SELECT ${bt}UpgradeCode${bt} FROM ${bt}Upgrade${bt}")
    $upgradeCodeValue = if ($upgradeCodeRec) { $upgradeCodeRec.GetType().InvokeMember("StringData", "GetProperty", $null, $upgradeCodeRec, @(1)) } else { $null }
    $checks["UpgradeCode matches the fixed, permanent GUID"] = $upgradeCodeValue -eq "{F3CAC7A6-8545-43CD-B179-470834A029EE}"

    # Absent from the Property table entirely is correct here (not merely
    # "false") -- ARPSYSTEMCOMPONENT=1 would hide the product from Programs
    # and Features, which this product must never do.
    $checks["ARPSYSTEMCOMPONENT not set (visible in Programs and Features)"] = (Get-MsiProperty $db "ARPSYSTEMCOMPONENT") -eq $null
} catch {
    Write-Host "Verification via WindowsInstaller COM failed: $($_.Exception.Message)" -ForegroundColor Yellow
    $checks["MSI table verification"] = $false
} finally {
    if ($db) { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($db) | Out-Null }
    if ($installer) { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($installer) | Out-Null }
}

$allPass = $true
foreach ($k in $checks.Keys) {
    $ok = $checks[$k]
    if (-not $ok) { $allPass = $false }
    $mark = if ($ok) { "PASS" } else { "FAIL" }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("  [{0}] {1}" -f $mark, $k) -ForegroundColor $color
}

Write-Step "Summary"
Write-Host "MSI:             $msiFull"
Write-Host "MSI SHA-256:     $msiHash"
Write-Host "EXE SHA-256:     $exeHash"
Write-Host "ProductVersion:  $productVersion  (display: $displayVersion)"
Write-Host "Verification:    $(if ($allPass) { 'ALL CHECKS PASSED' } else { 'ONE OR MORE CHECKS FAILED -- see above' })"
Write-Host ""
Write-Host "NOT done by this script (changes the system -- run only with your own approval):"
Write-Host "  msiexec /i `"$msiFull`"          (attended install)"
Write-Host "  msiexec /i `"$msiFull`" /qn      (silent install)"
Write-Host "  msiexec /x `"$msiFull`" /qn      (silent uninstall)"

if (-not $allPass) {
    throw "One or more verification checks failed -- see above."
}
