# Builds dist\AtlasStudio_ver_<VERSION>\ -- a folder containing
# AtlasStudio.exe plus its supporting files:
#
#   AtlasStudio_ver_<VERSION>\
#   |-- AtlasStudio.exe
#   |-- VERSION
#   |-- README.txt
#   |-- public\      (the frontend, promoted out of lib\)
#   `-- lib\         (the Python runtime and every other dependency)
#
# Adapted from OraPulse's own build-folder.ps1
# (D:\STMKJHA\00.Git\01.OraPulse\build-folder.ps1) -- same staged-build +
# promote-public + version-tagged-folder pattern, minus the peripheral-DLL
# promotion step (that was specifically working around oracledb's native
# extension modules, which this project doesn't have).
#
# Usage: .\build-folder.ps1
# Output: dist\AtlasStudio_ver_<VERSION>\ -- e.g. dist\AtlasStudio_ver_0.1.0\.
# A fresh, version-tagged folder name every build (rather than always
# dist\AtlasStudio\) means a rebuild only collides with a *previous build
# of that exact same version* -- ordinary version bumps never revisit a
# name that could be locked by something still holding it open.
#
# Zip the whole output folder to distribute it; the .exe alone will not
# run without its sibling files.
#
# This project's own venv\/dist\/build\/data\ are never touched here
# beyond creating/reading them -- and none of OraPulse's own venv\, dist\,
# or data\ are read or written by this script at all.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv and installing dependencies..."
    python -m venv venv
    .\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
    .\venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller --quiet
}

$version = (Get-Content ".\VERSION" -Raw).Trim()
$finalDir = ".\dist\AtlasStudio_ver_$version"

# PyInstaller's COLLECT always names its output folder after the .spec's
# own name='AtlasStudio', so it's built into a build-specific staging
# parent first -- named after the current process, so two builds can
# never collide with each other -- and only the finished AtlasStudio\
# folder inside it is promoted to the real, version-tagged name afterward.
$stagingParent = ".\dist\_build_$PID"
Remove-Item $stagingParent -Recurse -Force -ErrorAction SilentlyContinue

# --clean avoids PyInstaller silently reusing a stale COLLECT from a
# previous run's build\ cache, which otherwise leaves this script trying
# to move files that were never actually rebuilt.
.\venv\Scripts\python.exe -m PyInstaller AtlasStudio-Folder.spec --noconfirm --clean --distpath $stagingParent

$distRoot = "$stagingParent\AtlasStudio"
$lib = "$distRoot\lib"

Move-Item "$lib\public" "$distRoot\public" -Force

# main.py reads VERSION from next to the .exe (app_dir()).
Copy-Item ".\VERSION" "$distRoot\VERSION" -Force

@"
AtlasStudio -- Oracle 운영·분석 통합 워크스페이스 (UI 시안)
================================================

실행: AtlasStudio.exe 를 더블클릭하세요. 서버가 준비되면 전용 앱 창이
자동으로 열립니다. 창을 닫아도 트레이 아이콘은 계속 실행되며,
트레이 아이콘 메뉴에서 "창 열기" / "종료"를 선택할 수 있습니다.

폴더 구성:
  AtlasStudio.exe   앱 실행 파일
  public\           프런트엔드 (HTML/CSS/JS, 아이콘 포함)
  lib\              Python 런타임과 나머지 의존성
  data\             최초 실행 시 생성됨 (인스턴스 잠금 파일, 브라우저 프로필) --
                    삭제해도 앱을 초기 상태로 되돌릴 뿐, 안전하게 지울 수 있습니다.

이번 배포본은 메인 화면 UI 시안만 포함하며, 실제 Oracle 접속·데이터
수집 기능은 없습니다.
"@ | Out-File -FilePath "$distRoot\README.txt" -Encoding utf8

# Promote the finished build out of the staging wrapper to its real,
# version-tagged name.
Remove-Item $finalDir -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path $finalDir) {
    $finalDir = "$finalDir`_$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "WARNING: $($finalDir -replace '_\d{14}$', '') already exists and could not be replaced. Using $finalDir instead."
}
Move-Item $distRoot $finalDir
Remove-Item $stagingParent -Recurse -Force -ErrorAction SilentlyContinue

$finalDirFull = (Resolve-Path $finalDir).Path
Write-Host ""
Write-Host "Built: $finalDirFull\ (run $finalDirFull\AtlasStudio.exe)"
