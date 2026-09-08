# Builds dist\OraPulse\ -- a folder containing OraPulse.exe plus its
# supporting files, laid out like a typical installed Windows program
# rather than "one .exe and a single _internal folder":
#
#   OraPulse\
#   |-- OraPulse.exe
#   |-- VCRUNTIME140.dll, ucrtbase.dll, ... (a handful of peripheral
#   |     runtime DLLs, promoted out of lib\ -- see the note below on why
#   |     this is safe)
#   |-- README.txt
#   |-- public\      (the frontend, promoted out of lib\)
#   `-- lib\         (the Python runtime, oracledb, and every other
#                      dependency)
#
# Functionally identical to build.ps1's single-exe output -- same app code,
# same behavior, different packaging. See OraPulse-Folder.spec for how the
# PyInstaller step itself works (contents_directory='lib' renames its
# default '_internal' folder); this script does the *rest* of the layout
# as a post-build step, because PyInstaller's own COLLECT flatly refuses
# to place any file outside the dist folder via a '..' destination -- the
# only way to split output across lib\ and the top level at all.
#
# What can and can't be pulled out of lib\ this way (both found the hard
# way, by trying it and reading the actual failure):
# - public\ (plain data: HTML/CSS/JS/SVG) CAN. It's read via paths.py's
#   own resource_dir(), which checks the .exe's own directory before
#   falling back to lib\ -- not resolved through Windows' DLL search or
#   Python's import system at all, so it can sit wherever this script
#   puts it.
# - python314.dll / python3.dll CANNOT. PyInstaller's native bootloader
#   loads the Python DLL itself via a hardcoded full path pointing at the
#   contents directory, before Python -- and therefore this app's own
#   code -- has even started. Moving them produced
#   "[PYI-...:ERROR] Failed to load Python DLL ...\lib\python314.dll" at
#   the earliest possible point.
# - oracledb\ CANNOT, for a different reason: it ships compiled extension
#   modules (thin_impl.pyd etc.), and PyInstaller's frozen import
#   machinery (which intercepts `import oracledb` ahead of the normal
#   sys.path-based resolution, and therefore ahead of any sys.path fix
#   this app could add) has that module's location baked in at *build*
#   time. Moving the files afterwards doesn't update that -- it still
#   produced "ImportError: cannot import name 'base_impl' from partially
#   initialized module 'oracledb'" pointing at the old lib\oracledb\ path
#   even after the directory was physically moved out. There's no
#   supported way around this short of patching PyInstaller's own
#   embedded import bookkeeping, which isn't worth the fragility.
# - The 4 peripheral DLLs below CAN, once python314.dll/python3.dll (their
#   loader) stays put: Windows' standard DLL search order always includes
#   "the directory the application loaded from" (the .exe's own folder)
#   for every LoadLibrary call in the process, not just the main .exe's
#   own direct dependencies -- and PyInstaller's bootloader separately
#   registers lib\ (its configured contents_directory) as a search
#   directory too. Between the two, nothing loses access to anything.
#   Confirmed by actually connecting through a rebuilt copy afterwards.
#
# Usage: .\build-folder.ps1
# Output: dist\OraPulse_ver_<VERSION>\ -- e.g. dist\OraPulse_ver_1.0002\.
# A fresh, version-tagged folder name every build, rather than always
# dist\OraPulse\, is what sidesteps a problem hit once already: Windows can
# leave a onedir output folder locked by something outside this script's
# control (not any OraPulse.exe -- checked; not Explorer -- restarting it
# didn't help either) with no way to remove it short of a reboot. Reusing
# the same folder name every build meant hitting that same stuck folder
# forever; naming each build after its own VERSION means a rebuild only
# collides with a *previous build of that exact same version* -- ordinary
# version bumps never revisit a name that could be locked. (Building
# straight into PyInstaller's real COLLECT target -- see the two-step
# staging-then-rename below -- rather than building into dist\OraPulse\
# and renaming afterward, matters for the same reason: dist\OraPulse\ is
# exactly the fixed name that got stuck before, so this never touches it
# at all.)
#
# Zip the whole output folder to distribute it; the .exe alone will not
# run without its sibling files.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv and installing dependencies..."
    python -m venv venv
    .\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .\venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller --quiet
}

$version = (Get-Content ".\VERSION" -Raw).Trim()
$finalDir = ".\dist\OraPulse_ver_$version"

# PyInstaller's COLLECT always names its output folder after the .spec's
# own name='OraPulse' (there's no --name override for an existing .spec
# file), so it's built into a build-specific staging parent first --
# named after the current process, so two builds can never collide with
# each other -- and only the finished OraPulse\ folder inside it is
# promoted to the real, version-tagged name afterward.
$stagingParent = ".\dist\_build_$PID"
Remove-Item $stagingParent -Recurse -Force -ErrorAction SilentlyContinue

# --clean avoids PyInstaller silently reusing a stale COLLECT from a
# previous run's build\ cache, which otherwise leaves this script trying
# to move files that were never actually rebuilt.
.\venv\Scripts\python.exe -m PyInstaller OraPulse-Folder.spec --noconfirm --clean --distpath $stagingParent

$distRoot = "$stagingParent\OraPulse"
$lib = "$distRoot\lib"

Move-Item "$lib\public" "$distRoot\public" -Force

$peripheralDlls = @(
    'VCRUNTIME140.dll', 'VCRUNTIME140_1.dll',
    'ucrtbase.dll', 'api-ms-win-crt-runtime-l1-1-0.dll'
)
foreach ($dll in $peripheralDlls) {
    $src = Join-Path $lib $dll
    if (Test-Path $src) {
        Move-Item $src (Join-Path $distRoot $dll) -Force
    }
}

# main.py reads VERSION from next to the .exe (app_dir()).
Copy-Item ".\VERSION" "$distRoot\VERSION" -Force

@"
OraPulse -- Oracle Database Monitoring Client
================================================

To run: double-click OraPulse.exe. It opens your default browser to the
connect screen automatically.

Folder layout:
  OraPulse.exe   the app
  public\        the browser frontend
  lib\           the Python runtime, the Oracle DB driver, and the
                 remaining dependencies
  data\          created on first use (saved favorites, report history) --
                 safe to delete to reset the app to a clean state

Only Oracle Database 12.1 or later is supported.
"@ | Out-File -FilePath "$distRoot\README.txt" -Encoding utf8

# Promote the finished build out of the staging wrapper to its real,
# version-tagged name. Removing $finalDir first only matters when
# rebuilding the exact same VERSION twice in a row (bump VERSION.ps1/the
# VERSION file for a normal rebuild and this never comes up) -- if that
# specific folder is ever the one that's stuck, fall back to a
# timestamp-suffixed name rather than failing the whole build.
Remove-Item $finalDir -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $finalDir) {
    $finalDir = "$finalDir`_$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "WARNING: $($finalDir -replace '_\d{14}$', '') already exists and could not be replaced. Using $finalDir instead."
}
Move-Item $distRoot $finalDir
Remove-Item $stagingParent -Recurse -Force -ErrorAction SilentlyContinue

$finalDirFull = (Resolve-Path $finalDir).Path
Write-Host ""
Write-Host "Built: $finalDirFull\ (run $finalDirFull\OraPulse.exe)"
