/* data.js -- every piece of example content shown on the main screen, in
 * one place. This is a UI-only shell (see README.md): nothing here is
 * fetched from a server or a real Oracle instance, so anyone extending
 * this later should only need to touch this file (and, for genuinely new
 * sections, app.js's render*() functions) -- never the markup in
 * index.html directly.
 *
 * All company/DB/task names below are made up for this mockup. Do not
 * put real hostnames, account names, or credentials in this file even
 * temporarily -- see README.md's "예시 데이터" note.
 */

const APP_INFO = {
  name: "AtlasStudio",
  tagline: "Oracle 운영·분석 통합 워크스페이스",
  version: "0.1.0",
  edition: "UI 시안", // shown in the footer -- "design draft", not a shipped build
};

const WORKSPACE = {
  location: "작업 홈",
  user: { initials: "JK", role: "DB 운영 담당자", scope: "로컬 워크스페이스" },
};

// Sidebar structure: a flat list of groups, each with an optional heading
// (null for the top-level "작업 홈" item, which sits directly under the
// small "워크스페이스" label) and a list of menu items. `active: true`
// marks the one and only item that's actually navigable in this UI-only
// build -- see app.js's renderSidebar()/wireInertControls().
const SIDEBAR_MENU = [
  {
    group: null,
    items: [{ id: "home", label: "작업 홈", icon: "home", active: true }],
  },
  {
    group: "비교·변경",
    items: [
      { id: "schema-diff", label: "스키마 비교", icon: "compare" },
      { id: "deploy-check", label: "배포 사전 점검", icon: "shieldCheck" },
      { id: "data-diff", label: "데이터 대사", icon: "listCheck" },
      { id: "change-history", label: "변경 이력", icon: "history" },
    ],
  },
  {
    group: "분석·진단",
    items: [
      { id: "sql-analysis", label: "SQL 분석", icon: "code" },
      { id: "incident-collect", label: "장애 자료 수집", icon: "searchAlert" },
      { id: "lock-session", label: "잠금·세션 기록", icon: "lock" },
    ],
  },
  {
    group: "운영 관리",
    items: [
      { id: "stats", label: "통계정보", icon: "barChart" },
      { id: "capacity-plan", label: "용량·증설 계획", icon: "trendingUp" },
      { id: "backup-check", label: "백업 점검", icon: "archive" },
      { id: "scheduler", label: "배치·스케줄러", icon: "calendarClock" },
      { id: "account-access", label: "계정·권한", icon: "userShield" },
    ],
  },
  {
    group: "문서·고객사",
    items: [
      { id: "handover-doc", label: "인수인계 문서", icon: "fileText" },
      { id: "customer-checkup", label: "고객사 정기점검", icon: "building" },
    ],
  },
];

// Top bar, right side: kept visually close to the design draft's
// "● 연결 3개 / 조회 모드" chips, but every label is explicit about being
// example content -- see requirement #2 ("실제 연결 상태로 오해하지 않도록
// '데모 화면' 표시") in the project brief this was built from.
const TOP_BAR_STATUS = {
  connectionsLabel: "예시 연결 3건",
  modeLabel: "조회 모드",
  demoLabel: "데모 화면",
};

// The three example DB cards. `tone` selects the card's accent color
// scheme (see styles.css's [data-tone] rules) and `status.tone` selects
// just the small status pill's color -- kept separate so a card's overall
// tone (its role: prod/stage/dev) doesn't have to match its current
// status color.
const DB_CARDS = [
  {
    tag: "운영",
    tone: "prod",
    name: "ERP_PROD",
    host: "erp.company.local",
    connectType: "SERVICE_NAME",
    dbVersion: "19c",
    status: { label: "확인 필요 2건", tone: "warning" },
  },
  {
    tag: "검증",
    tone: "stage",
    name: "ERP_STAGE",
    host: "stage.company.local",
    connectType: "SERVICE_NAME",
    dbVersion: "19c",
    status: { label: "최근 점검 정상", tone: "good" },
  },
  {
    tag: "개발",
    tone: "dev",
    name: "ERP_DEV",
    host: "dev.company.local",
    connectType: "SERVICE_NAME",
    dbVersion: "19c",
    status: { label: "연결 정상", tone: "neutral" },
  },
];

const QUICK_ACTIONS_NOTE = "변경 전 확인하는 세 가지";
const QUICK_ACTIONS = [
  { icon: "compare", title: "스키마 비교", desc: "개발과 운영의 구조 차이" },
  { icon: "listCheck", title: "데이터 대사", desc: "이관 전후 데이터 일치 확인" },
  { icon: "fileText", title: "인수인계 문서", desc: "DB 구성과 운영 정보 정리" },
];

const PENDING_TASKS_NOTE = "예시 3건";
const PENDING_TASKS = [
  {
    icon: "alertTriangle",
    tone: "warning",
    title: "ERP 운영·백업 경고",
    desc: "09:00 전체 백업 · 경고 포함 완료",
  },
  {
    icon: "trendingUp",
    tone: "neutral",
    title: "APP_DATA·용량 추세 확인",
    desc: "최근 30일 18GB 증가",
  },
  {
    icon: "compare",
    tone: "neutral",
    title: "9월 배포·스키마 차이 6건",
    desc: "검토 대기 · ERP_DEV → ERP_PROD",
  },
];

const RECENT_ACTIVITY_DATE = "9월 10일";
const RECENT_ACTIVITY = [
  { time: "10:42", title: "스키마 비교 완료", desc: "ERP_DEV → ERP_PROD · 차이 6건" },
  { time: "10:18", title: "월간 정기점검 작성", desc: "한빛제조 · 검토 대기" },
  { time: "09:35", title: "주문 데이터 대사 완료", desc: "ORDERS · 불일치 12건" },
  { time: "09:00", title: "백업 이력 수집", desc: "ERP_PROD · 경고 1건" },
];

// `right` starts from APP_INFO.version (this file's own build-time
// default) and is refreshed once app.js reads the live value back from
// GET /api/version -- see app.js's loadAppVersion(). Kept as a function
// (not a plain string) so that refresh can recompute it without needing
// to touch data.js again.
const FOOTER_STATUS = {
  left: "ORACLE 19c 예시 · ERP 운영 / 검증 / 개발",
  right: (version) => `${APP_INFO.name} v${version || APP_INFO.version} · 예시 데이터 · 실제 DB 작업 없음`,
};
