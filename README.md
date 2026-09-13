# AtlasStudio -- 실행 구조 + 메인 화면 UI 시안

Oracle 운영·분석 통합 워크스페이스를 표방하는 신규 프로젝트 **AtlasStudio**의 독립 실행형
프로그램 기본 구조와 메인 화면(작업 홈) UI입니다. 실행 방식(로컬 FastAPI 서버 + 전용 브라우저
앱 창 + 트레이 아이콘)은 `D:\STMKJHA\00.Git\01.OraPulse`의 구조를 참고했고, 화면은 첨부된
디자인 시안(짙은 네이비 사이드바 + 청록 강조 색상 + 밝은 배경의 대시보드)을 그대로 구현했습니다.

**OraPulse 소스·데이터는 전혀 건드리지 않았습니다.**

## 소스 위치 이력 / 이 저장소·브랜치에 대한 중요한 참고사항

1. 처음 `D:\STMKJHA\00.Git\02.AtlasStudio`에서 개발.
2. `D:\STMKJHA\69.DevData\AtlasStudio`(하위 폴더)로 이전.
3. **현재**: `D:\STMKJHA\69.DevData`(이 README가 있는 위치, 저장소 루트)로 다시 이전 -- 더 이상
   하위 폴더가 아니라 `main.py`/`backend`/`public` 등이 루트에 직접 있습니다.

`D:\STMKJHA\00.Git\02.AtlasStudio`(1번 위치)는 보관 목적으로 삭제하지 않고 그대로 남겨두었습니다.
실제로 쓰이는 소스는 이 README가 있는 현재 위치 하나뿐입니다.

**이 폴더는 OraPulse와 같은 git 저장소(`69.DevData`)를 공유하지만, 서로 다른 브랜치입니다.**
이 저장소에는 `main`(초기 커밋뿐), `OraPulse`(실제 OraPulse 소스·이력이 있는 브랜치),
`OraPulse_Demo`, 그리고 `AtlasStudio`(이 프로젝트, `main`에서 분기, 아직 커밋 없음) 브랜치가
있습니다. 지금 이 작업 폴더는 `AtlasStudio` 브랜치가 체크아웃된 상태이고, `main`에서 분기했기
때문에 OraPulse의 실제 소스 파일과는 애초에 겹치지 않습니다(OraPulse의 소스는 `OraPulse`
브랜치에만 있습니다). **다른 브랜치로 체크아웃하면 이 폴더의 내용물(AtlasStudio 소스)이
디스크에서 사라지므로**(git이 정상적으로 작동 중이라는 뜻일 뿐 삭제/유실이 아니라, 아직
커밋하지 않은 이 작업 내용은 커밋해두는 것이 안전합니다), 작업을 마쳤다면 이 브랜치에
커밋해 두시길 권장합니다. 이번 작업에서는 git 실행 파일이 이 환경에 없어 커밋을 직접
수행하지 못했습니다(아래 "검증 결과"의 미검증 항목 참고).

이전(위 2번 위치) 당시, 이 폴더에는 예전에 `OraPulse` 브랜치가 체크아웃되어 있었을 때 남은,
git이 추적하지 않는(커밋되지 않은) OraPulse의 실제 런타임 산출물(`venv\`, `data\
browser-profile`, `demo\OraPulse_Demo_ver_1.0051`, `report\`)이 브랜치 전환 후에도 그대로
남아 있었습니다. 사용자 확인 후 전부 삭제했습니다(모두 재생성 가능한 산출물이며, OraPulse의
실제 소스·이력은 `OraPulse` 브랜치에 안전하게 남아 있어 영향이 없습니다).

## 구현 범위

- **독립 실행 가능한 프로그램의 기본 구조**와 **초기 DB 연결 화면 + 메인 화면(작업 홈) UI**만
  구현했습니다. 앱을 실행하면(또는 `/`에 접속하면) 먼저 `index.html`(DB 연결 화면)이 뜨고,
  "Oracle DB 연결 시작"을 누르면 `dashboard.html`(작업 홈)로 이동합니다.
- 이 연결 화면은 **UI 시안(데모)입니다** -- 입력값에 대한 형식 검증(IP/호스트명, 포트,
  SID/Service Name 문자 규칙, 계정/비밀번호 필수 입력)만 클라이언트에서 수행하고, 실제로는
  어디에도 전송하지 않습니다. 형식이 올바르면 무조건 작업 홈으로 이동합니다.
- 연결 화면에 **즐겨찾기**(접속 정보 저장/선택/삭제)가 있습니다. 이 브라우저 프로필의
  `localStorage`에만 저장되며(비밀번호는 저장하지 않음), 서버로는 전송되지 않습니다 -- 자세한
  내용은 아래 "즐겨찾기" 절 참고.
- Oracle 접속, SQL 실행, 데이터 수집, 실제 모니터링 등 상세 기능은 **전혀 없습니다.**
- 화면에 보이는 DB명·작업 이력 등은 전부 `public/data.js`의 **예시 데이터**이며, 실제 접속
  정보나 비밀번호는 어디에도 없습니다.
- "작업 홈"을 제외한 모든 사이드바 메뉴, 그리고 메인 화면의 모든 버튼/카드/링크는 클릭 시
  우측 하단에 "준비 중인 기능입니다" 토스트만 보여주고, 페이지 이동이나 실제 동작은
  발생시키지 않습니다.
- 로그인 화면, 설정 화면, 메뉴별 빈 페이지는 만들지 않았습니다.
- Oracle 드라이버, 보고서 수집기 등 이번 범위에 없는 기능의 의존성은 포함하지 않았습니다
  (`requirements.txt`가 `fastapi` / `uvicorn` / `pystray` / `Pillow` 4개뿐인 이유) -- 즐겨찾기는
  서버·드라이버 없이 브라우저 `localStorage`만으로 동작하므로 이 목록에 영향을 주지 않습니다.

## 즐겨찾기 (연결 화면)

- 연결 화면(`index.html`)의 드롭다운에서 저장된 접속 정보를 고르면 IP/Port/접속 방식/SID·Service
  Name/계정 필드가 채워집니다. **비밀번호는 절대 저장되지 않으며 매번 다시 입력해야 합니다**
  (OraPulse는 즐겨찾기 비밀번호를 서버에서 암호화해 보관하지만, 이 데모에는 그럴 서버 저장소가
  없으므로 가장 안전한 선택은 애초에 저장하지 않는 것입니다).
- 저장 위치: 이 브라우저 프로필의 `localStorage`(`atlasstudio.connectFavorites.v1` 키) --
  AtlasStudio는 항상 같은 전용 브라우저 프로필(`data\browser-profile`)로 열리므로, 다시 실행해도
  그대로 남아 있습니다. 서버로 전송되지 않고, OraPulse의 즐겨찾기 저장소와도 완전히 분리되어
  있습니다.
- "+ 저장"은 이름을 물어본 뒤 같은 이름이 있으면 덮어쓸지 확인합니다. 각 항목의 "✕"로 개별
  삭제할 수 있습니다.

## 작업 홈 상단에 접속 DB 표시 (회사명은 표시하지 않음)

연결 화면에서 "Oracle DB 연결 시작"을 누르면, 입력했던 **접속 방식(SID/Service Name)과 그
값**을 `sessionStorage`(`atlasstudio.currentConnection.v1` 키, 비밀번호 등 다른 값은 저장하지
않음)에 남기고 작업 홈으로 이동합니다. 작업 홈(`dashboard.html`) 상단 좌측에
`SID: ORCL / 작업 홈` / `Service Name: atlaspdb1.example.com / 작업 홈` 형태로 표시됩니다.
(처음에는 회사명 옆에 덧붙이는 형태였는데, 요청에 따라 **회사명 자체를 아예 빼고** 접속
정보만 보이도록 바꿨습니다 -- `data.js`의 `WORKSPACE`에서 `company` 필드도 함께 제거했습니다.)

- `localStorage`가 아닌 `sessionStorage`를 쓴 이유: 즐겨찾기처럼 여러 번 재사용할 저장값이
  아니라 "지금 이 창에서 마지막으로 연결(시도)한 값" 하나만 필요하기 때문입니다.
- "연결 해제"를 누르면 이 값을 지우므로, 연결 화면으로 돌아간 뒤 작업 홈에 직접 주소로
  들어가도 지워진 이전 값이 남아있지 않습니다.
- 연결 화면을 거치지 않고 `dashboard.html`을 바로 열면(북마크 등) 저장된 값이 없으므로,
  오류 없이 그냥 `작업 홈`만 표시됩니다(앞에 아무것도 붙지 않음).
- Chrome DevTools Protocol로 두 가지를 각각 실제로 확인했습니다: (1) 폼을 채우고
  `attemptConnect()`를 호출해 작업 홈으로 넘어간 뒤 상단이 `SID: ATLASDB1 / 작업 홈` /
  `Service Name: atlaspdb1.example.com / 작업 홈`으로 표시되고 회사명은 어디에도 없음, (2)
  접속 정보가 없는 상태로 `dashboard.html`을 열면 `작업 홈`만 표시됨. "연결 해제" 후
  `sessionStorage`가 실제로 비워지는 것도 확인했습니다 (아래 "검증 결과" 참고).

## 앱 창 크기 · DB 연결 화면 -- OraPulse 실제 소스와 재비교 후 원복

지난 몇 차례 요청(화면의 50% → 45% → 50% → 100%, 스크롤 방지용 CSS 압축 등)으로 이 앱의 창
크기 로직이 실제 참고 대상인 `D:\STMKJHA\00.Git\01.OraPulse`(OraPulse의 진짜 소스)와 점점
멀어졌습니다. OraPulse의 실제 `browser.py`/`public/index.html`을 다시 읽고 비교한 결과:

- **OraPulse의 `browser.py`는 `--window-size`/`--window-position`을 전혀 지정하지 않습니다.**
  `--app=<url>` 만으로 창을 열고, Chrome/Edge가 알아서 창 크기를 정하게 둡니다. 매번 같은
  전용 프로필(`data\browser-profile`)을 재사용하기 때문에, 사용자가 마지막으로 조절한 창
  크기·위치를 브라우저가 자체적으로 기억했다가 다음 실행에 그대로 다시 열어줍니다 -- 별도의
  창 크기 코드가 전혀 필요 없습니다.
- OraPulse의 실제 연결 화면(`public/index.html`)도 이번에 AtlasStudio가 압축했던 것보다 훨씬
  여유 있는 여백/글자 크기를 씁니다(예: `body` 패딩 24px, 브랜드 패널 패딩 48px 36px, 로고
  64×64, 입력창 패딩 12px 14px 등).

그래서 이번에 다음과 같이 **OraPulse 실제 소스에 맞춰 되돌렸습니다**:

1. **`browser.py`에서 창 크기/위치 지정 로직을 전부 제거**했습니다(`_WINDOW_SCREEN_FRACTION`,
   `GetSystemMetrics` 호출, 관련 `ctypes` import 전부 삭제). 이제 OraPulse와 완전히 동일하게
   `--app=<url>`만으로 창을 열며, 창 크기는 Chrome/Edge가 정하고 같은 전용 프로필을 통해
   자연스럽게 기억됩니다.
2. **연결 화면·작업 홈에서 `window.resizeTo()`/`moveTo()`로 창 크기를 직접 바꾸던 JS 로직을
   전부 제거**했습니다(`index.html`/`app.js`의 `resizeAppWindow()`). 화면 전환 시 창 크기가
   더 이상 바뀌지 않습니다 -- OraPulse도 그렇게 동작하지 않습니다.
3. **연결 화면(`index.html`)의 CSS를 OraPulse의 실제 연결 화면과 동일한 여백/글자 크기로
   복원**했습니다(작은 창에 맞춰 압축했던 버전은 폐기). `.shell`의 `max-height`/내부
   `overflow-y` 안전장치도 함께 제거했습니다 -- 더 이상 강제로 작게 만드는 창이 없으므로
   필요하지 않습니다.

결과적으로 창 크기는 Chrome/Edge의 기본 동작(및 프로필별 기억 기능)에 맡기고, 이 앱이 직접
관여하는 부분은 OraPulse와 동일하게 없습니다.

## 실행 방법 (소스)

```powershell
cd D:\STMKJHA\69.DevData
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

서버가 준비되면(uvicorn이 실제로 요청을 받을 수 있는 상태가 된 뒤) 전용 브라우저 앱 창이
자동으로 열립니다 (Chrome/Edge 앱 모드 우선, 못 찾으면 시스템 기본 브라우저) -- **첫 화면은
DB 연결 화면(`index.html`)**이며, "Oracle DB 연결 시작"을 누르면 작업 홈(`dashboard.html`)으로
이동합니다. 콘솔에 출력되는
`http://127.0.0.1:<port>` 주소로 직접 접속해도 됩니다. 포트는 실행마다 사용 가능한 포트 중에서
새로 선택됩니다.

**종료:** 소스 실행 중에는 콘솔에서 Ctrl+C.

**재실행 동작:** AtlasStudio가 이미 실행 중일 때 다시 실행하면 새 서버를 띄우지 않고 기존
인스턴스의 창만 엽니다 (`data/.instance-port` 잠금 파일 + `/api/version`의 `product` 필드로
확인 -- 아래 "OraPulse와의 독립성" 참고).

## 빌드 방법 (폴더형 배포본)

```powershell
cd D:\STMKJHA\69.DevData
.\build-folder.ps1
```

venv가 없으면 스크립트가 자동으로 만들고 의존성(및 PyInstaller)을 설치합니다. 결과물은
`dist\AtlasStudio_ver_<VERSION>\AtlasStudio.exe` 로 생성됩니다. 재실행 가능하며, 버전을
올리고(`VERSION` 파일 수정) 다시 실행하면 새 버전 폴더가 생성됩니다.

배포본 실행 시(패키징 실행)에는 콘솔 창 없이 **시스템 트레이 아이콘**만 표시됩니다.
트레이 메뉴: **창 열기** / **종료**. "종료"를 누르면 서버(uvicorn)와 관련 작업이 정상
종료됩니다.

## 저장 경로

| 상황 | 저장 위치 |
| --- | --- |
| 소스 실행 (`python main.py`) | `main.py` 옆 `data\` (인스턴스 잠금 파일, 전용 브라우저 프로필) |
| 배포 EXE, 쓰기 가능한 위치에 설치됨 | `AtlasStudio.exe` 옆 `data\` |
| 배포 EXE, 설치 위치에 쓰기 권한 없음 (예: Program Files) | `%LOCALAPPDATA%\AtlasStudio\data` (사용자별 저장 경로로 자동 전환) |

두 경우 모두 OraPulse의 `data\`, 암호화 키, 저장된 접속 정보, 브라우저 프로필과는 **완전히
분리**되어 있습니다. `data\`는 삭제해도 앱을 초기 상태로 되돌릴 뿐이며, 실제 사용자 데이터는
들어있지 않습니다(예시 화면 데이터는 `public/data.js`에 소스 코드로만 존재).

## OraPulse와의 독립성

아래 항목을 모두 AtlasStudio 전용으로 분리했습니다 (OraPulse와 공유하는 것이 하나도 없습니다):

| 항목 | AtlasStudio | OraPulse (참고) |
| --- | --- | --- |
| 실행 인스턴스 잠금 파일 | `data\.instance-port` (이 프로젝트 자신의 `data\`) | 별도 `data\.instance-port` |
| 재실행 시 기존 인스턴스 판별 | `/api/version` 응답의 `"product": "AtlasStudio"` 필드까지 확인 (단순 `success` 여부만 보지 않음) | 자체 판별 로직, `product` 필드 없음 |
| 브라우저 프로필 | `data\browser-profile` (이 프로젝트 자신의 `data\`) | 별도 `data\browser-profile` |
| 사용자 데이터/설정 경로 | `%LOCALAPPDATA%\AtlasStudio` (쓰기 불가 시) | `%LOCALAPPDATA%\OraPulse` |
| 트레이 이름/아이콘 | `AtlasStudio`, 전용 `favicon.ico` | `OraPulse`, 전용 `favicon.ico` |
| EXE 이름 / 빌드 산출물 | `AtlasStudio.exe`, `dist\AtlasStudio_ver_*\` | `OraPulse.exe`, `dist\OraPulse_ver_*\` |
| 앱 메타데이터/버전 | 이 프로젝트 자신의 `VERSION` 파일, `FastAPI(title="AtlasStudio", ...)` | 별도 `VERSION`, `title="OraPulse"` |

`/api/version`이 단순히 `{"success": true}`만 보고 "이미 실행 중"이라고 판단하면, 우연히 같은
포트 번호를 다른 로컬 서비스(OraPulse 포함)가 쓰고 있을 때 그 창을 잘못 열어버릴 수 있습니다.
그래서 `main.py`의 `_running_instance_url()`은 `success`와 함께 `product == "AtlasStudio"`를
반드시 확인합니다 (`backend/core.py`의 `PRODUCT_ID`). 이 검사는 OraPulse처럼 `product` 필드가
아예 없는 응답, 또는 다른 값의 `product`를 가진 응답을 모두 "내 인스턴스 아님"으로 정확히
걸러내는 것을 실제로 확인했습니다 (아래 "검증 결과" 참고).

## 파일 구성

| 파일/폴더 | 역할 |
| --- | --- |
| `main.py` | 진입점 -- 단일 인스턴스 판별, 포트 선택, 정적 프런트엔드 마운트, (패키징 시) 트레이 구동. |
| `backend/core.py` | FastAPI 앱 인스턴스, `/api/version`, 앱 버전/제품 식별자. 실제 기능이 생기면 `backend/routes_*.py`를 추가해 여기서 등록. |
| `paths.py` | 소스 실행/패키징 실행 양쪽에서 정적 리소스·저장 경로를 올바르게 찾는 헬퍼. |
| `browser.py` | 전용 브라우저 프로필로 앱 창을 여는 로직 (Chrome/Edge 우선, 없으면 기본 브라우저). |
| `tray.py` | 패키징 실행 시 시스템 트레이 아이콘 (창 열기 / 종료). |
| `public/index.html` | **초기 화면 (DB 연결 화면).** OraPulse의 연결 화면을 본떠 만든 독립된 페이지(자체 `<style>`/`<script>` 포함, `styles.css`/`app.js`와 무관) -- DB Host/IP·Port·접속 방식(SID/Service Name)·계정·비밀번호 입력폼 + 즐겨찾기(브라우저 `localStorage`, 비밀번호 제외). **실제 Oracle 연결은 하지 않는 데모**이며, 형식만 맞으면 접속 방식/SID를 `sessionStorage`에 남기고 `dashboard.html`로 이동합니다. |
| `public/dashboard.html` | 연결 후 이동하는 "작업 홈" 화면 뼈대(빈 컨테이너)만 정의 -- 실제 내용은 `app.js`가 채웁니다. |
| `public/styles.css` | `dashboard.html` 전용 색상·레이아웃·반응형 스타일 전체. |
| `public/data.js` | **메뉴 구성·DB 카드·작업 목록 등 모든 예시 데이터.** 내용을 바꾸거나 항목을 추가/삭제하려면 이 파일만 수정하면 됩니다. |
| `public/icons.js` | 사이드바/카드에서 쓰는 단순 선(line) 아이콘 모음 (외부 아이콘 폰트/CDN 미사용, 인터넷 없이도 표시됨). |
| `public/app.js` | `dashboard.html` 전용. `data.js`의 내용을 화면에 그리고, 비활성 메뉴/버튼에 "준비 중" 토스트를 연결, 상단에 `sessionStorage`에서 읽은 접속 SID/Service Name을 표시, "연결 해제" 버튼으로 그 값을 지우고 `index.html`(연결 화면)로 되돌아가는 동작을 연결. `/api/version`을 불러와 하단 버전 표시만 갱신(유일한 네트워크 요청, 같은 서버로의 요청). |
| `public/favicon.svg` / `public/favicon.ico` | 브라우저 탭 아이콘 / 트레이 아이콘 (로컬 파일, 인터넷 연결 불필요). |
| `requirements.txt` | `fastapi`, `uvicorn`, `pystray`, `Pillow` -- 이번 범위에 필요한 최소 의존성. |
| `AtlasStudio-Folder.spec` | PyInstaller 폴더형 배포본 스펙. |
| `build-folder.ps1` | venv 자동 생성 + PyInstaller 빌드 + 버전 태그 폴더 생성까지 한 번에 처리하는 재실행 가능한 빌드 스크립트. |
| `.gitignore` | `venv/`, `data/`, `logs/`, `build/`, `dist/`, `__pycache__/` 제외. |

메뉴 그룹, DB 카드, 확인이 필요한 작업, 최근 작업 등은 각각 `data.js`의 배열 하나씩과
`app.js`의 렌더 함수 하나씩으로 분리되어 있어, 나중에 실제 기능을 붙일 때 해당 배열/함수만
교체하면 되도록 구성했습니다. 사용하지 않는 기능별 파일(예: `backend/routes_schema_diff.py`
같은 빈 껍데기)은 미리 만들어두지 않았습니다.

## 검증 결과

아래는 실제로 수행한 검증이며, 수행하지 못한 항목은 별도로 명시했습니다.

**실제로 확인함 (현재 루트 위치에서 재검증):**
- **작업 홈 상단의 접속 DB 표시 (회사명 제거)**: Chrome DevTools Protocol로 실제 연결 화면
  폼에 IP/Port/접속방식/SID를 채우고 `attemptConnect()`를 호출해 작업 홈으로 이동시킨 뒤,
  상단에 실제로 `SID: ATLASDB1 / 작업 홈`이 표시되고 회사명은 어디에도 없음을 확인. 접속
  방식을 Service Name으로 바꿔 같은 과정을 반복하니 `Service Name: atlaspdb1.example.com /
  작업 홈`으로 정확히 표시됨을 확인. 접속 정보가 없는 상태로 `dashboard.html`을 직접 열면
  `작업 홈`만(앞에 아무것도 안 붙고) 표시됨도 확인. "연결 해제" 클릭 후
  `sessionStorage.getItem('atlasstudio.currentConnection.v1')`이 `null`로 비워짐도 확인.
- **OraPulse 실제 소스와의 재비교 후 원복**: `D:\STMKJHA\00.Git\01.OraPulse`의 실제
  `browser.py`/`public/index.html`을 다시 읽고, `--window-size`/`--window-position` 및
  `resizeAppWindow()` 관련 코드가 AtlasStudio에만 있고 OraPulse 원본에는 전혀 없음을 확인한 뒤
  전부 제거했습니다. (이전 세션에서 실측했던 "화면 전환 시 창 크기 변경" 동작은 이번에
  제거된 기능이므로 더 이상 유효하지 않습니다 -- 지금은 OraPulse처럼 창 크기를 코드로 바꾸는
  동작 자체가 없습니다.)
- 소스 실행(`python main.py`) 시 서버가 정상 기동하고(`Application startup complete`),
  `/api/version`이 `{"success": true, "product": "AtlasStudio", "version": "0.1.0"}`를
  반환함을 확인.
- `index.html`, `styles.css`, `data.js`, `icons.js`, `app.js`, `favicon.svg` 모두 200 OK로
  서빙됨을 확인.
- 두 번째 인스턴스를 실행하면 새 서버를 띄우지 않고 즉시 종료됨을 확인(기존 인스턴스로 판단,
  잠금 파일 포트 불변).
- venv를 루트에서 새로 생성하고 `requirements.txt`로 의존성을 재설치해 빌드/실행에 사용함
  (예전 위치의 venv를 복사하지 않음).
- PyInstaller 폴더형 배포본을 루트에서 새로 빌드 성공, 패키징 EXE도 위와 동일하게 정상 동작
  확인(정적 리소스/버전 응답/재실행 판별 모두).
- 빌드 산출물에 OraPulse의 데이터·자격증명·즐겨찾기·보고서 등이 전혀 포함되지 않음을 폴더
  목록으로 확인.
- 이번 이전 작업 중 `D:\STMKJHA\00.Git\01.OraPulse`는 어떤 파일도 열람 외에 변경/이동하지
  않았고, `D:\STMKJHA\00.Git\02.AtlasStudio`(1번 옛 위치)도 삭제하지 않고 그대로 보존했습니다.
- 이전 과정에서 대상 루트(`69.DevData`)에 이미 있던 `.gitignore`/`README.md`는 내용을 확인한
  뒤 AtlasStudio 쪽 버전으로 교체했습니다(옛 루트 README는 "# DevData / A repository for the
  source code of my programs."라는 2줄짜리 일반 플레이스홀더였고, 옛 `.gitignore`는 "이전
  위치가 하위 폴더였을 때"만 의미 있던 규칙이라 지금은 그대로 둘 수 없었습니다). 이 교체
  내용은 이 문단에 정직하게 기록해 둡니다.
- 루트에 남아 있던, git이 추적하지 않는 OraPulse 런타임 잔여물(`venv\`, `data\
  browser-profile`, `demo\OraPulse_Demo_ver_1.0051`, `report\`)은 사용자 확인 후 삭제했습니다
  (전부 재생성 가능한 산출물이며, OraPulse의 실제 소스·이력은 `OraPulse` 브랜치에 그대로
  있어 영향이 없습니다).

**미검증 (실제로 수행하지 못함, 정직하게 구분):**
- **git 커밋**: 이 환경에 `git` 실행 파일이 없어(경로 탐색 실패), 이번에 옮긴 내용을
  `AtlasStudio` 브랜치에 실제로 커밋하지 못했습니다. 지금은 워킹 디렉터리에만 존재하는
  미커밋 상태이니, 다른 브랜치로 체크아웃하기 전에 직접 커밋해 두시길 권장합니다.
- **트레이 메뉴("창 열기"/"종료")의 실제 클릭 동작**: GUI 자동화 도구가 없어 사람이 직접
  클릭해 확인하지 못했습니다. 코드 수준에서 OraPulse의 이미 검증된 동일 패턴(`tray.py`)을
  그대로 재사용했고, 프로세스가 정상 기동/구동되는 것까지는 확인했습니다.
- **실제 브라우저 콘솔 오류 유무의 육안 확인 / 창 크기별 겹침**: 이 환경의 PowerShell 셸이
  비대화형 세션이라 직접 확인하지 못했습니다. `styles.css`는 이전 UI 시안 작업 때 이미
  구현해 둔 반응형 동작(1080px/900px/720px/520px 단계적 축소) 그대로이며 이번에
  변경하지 않았습니다.
- MSI/Inno Setup 설치 프로그램, 단일 파일(onefile) EXE는 이번 범위에서 의도적으로 제외했습니다
  (요청사항).
