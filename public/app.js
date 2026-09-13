/* app.js -- renders the main screen from data.js into the empty
 * containers in index.html, and wires every interactive element to the
 * same "준비 중입니다" toast instead of a real action.
 *
 * This is a UI-only mockup (see README.md): the only network call
 * anywhere in this file is loadAppVersion()'s same-origin
 * `fetch("/api/version")` -- this app's own local server, nothing else.
 * There is no XMLHttpRequest, no WebSocket, and no other fetch() call,
 * and it should stay that way: opening this page's Network tab in
 * devtools should show only the local .css/.js files it references plus
 * that one same-origin /api/version request.
 *
 * Rendering is split into one function per section (sidebar / top bar /
 * DB cards / quick actions / pending tasks / recent activity / footer) so
 * adding a new section later means adding one function + one call below,
 * not editing the others.
 */

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else node.setAttribute(key, value);
  }
  for (const child of children || []) {
    if (child == null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

function icon(name, extraClass) {
  return el("span", { class: `icon${extraClass ? " " + extraClass : ""}`, html: ICONS[name] || "" });
}

// ---- Toast: the one feedback mechanism for every non-functional control ----
let toastTimer = null;
function showComingSoon(label) {
  const toast = document.getElementById("toast");
  toast.textContent = label ? `"${label}"은(는) 준비 중인 기능입니다.` : "준비 중인 기능입니다.";
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 2200);
}

// Marks a control as inert: no navigation, no real action, just the toast
// above. Used for every sidebar item except "작업 홈" and every button/card
// in the central content -- see each render function below.
function makeInert(node, label) {
  node.classList.add("is-inert");
  node.setAttribute("aria-disabled", "true");
  node.title = "준비 중인 기능입니다.";
  node.addEventListener("click", (e) => {
    e.preventDefault();
    showComingSoon(label);
  });
  return node;
}

function renderIdStrip() {
  document.getElementById("idStripPath").innerHTML =
    `<b>${APP_INFO.name}</b> / ${APP_INFO.tagline}`;
  document.getElementById("idStripNote").textContent = "디자인 시안 · 예시 데이터";
}

function renderSidebar() {
  const brand = document.getElementById("sidebarBrand");
  brand.appendChild(el("div", { class: "brand-mark" }, ["AS"]));
  brand.appendChild(
    el("div", { class: "brand-text" }, [
      el("h1", {}, [APP_INFO.name]),
      el("p", {}, ["STUDIO"]),
    ])
  );

  const scroll = document.getElementById("sidebarScroll");
  SIDEBAR_MENU.forEach((group) => {
    const groupEl = el("div", { class: "menu-group" });
    if (group.group) {
      groupEl.appendChild(el("div", { class: "menu-group-label" }, [group.group]));
    }
    group.items.forEach((item) => {
      const button = el(
        "button",
        { class: `menu-item${item.active ? " is-active" : ""}`, type: "button" },
        [icon(item.icon), el("span", { class: "label" }, [item.label])]
      );
      if (!item.active) {
        makeInert(button, item.label);
      } else {
        button.disabled = false;
      }
      groupEl.appendChild(button);
    });
    scroll.appendChild(groupEl);
  });

  const userBlock = document.getElementById("sidebarUser");
  userBlock.appendChild(el("div", { class: "sidebar-user-avatar" }, [WORKSPACE.user.initials]));
  userBlock.appendChild(
    el("div", { class: "sidebar-user-meta" }, [
      el("div", { class: "role" }, [WORKSPACE.user.role]),
      el("div", { class: "scope" }, [WORKSPACE.user.scope]),
    ])
  );
}

// The connect screen (index.html) saves whatever SID/Service Name it
// last "connected" with here (see its own saveCurrentConnection()) --
// sessionStorage, not localStorage, since this is this tab's current
// one-off connection, not a saved favorite. Missing/unreadable (e.g.
// dashboard.html opened directly without ever going through the connect
// screen in this session) just means the breadcrumb falls back to
// showing only the location -- never an error.
const CURRENT_CONNECTION_STORAGE_KEY = "atlasstudio.currentConnection.v1";

function loadCurrentConnection() {
  try {
    const raw = sessionStorage.getItem(CURRENT_CONNECTION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (err) {
    return null;
  }
}

function renderTopBar() {
  const breadcrumb = document.getElementById("breadcrumb");
  breadcrumb.appendChild(icon("home"));

  const connection = loadCurrentConnection();
  if (connection && connection.sid) {
    const typeLabel = connection.connectType === "service_name" ? "Service Name" : "SID";
    breadcrumb.appendChild(
      el("span", { class: "breadcrumb-db" }, [`${typeLabel}: ${connection.sid}`])
    );
    breadcrumb.appendChild(el("span", {}, ["/"]));
  }

  breadcrumb.appendChild(el("b", {}, [WORKSPACE.location]));

  const status = document.getElementById("topbarStatus");
  status.appendChild(
    el("span", { class: "pill pill-connections" }, [
      el("span", { class: "pill-dot" }),
      TOP_BAR_STATUS.connectionsLabel,
    ])
  );
  status.appendChild(el("span", { class: "pill" }, [TOP_BAR_STATUS.modeLabel]));
  status.appendChild(el("span", { class: "pill pill-demo" }, [TOP_BAR_STATUS.demoLabel]));

  // No real session to end (see index.html's own comment on why connecting
  // here does nothing but redirect) -- this just sends the browser back to
  // the connect screen, mirroring OraPulse's actual Disconnect button so
  // the demo's "connect -> work -> disconnect" loop feels complete.
  const disconnectBtn = el("button", { class: "btn-disconnect", type: "button" }, ["연결 해제"]);
  disconnectBtn.addEventListener("click", () => {
    try {
      sessionStorage.removeItem(CURRENT_CONNECTION_STORAGE_KEY);
    } catch (err) {
      // Non-critical.
    }
    window.location.href = "index.html";
  });
  status.appendChild(disconnectBtn);
}

function renderHeader() {
  const startBtn = el("button", { class: "btn-primary", type: "button" }, [
    icon("compare"),
    "스키마 비교 시작",
  ]);
  makeInert(startBtn, "스키마 비교 시작");
  document.getElementById("pageHeaderAction").appendChild(startBtn);
}

function renderDbCards() {
  const wrap = document.getElementById("dbCards");
  DB_CARDS.forEach((card) => {
    wrap.appendChild(
      el("div", { class: "db-card", dataset: { tone: card.tone } }, [
        el("div", { class: "db-card-top" }, [
          el("span", { class: "db-card-tag" }, [card.tag]),
          el("span", { class: "db-card-version" }, [
            el("span", { class: "pill-dot" }),
            card.dbVersion,
          ]),
        ]),
        el("p", { class: "db-card-name" }, [card.name]),
        el("p", { class: "db-card-host" }, [card.host]),
        el("div", { class: "db-card-bottom" }, [
          el("span", { class: "db-card-connect-type" }, [card.connectType]),
          el("span", { class: "status-pill", dataset: { tone: card.status.tone } }, [card.status.label]),
        ]),
      ])
    );
  });
}

function renderQuickActions() {
  document.getElementById("quickActionsNote").textContent = QUICK_ACTIONS_NOTE;
  const wrap = document.getElementById("quickActions");
  QUICK_ACTIONS.forEach((action) => {
    const card = el("button", { class: "quick-action-card", type: "button" }, [
      el("span", { class: "quick-action-icon" }, [icon(action.icon)]),
      el("span", {}, [
        el("p", { class: "quick-action-title" }, [action.title]),
        el("p", { class: "quick-action-desc" }, [action.desc]),
      ]),
    ]);
    makeInert(card, action.title);
    wrap.appendChild(card);
  });
}

function renderPendingTasks() {
  document.getElementById("pendingTasksNote").textContent = PENDING_TASKS_NOTE;
  const panel = document.getElementById("pendingTasksPanel");
  PENDING_TASKS.forEach((task) => {
    const link = el("button", { class: "list-row-action", type: "button" }, [
      "확인",
      icon("chevronRight"),
    ]);
    makeInert(link, task.title);
    panel.appendChild(
      el("div", { class: "list-row" }, [
        el("span", { class: "list-row-icon", dataset: { tone: task.tone } }, [icon(task.icon)]),
        el("div", { class: "list-row-body" }, [
          el("div", { class: "list-row-title" }, [task.title]),
          el("div", { class: "list-row-desc" }, [task.desc]),
        ]),
        link,
      ])
    );
  });
}

function renderRecentActivity() {
  document.getElementById("recentActivityNote").textContent = RECENT_ACTIVITY_DATE;
  const panel = document.getElementById("recentActivityPanel");
  RECENT_ACTIVITY.forEach((entry) => {
    panel.appendChild(
      el("div", { class: "list-row" }, [
        el("span", { class: "list-row-time" }, [entry.time]),
        el("div", { class: "list-row-body" }, [
          el("div", { class: "list-row-title" }, [entry.title]),
          el("div", { class: "list-row-desc" }, [entry.desc]),
        ]),
      ])
    );
  });
}

function renderFooter(version) {
  document.getElementById("footerLeft").textContent = FOOTER_STATUS.left;
  document.getElementById("footerRight").textContent = FOOTER_STATUS.right(version);
}

// The footer starts from data.js's own build-time APP_INFO.version, then
// this is the one legitimate network call this page makes: the same-origin
// GET /api/version this app's own local server exposes (see
// backend/core.py), so the footer always reflects the VERSION file the
// running server was actually started with, not a copy baked into data.js
// that could drift out of sync after a rebuild. Silently keeps the
// build-time default if the request fails for any reason (e.g. this file
// opened directly from disk during frontend-only work, with no server
// behind it) -- never blocks rendering on it.
async function loadAppVersion() {
  try {
    const res = await fetch("/api/version");
    const data = await res.json();
    if (data.success && data.version) {
      renderFooter(data.version);
    }
  } catch (err) {
    // Non-critical -- the footer already shows data.js's build-time version.
  }
}

(function init() {
  renderIdStrip();
  renderSidebar();
  renderTopBar();
  renderHeader();
  renderDbCards();
  renderQuickActions();
  renderPendingTasks();
  renderRecentActivity();
  renderFooter();
  loadAppVersion();
})();
