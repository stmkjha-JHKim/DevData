# OraPulse

OraPulse는 Windows PC에서 직접 실행하는 **Oracle Database 모니터링 클라이언트**입니다. 별도의 중앙 서버나 계정 시스템 없이 로컬 앱이 사용자가 지정한 Oracle Database에 직접 연결하며, 관리 화면은 기본 브라우저에서 열립니다.

![OraPulse Oracle Database 연결 화면](screenshots/OraPulse-connect.png)

## 주요 기능

- 인스턴스 정보, CPU·메모리, 세션, Blocking Session, Long Running Session 및 대기 이벤트 확인
- 테이블 통계정보 수집 상태, Invalid Object 및 Alert Log 확인
- 주요 SQL, Instance Efficiency, Load Profile, 주요 파라미터, Undo·TEMP·Redo 및 I/O 상태 확인
- FRA 사용량과 최근 DML 확인
- SELECT 전용 SQL Query Runner
- 한국어·영어 화면 지원
- 자주 사용하는 접속 정보의 로컬 암호화 저장

## 지원 환경

- 64비트 Windows 10 또는 Windows 11
- Oracle Database 12.1 이상
- PC에서 대상 Oracle Listener의 IP와 포트로 연결할 수 있는 네트워크 환경
- 모니터링 항목에 필요한 Oracle 조회 권한

Python, Node.js 또는 Oracle Instant Client를 별도로 설치할 필요가 없습니다.

## 설치 및 실행

1. Releases에서 `OraPulse_Windows.zip`을 내려받습니다.
2. ZIP 파일의 압축을 원하는 폴더에 풉니다. ZIP 안에서 직접 실행하지 마세요.
3. `OraPulse.exe`를 더블클릭합니다.
4. 기본 브라우저에 Oracle Database 연결 화면이 자동으로 열립니다.
5. DB Host/IP, Port, SID/Instance, Oracle 계정과 비밀번호를 입력한 뒤 **Oracle DB 연결 시작**을 선택합니다.

앱이 실행 중일 때는 Windows 알림 영역에 OraPulse 아이콘이 표시됩니다. 화면을 다시 열려면 아이콘의 **Open OraPulse**, 종료하려면 **Exit**를 선택하세요.

## Windows 보안 알림

현재 배포 파일에는 디지털 서명이 없습니다. 따라서 첫 실행 시 Microsoft Defender SmartScreen이 “인식할 수 없는 앱” 경고를 표시할 수 있습니다.

파일을 공식 배포 페이지에서 받았는지 확인하고, 아래 SHA-256 값과 다운로드한 파일의 값이 같은 경우에만 실행하세요. 신뢰할 수 없는 출처의 파일은 실행하지 마세요.

```text
20B3EE8F31FF918F913C2B29C4AA19B36137E0D002A4ECDD6CB07308CEA2A28E  OraPulse.exe
```

PowerShell에서 확인하는 방법:

```powershell
Get-FileHash .\OraPulse.exe -Algorithm SHA256
```

## Oracle Database 연결 권한

OraPulse는 입력한 Oracle 계정으로 접속합니다. 일반 계정도 연결할 수 있지만, 대부분의 모니터링 항목이 `V$` 및 `DBA_` 뷰를 조회하므로 SYSTEM 수준의 조회 권한이 권장됩니다. 권한이 부족하면 해당 항목에 권한 안내가 표시됩니다.

세션 강제 종료와 통계정보 수집처럼 데이터베이스 상태를 변경하는 작업은 별도의 Oracle 권한이 필요하며, 사용자가 화면에서 직접 실행할 때만 수행됩니다. SQL Query Runner는 SELECT문만 허용합니다.

## 개인정보 및 접속 정보

- 앱 서버는 `127.0.0.1`에서만 실행되며(실행할 때마다 사용 가능한 포트를 자동으로 고름), 다른 PC에 공개되지 않습니다.
- 입력한 DB 접속 정보는 OraPulse에서 외부 서비스로 전송되지 않습니다.
- 즐겨찾기를 저장하면 비밀번호를 포함한 접속 정보가 실행 파일 옆 `data` 폴더에 암호화되어 저장됩니다.
- 공용 PC에서는 즐겨찾기 저장을 권장하지 않습니다. `data` 폴더와 암호화 키를 함께 복사하거나 공유하지 마세요.

## 종료 및 삭제

Windows 알림 영역의 OraPulse 아이콘을 우클릭하고 **Exit**를 선택합니다. 삭제하려면 앱 종료 후 압축을 풀었던 폴더 전체를 삭제합니다. `data` 폴더를 삭제하면 저장된 즐겨찾기와 로컬 기록도 함께 삭제됩니다.

## 알려진 제한 사항

- Oracle Database 11g 이하는 지원하지 않습니다.
- 점검레포트 생성 기능은 현재 Windows EXE 버전에 포함되어 있지 않습니다.
- 디지털 서명이 없어 Windows에서 처음 실행할 때 보안 경고가 나타날 수 있습니다.

## 문의 및 오류 신고

배포 페이지의 **Issues** 탭에서 새 문의를 등록해 주세요. 문의에는 아래 내용을 포함하면 확인이 빠릅니다.

- OraPulse 버전
- Windows 버전
- Oracle Database 버전
- 오류가 발생한 화면과 재현 순서
- 전체 오류 메시지 또는 비밀번호가 보이지 않는 화면 캡처

DB 비밀번호, 실제 내부 IP, 개인정보 또는 업무상 민감한 데이터는 등록하지 마세요.

