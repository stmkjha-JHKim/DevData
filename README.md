# OraPulse Backup

**Oracle Data Pump 기반 중앙 백업 관리** -- OraPulse(Oracle DB 모니터링 클라이언트)와
같은 환경(FastAPI + 브라우저 프론트엔드, python-oracledb thin 모드, Oracle Instant
Client 불필요)을 재사용해서 만든 자매 프로젝트입니다. OraPulse가 DB 1개에 붙어
모니터링만 한다면, 이 프로젝트는 **여러 DB를 등록**해 두고 각 DB의 백업 정책·스
케줄·실행 이력·복구 가능성 검증을 한 화면에서 중앙 관리합니다.

## 이 프로젝트만의 핵심 설계: Instant Client 없이 Data Pump 실행

`expdp.exe`를 서브프로세스로 실행하거나 Oracle Instant Client를 설치하는 대신,
**`DBMS_DATAPUMP` PL/SQL 패키지를 python-oracledb thin 커넥션 위에서 직접 호출**
합니다 (`backend/datapump.py`). Export 작업을 열고(OPEN) 옵션을 설정하고
(ADD_FILE/SET_PARALLEL/SET_PARAMETER/METADATA_FILTER) 시작한 뒤
(START_JOB), 같은 커넥션에서 다시 붙어(ATTACH) 완료될 때까지 기다리고
(WAIT_FOR_JOB), 로그 파일과 덤프 파일 크기까지 `UTL_FILE`로 읽어옵니다. 덤프/로그
파일은 이 앱이 아니라 **DB 서버 자신의 Directory Object 경로**에 생성되므로, 이
앱을 실행하는 PC가 그 경로에 접근할 필요가 없습니다 -- OraPulse README가 명시한
"Instant Client 불필요, thin 모드만 사용" 철학을 백업 실행에도 그대로 적용한
것입니다.

`DBMS_DATAPUMP.WAIT_FOR_JOB`은 DB 쪽에서 작업이 끝날 때까지 블로킹되므로,
`backend/datapump.py`의 함수들은 전부 동기(sync) 코드입니다. FastAPI 라우트에서는
`asyncio.to_thread`로, 스케줄러(APScheduler)에서는 이미 별도 스레드이므로 직접
호출합니다 (`backend/jobs.py`).

## 지금 구현된 것 / 스텁으로 남긴 것

구현됨:
- DB 등록 (여러 개, AES-256-GCM 암호화 저장 -- OraPulse의 Favorites와 동일한 방식)
- 백업 정책 CRUD (FULL/SCHEMA/TABLE 범위, Directory Object, 압축, 병렬도,
  CONTENT, 스케줄, 보관 기간, RPO/RTO 등급)
- "지금 실행" -- 실제로 `DBMS_DATAPUMP` Export 작업을 실행하고 결과를 기록
- APScheduler 기반 자동 스케줄 실행 (정책 변경은 최대 60초 내 반영)
- 실행 이력 (상태/소요시간/덤프 크기/로그 전문)
- 대시보드 요약 (등록 DB 현황, 정책 개수, 최근 24시간 실패, 최근 실행, 경고 목록
  -- 전부 실제 저장된 데이터 기준, 가짜 수치 없음)

**스텁(다음 단계)**: 복구 가능성 검증(`백업 파일 존재`가 아니라 `실제로 복구 가
능함`을 증명하는 것)은 검증용 스키마로의 실제 `DBMS_DATAPUMP` Import, 그 대상
스키마/테이블스페이스를 어떻게 마련하고 정리할지, RTO 측정 방식 등 별도 설계가
필요해서 이번 버전에서는 이력 저장 구조만 만들고 실제 실행은 `backend/
routes_recovery.py`에 명확히 "미구현"으로 표시해 두었습니다 (OraPulse Backup의
초기 RMAN 기반 프로토타입에서도 복구 테스트 실행은 같은 이유로 스텁으로 남겼던
것과 같은 판단입니다).

그 외 알려진 제한:
- TABLE 범위는 **하나의 소유 스키마**만 지원합니다 (`SCHEMA:TABLE1,TABLE2` 형식).
  여러 스키마에 걸친 테이블을 한 정책으로 묶을 수는 없습니다 -- 정책을 나눠서
  등록하세요.
- 단일 관리자 모델입니다 (다중 사용자/권한 구분 없음).
- 코드 서명(codesign)이 되어 있지 않습니다 -- 처음 실행 시 Windows SmartScreen/백신이
  경고를 띄울 수 있습니다 ("추가 정보" -> "실행"으로 넘어가면 됩니다).
- 재시도(retry)/보관 기간(retention) 자동 삭제(오래된 덤프 파일 정리)는 아직
  구현되지 않았습니다. `retention_days` 값은 정책에 저장만 되고 있습니다.
- 실패 알림 이메일(`notify_email`)은 정책에 저장만 되고, 실제 발송 로직은 없습니다.
- Import를 통한 REUSE_FILE=1 설정으로 동일 파일명 재실행 시 기존 덤프가 덮어써질
  수 있습니다 -- 파일명 패턴에 `%DATE%`를 포함해 매 실행 파일명이 달라지게 하는
  것을 권장합니다 (기본 패턴에는 포함되어 있습니다).

## 프로젝트 구조

```
backup_manager/
├── main.py                    # 진입점: FastAPI 앱 생성, 라우터 등록, 서버 실행
├── paths.py                   # 데이터/정적 파일 경로 (소스 실행 + PyInstaller .exe 모두 지원)
├── oracle_dsn.py               # TNS 접속 문자열 생성 (OraPulse와 동일)
├── crypto_store.py              # AES-256-GCM 암호화 리스트 저장소 (OraPulse Favorites 방식)
├── registered_dbs.py           # 등록된 DB 목록 (crypto_store 사용)
├── backend/
│   ├── core.py                 # FastAPI 앱, Oracle 연결 헬퍼
│   ├── db.py                   # SQLAlchemy 모델 (정책/실행이력/복구검증) + SQLite
│   ├── datapump.py              # DBMS_DATAPUMP 실행 드라이버 (핵심 로직)
│   ├── jobs.py                  # 정책 실행 (수동/자동 공통)
│   ├── scheduler.py             # APScheduler 자동 실행
│   ├── routes_db.py             # DB 등록/조회/테스트/삭제
│   ├── routes_policies.py       # 백업 정책 CRUD + 지금 실행
│   ├── routes_history.py        # 실행 이력 조회
│   ├── routes_dashboard.py      # 개요 탭 집계
│   └── routes_recovery.py       # 복구 검증 (스텁)
├── requirements.txt
├── VERSION                     # 다음 빌드에서 만들어질 버전 (4자리, 예: 1.0.0.1) -- build.ps1이 매 빌드 후 자동 증가
├── OraPulseBackup.spec          # PyInstaller 빌드 스펙 (.exe에 무엇을 포함할지)
├── build.ps1                    # Windows .exe 빌드 스크립트 (아래 "Windows .exe 빌드" 참고)
├── favicon.ico                  # .exe 아이콘
└── public/                     # 브라우저 프론트엔드
    ├── index.html               # DB 등록 화면
    ├── dashboard.html            # 개요/정책/이력/복구검증 탭
    ├── css/dashboard.css
    ├── js/{connect,dashboard}.js
    └── favicon.svg
```

## 실행 방법

```bash
pip install -r requirements.txt
python main.py
```

기본적으로 `127.0.0.1:8000`에서 실행됩니다 (`PORT` 환경변수로 변경 가능). 브라우저
에서 `http://127.0.0.1:8000` 을 열면 DB 등록 화면으로 이동합니다.

## Windows .exe 빌드

Python이 설치되어 있지 않은 Windows PC에서도 실행할 수 있는 단일 실행 파일을
만들 수 있습니다 (PyInstaller 사용). Windows PowerShell에서:

```powershell
.\build.ps1
```

최초 실행 시 `venv`가 없으면 자동으로 만들고 `requirements.txt` + `pyinstaller`를
설치합니다 (Python은 미리 설치되어 있어야 합니다). 이후:

1. `dist` 폴더가 없으면 생성합니다.
2. `VERSION` 파일(4자리, 이 프로젝트는 `1.0.0.1`부터 시작)을 읽어 `dist\<버전>\`
   폴더를 새로 만들고 그 안에 `OraPulseBackup.exe`를 빌드합니다. 이전 버전 폴더는
   건드리지 않습니다.
3. 빌드가 끝나면 `VERSION`의 마지막 자리를 자동으로 1 증가시켜 저장합니다 --
   다음에 `.\build.ps1`을 실행하면 자동으로 다음 버전(`1.0.0.2`, `1.0.0.3`, ...)이
   빌드되고 그만큼 새 폴더가 생깁니다. 버전을 수동으로 관리할 필요가 없습니다.

빌드된 `dist\1.0.0.1\OraPulseBackup.exe`는 그 폴더를 통째로 복사해서 배포하면
됩니다. 실행하면 `.exe` 옆에 `data\` 폴더(암호화된 DB 등록 정보, 정책/이력
SQLite)가 자동으로 생기고, 재시작해도 유지됩니다 (`.exe`가 있는 위치에 쓰기
권한이 없으면 `%LOCALAPPDATA%\OraPulseBackup\data`로 자동 대체됩니다).
콘솔 창이 함께 뜨는데, 거기 표시되는 `http://127.0.0.1:PORT` 주소를 브라우저로
열어서 사용하면 됩니다 (트레이 아이콘/자동 브라우저 실행은 아직 없습니다).

> **참고**: 이 `.exe` 빌드는 개발 환경(Linux, Windows/PowerShell 없음)에서는
> 직접 실행해 검증할 수 없었습니다 -- 스펙 파일/빌드 스크립트/`paths.py`의 프리즌
> 모드 경로 처리는 OraPulse가 실제로 쓰는 것과 같은 구조로 만들고 로직도
> 재검토했지만, 실제 Windows에서 첫 빌드를 돌려보고 정상적으로 뜨는지, DB 연결이
> 되는지 확인해 주세요. 문제가 있으면 (예: DLL 누락, oracledb thin 모드 관련
> 오류) 알려주시면 바로 고치겠습니다.

백업 전용 Oracle 계정에는 최소한 다음 권한이 필요합니다: `EXP_FULL_DATABASE` (또는
필요한 범위만큼의 권한), 대상 Directory Object에 대한 `READ`/`WRITE`,
`EXECUTE ON DBMS_DATAPUMP`, `EXECUTE ON UTL_FILE` (또는 해당 Directory Object에
대한 UTL_FILE 접근 권한).

## 테스트

`oracledb.connect`/`connect_async`를 가짜(mock) 구현으로 바꿔치기해서 실제 Oracle
DB 없이도 DB 등록 실패/성공, 정책 CRUD, "지금 실행"의 성공/실패 두 경로,
`DBMS_DATAPUMP` 호출부의 바인드 변수 이름 정합성, 대시보드 집계, 스케줄러 트리거
생성까지 검증했습니다 (자동화된 스크립트로, 이 저장소에는 포함하지 않았습니다 --
필요하면 같은 방식으로 다시 만들어 드릴 수 있습니다). 실제 Oracle DB에 대해서는
아직 검증되지 않았으니, 운영 DB에 정책을 걸기 전에 테스트 DB로 먼저 "지금 실행"을
한 번 돌려보는 것을 권장합니다.
