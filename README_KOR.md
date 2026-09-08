# OraPulse

**Oracle Database Monitoring(ODM)** -- 사용자 자신의 PC에서 단독으로 실행되는 소형 Oracle Database 모니터링 앱입니다. 공유 백엔드나 중앙 서버, 앱 자체 로그인이 없습니다: 각 사용자가 자신의 로컬 인스턴스를 실행하고, 접속 정보를 직접 입력해 Oracle DB에 연결한 뒤 브라우저에서 대시보드를 여는 방식으로 동작합니다 -- 데스크톱 DB 클라이언트(SQL Developer, Toad 등)를 쓰는 것과 동일한 사용 방식이며, 다만 그 "클라이언트"가 작은 로컬 웹 서버일 뿐입니다.

## 개요

- **자체 로그인이 없습니다.** 접속 화면에 입력하는 Oracle 계정/비밀번호가 유일한 인증 정보이며, OraPulse가 실행 중인 PC 밖으로 절대 전송되지 않습니다. 서버는 `127.0.0.1`에만 바인딩됩니다.
- **단일 Python 백엔드.** `main.py`(FastAPI + `python-oracledb`)가 REST API와 `public/`의 정적 프론트엔드를 모두 서비스합니다. 개발 초기에는 동일한 기능을 Node.js/Express로도 병행 구현했었지만, 그 원조 구현은 참고용으로 `legacy-nodejs/`에 보관만 되어 있을 뿐 더 이상 빌드·실행·테스트되지 않습니다 -- 패키징된 Windows 배포판도, 이 문서가 설명하는 내용도 전부 Python 백엔드 기준입니다.
- **Oracle 12.1 이상 모든 에디션/버전에서 동작합니다.** 모든 기능은 일반 계정으로도 접근 가능한 `V$`/`DBA_` 뷰만으로 구현되어 있습니다(모든 카드에 실제 데이터가 표시되려면 SYSTEM 수준의 조회 권한을 권장하지만, 앱 실행 자체에는 필요하지 않습니다). Diagnostics Pack이나 Tuning Pack 라이선스가 전혀 필요하지 않습니다.

## 기능

### DashBoard 탭
- 인스턴스 정보 (이름, 상태, 호스트, `V$INSTANCE.VERSION_FULL` 기준 전체 버전, 기동 시각, 가동 시간)
- CPU / 메모리 사용량
- 현재 세션 목록 -- ACTIVE 세션 우선, 그다음 로그인 시간이 오래된 순으로 정렬; Status/Machine/Program 필터 제공; 행을 우클릭하면 **세션 강제 종료(IMMEDIATE)**, 실행 중인 쿼리 보기, 대기 상세 보기(파일/블록 기반 대기의 경우 `DBA_EXTENTS` 조회를 통한 파일/블록 객체 조회 포함)를 수행할 수 있습니다; OraPulse 자신의 짧은 모니터링 연결은 목록/카운트에서 제외됩니다
- Blocking Session 목록
- Long Running Session 진행률 표시 (`V$SESSION_LONGOPS`)
- 테이블 통계정보 수집 현황(선택한 여러 테이블의 통계를 한 번에 수집하는 배치 기능 포함), 테이블 우클릭 메뉴에서 열 수 있는 **테이블 속성** 보기(컬럼, 인덱스)
- 스케줄러/작업 실패 이력 -- `DBMS_SCHEDULER` 실행 이력(SUCCEEDED가 아닌 모든 결과) 및 문제가 있는 legacy `DBMS_JOB` 작업의 현재 스냅샷, 스키마 필터 제공
- 계정 보안 -- `DBA_USERS` 기준으로 현재 잠긴 계정, 비밀번호가 이미 만료됐거나 곧 만료될 계정 목록
- Alert Log 분석 (`V$DIAG_ALERT_EXT`)

### 운영(Ops) 탭
주요 인스턴스 파라미터와 Undo 설정 및 상태가 나란히, 인스턴스 효율성 지표와 로드 프로파일이 나란히 배치되며, 그 아래로 한 줄씩: TEMP 테이블스페이스 사용량, 세션별 TEMP 사용량, 데이터파일 자동확장 상태(MAXSIZE 도달 임박 여부), Redo Log 상태, 테이블스페이스 I/O 통계(물리적 읽기 기준 정렬), 실행시간 상위 5개 쿼리, CPU 시간 상위 5개 쿼리, Buffer Gets 상위 5개 쿼리, 대기 이벤트 Top 5 순서로 배치됩니다. 이 탭의 모든 카드는 (탭 간 이동을 포함해) 자유롭게 드래그 앤 드롭으로 순서를 바꿀 수 있으며, 배치 결과는 `localStorage`에 저장되고 앱의 기본 배치와 병합되어 적용됩니다. 따라서 앱 업데이트로 기본 배치가 바뀌어도 예전에 저장된 배치에 의해 조용히 무시되지 않고, 예전 저장 배치에 없던 새 카드도 엉뚱하게 맨 앞/뒤로 밀리지 않고 제자리에 배치됩니다.

### 복구(Recovery) 탭
최근 DML(Top 50, 최신순, Type/Schema 필터 제공), Fast Recovery Area 개요, 파일 유형별 FRA 사용량.

### 튜닝(Tuning) 탭
규칙 기반 튜닝 어드바이저입니다 -- AWR/ASH나 Diagnostics/Tuning Pack 라이선스가 필요 없습니다. `V$SYSSTAT`, `V$LIBRARYCACHE`, `V$SYSTEM_EVENT`, `V$SQL`, `DBA_DATA_FILES`/`DBA_FREE_SPACE`, `DBA_OBJECTS`, `V$SESSION`만을 대상으로 정해진 항목들(버퍼/라이브러리 캐시 히트율, 하드 파싱 비율, 디스크 정렬, 대기 이벤트 증가, 테이블스페이스 여유공간, Invalid Object, Blocking Session, 느린 SQL)을 점검합니다. 증가율 기반 점검은 암호화되어 로컬에 저장된 이전 점검 스냅샷과 비교하는 방식(실제 AWR 이력이 아닌, statspack과 유사한 소규모 델타 비교)이라, 해당 DB에 대한 첫 점검에서는 이 항목들에 한해 "이력이 충분하지 않음"으로 표시되며 다시 점검하면 비교가 가능해집니다. 같은 유형의 발견 항목은 표 형태의 한 항목으로 묶여 표시되고(예: 여유공간이 부족한 모든 테이블스페이스를 나열하는 "테이블스페이스 사용률" 항목 하나), 느린 SQL 표의 SQL_ID를 클릭하면 전체 쿼리 텍스트를 볼 수 있습니다.

### Obj View/SQL 탭
왼쪽에는 SQL Developer 스타일의 오브젝트 탐색기(계정 선택, 유형 필터, 텍스트 필터, 오브젝트 유형별로 묶인 트리)가 있어 오브젝트를 클릭하면 `DBMS_METADATA.GET_DDL`로 조회한 DDL이 오른쪽에 표시됩니다. 그 아래에는 읽기 전용 **SQL Query Runner**가 있어 단일 SELECT문만 허용하며 최대 200행까지 표시하고, CLOB은 텍스트로 표시됩니다(BLOB은 지원 범위 밖입니다).

### Weekly DB Health Report
상단의 **Report** 버튼을 누르면 최근 N일간의 DB 상태를 담은 독립 실행형 HTML 리포트(인라인 SVG 차트 포함, 외부 의존성 없음)가 생성됩니다. 리포트에 필요한 대부분의 지표가 이력 없이 현재값만 노출하는 `V$` 뷰 기반이므로, 접속에 성공하는 즉시(브라우저를 계속 열어두지 않아도) 15분마다 백그라운드에서 가벼운 스냅샷을 수집해 AES-256-GCM으로 암호화된 로컬 이력 파일에 누적합니다 -- AWR 리포지토리를 대신하는 작고 라이선스가 필요 없는 대체 수단입니다. Report 버튼을 누르면 완성된 HTML이 실행 파일 옆 `report/<YYYY-MM-DD>/` 폴더에 저장됩니다.

### 즐겨찾기
접속 정보(IP/Port/SID/계정, 비밀번호 포함)를 AES-256-GCM으로 암호화된 로컬 저장소에 저장할 수 있습니다. 접속 화면에서 저장된 즐겨찾기를 클릭하면 추가 클릭 없이 바로 연결됩니다.

### DB 부하 절감
DashBoard 탭의 데이터는 하나의 고정 주기 대신, 성격별로 독립된 자동 갱신 주기로 나뉘어 있습니다: 세션 목록/Blocking Session은 15초, CPU/메모리는 30초, 인스턴스 정보는 5분; Ops 탭은(활성 탭일 때) 5분, Tuning 탭은(활성 탭일 때) 10분마다 갱신됩니다. 브라우저 탭이 숨겨지거나 최소화되면 이 모든 자동 갱신이 자동으로 멈추고, OraPulse를 여러 탭/창으로 열어도(Web Locks API 기반 리더 선출로) 단 하나의 탭만 실제로 조회하며, 다시 보이거나 리더가 되는 순간 즉시 한 번 갱신해 따라잡습니다. 여기에 더해 서버 자체도 같은 DB 대상에 대한 동일 요청을 15초간 캐시해서, 수동 새로고침과 자동 갱신이 우연히 겹치는 등 거의 동시에 들어온 요청들이 실제로는 Oracle을 한 번만 조회하도록 합니다.

### 데스크톱 패키징 (Windows)
패키징된 배포판은 콘솔 창 없이 실행되며, 시스템 트레이 아이콘(Open / Exit)만으로 창을 다시 열거나 앱을 종료할 수 있습니다. 실행할 때마다 OS가 골라주는 빈 포트를 새로 사용하므로(고정 포트 아님) 서로 다른 실행끼리 충돌하지 않으며, 이미 실행 중인 인스턴스가 있으면 현재 사용 중인 포트를 적어둔 작은 lock 파일을 확인하고 실제로 그 포트에 `/api/version`을 호출해 살아있는지 검증한 뒤(단순 추측이 아님) 새 서버를 띄우는 대신 그 인스턴스로 이동합니다. 앱 창 자체는 전용 격리된 Chrome/Edge 프로파일에서 `--app` 모드(주소창/탭 없음)로 열리며, 이 프로파일은 비밀번호 저장 제안 기능이 꺼져 있습니다 -- 포트가 매번 바뀌면서 Chrome이 사이트별로 기억하는 "저장 안 함" 선택이 실행할 때마다 초기화되어 매번 다시 물어보는 문제를 이렇게 막습니다. Chrome/Edge를 찾지 못하면 OS 기본 브라우저로 대체됩니다.

### 도움말 탭
위의 모든 기능을 실제 스크린샷과 함께 설명하는, 앱에 내장된 사용설명서입니다(영어/한국어 둘 다 제공). 인터넷 연결이나 별도 문서 없이도 앱 안에 그대로 포함되어 있습니다. 설명서 안 검색창으로 원하는 단어를 찾으면 모든 일치 항목이 강조 표시되고, Enter나 위/아래 버튼으로 하나씩 이동할 수 있습니다.

### 기타
- 영어/한국어 화면 전환(선택 값 저장됨; "DashBoard", "Obj View/SQL" 등 일부 명칭은 두 언어에서 의도적으로 동일하게 유지됩니다).
- 다크/라이트 테마 전환(선택 값 저장됨; 순수 CSS 변수 전환 방식이라 다시 그릴 필요가 없습니다).

## 요구 사항

- Oracle Database 12.1 이상. (인스턴스 정보 카드의 버전 표시는 `V$INSTANCE.VERSION_FULL`을 사용하므로 12.2 이상에서만 값이 채워집니다 -- 12.1에서는 이 카드에서만 권한 오류 형태의 메시지가 표시됩니다.)
- OraPulse가 실행되는 위치에서 대상 Oracle Listener의 호스트/포트로 접속 가능한 네트워크 환경.
- Oracle Instant Client 설치가 필요 없습니다 -- `python-oracledb`의 순수 Python 구현("thin mode")만 사용합니다.

## 프로젝트 구조

```
orapulse/
├── main.py                 # 진입점: 앱 생성, 라우터 등록, 서버 기동
├── backend/                # 탭/기능별로 나뉜 FastAPI 라우트 모듈
│   ├── core.py             # 공용 인프라: 앱 인스턴스, DB 연결 헬퍼, 세션 스토어
│   ├── routes_connect.py   # 버전, 접속/해제 라이프사이클, 즐겨찾기, DashBoard의 /api/db-status
│   ├── routes_session.py   # 세션 목록 행 동작 (대기 상세, SQL 보기, 세션 종료)
│   ├── routes_table_stats.py  # 테이블 통계정보 수집 + 테이블 속성
│   ├── routes_object_view.py  # Obj View/SQL 탭의 오브젝트 탐색기
│   ├── routes_sql_runner.py   # Obj View/SQL 탭의 SQL Query Runner + 취소
│   ├── routes_tuning.py    # 튜닝 탭
│   ├── routes_jobs.py      # 스케줄러/작업 실패 이력 카드
│   ├── routes_account_security.py  # 계정 보안 카드
│   ├── routes_alert_log.py # Alert Log 분석
│   ├── routes_ops.py       # 운영(Ops) 탭
│   ├── routes_recovery.py  # 복구(Recovery) 탭
│   └── routes_report.py    # Weekly DB Health Report 생성
├── report.py                # Weekly DB Health Report: 스냅샷 수집기 + HTML 렌더러
├── favorites.py              # 암호화된 로컬 즐겨찾기 저장소
├── tuning.py                 # 규칙 기반 튜닝 어드바이저
├── browser.py               # 실행 시 격리된 브라우저 프로파일을 여는 모듈 (데스크톱 패키징 참고)
├── tray.py                 # Windows 시스템 트레이 아이콘 (패키징된 배포판 전용)
├── paths.py                # 경로 관련 공통 헬퍼 (소스 실행 vs. 패키징된 .exe 구분)
├── requirements.txt        # Python 의존성
├── VERSION                 # 일반 텍스트 앱 버전 (1.NNNN)
├── OraPulse.spec / OraPulse-Folder.spec  # PyInstaller 빌드 스펙
├── installer.iss           # Inno Setup 설치 스크립트
├── build.ps1 / build-folder.ps1 / build-installer.ps1  # 빌드 스크립트
├── data/                   # 실행 시 생성됨: 암호화된 즐겨찾기/스냅샷 (버전관리 제외)
├── report/                 # 실행 시 생성됨: 날짜별로 생성된 리포트 HTML 파일
├── legacy-nodejs/          # 보관된 예전 Node.js/Express 구현 (더 이상 유지보수 안 함, 자체 README 참고)
└── public/                 # 브라우저 프론트엔드
    ├── index.html          # 접속 화면
    ├── dashboard.html      # 대시보드 뼈대 (마크업만 포함 -- 스타일/스크립트는 아래 참고)
    ├── troubleshooting.html
    ├── favicon.svg / favicon.ico
    ├── images/help/        # 도움말 탭 사용설명서에 포함된 스크린샷
    ├── css/dashboard.css   # 대시보드 전체 스타일
    └── js/                 # 대시보드 스크립트 (아래 순서대로 로드됨)
        ├── i18n.js         # I18N 사전, t(), applyStaticI18n()
        ├── cards.js        # DashBoard/Ops/Recovery/Tuning/SQL Runner 데이터 로딩 + 렌더링
        └── app-shell.js    # 탭 전환, 카드 드래그앤드롭, 모달/컨텍스트 메뉴, Obj View 탭, 부트스트랩
```

## 소스에서 직접 실행하기

```bash
pip install -r requirements.txt
python main.py
```

실행할 때마다 사용 가능한 포트를 자동으로 골라 기본 브라우저로 엽니다 (콘솔 출력에도
주소가 표시됩니다, 예: `http://127.0.0.1:54231`). 특정 포트를 고정해서 쓰려면(주로
스크립트/테스트에서 정해진 주소가 필요할 때) `PORT=<번호>`를 지정하세요.

## Windows 배포판 빌드하기

```powershell
.\build.ps1             # 단일 파일 OraPulse_ver_<버전>.exe (PyInstaller --onefile)
.\build-installer.ps1   # 폴더 배포판과 Inno Setup 설치 프로그램까지 함께 빌드
```

두 스크립트 모두 `VERSION` 파일에서 버전을 읽습니다. `build-installer.ps1`은 먼저 `build-folder.ps1`을 실행한 뒤 `installer.iss`를 컴파일해 `dist\OraPulse-Setup_ver_<버전>.exe`를 생성합니다. 설치 위치는 `C:\Program Files (x86)\OraPulse_Windows_x86`이며 관리자 권한/UAC가 필요합니다.

## 데이터 저장 및 개인정보

OraPulse가 저장하는 모든 데이터는 실행 중인 앱 옆(실행 파일, 또는 소스에서 실행 시 `main.py` 옆)에 생성되는 `data/` 폴더에만 저장되며, 사용자가 연결한 Oracle DB 이외에는 어디로도 전송되지 않습니다:

- `favorites.enc` / `.favorites-key` -- 저장된 접속 정보, AES-256-GCM
- `snapshot-history.jsonl` / `.snapshot-key` -- Weekly Report 이력
- `tuning-last-snapshot.enc` / `.tuning-key` -- 튜닝 어드바이저의 이전 점검 결과
- `.instance-port` -- 현재 실행 중인 인스턴스가 사용 중인 포트 번호로, 재실행 시 이미 실행 중인 인스턴스를 감지/이동하는 용도로만 쓰입니다; 민감한 정보가 아니며 앱이 실행 중이 아닐 때 삭제해도 안전합니다
- `browser-profile/` -- OraPulse가 스스로 여는 전용 Chrome/Edge 프로파일 폴더(위 "데스크톱 패키징" 참고); 일반적인 브라우저 프로파일 데이터일 뿐 Oracle 접속 정보와는 무관하며, 마찬가지로 삭제해도 안전합니다

각 저장소는 자체 키 파일을 사용하며 서로 독립적입니다. `data/` 폴더를 삭제하면 이 데이터가 모두 삭제되며, 다음 사용 시 각 파일이 빈 상태로 다시 생성되므로 언제든 안전하게 삭제할 수 있습니다.

## 알려진 제한 사항

- Oracle Database 11g 이하는 지원하지 않습니다 (thin-mode 드라이버의 제약).
- `V$INSTANCE.VERSION_FULL`(인스턴스 정보의 버전 표시)은 Oracle 12.1에서는 값이 채워지지 않습니다 -- 이 경우 해당 카드에서만 권한 오류 형태의 메시지가 표시되며, 다른 모든 기능은 정상 동작합니다.
- SQL Query Runner에는 바인드 변수 입력 UI가 없어, 바인드 변수가 필요한 쿼리는 리터럴 값을 직접 넣어야 합니다. BLOB 컬럼은 표시되지 않습니다.
- OS 레벨의 호스트 지표(디스크/파일시스템 여유공간, Oracle이 직접 보고하지 않는 CPU 부하 등)는 제공하지 않습니다 -- 설계상 DB 접속을 통해 얻을 수 있는 정보만 다룹니다.
- 전용 프로파일을 통한 비밀번호 저장 알림 방지(위 "데스크톱 패키징" 참고)는 Chrome이나 Edge가 표준 Windows 설치 경로에 있을 때만 적용됩니다 -- 그렇지 않으면 이 조치 없이 OS 기본 브라우저로 열립니다.
