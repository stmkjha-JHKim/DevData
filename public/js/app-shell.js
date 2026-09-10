  const TABS = {
    main: {
      btn: document.getElementById('tabBtnMain'),
      panel: document.getElementById('tabPanelMain')
      // Main's data loads as part of the regular loadStatus()/auto-refresh cycle, not here.
    },
    ops: {
      btn: document.getElementById('tabBtnOps'),
      panel: document.getElementById('tabPanelOps'),
      loaded: false,
      load: loadOpsUsage
    },
    recovery: {
      btn: document.getElementById('tabBtnRecovery'),
      panel: document.getElementById('tabPanelRecovery'),
      loaded: false,
      load: loadRecoveryUsage
    },
    tuning: {
      btn: document.getElementById('tabBtnTuning'),
      panel: document.getElementById('tabPanelTuning'),
      loaded: false,
      load: loadTuningCheck
    },
    objectview: {
      btn: document.getElementById('tabBtnObjectView'),
      panel: document.getElementById('tabPanelObjectView'),
      loaded: false,
      load: loadObjectViewOwners
      // The SQL Query Runner card lives in this same tab now (merged with
      // what used to be a separate SQL tab) but has no data to lazily load
      // on first visit -- it only shows results once the user runs a
      // query -- so `load` here only ever populates the object explorer's
      // owner list, and (like Temp/Recovery) this tab is never touched by
      // the 15s auto-refresh timer, which only ever calls loadStatus()
      // (Main tab data).
    },
    help: {
      btn: document.getElementById('tabBtnHelp'),
      panel: document.getElementById('tabPanelHelp')
      // Static content, already in the page markup -- nothing to load.
    }
  };

  function switchTab(tab) {
    if (!TABS[tab]) return;
    Object.keys(TABS).forEach(key => {
      const isActive = key === tab;
      TABS[key].btn.classList.toggle('active', isActive);
      TABS[key].panel.hidden = !isActive;
    });
    const entry = TABS[tab];
    if (entry.load && !entry.loaded) {
      entry.loaded = true;
      entry.load();
    }
  }

  Object.keys(TABS).forEach(key => {
    TABS[key].btn.addEventListener('click', () => switchTab(key));
  });

  // --- Card drag-and-drop reordering / cross-tab moving ---
  // Every card can be dragged (via the small grip handle added to its
  // header below) to reorder it within a tab, or dropped onto a different
  // tab's button to move it there. The resulting per-tab card order is
  // persisted to localStorage (like the language preference above) so it
  // survives app restarts, and cards can move freely between all three tabs.
  //
  // Implementation notes:
  // - Uses the Pointer Events API so the same code handles mouse and touch.
  // - Each card's identity is its `data-card-id` (derived from its
  //   `dot-<id>`/`box-<id>` element ids, which every card already has), not
  //   its DOM position -- so rendering code elsewhere (which all targets
  //   elements by id via getElementById/querySelector) keeps working no
  //   matter where a card has been dragged to.
  // - Since Main's cards are populated by the always-running 15s
  //   auto-refresh regardless of which tab is visible, a Main card dragged
  //   into Temp/Recovery just keeps updating normally. Going the other way
  //   (a Temp/Recovery card dragged into Main) would otherwise never load
  //   its data unless the user happens to visit its original tab -- see
  //   ensureLoadedForRelocatedCards() below, which handles that.

  // Bumped (V2, then V3, then V4) each time a tab's default card order was
  // intentionally redesigned -- a saved layout otherwise wins over the
  // default for any card it already lists (see applyCardLayout()'s merge
  // below), which would silently keep old installs on the pre-redesign
  // order forever. Bump this again for any future deliberate default-order
  // change; simple additions/relocations of individual cards don't need it
  // (CARD_HOME_TAB already handles those without discarding the user's
  // whole layout).
  const CARD_LAYOUT_KEY = 'orapulseCardLayoutV4';
  const DEFAULT_CARD_LAYOUT = {
    main: ['instance', 'combo', 'sessionlist', 'blocking', 'longops', 'tablestats', 'jobfailures', 'accountsecurity', 'alertlog'],
    ops: ['keyparams', 'undoconfig', 'instanceeff', 'loadprofile', 'tempspace', 'tempsession', 'autoextend', 'redolog', 'tablespaceio', 'topqueries', 'topqueriescpu', 'topqueriesgets', 'waitevent'],
    recovery: ['recentdml', 'recoverydest', 'recoverytype']
    // No 'objectview' entry: that tab (object explorer + SQL Query Runner)
    // is a fixed layout, not a rearrangeable dashboard, so its cards are
    // deliberately outside this drag-and-drop/reorder system -- see
    // ensureLoadedForRelocatedCards()'s own guard for the same reasoning.
  };
  const ALL_CARD_IDS = new Set();
  Object.values(DEFAULT_CARD_LAYOUT).forEach(ids => ids.forEach(id => ALL_CARD_IDS.add(id)));

  // Which tab each card currently belongs to by default -- used to detect a
  // saved layout entry left over from before an app update moved a card to
  // a different tab (e.g. Top 5 Wait Events: Main -> Ops). Without this, a
  // user's old localStorage layout would keep pulling the card back to its
  // former tab forever, silently overriding the new default on every load.
  const CARD_HOME_TAB = {};
  Object.keys(DEFAULT_CARD_LAYOUT).forEach(tabKey => {
    DEFAULT_CARD_LAYOUT[tabKey].forEach(id => { CARD_HOME_TAB[id] = tabKey; });
  });

  function getTabGrid(tabKey) {
    return TABS[tabKey].panel.querySelector('.grid');
  }

  function getActiveTabKey() {
    return Object.keys(TABS).find(k => TABS[k].btn.classList.contains('active'));
  }

  // Tags each card with a stable data-card-id (read off its existing
  // dot-<id> element, so no separate id list needs to be kept in sync by
  // hand) and inserts a small grip handle at the start of its header --
  // inside .h2-left when present (cards with a badge/button on the right,
  // which use justify-content: space-between), otherwise directly in <h2>.
  function initCardDragHandles() {
    document.querySelectorAll('.tab-panel .grid > .card').forEach(card => {
      const dot = card.querySelector('.status-dot[id^="dot-"]');
      if (!dot) return; // every current card has one; skip defensively if a future card doesn't
      const cardId = dot.id.replace(/^dot-/, '');
      // Object View / SQL Query Runner (and any future card like them) are
      // deliberately outside the reorder/persistence system -- see
      // DEFAULT_CARD_LAYOUT's own comment -- so they get no drag handle at
      // all, rather than one that would visually invite dragging but snap
      // back to its fixed spot on the next reload regardless.
      if (!ALL_CARD_IDS.has(cardId)) return;
      card.setAttribute('data-card-id', cardId);

      const h2 = card.querySelector('h2');
      if (!h2 || h2.querySelector('.card-drag-handle')) return;
      const handle = document.createElement('span');
      handle.className = 'card-drag-handle';
      handle.setAttribute('data-i18n-title', 'dragHandleTitle');
      handle.title = t('dragHandleTitle');
      handle.textContent = '⠿';
      const leftGroup = h2.querySelector('.h2-left') || h2;
      leftGroup.insertBefore(handle, leftGroup.firstChild);

      handle.addEventListener('pointerdown', (e) => {
        if (e.button > 0) return; // left mouse button / touch / pen only, not right/middle-click
        e.preventDefault();
        try { handle.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
        startCardDrag(e, card);
      });
      handle.addEventListener('pointermove', (e) => {
        if (cardDragState && cardDragState.pointerId === e.pointerId) updateCardDragPosition(e);
      });
      handle.addEventListener('pointerup', (e) => {
        if (cardDragState && cardDragState.pointerId === e.pointerId) endCardDrag();
      });
      handle.addEventListener('pointercancel', (e) => {
        if (cardDragState && cardDragState.pointerId === e.pointerId) endCardDrag();
      });
    });
  }

  let cardDragState = null; // { card, placeholder, pointerId, offsetX, offsetY, tabHoverKey, tabHoverTimer }

  function startCardDrag(e, card) {
    if (cardDragState) return;
    const rect = card.getBoundingClientRect();

    // The card is deliberately NOT reparented to <body> here, even though
    // it's visually floating via position:fixed for the rest of the drag --
    // removing+reinserting the pointer-capturing element mid-gesture causes
    // Chromium (and other engines) to silently release pointer capture,
    // which would strand the card mid-drag with no pointerup ever firing.
    // It's left as a sibling of its own placeholder inside its original
    // grid; position:fixed already excludes it from grid layout, so this
    // doesn't visually double up the space. The one-time reparent into
    // wherever the placeholder ends up happens in endCardDrag(), after the
    // gesture (and the need for capture) is already over.
    const placeholder = document.createElement('div');
    placeholder.className = 'card-drag-placeholder';
    if (card.classList.contains('card-wide')) placeholder.classList.add('card-wide');
    placeholder.style.height = `${rect.height}px`;
    card.parentNode.insertBefore(placeholder, card.nextSibling);

    card.classList.add('dragging');
    card.style.width = `${rect.width}px`;
    card.style.height = `${rect.height}px`;
    card.style.left = `${rect.left}px`;
    card.style.top = `${rect.top}px`;

    cardDragState = {
      card,
      placeholder,
      pointerId: e.pointerId,
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
      tabHoverKey: null,
      tabHoverTimer: null
    };
    document.body.classList.add('card-drag-active');
  }

  function updateCardDragPosition(e) {
    const state = cardDragState;
    if (!state) return;
    state.card.style.left = `${e.clientX - state.offsetX}px`;
    state.card.style.top = `${e.clientY - state.offsetY}px`;

    const elUnderPointer = document.elementFromPoint(e.clientX, e.clientY);

    // Hovering a *different* tab's button for a short moment switches to
    // it, so the card can be dropped there -- the placeholder (marking the
    // drop position) moves along with the switch.
    const tabBtn = elUnderPointer && elUnderPointer.closest('.tab-btn');
    const hoverTabKey = tabBtn ? tabBtn.getAttribute('data-tab') : null;
    const activeTabKey = getActiveTabKey();

    document.querySelectorAll('.tab-btn.drag-hover').forEach(b => b.classList.remove('drag-hover'));

    if (hoverTabKey && hoverTabKey !== activeTabKey) {
      tabBtn.classList.add('drag-hover');
      if (state.tabHoverKey !== hoverTabKey) {
        state.tabHoverKey = hoverTabKey;
        clearTimeout(state.tabHoverTimer);
        state.tabHoverTimer = setTimeout(() => {
          if (!cardDragState || cardDragState.tabHoverKey !== hoverTabKey) return;
          switchTab(hoverTabKey);
          getTabGrid(hoverTabKey).appendChild(state.placeholder);
        }, 450);
      }
    } else {
      state.tabHoverKey = null;
      clearTimeout(state.tabHoverTimer);
    }

    // Reposition the placeholder within whichever grid is currently
    // visible, based on which card (if any) the pointer is over.
    const grid = getTabGrid(getActiveTabKey());
    const targetCard = elUnderPointer && elUnderPointer.closest('.card');
    if (targetCard && targetCard !== state.card && grid.contains(targetCard)) {
      const targetRect = targetCard.getBoundingClientRect();
      const isWide = targetCard.classList.contains('card-wide');
      const before = isWide
        ? (e.clientY < targetRect.top + targetRect.height / 2)
        : (e.clientX < targetRect.left + targetRect.width / 2);
      grid.insertBefore(state.placeholder, before ? targetCard : targetCard.nextSibling);
    } else if (state.placeholder.parentNode !== grid) {
      grid.appendChild(state.placeholder);
    }
  }

  function endCardDrag() {
    const state = cardDragState;
    if (!state) return;
    clearTimeout(state.tabHoverTimer);
    document.querySelectorAll('.tab-btn.drag-hover').forEach(b => b.classList.remove('drag-hover'));

    state.placeholder.parentNode.insertBefore(state.card, state.placeholder);
    state.placeholder.remove();
    state.card.classList.remove('dragging');
    state.card.style.position = '';
    state.card.style.left = '';
    state.card.style.top = '';
    state.card.style.width = '';
    state.card.style.height = '';
    document.body.classList.remove('card-drag-active');

    cardDragState = null;
    saveCardLayout();
    ensureLoadedForRelocatedCards();
  }

  // Reads the *actual* current DOM placement of cards across all three tabs
  // (the source of truth once drag-and-drop has happened).
  function captureCurrentLayout() {
    const layout = {};
    Object.keys(TABS).forEach(tabKey => {
      layout[tabKey] = Array.from(getTabGrid(tabKey).children)
        .filter(el => el.classList.contains('card'))
        .map(el => el.getAttribute('data-card-id'));
    });
    return layout;
  }

  function saveCardLayout() {
    try {
      localStorage.setItem(CARD_LAYOUT_KEY, JSON.stringify(captureCurrentLayout()));
    } catch (_) {
      // localStorage can throw in some restricted browser contexts -- the
      // new layout still applies for the rest of this session, it just
      // won't be remembered on next launch.
    }
  }

  function loadSavedCardLayout() {
    try {
      const raw = localStorage.getItem(CARD_LAYOUT_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return (parsed && typeof parsed === 'object') ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  // Moves each card's actual DOM node (not a clone, so ids/listeners are
  // untouched) into the tab/position recorded in `layout`. This is a merge,
  // not a blind replay of `layout`: for each tab, DEFAULT_CARD_LAYOUT[tabKey]
  // is walked in its default order as the skeleton, and at every slot whose
  // card the user has an explicit saved position for (present in `layout`
  // AND still belonging to this tab per CARD_HOME_TAB -- a stale entry left
  // over from before an app update relocated the card to a different tab is
  // treated as absent, not honored), that slot is filled from the saved
  // order instead. A card missing from the saved layout entirely (new since
  // it was saved, e.g. a card an app update added or relocated here) simply
  // keeps its default position, rather than being incidentally shoved to
  // one end of the tab by every other, known card getting moved around it.
  function applyCardLayout(layout) {
    if (!layout) return;
    Object.keys(DEFAULT_CARD_LAYOUT).forEach(tabKey => {
      const grid = getTabGrid(tabKey);
      const wanted = Array.isArray(layout[tabKey]) ? layout[tabKey] : [];
      const known = [];
      const seen = new Set();
      wanted.forEach(cardId => {
        if (CARD_HOME_TAB[cardId] === tabKey && !seen.has(cardId)) {
          known.push(cardId);
          seen.add(cardId);
        }
      });
      const knownQueue = known.slice();
      const finalOrder = DEFAULT_CARD_LAYOUT[tabKey].map(
        defaultId => (seen.has(defaultId) ? knownQueue.shift() : defaultId)
      );
      finalOrder.forEach(cardId => {
        const card = document.querySelector(`.card[data-card-id="${cardId}"]`);
        if (card) grid.appendChild(card);
      });
    });
  }

  // If a Temp/Recovery card has been relocated out of its home tab (either
  // by a saved layout applied at startup, or by a drag-drop that just
  // happened) and that tab hasn't loaded its data yet, load it right away
  // instead of waiting for the user to happen to click that tab -- otherwise
  // the relocated card would be stuck on "Loading..." indefinitely.
  function ensureLoadedForRelocatedCards() {
    const currentLayout = captureCurrentLayout();
    Object.keys(TABS).forEach(tabKey => {
      const entry = TABS[tabKey];
      if (!entry.load || entry.loaded) return;
      // Tabs outside the drag-and-drop card system (e.g. Object View,
      // whose single card is a fixed explorer/viewer tool rather than a
      // reorderable data card) have no DEFAULT_CARD_LAYOUT entry -- their
      // card can never have been "relocated" away, so there's nothing to
      // check here; they still load normally the first time their tab is
      // opened, via switchTab()'s own entry.load() call.
      if (!DEFAULT_CARD_LAYOUT[tabKey]) return;
      const stillHome = DEFAULT_CARD_LAYOUT[tabKey].every(id => currentLayout[tabKey].includes(id));
      if (!stillHome) {
        entry.loaded = true;
        entry.load();
      }
    });
  }

  initCardDragHandles();
  applyCardLayout(loadSavedCardLayout());
  ensureLoadedForRelocatedCards();

  // Table Statistics Collection card: the user (OWNER) list is loaded only once when the page loads,
  // and the actual table list is fetched only when a user is selected in the select box.
  const tableStatsOwnerSelect = document.getElementById('tableStatsOwnerSelect');
  const boxTableStats = document.getElementById('box-tablestats');
  function TABLE_STATS_EMPTY_MSG() {
    return `<div class="empty-msg">${t('tableStatsSelectPrompt')}</div>`;
  }

  async function loadTableOwners() {
    setDot('tablestats', 'loading');
    try {
      const res = await fetch('/api/table-owners');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('tablestats', 'error');
        tableStatsOwnerSelect.innerHTML = `<option value="">${t('tableOwnersLoadFailedOption')}</option>`;
        boxTableStats.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      setDot('tablestats', 'ok');
      const options = data.data
        .map(owner => `<option value="${escapeHtml(owner)}">${escapeHtml(owner)}</option>`)
        .join('');
      tableStatsOwnerSelect.innerHTML = `<option value="">${t('selectUserPlaceholder')}</option>${options}`;
    } catch (err) {
      setDot('tablestats', 'error');
      boxTableStats.innerHTML = `<div class="empty-msg">${t('tableOwnersLoadFailedMsg', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  async function loadTableStats(owner) {
    if (!owner) {
      lastTableStatsOwner = null;
      lastTableStatsData = null;
      boxTableStats.innerHTML = TABLE_STATS_EMPTY_MSG();
      return;
    }
    boxTableStats.innerHTML = `<div class="skeleton">${t('loadingLabel')}</div>`;
    try {
      const res = await fetch(`/api/table-stats?owner=${encodeURIComponent(owner)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('tablestats', 'error');
        boxTableStats.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      lastTableStatsOwner = owner;
      lastTableStatsData = data;
      setDot('tablestats', 'ok');
      if (!data.data.length) {
        boxTableStats.innerHTML = `<div class="empty-msg">${t('tableStatsNoTablesForOwner', { owner: escapeHtml(owner) })}</div>`;
        return;
      }
      const rows = data.data.map(row => `
        <tr class="ctx-row" data-owner="${escapeHtml(owner)}" data-table="${escapeHtml(row.TABLE_NAME)}" data-partition="${escapeHtml(row.PARTITION_NAME || '')}" title="${escapeHtml(t('tableRowTooltip'))}">
          <td class="ts-check-col"><input type="checkbox" class="ts-row-check" data-table="${escapeHtml(row.TABLE_NAME)}" data-partition="${escapeHtml(row.PARTITION_NAME || '')}"></td>
          <td>${escapeHtml(row.TABLE_NAME)}</td>
          <td>${escapeHtml(row.PARTITION_NAME || '-')}</td>
          <td>${escapeHtml(row.TABLESPACE_NAME || '-')}</td>
          <td>${row.NUM_ROWS === null ? '-' : Number(row.NUM_ROWS).toLocaleString()}</td>
          <td>${row.BLOCKS === null ? '-' : Number(row.BLOCKS).toLocaleString()}</td>
          <td>${row.CHAIN_CNT === null ? '-' : Number(row.CHAIN_CNT).toLocaleString()}</td>
          <td>${escapeHtml(row.LAST_ANALYZED || t('noCollectionHistory'))}</td>
        </tr>`).join('');
      const note = data.truncated
        ? `<div class="sess-table-note">${t('tableStatsTruncatedNote', { n: Number(data.totalCount).toLocaleString() })}</div>`
        : '';
      boxTableStats.innerHTML = `
        <div class="ts-batch-bar">
          <button type="button" class="primary" id="tableStatsBatchBtn" disabled>${t('btnGatherSelected')}</button>
          <span class="ts-batch-count" id="tableStatsBatchCount">${t('selectedCount', { n: 0 })}</span>
        </div>
        <div class="sess-table-wrap">
          <table class="sess-table">
            <thead><tr>
              <th class="ts-check-col"><input type="checkbox" class="ts-select-all" id="tableStatsSelectAll" title="${escapeHtml(t('selectAllTitle'))}"></th>
              <th>${t('tableNameHeader')}</th><th>${t('partitionNameHeader')}</th><th>${t('tablespaceNameHeader')}</th>
              <th>${t('numRowsHeader')}</th><th>${t('blocksHeader')}</th><th>${t('chainCntHeader')}</th><th>${t('lastAnalyzedHeader')}</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        ${note}
        <div id="tableStatsBatchResult"></div>`;
    } catch (err) {
      setDot('tablestats', 'error');
      boxTableStats.innerHTML = `<div class="empty-msg">${t('tableStatsLoadFailedMsg', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  tableStatsOwnerSelect.addEventListener('change', () => loadTableStats(tableStatsOwnerSelect.value));

  // Right-clicking a row in the table statistics collection grid opens a custom
  // context menu ("Gather Statistics"), and clicking it runs DBMS_STATS.GATHER_TABLE_STATS.
  // Since box-tablestats is entirely replaced via innerHTML on every refresh,
  // the event is delegated to the fixed parent element (box-tablestats), just like the session list.
  const toast = document.getElementById('toast');
  let toastTimer = null;
  function showToast(message, type) {
    toast.textContent = message;
    toast.className = `toast show ${type === 'error' ? 'error' : 'ok'}`;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.classList.remove('show'); }, 6000);
  }

  const tableStatsCtxMenu = document.getElementById('tableStatsCtxMenu');
  const tableStatsCtxMenuTitle = document.getElementById('tableStatsCtxMenuTitle');
  const tableStatsCtxMenuGather = document.getElementById('tableStatsCtxMenuGather');
  const tableStatsCtxMenuProperties = document.getElementById('tableStatsCtxMenuProperties');
  let ctxTarget = null; // { owner, tableName, partitionName }

  function closeTableStatsCtxMenu() {
    tableStatsCtxMenu.classList.remove('show');
    ctxTarget = null;
  }

  function openTableStatsCtxMenu(x, y, owner, tableName, partitionName) {
    ctxTarget = { owner, tableName, partitionName };
    tableStatsCtxMenuTitle.textContent = partitionName
      ? `${owner}.${tableName} (${partitionName})`
      : `${owner}.${tableName}`;
    tableStatsCtxMenuGather.disabled = false;
    tableStatsCtxMenuGather.textContent = t('btnGatherStats');
    tableStatsCtxMenuProperties.disabled = false;
    tableStatsCtxMenuProperties.textContent = t('btnViewTableProperties');
    tableStatsCtxMenu.classList.add('show');
    // Adjust the position so the menu doesn't go off-screen.
    const menuW = tableStatsCtxMenu.offsetWidth || 240;
    const menuH = tableStatsCtxMenu.offsetHeight || 80;
    const left = Math.min(x, window.innerWidth - menuW - 8);
    const top = Math.min(y, window.innerHeight - menuH - 8);
    tableStatsCtxMenu.style.left = `${Math.max(8, left)}px`;
    tableStatsCtxMenu.style.top = `${Math.max(8, top)}px`;
  }

  // Long-press support (touch devices) for this context menu too -- see the
  // watchLongPress() definition further below, near the session list
  // context menu, for why this is needed on top of 'contextmenu'.
  let tableStatsCtxFiredByTouch = false;

  watchLongPress(boxTableStats, 'tr.ctx-row', (tr, x, y) => {
    tableStatsCtxFiredByTouch = true;
    openTableStatsCtxMenu(
      x, y,
      tr.getAttribute('data-owner'),
      tr.getAttribute('data-table'),
      tr.getAttribute('data-partition') || ''
    );
  });

  boxTableStats.addEventListener('contextmenu', (e) => {
    const tr = e.target.closest('tr.ctx-row');
    if (!tr) return;
    e.preventDefault();
    if (tableStatsCtxFiredByTouch) {
      tableStatsCtxFiredByTouch = false;
      return;
    }
    openTableStatsCtxMenu(
      e.clientX, e.clientY,
      tr.getAttribute('data-owner'),
      tr.getAttribute('data-table'),
      tr.getAttribute('data-partition') || ''
    );
  });

  document.addEventListener('click', (e) => {
    if (tableStatsCtxMenu.classList.contains('show') && !tableStatsCtxMenu.contains(e.target)) {
      closeTableStatsCtxMenu();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && tableStatsCtxMenu.classList.contains('show')) closeTableStatsCtxMenu();
  });
  // Close the menu on scroll/refresh so a misplaced menu doesn't stay open.
  window.addEventListener('scroll', closeTableStatsCtxMenu, true);

  tableStatsCtxMenuGather.addEventListener('click', async () => {
    if (!ctxTarget) return;
    const { owner, tableName, partitionName } = ctxTarget;
    const label = partitionName ? `${owner}.${tableName} (${partitionName})` : `${owner}.${tableName}`;
    if (!confirm(t('confirmGatherSingle', { label }))) {
      closeTableStatsCtxMenu();
      return;
    }
    tableStatsCtxMenuGather.disabled = true;
    tableStatsCtxMenuGather.textContent = t('collectingLabel');
    try {
      const res = await fetch('/api/gather-table-stats', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner, tableName, partitionName: partitionName || undefined })
      });
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      showToast(data.message, data.success ? 'ok' : 'error');
      if (data.success) {
        // Reload the current user's list since the collection history (LAST_ANALYZED) has changed.
        loadTableStats(tableStatsOwnerSelect.value);
      }
    } catch (err) {
      showToast(t('requestStatsFailed', { msg: err.message }), 'error');
    } finally {
      closeTableStatsCtxMenu();
    }
  });

  tableStatsCtxMenuProperties.addEventListener('click', () => {
    if (!ctxTarget) return;
    const { owner, tableName, partitionName } = ctxTarget;
    closeTableStatsCtxMenu();
    openTablePropertiesModal(owner, tableName, partitionName);
  });

  // Multi-select batch statistics collection: checkboxes on each row
  // ("select all" in the header, or individual rows) plus a
  // "Gather Statistics for Selected" button that runs all of them in a
  // single request. Since box-tablestats is entirely rebuilt via innerHTML
  // on every load/refresh, all of this is delegated to the fixed parent
  // element, matching the pattern used for the context menu above.
  function updateTableStatsBatchUI() {
    const checks = boxTableStats.querySelectorAll('input.ts-row-check');
    const checked = boxTableStats.querySelectorAll('input.ts-row-check:checked');
    const batchBtn = document.getElementById('tableStatsBatchBtn');
    const batchCount = document.getElementById('tableStatsBatchCount');
    if (batchBtn) batchBtn.disabled = checked.length === 0;
    if (batchCount) batchCount.textContent = t('selectedCount', { n: checked.length });
    const selectAll = document.getElementById('tableStatsSelectAll');
    if (selectAll) {
      selectAll.checked = checks.length > 0 && checked.length === checks.length;
      selectAll.indeterminate = checked.length > 0 && checked.length < checks.length;
    }
  }

  boxTableStats.addEventListener('change', (e) => {
    if (e.target.classList.contains('ts-select-all')) {
      const checked = e.target.checked;
      boxTableStats.querySelectorAll('input.ts-row-check').forEach(cb => { cb.checked = checked; });
      updateTableStatsBatchUI();
    } else if (e.target.classList.contains('ts-row-check')) {
      updateTableStatsBatchUI();
    }
  });

  function renderTableStatsBatchResult(results, owner) {
    const container = document.getElementById('tableStatsBatchResult');
    if (!container) return;
    const rowsHtml = results.map(r => {
      const label = r.partitionName ? `${r.tableName} (${r.partitionName})` : r.tableName;
      return `
        <div class="ts-batch-result-row ${r.ok ? 'ok' : 'fail'}">
          <span class="icon">${r.ok ? '✓' : '✕'}</span>
          <span><strong>${escapeHtml(label)}</strong> <span class="msg">${escapeHtml(r.message)}</span></span>
        </div>`;
    }).join('');
    // The table above is left as-is (still showing the pre-collection
    // LAST_ANALYZED values) rather than auto-reloaded, so these results
    // stay visible instead of being wiped out immediately. Refresh
    // explicitly (via the button below, or by reselecting the owner) once
    // you're done reading them.
    container.innerHTML = `
      <div class="sess-filter-row" style="margin-top: 10px; margin-bottom: 0;">
        <button type="button" class="sess-filter-reset" id="tableStatsBatchRefreshBtn">${t('btnRefreshList')}</button>
      </div>
      <div class="ts-batch-result">${rowsHtml}</div>`;
    const refreshBtn = document.getElementById('tableStatsBatchRefreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => loadTableStats(owner));
    }
  }

  boxTableStats.addEventListener('click', async (e) => {
    const btn = e.target.closest('#tableStatsBatchBtn');
    if (!btn) return;

    const owner = tableStatsOwnerSelect.value;
    const checked = Array.from(boxTableStats.querySelectorAll('input.ts-row-check:checked'));
    if (!owner || !checked.length) return;

    const items = checked.map(cb => ({
      tableName: cb.getAttribute('data-table'),
      partitionName: cb.getAttribute('data-partition') || undefined
    }));

    const label = items.length === 1
      ? (items[0].partitionName ? `${items[0].tableName} (${items[0].partitionName})` : items[0].tableName)
      : t('nTablesLabel', { n: items.length });
    if (!confirm(t('confirmGatherBatch', { label }))) {
      return;
    }

    btn.disabled = true;
    const originalText = btn.textContent;
    // This is a single request that runs all items sequentially server-side
    // and responds once everything is done -- there's no incremental
    // progress to report while it's in flight, so the label just says how
    // many are queued rather than showing a fake live counter.
    btn.textContent = t('collectingItemsLabel', { n: items.length });

    try {
      const res = await fetch('/api/gather-table-stats-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ owner, items })
      });
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        showToast(data.message || t('requestStatsFailedGeneric'), 'error');
        return;
      }
      const { total, succeeded, failed } = data.summary;
      showToast(
        failed === 0
          ? t('statsCompletedAll', { n: total })
          : t('statsCompletedPartial', { succeeded, failed, total }),
        failed === 0 ? 'ok' : 'error'
      );
      renderTableStatsBatchResult(data.results, owner);
    } catch (err) {
      showToast(t('requestStatsFailed', { msg: err.message }), 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });

  function renderMeter(pct) {
    const p = Math.max(0, Math.min(100, Number(pct) || 0));
    const cls = pctClass(p);
    return `
      <div class="bar-track">
        <div class="bar-fill ${cls}" style="width:${p}%"></div>
      </div>`;
  }

  // The DashBoard tab's data used to be one /api/db-status call on a
  // single 15s timer. It's now three independent calls, each polled at a
  // cadence matching how fast that data actually changes (session/blocking
  // activity is worth checking often; instance info almost never changes)
  // -- see backend/routes_connect.py's three db_status_*() endpoints. Each
  // loadXxxStatus() below owns its own lastDbStatusData merge (so
  // rerenderAll() on a language switch still has a full picture) and its
  // own isLoading guard (so its own auto-tick and the manual refresh
  // button don't overlap with each other, independent of the other two).
  let isLoadingSessions = false;
  let isLoadingResources = false;
  let isLoadingInstance = false;
  const SESSIONS_REFRESH_MS = 15000;
  const RESOURCES_REFRESH_MS = 30000;
  const INSTANCE_REFRESH_MS = 5 * 60000;

  async function loadSessionsStatus() {
    if (isLoadingSessions) return;
    isLoadingSessions = true;
    hideBanner();
    try {
      const res = await fetch('/api/db-status-sessions');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        showBanner(data.message || t('dbStatusLoadFailed'));
        return;
      }
      lastDbStatusData = { ...lastDbStatusData, ...data };
      renderSessionCountBadge(data.sessionCount);
      renderSessionList(data.sessionList);
      renderBlockingSessions(data.blockingSessions);
      renderLongRunningOps(data.longRunningOps);
    } catch (err) {
      showBanner(t('networkError', { msg: err.message }));
    } finally {
      isLoadingSessions = false;
    }
  }

  async function loadResourcesStatus() {
    if (isLoadingResources) return;
    isLoadingResources = true;
    hideBanner();
    try {
      const res = await fetch('/api/db-status-resources');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        showBanner(data.message || t('dbStatusLoadFailed'));
        return;
      }
      lastDbStatusData = { ...lastDbStatusData, ...data };
      renderCombo(data.cpu, data.memory);
    } catch (err) {
      showBanner(t('networkError', { msg: err.message }));
    } finally {
      isLoadingResources = false;
    }
  }

  async function loadInstanceStatus() {
    if (isLoadingInstance) return;
    isLoadingInstance = true;
    hideBanner();
    try {
      const res = await fetch('/api/db-status-instance');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        showBanner(data.message || t('dbStatusLoadFailed'));
        return;
      }
      lastDbStatusData = { ...lastDbStatusData, ...data };
      renderInstance(data.instance);
    } catch (err) {
      showBanner(t('networkError', { msg: err.message }));
    } finally {
      isLoadingInstance = false;
    }
  }

  // Manual refresh button and the very first page load always fetch all
  // three, unconditionally (no visibility/leader-tab gating -- see
  // shouldAutoRefresh() below, which only gates the *automatic* timers).
  async function loadStatus() {
    refreshBtn.disabled = true;
    refreshBtn.textContent = t('loadingLabel');
    try {
      await Promise.all([loadSessionsStatus(), loadResourcesStatus(), loadInstanceStatus()]);
    } finally {
      refreshBtn.disabled = false;
      refreshBtn.textContent = t('btnRefresh');
    }
  }

  refreshBtn.addEventListener('click', loadStatus);

  // --- Reduce DB load: pause auto-refresh while hidden, and only the
  // "leader" tab (of possibly several OraPulse tabs/windows open at once)
  // actually polls. ---
  //
  // Leader election uses the Web Locks API: only one tab across the whole
  // browser can hold a given named lock at a time. A lock held for this
  // tab's entire lifetime (the original design) has a bug, though: Web
  // Locks has no concept of page visibility, so a *hidden* tab that
  // grabbed the lock first just keeps holding it forever -- it never
  // refreshes itself (shouldAutoRefresh also requires !document.hidden),
  // and no other, actually-visible tab/window can become leader either,
  // so NOTHING auto-refreshes anywhere until that hidden tab is closed.
  // Fix: this tab actively RELEASES the lock (via AbortController) the
  // moment it's hidden, and re-acquires it the moment it becomes visible
  // again, so leadership always tracks "am I visible", not "did I ask
  // first". Supported in every browser this app targets (Chrome, Edge,
  // Firefox 96+); on an older browser without navigator.locks, every tab
  // just falls back to always being "the leader" (today's behavior),
  // relying solely on the document.hidden check in shouldAutoRefresh().
  let isLeader = false;
  let leaderLockController = null; // non-null while a lock request is in flight or held
  const leaderLockStartedAt = Date.now();

  function handleBecameLeader() {
    if (document.hidden) return; // became leader right as this tab was hidden again -- nothing to catch up on screen
    // Catch up whichever tab is actually being looked at right now, since
    // its data may have gone stale while this tab/window wasn't leader
    // (hidden, or another tab/window was holding the lock instead).
    if (tabIsActive('main')) loadStatus();
    else if (tabIsActive('ops')) loadOpsUsage();
    else if (tabIsActive('tuning')) loadTuningCheck();
  }

  // Requests the lock if this tab doesn't already hold it (or isn't
  // already waiting for it) -- the leaderLockController guard means a
  // burst of rapid visibility toggles never stacks up duplicate requests,
  // it just leaves the one already in flight/held alone.
  function acquireLeaderLock() {
    if (!navigator.locks) {
      isLeader = true;
      // Skip the catch-up refresh only when this happens within the same
      // initial page load -- the page's own bootstrap sequence below
      // already does an unconditional first load regardless of leader
      // status, so firing here too would just double-fetch on every
      // normal page load. Any later call (this tab was hidden and is now
      // visible again) is always well past that window.
      if (Date.now() - leaderLockStartedAt > 1000) handleBecameLeader();
      return;
    }
    if (leaderLockController) return; // a request is already in flight or held
    const controller = new AbortController();
    leaderLockController = controller;
    navigator.locks.request(
      'orapulse-auto-refresh-leader',
      { signal: controller.signal },
      () => new Promise((resolve) => {
        isLeader = true;
        if (Date.now() - leaderLockStartedAt > 1000) handleBecameLeader();
        // Web Locks does not free an already-granted lock just because its
        // AbortSignal aborts -- releaseLeaderLock() below triggers this
        // listener, and resolving the promise is what actually lets go of
        // the lock and hands it to the next waiting tab.
        controller.signal.addEventListener('abort', () => resolve());
      })
    ).catch(() => {}); // AbortError from a cancelled queued/held request -- expected, not an error
  }

  // Cancels a queued request, or releases an already-held lock -- either
  // way, safe to call even if nothing is currently held/pending.
  function releaseLeaderLock() {
    isLeader = false;
    if (leaderLockController) {
      leaderLockController.abort();
      leaderLockController = null;
    }
  }

  function tabIsActive(tabKey) {
    return !TABS[tabKey].panel.hidden;
  }

  function shouldAutoRefresh(tabKey) {
    return isLeader && !document.hidden && tabIsActive(tabKey);
  }

  function updateLeaderLockForVisibility() {
    if (document.hidden) releaseLeaderLock();
    else acquireLeaderLock();
  }

  updateLeaderLockForVisibility();
  document.addEventListener('visibilitychange', updateLeaderLockForVisibility);

  // Small "v1.0001" next to the title, fetched from whichever backend is
  // actually running (main.js or main.py both serve the same VERSION file
  // via /api/version) rather than hardcoded here, so it can't drift out of
  // sync with the real running version.
  (async function loadAppVersion() {
    try {
      const res = await fetch('/api/version');
      const data = await res.json();
      if (data.success && data.version) {
        document.getElementById('appVersion').textContent = `v${data.version}`;
      }
    } catch (err) {
      // Non-critical -- just leave the version text empty.
    }
  })();

  // Auto-refresh timers, each gated by shouldAutoRefresh() so a hidden
  // browser tab, a non-leader duplicate OraPulse tab, or a currently
  // inactive app tab (e.g. viewing Main while Ops's timer ticks) all skip
  // the actual fetch instead of running it needlessly.
  const OPS_REFRESH_MS = 5 * 60000;
  const TUNING_REFRESH_MS = 10 * 60000;
  const autoRefreshTimers = [
    setInterval(() => { if (shouldAutoRefresh('main')) loadSessionsStatus(); }, SESSIONS_REFRESH_MS),
    setInterval(() => { if (shouldAutoRefresh('main')) loadResourcesStatus(); }, RESOURCES_REFRESH_MS),
    setInterval(() => { if (shouldAutoRefresh('main')) loadInstanceStatus(); }, INSTANCE_REFRESH_MS),
    setInterval(() => { if (shouldAutoRefresh('ops')) loadOpsUsage(); }, OPS_REFRESH_MS),
    setInterval(() => { if (shouldAutoRefresh('tuning')) loadTuningCheck(); }, TUNING_REFRESH_MS)
  ];

  // Ends the DB session (and stops the Weekly DB Health Report's background
  // collector) when the browser tab/window actually closes -- not just when
  // Disconnect is clicked. `pagehide` also fires on an in-app reload or
  // navigation, which looks identical to a real close at this point in
  // time, so this doesn't disconnect directly -- it tells the server "start
  // a few-second countdown," and any further request from this page (this
  // same reload re-fetching /api/db-status-*, for example) cancels that
  // countdown server-side. Only a real close, with no follow-up request,
  // lets it run out. sendBeacon (rather than fetch) is used because it's
  // designed to reliably deliver a request that starts as the page is being
  // torn down.
  window.addEventListener('pagehide', () => {
    navigator.sendBeacon('/api/browser-closing');
  });

  // --- Check Report ("점검레포트" button, next to Refresh) ---
  // A single click generates a point-in-time inspection report against
  // the currently connected DB and POSTs to /api/generate-report -- no
  // filename prompt: the server itself records the click instant (as
  // close to this click as a same-machine synchronous call gets) and
  // derives both the report's own "reference time" and the fixed
  // OraPulse_CheckReport_<timestamp>.html filename from it (see
  // backend/routes_report.py), so nothing here needs to invent or
  // negotiate a filename. The server saves the generated HTML straight to
  // disk (report/<YYYY-MM-DD>/<name>, never overwriting an existing file
  // of the same name -- see its own numbering fallback) and replies with
  // exactly where it landed; there is no browser download step at all,
  // since that depended on the browser's own download/Save-As handling
  // actually completing, which wasn't reliable.
  reportBtn.addEventListener('click', async () => {
    reportBtn.disabled = true;
    reportBtn.textContent = t('reportGeneratingLabel');

    try {
      const res = await fetch('/api/generate-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lang: currentLang })
      });

      if (res.status === 401) {
        window.location.href = '/';
        return;
      }

      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.success) {
        showToast(t('reportFailedToast', { msg: data.message || `HTTP ${res.status}` }), 'error');
        return;
      }

      showToast(t('reportGeneratedToast', { filename: data.filename, path: data.path }), 'ok');
    } catch (err) {
      showToast(t('reportFailedToast', { msg: err.message }), 'error');
    } finally {
      reportBtn.disabled = false;
      reportBtn.textContent = t('btnReport');
    }
  });

  // Status / Machine / Program filter (select boxes) for the current session list - filters instantly on the client without a server round-trip
  const filterStatusSelect = document.getElementById('filterStatus');
  const filterMachineSelect = document.getElementById('filterMachine');
  const filterProgramSelect = document.getElementById('filterProgram');
  const filterResetBtn = document.getElementById('filterResetBtn');

  filterStatusSelect.addEventListener('change', applySessionFilters);
  filterMachineSelect.addEventListener('change', applySessionFilters);
  filterProgramSelect.addEventListener('change', applySessionFilters);
  filterResetBtn.addEventListener('click', () => {
    filterStatusSelect.value = '';
    filterMachineSelect.value = '';
    filterProgramSelect.value = '';
    applySessionFilters();
  });

  // Clicking a session row in the current session list shows wait detail info (gv$session) +
  // if applicable, file/block object (dba_extents) lookup results in a modal.
  const sessionDetailBackdrop = document.getElementById('sessionDetailBackdrop');
  const sessionDetailTitle = document.getElementById('sessionDetailTitle');
  const sessionDetailBody = document.getElementById('sessionDetailBody');
  const sessionDetailClose = document.getElementById('sessionDetailClose');
  const boxSessionList = document.getElementById('box-sessionlist');

  function closeSessionDetail() {
    sessionDetailBackdrop.classList.remove('show');
    sessionDetailBody.innerHTML = '';
  }

  sessionDetailClose.addEventListener('click', closeSessionDetail);
  sessionDetailBackdrop.addEventListener('click', (e) => {
    if (e.target === sessionDetailBackdrop) closeSessionDetail();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sessionDetailBackdrop.classList.contains('show')) closeSessionDetail();
  });

  // Since box-sessionlist's content is entirely replaced via innerHTML on every refresh,
  // the click event is delegated to the box itself (a fixed element) so listeners don't need to be reattached each time.
  boxSessionList.addEventListener('click', (e) => {
    const tr = e.target.closest('tr.clickable-row');
    if (!tr) return;
    const sid = tr.getAttribute('data-sid');
    if (sid) openSessionDetail(sid);
  });

  // Right-clicking (or, on a touchscreen, long-pressing) a
  // row in the current session list opens a context menu with two actions:
  // "View Running Query" (looks up the session's current SQL_ID in v$sql)
  // and "Kill Session (IMMEDIATE)", which runs ALTER SYSTEM KILL SESSION ...
  // IMMEDIATE for that SID/SERIAL#. Same delegated-event pattern as the
  // Table Statistics Collection context menu above, since box-sessionlist's
  // content is also entirely replaced via innerHTML on every refresh.
  const sessionCtxMenu = document.getElementById('sessionCtxMenu');
  const sessionCtxMenuTitle = document.getElementById('sessionCtxMenuTitle');
  const sessionCtxMenuQuery = document.getElementById('sessionCtxMenuQuery');
  const sessionCtxMenuKill = document.getElementById('sessionCtxMenuKill');
  let sessionCtxTarget = null; // { sid, serial, sqlId }

  function closeSessionCtxMenu() {
    sessionCtxMenu.classList.remove('show');
    sessionCtxTarget = null;
  }

  function openSessionCtxMenu(x, y, sid, serial, sqlId) {
    sessionCtxTarget = { sid, serial, sqlId: sqlId || '' };
    sessionCtxMenuTitle.textContent = t('sidSerialTitle', { sid, serial });
    sessionCtxMenuQuery.disabled = !sqlId;
    sessionCtxMenuQuery.textContent = sqlId ? t('viewRunningQuery') : t('viewRunningQueryDisabled');
    sessionCtxMenuKill.disabled = false;
    sessionCtxMenuKill.textContent = t('killSessionImmediate');
    sessionCtxMenu.classList.add('show');
    const menuW = sessionCtxMenu.offsetWidth || 240;
    const menuH = sessionCtxMenu.offsetHeight || 80;
    const left = Math.min(x, window.innerWidth - menuW - 8);
    const top = Math.min(y, window.innerHeight - menuH - 8);
    sessionCtxMenu.style.left = `${Math.max(8, left)}px`;
    sessionCtxMenu.style.top = `${Math.max(8, top)}px`;
  }

  // --- Long-press support for touch devices ---
  // On a desktop browser, right-clicking a row fires the native
  // 'contextmenu' DOM event, handled below. A touch-only device (phone/
  // tablet browser) has no right mouse button, so the same menu is opened
  // by a long-press instead. Rather than relying on a given mobile
  // browser's own synthesized 'contextmenu' event from a long touch
  // (inconsistent across browsers/devices), this tracks the press itself
  // with touchstart/touchmove/touchend timers, and a "firedByTouch" flag
  // suppresses a real 'contextmenu' the browser might *also* dispatch
  // right after, so the menu isn't opened twice.
  function watchLongPress(boxEl, rowSelector, onLongPress) {
    const LONG_PRESS_MS = 500;
    const MOVE_TOLERANCE_PX = 12;
    let timer = null;
    let startX = 0;
    let startY = 0;

    boxEl.addEventListener('touchstart', (e) => {
      const tr = e.target.closest(rowSelector);
      if (!tr || e.touches.length !== 1) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      timer = setTimeout(() => {
        timer = null;
        if (navigator.vibrate) { try { navigator.vibrate(15); } catch (_) { /* not supported, ignore */ } }
        onLongPress(tr, startX, startY);
      }, LONG_PRESS_MS);
    }, { passive: true });

    boxEl.addEventListener('touchmove', (e) => {
      if (!timer) return;
      const t = e.touches[0];
      if (Math.abs(t.clientX - startX) > MOVE_TOLERANCE_PX || Math.abs(t.clientY - startY) > MOVE_TOLERANCE_PX) {
        clearTimeout(timer);
        timer = null;
      }
    }, { passive: true });

    const cancelTimer = () => { if (timer) { clearTimeout(timer); timer = null; } };
    boxEl.addEventListener('touchend', cancelTimer);
    boxEl.addEventListener('touchcancel', cancelTimer);
  }

  let sessionCtxFiredByTouch = false;

  watchLongPress(boxSessionList, 'tr.clickable-row', (tr, x, y) => {
    sessionCtxFiredByTouch = true;
    openSessionCtxMenu(
      x, y,
      tr.getAttribute('data-sid'),
      tr.getAttribute('data-serial'),
      tr.getAttribute('data-sqlid')
    );
  });

  boxSessionList.addEventListener('contextmenu', (e) => {
    const tr = e.target.closest('tr.clickable-row');
    if (!tr) return;
    e.preventDefault();
    // If our own long-press timer already opened the menu for this touch,
    // don't reopen/reposition it a second time for a following synthesized
    // 'contextmenu' event.
    if (sessionCtxFiredByTouch) {
      sessionCtxFiredByTouch = false;
      return;
    }
    openSessionCtxMenu(
      e.clientX, e.clientY,
      tr.getAttribute('data-sid'),
      tr.getAttribute('data-serial'),
      tr.getAttribute('data-sqlid')
    );
  });

  document.addEventListener('click', (e) => {
    if (sessionCtxMenu.classList.contains('show') && !sessionCtxMenu.contains(e.target)) {
      closeSessionCtxMenu();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sessionCtxMenu.classList.contains('show')) closeSessionCtxMenu();
  });
  window.addEventListener('scroll', closeSessionCtxMenu, true);

  sessionCtxMenuQuery.addEventListener('click', () => {
    if (!sessionCtxTarget || !sessionCtxTarget.sqlId) return;
    const { sid, sqlId } = sessionCtxTarget;
    closeSessionCtxMenu();
    openSessionQueryDetail(sid, sqlId);
  });

  sessionCtxMenuKill.addEventListener('click', async () => {
    if (!sessionCtxTarget) return;
    const { sid, serial } = sessionCtxTarget;
    if (!confirm(t('confirmKillSession', { sid, serial }))) {
      closeSessionCtxMenu();
      return;
    }
    sessionCtxMenuKill.disabled = true;
    sessionCtxMenuKill.textContent = t('killingLabel');
    try {
      const res = await fetch('/api/kill-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sid: Number(sid), serial: Number(serial) })
      });
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      showToast(data.message, data.success ? 'ok' : 'error');
      if (data.success) {
        // Refresh the session list/count/blocking sessions so they
        // reflect the session being gone -- CPU/memory/instance info are
        // unaffected by a kill, so no need to refetch those too.
        loadSessionsStatus();
      }
    } catch (err) {
      showToast(t('killSessionRequestFailed', { msg: err.message }), 'error');
    } finally {
      closeSessionCtxMenu();
    }
  });

  function renderSessionWaitRows(rows) {
    return rows.map(r => `
      <tr>
        <td>${escapeHtml(r.INST_ID)}</td>
        <td>${escapeHtml(r.SID)}</td>
        <td>${escapeHtml(r.SERIAL_NUM)}</td>
        <td>${escapeHtml(r.SQL_ID || '-')}</td>
        <td>${escapeHtml(r.EVENT || '-')}</td>
        <td>${escapeHtml(r.STATE || '-')}</td>
        <td>${escapeHtml(r.SECONDS_IN_WAIT)}</td>
        <td>${escapeHtml(r.P1TEXT || '-')}</td>
        <td>${escapeHtml(r.P1)}</td>
        <td>${escapeHtml(r.P2TEXT || '-')}</td>
        <td>${escapeHtml(r.P2)}</td>
        <td>${escapeHtml(r.P3TEXT || '-')}</td>
        <td>${escapeHtml(r.P3)}</td>
        <td>${escapeHtml(r.ROW_WAIT_OBJ ?? '-')}</td>
        <td>${escapeHtml(r.ROW_WAIT_FILE ?? '-')}</td>
        <td>${escapeHtml(r.ROW_WAIT_BLOCK ?? '-')}</td>
        <td>${escapeHtml(r.BLOCKING_INSTANCE ?? '-')}</td>
        <td>${escapeHtml(r.BLOCKING_SESSION ?? '-')}</td>
      </tr>`).join('');
  }

  function renderBlockObjectRows(rows) {
    return rows.map(r => `
      <tr>
        <td>${escapeHtml(r.OWNER)}</td>
        <td>${escapeHtml(r.SEGMENT_NAME)}</td>
        <td>${escapeHtml(r.PARTITION_NAME || '-')}</td>
        <td>${escapeHtml(r.SEGMENT_TYPE)}</td>
        <td>${escapeHtml(r.TABLESPACE_NAME)}</td>
        <td>${escapeHtml(r.RELATIVE_FNO)}</td>
        <td>${escapeHtml(r.EXTENT_START_BLOCK)}</td>
        <td>${escapeHtml(r.EXTENT_END_BLOCK)}</td>
        <td>${escapeHtml(r.BLOCK_OFFSET)}</td>
      </tr>`).join('');
  }

  async function loadBlockObjectSection(fileNo, blockNo) {
    const sectionId = 'blockObjectSection';
    const existing = document.getElementById(sectionId);
    if (existing) existing.remove();

    const section = document.createElement('div');
    section.className = 'modal-section';
    section.id = sectionId;
    const sectionTitle = t('fileBlockLookupTitle', { file: escapeHtml(fileNo), block: escapeHtml(blockNo) });
    section.innerHTML = `
      <div class="modal-section-title">${sectionTitle}</div>
      <div class="skeleton">${t('loadingLabel')}</div>`;
    sessionDetailBody.appendChild(section);

    try {
      const res = await fetch(`/api/block-object?fileno=${encodeURIComponent(fileNo)}&blockno=${encodeURIComponent(blockNo)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        section.innerHTML = `
          <div class="modal-section-title">${sectionTitle}</div>
          <div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      if (!data.data.length) {
        section.innerHTML = `
          <div class="modal-section-title">${sectionTitle}</div>
          <div class="empty-msg">${t('noObjectFound')}</div>`;
        return;
      }
      section.innerHTML = `
        <div class="modal-section-title">${sectionTitle}</div>
        <div class="sess-table-wrap">
          <table class="sess-table">
            <thead><tr>
              <th>${t('ownerHeader')}</th><th>${t('segmentNameHeader')}</th><th>${t('partitionNameHeader')}</th>
              <th>${t('segmentTypeHeader')}</th><th>${t('tablespaceNameHeader')}</th><th>${t('relativeFnoHeader')}</th>
              <th>${t('extentStartBlockHeader')}</th><th>${t('extentEndBlockHeader')}</th><th>${t('blockOffsetHeader')}</th>
            </tr></thead>
            <tbody>${renderBlockObjectRows(data.data)}</tbody>
          </table>
        </div>`;
    } catch (err) {
      section.innerHTML = `
        <div class="modal-section-title">${sectionTitle}</div>
        <div class="empty-msg">${t('fileBlockLookupFailed', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  async function openSessionDetail(sid) {
    sessionDetailTitle.textContent = t('sessionDetailTitleWithSid', { sid });
    sessionDetailBody.innerHTML = `<div class="skeleton">${t('loadingLabel')}</div>`;
    sessionDetailBackdrop.classList.add('show');

    try {
      const res = await fetch(`/api/session-wait-detail?sid=${encodeURIComponent(sid)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        sessionDetailBody.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      if (!data.data.length) {
        sessionDetailBody.innerHTML = `<div class="empty-msg">${t('sessionNotFound')}</div>`;
        return;
      }

      sessionDetailBody.innerHTML = `
        <div class="modal-section">
          <div class="modal-section-title">${t('waitSessionDetailTitle')}</div>
          <div class="sess-table-wrap">
            <table class="sess-table">
              <thead><tr>
                <th>${t('instIdHeader')}</th><th>SID</th><th>SERIAL#</th><th>SQL_ID</th><th>${t('eventHeader')}</th><th>${t('stateHeader')}</th>
                <th>${t('secondsInWaitHeader')}</th><th>P1 Text</th><th>P1</th><th>P2 Text</th><th>P2</th>
                <th>P3 Text</th><th>P3</th><th>Row Wait Obj#</th><th>Row Wait File#</th>
                <th>Row Wait Block#</th><th>${t('blockingInstHeader')}</th><th>${t('blockingSessionColHeader')}</th>
              </tr></thead>
              <tbody>${renderSessionWaitRows(data.data)}</tbody>
            </table>
          </div>
        </div>`;

      // Using the first row's P1(FILE_NO) / P2(BLOCK_NO) values, proceed to look up the file/block object.
      // (Whether P1/P2 actually represent file#/block# can vary depending on the wait event type.)
      const first = data.data[0];
      const fileNo = Number(first.P1);
      const blockNo = Number(first.P2);
      if (Number.isInteger(fileNo) && fileNo > 0 && Number.isInteger(blockNo) && blockNo >= 0) {
        loadBlockObjectSection(fileNo, blockNo);
      } else {
        const note = document.createElement('div');
        note.className = 'modal-section';
        note.innerHTML = `<div class="empty-msg">${t('p1p2NotFileBlock', { p1: escapeHtml(first.P1 ?? '-'), p2: escapeHtml(first.P2 ?? '-') })}</div>`;
        sessionDetailBody.appendChild(note);
      }
    } catch (err) {
      sessionDetailBody.innerHTML = `<div class="empty-msg">${t('sessionDetailLoadFailed', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  // Triggered from the "View Running Query" item in the session list's
  // context menu. Reuses the same session-detail modal as openSessionDetail()
  // above, just with different content: the SQL_ID's full text and a few
  // execution-stat columns from v$sql.
  // sid is optional: pass a SID when opened from the session list's "View
  // Running Query" context menu item (so the title reads "Running Query
  // (SID: ...)"), or omit it (null) when opened by SQL_ID alone -- e.g. from
  // the Recovery tab's Recent DML table -- in which case the title reads
  // "SQL Text (SQL_ID: ...)" instead. Either way the lookup itself is the
  // same /api/session-sql call keyed only by sqlId.
  async function openSessionQueryDetail(sid, sqlId) {
    sessionDetailTitle.textContent = sid != null ? t('runningQueryTitleWithSid', { sid }) : t('sqlTextTitleWithId', { sqlId });
    sessionDetailBody.innerHTML = `<div class="skeleton">${t('loadingLabel')}</div>`;
    sessionDetailBackdrop.classList.add('show');

    try {
      const res = await fetch(`/api/session-sql?sqlId=${encodeURIComponent(sqlId)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        sessionDetailBody.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      if (!data.data.length) {
        sessionDetailBody.innerHTML = `<div class="empty-msg">${t('sqlTextNotCached', { sqlId: escapeHtml(sqlId) })}</div>`;
        return;
      }

      const row = data.data[0];
      sessionDetailBody.innerHTML = `
        <div class="modal-section">
          <div class="modal-section-title">${t('sqlIdTitle', { id: escapeHtml(row.SQL_ID) })}</div>
          <div class="sql-meta-row">
            <span><b>${t('labelParsingSchema')}:</b> ${escapeHtml(row.PARSING_SCHEMA_NAME || '-')}</span>
            <span><b>${t('labelExecutions')}:</b> ${escapeHtml(row.EXECUTIONS ?? '-')}</span>
            <span><b>${t('labelElapsed')}:</b> ${row.ELAPSED_SEC != null ? Number(row.ELAPSED_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</span>
            <span><b>${t('labelCpu')}:</b> ${row.CPU_SEC != null ? Number(row.CPU_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</span>
            <span><b>${t('labelLastActive')}:</b> ${escapeHtml(row.LAST_ACTIVE_TIME || '-')}</span>
          </div>
          <div class="sql-text-block">${escapeHtml(row.SQL_TEXT || t('sqlTextEmptyPlaceholder'))}</div>
          <div class="info-note">${t('sqlSourceNote')}</div>
        </div>`;

      // Second section, loaded after the SQL text above has already
      // rendered: a formatted copy of the same SQL, its execution plan, and
      // a rule-based analysis of that plan. Same shared modal regardless of
      // where it was opened from (Ops tab's Top SQL cards, Tuning tab's Slow
      // SQL, Recovery's Recent DML, the session list's "View Running Query").
      loadSqlPlanSection(sqlId);
    } catch (err) {
      sessionDetailBody.innerHTML = `<div class="empty-msg">${t('sqlTextLoadFailed', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  // Bytes are shown at whatever unit keeps the number readable (matching
  // how DBMS_XPLAN itself scales its own plan output), since a plan mixes
  // steps ranging from a few rows to many gigabytes.
  function fmtPlanBytes(bytes) {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n <= 0) return '-';
    if (n >= 1024 * 1024 * 1024) return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
    if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(2) + ' MB';
    if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
    return n + ' B';
  }

  // One row per plan step, indented by DEPTH so the tree shape reads the
  // same way DBMS_XPLAN's own text output does, even though this table is
  // built straight from V$SQL_PLAN columns instead.
  function renderPlanRows(plan) {
    return (plan || []).map(r => {
      const depth = Number(r.DEPTH) || 0;
      const indent = '   '.repeat(depth);
      const opLabel = r.OPTIONS ? `${r.OPERATION} (${r.OPTIONS})` : (r.OPERATION || '-');
      const objName = r.OBJECT_NAME ? (r.OBJECT_OWNER ? `${r.OBJECT_OWNER}.${r.OBJECT_NAME}` : r.OBJECT_NAME) : '-';
      const predicate = r.ACCESS_PREDICATES || r.FILTER_PREDICATES || '';
      return `
        <tr>
          <td>${r.ID}</td>
          <td class="plan-op">${indent}${escapeHtml(opLabel)}</td>
          <td>${escapeHtml(objName)}</td>
          <td>${r.CARDINALITY != null ? Math.round(r.CARDINALITY).toLocaleString() : '-'}</td>
          <td>${r.BYTES != null ? fmtPlanBytes(r.BYTES) : '-'}</td>
          <td>${r.COST != null ? Math.round(r.COST).toLocaleString() : '-'}</td>
          <td class="plan-predicate">${predicate ? escapeHtml(predicate) : '-'}</td>
        </tr>`;
    }).join('');
  }

  const PLAN_RULE_TITLE_KEY = {
    plan_full_table_scan: 'planRuleFullTableScanTitle',
    plan_cartesian_join: 'planRuleCartesianJoinTitle',
    plan_nested_loop_large: 'planRuleNestedLoopLargeTitle',
    plan_large_sort: 'planRuleLargeSortTitle',
    plan_top_cost_step: 'planRuleTopCostStepTitle',
  };

  // Turns one occurrence (one plan row) of a grouped finding into its
  // localized message -- a rule can fire on more than one step (e.g. two
  // separate full table scans in the same plan), each rendered as its own
  // line within that rule's card.
  function planFindingLine(ruleId, row) {
    const objectLabel = row.objectName ? (row.objectOwner ? `${row.objectOwner}.${row.objectName}` : row.objectName) : '-';
    switch (ruleId) {
      case 'plan_full_table_scan':
        return t('planRuleFullTableScanMsg', {
          id: row.id, object: objectLabel,
          rows: row.cardinality != null ? Math.round(row.cardinality).toLocaleString() : '?',
        });
      case 'plan_cartesian_join':
        return t('planRuleCartesianJoinMsg', {
          id: row.id, operation: row.options ? `${row.operation} ${row.options}` : (row.operation || '-'),
        });
      case 'plan_nested_loop_large':
        return t('planRuleNestedLoopLargeMsg', {
          id: row.id, rows: row.cardinality != null ? Math.round(row.cardinality).toLocaleString() : '?',
        });
      case 'plan_large_sort':
        return t('planRuleLargeSortMsg', {
          id: row.id, operation: row.operation || '-', options: row.options || '', bytes: fmtPlanBytes(row.bytes),
        });
      default:
        return '';
    }
  }

  function renderPlanFindings(findings) {
    if (!findings || !findings.length) {
      return `<div class="empty-msg tuning-clean">${t('sqlPlanNoFindings')}</div>`;
    }
    return `<div class="tuning-list">${findings.map(f => {
      let bodyHtml;
      if (f.ruleId === 'plan_top_cost_step' && f.step) {
        const s = f.step;
        const objectLabel = s.objectName ? (s.objectOwner ? `${s.objectOwner}.${s.objectName}` : s.objectName) : (s.operation || '-');
        bodyHtml = `<div class="tuning-item-msg">${escapeHtml(t('planRuleTopCostStepMsg', {
          id: s.id, operation: s.operation || '-', object: objectLabel, pct: s.costPct,
        }))}</div>`;
      } else {
        bodyHtml = (f.rows || [])
          .map(row => `<div class="tuning-item-msg">${escapeHtml(planFindingLine(f.ruleId, row))}</div>`)
          .join('');
      }
      return `
        <div class="tuning-item">
          <div class="tuning-item-head">
            ${tuningSevBadge(f.severity)}
            <span class="tuning-item-title">${escapeHtml(t(PLAN_RULE_TITLE_KEY[f.ruleId] || f.ruleId))}</span>
          </div>
          ${bodyHtml}
        </div>`;
    }).join('')}</div>`;
  }

  // Appended as a second modal-section under the SQL text one, once
  // /api/sql-plan resolves -- same lazy-secondary-section pattern as
  // loadBlockObjectSection() above (the primary section renders first, this
  // one fills in once its own request completes).
  async function loadSqlPlanSection(sqlId) {
    const sectionId = 'sqlPlanSection';
    const existing = document.getElementById(sectionId);
    if (existing) existing.remove();

    const section = document.createElement('div');
    section.className = 'modal-section';
    section.id = sectionId;
    section.innerHTML = `
      <div class="modal-section-title">${t('sqlPlanSectionTitle')}</div>
      <div class="skeleton">${t('loadingLabel')}</div>`;
    sessionDetailBody.appendChild(section);

    try {
      const res = await fetch(`/api/sql-plan?sqlId=${encodeURIComponent(sqlId)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        section.innerHTML = `
          <div class="modal-section-title">${t('sqlPlanSectionTitle')}</div>
          <div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      if (!data.found) {
        section.innerHTML = `
          <div class="modal-section-title">${t('sqlPlanSectionTitle')}</div>
          <div class="empty-msg">${t('sqlPlanNotCached')}</div>`;
        return;
      }

      section.innerHTML = `
        <div class="modal-section-title">${t('sqlPlanSectionTitle')}</div>
        <div class="modal-subsection">
          <div class="modal-subsection-title">${t('sqlFormattedTitle')}</div>
          <div class="sql-text-block">${escapeHtml(data.formattedSql || t('sqlTextEmptyPlaceholder'))}</div>
        </div>
        <div class="modal-subsection">
          <div class="modal-subsection-title">${t('sqlPlanTitle')}</div>
          <div class="sess-table-wrap"><table class="sess-table plan-table">
            <thead><tr>
              <th>${t('planColId')}</th><th>${t('planColOperation')}</th><th>${t('planColObject')}</th>
              <th>${t('planColRows')}</th><th>${t('planColBytes')}</th><th>${t('planColCost')}</th><th>${t('planColPredicate')}</th>
            </tr></thead>
            <tbody>${renderPlanRows(data.plan)}</tbody>
          </table></div>
          <div class="info-note">${t('sqlPlanNote')}</div>
        </div>
        <div class="modal-subsection">
          <div class="modal-subsection-title">${t('sqlPlanAnalysisTitle')}</div>
          ${renderPlanFindings(data.findings)}
        </div>`;
    } catch (err) {
      section.innerHTML = `
        <div class="modal-section-title">${t('sqlPlanSectionTitle')}</div>
        <div class="empty-msg">${t('sqlPlanLoadFailed', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  // Triggered from the "View Table Properties" item in the Table Statistics
  // Collection screen's context menu. Reuses the same session-detail modal
  // as openSessionDetail()/openSessionQueryDetail() above, just with a
  // basic-info/columns/indexes layout. Each of the three sections is
  // rendered (or shown as failed) independently, matching the backend's
  // per-section ok/message shape.
  const TABLE_PROPERTIES_LENGTHED_TYPES = ['VARCHAR2', 'CHAR', 'NVARCHAR2', 'NCHAR', 'RAW'];
  function renderTablePropertiesColumnRows(columns) {
    return columns.map(col => {
      let typeSuffix = '';
      if (col.DATA_PRECISION != null) {
        typeSuffix = `(${col.DATA_PRECISION}${col.DATA_SCALE ? ',' + col.DATA_SCALE : ''})`;
      } else if (col.DATA_LENGTH != null && TABLE_PROPERTIES_LENGTHED_TYPES.includes(col.DATA_TYPE)) {
        typeSuffix = `(${col.DATA_LENGTH})`;
      }
      return `
      <tr>
        <td>${col.COLUMN_ID}</td>
        <td>${escapeHtml(col.COLUMN_NAME)}</td>
        <td>${escapeHtml(col.DATA_TYPE)}${typeSuffix}</td>
        <td>${col.NULLABLE === 'N' ? t('notNullLabel') : t('nullableLabel')}</td>
      </tr>`;
    }).join('');
  }

  function renderTablePropertiesIndexRows(indexes) {
    return indexes.map(idx => `
      <tr>
        <td>${escapeHtml(idx.INDEX_NAME)}</td>
        <td>${escapeHtml(idx.UNIQUENESS)}</td>
        <td>${escapeHtml(idx.STATUS)}</td>
        <td>${escapeHtml(idx.COLUMNS || '-')}</td>
      </tr>`).join('');
  }

  async function openTablePropertiesModal(owner, tableName, partitionName) {
    const label = partitionName ? `${owner}.${tableName} (${partitionName})` : `${owner}.${tableName}`;
    sessionDetailTitle.textContent = t('tablePropertiesTitleWithName', { name: label });
    sessionDetailBody.innerHTML = `<div class="skeleton">${t('loadingLabel')}</div>`;
    sessionDetailBackdrop.classList.add('show');

    try {
      const res = await fetch(`/api/table-properties?owner=${encodeURIComponent(owner)}&tableName=${encodeURIComponent(tableName)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        sessionDetailBody.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }

      const basicSection = (() => {
        if (!data.basic.ok) return `<div class="empty-msg">${escapeHtml(data.basic.message)}</div>`;
        const b = data.basic.data;
        if (!b) return `<div class="empty-msg">${t('tablePropertiesNotFound')}</div>`;
        return `
          <div class="sql-meta-row">
            <span><b>${t('tablespaceNameHeader')}:</b> ${escapeHtml(b.TABLESPACE_NAME || '-')}</span>
            <span><b>${t('tablePropertiesPartitioned')}:</b> ${escapeHtml(b.PARTITIONED || '-')}</span>
            <span><b>${t('numRowsHeader')}:</b> ${b.NUM_ROWS == null ? '-' : Number(b.NUM_ROWS).toLocaleString()}</span>
            <span><b>${t('blocksHeader')}:</b> ${b.BLOCKS == null ? '-' : Number(b.BLOCKS).toLocaleString()}</span>
            <span><b>${t('tablePropertiesAvgRowLen')}:</b> ${b.AVG_ROW_LEN == null ? '-' : Number(b.AVG_ROW_LEN).toLocaleString()}</span>
            <span><b>${t('tablePropertiesLogging')}:</b> ${escapeHtml(b.LOGGING || '-')}</span>
            <span><b>${t('tablePropertiesCompression')}:</b> ${escapeHtml(b.COMPRESSION || '-')}</span>
            <span><b>${t('tablePropertiesDegree')}:</b> ${escapeHtml(b.DEGREE || '-')}</span>
            <span><b>${t('lastAnalyzedHeader')}:</b> ${escapeHtml(b.LAST_ANALYZED || t('noCollectionHistory'))}</span>
          </div>`;
      })();

      const columnsSection = !data.columns.ok
        ? `<div class="empty-msg">${escapeHtml(data.columns.message)}</div>`
        : !data.columns.data.length
          ? `<div class="empty-msg">${t('tablePropertiesNoColumns')}</div>`
          : `<div class="sess-table-wrap">
              <table class="sess-table">
                <thead><tr><th>#</th><th>${t('tablePropertiesColumnName')}</th><th>${t('tablePropertiesDataType')}</th><th>${t('tablePropertiesNullable')}</th></tr></thead>
                <tbody>${renderTablePropertiesColumnRows(data.columns.data)}</tbody>
              </table>
            </div>`;

      const indexesSection = !data.indexes.ok
        ? `<div class="empty-msg">${escapeHtml(data.indexes.message)}</div>`
        : !data.indexes.data.length
          ? `<div class="empty-msg">${t('tablePropertiesNoIndexes')}</div>`
          : `<div class="sess-table-wrap">
              <table class="sess-table">
                <thead><tr><th>${t('tablePropertiesIndexName')}</th><th>${t('tablePropertiesUniqueness')}</th><th>${t('statusHeader')}</th><th>${t('tablePropertiesIndexColumns')}</th></tr></thead>
                <tbody>${renderTablePropertiesIndexRows(data.indexes.data)}</tbody>
              </table>
            </div>`;

      sessionDetailBody.innerHTML = `
        <div class="modal-section">
          <div class="modal-section-title">${t('tablePropertiesBasicInfoTitle')}</div>
          ${basicSection}
        </div>
        <div class="modal-section">
          <div class="modal-section-title">${t('tablePropertiesColumnsTitle')}</div>
          ${columnsSection}
        </div>
        <div class="modal-section">
          <div class="modal-section-title">${t('tablePropertiesIndexesTitle')}</div>
          ${indexesSection}
        </div>`;
    } catch (err) {
      sessionDetailBody.innerHTML = `<div class="empty-msg">${t('tablePropertiesLoadFailed', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  // --- Object View tab: object explorer (left) + script viewer (right) ---
  // Owners load lazily the first time this tab is opened (via TABS.objectview.load,
  // same lazy pattern as Ops/Recovery); picking an owner loads its full object
  // list once and caches it, and the type-select/text-filter inputs re-render
  // the (already-grouped-by-type) tree from that cache without refetching.
  // Clicking an object fetches its DBMS_METADATA DDL on demand.
  const objectViewOwnerSelect = document.getElementById('objectViewOwnerSelect');
  const objectViewTypeSelect = document.getElementById('objectViewTypeSelect');
  const objectViewFilterInput = document.getElementById('objectViewFilterInput');
  const objectViewTree = document.getElementById('objectViewTree');
  const objectViewTitle = document.getElementById('objectViewTitle');
  const objectViewCode = document.getElementById('objectViewCode');

  let objectViewObjects = null; // cached /api/object-list result for the current owner
  let objectViewSelectedKey = null; // `${owner}::${objectType}::${objectName}` of the active item

  async function loadObjectViewOwners() {
    setDot('objectview', 'loading');
    try {
      const res = await fetch('/api/table-owners');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('objectview', 'error');
        objectViewOwnerSelect.innerHTML = `<option value="">${t('tableOwnersLoadFailedOption')}</option>`;
        return;
      }
      setDot('objectview', 'ok');
      const options = data.data
        .map(owner => `<option value="${escapeHtml(owner)}">${escapeHtml(owner)}</option>`)
        .join('');
      objectViewOwnerSelect.innerHTML = `<option value="">${t('selectUserPlaceholder')}</option>${options}`;
    } catch (err) {
      setDot('objectview', 'error');
      objectViewTree.innerHTML = `<div class="empty-msg">${t('tableOwnersLoadFailedMsg', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  function objectViewClearViewer() {
    objectViewSelectedKey = null;
    objectViewTitle.textContent = t('objectViewNoSelection');
    objectViewCode.textContent = '';
  }

  async function loadObjectViewList(owner) {
    objectViewObjects = null;
    objectViewClearViewer();
    objectViewTypeSelect.innerHTML = `<option value="">${t('filterAllOption', { label: t('filterLabelType') })}</option>`;
    objectViewFilterInput.value = '';

    if (!owner) {
      objectViewTree.innerHTML = `<div class="empty-msg">${t('objectViewSelectPrompt')}</div>`;
      return;
    }

    objectViewTree.innerHTML = `<div class="skeleton">${t('loadingLabel')}</div>`;
    try {
      const res = await fetch(`/api/object-list?owner=${encodeURIComponent(owner)}`);
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('objectview', 'error');
        objectViewTree.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      setDot('objectview', 'ok');
      if (!data.data.length) {
        objectViewTree.innerHTML = `<div class="empty-msg">${t('objectViewNoObjectsForOwner', { owner: escapeHtml(owner) })}</div>`;
        return;
      }
      objectViewObjects = data.data;
      populateFilterSelect(objectViewTypeSelect, data.data.map(o => o.OBJECT_TYPE), t('filterLabelType'));
      objectViewTypeSelect.value = '';
      renderObjectViewTree();
      if (data.truncated) {
        objectViewTree.insertAdjacentHTML(
          'beforeend',
          `<div class="sess-table-note">${t('objectViewTruncatedNote', { n: Number(data.totalCount).toLocaleString() })}</div>`
        );
      }
    } catch (err) {
      setDot('objectview', 'error');
      objectViewTree.innerHTML = `<div class="empty-msg">${t('objectViewLoadFailedMsg', { msg: escapeHtml(err.message) })}</div>`;
    }
  }

  function renderObjectViewTree() {
    if (!objectViewObjects) return;
    const owner = objectViewOwnerSelect.value;
    const typeFilter = objectViewTypeSelect.value;
    const textFilter = objectViewFilterInput.value.trim().toUpperCase();

    const filtered = objectViewObjects.filter(o => {
      if (typeFilter && o.OBJECT_TYPE !== typeFilter) return false;
      if (textFilter && !o.OBJECT_NAME.toUpperCase().includes(textFilter)) return false;
      return true;
    });

    if (!filtered.length) {
      objectViewTree.innerHTML = `<div class="empty-msg">${t('objectViewNoMatch')}</div>`;
      return;
    }

    const byType = new Map();
    filtered.forEach(o => {
      if (!byType.has(o.OBJECT_TYPE)) byType.set(o.OBJECT_TYPE, []);
      byType.get(o.OBJECT_TYPE).push(o);
    });

    const groupsHtml = Array.from(byType.keys()).sort().map(type => {
      const items = byType.get(type);
      const itemsHtml = items.map(o => {
        const key = `${owner}::${o.OBJECT_TYPE}::${o.OBJECT_NAME}`;
        const isActive = key === objectViewSelectedKey;
        const isInvalid = o.STATUS && o.STATUS !== 'VALID';
        return `<button type="button" class="objectview-item${isActive ? ' active' : ''}${isInvalid ? ' invalid-status' : ''}"
                  data-owner="${escapeHtml(owner)}" data-name="${escapeHtml(o.OBJECT_NAME)}" data-type="${escapeHtml(o.OBJECT_TYPE)}"
                  title="${escapeHtml(o.OBJECT_NAME)} (${escapeHtml(o.STATUS || '-')})">${escapeHtml(o.OBJECT_NAME)}</button>`;
      }).join('');
      return `<details class="objectview-group" open>
        <summary>${escapeHtml(type)} (${items.length})</summary>
        ${itemsHtml}
      </details>`;
    }).join('');

    objectViewTree.innerHTML = groupsHtml;
  }

  async function loadObjectViewDdl(owner, objectName, objectType) {
    objectViewSelectedKey = `${owner}::${objectType}::${objectName}`;
    objectViewTree.querySelectorAll('.objectview-item').forEach(btn => {
      btn.classList.toggle(
        'active',
        btn.dataset.owner === owner && btn.dataset.name === objectName && btn.dataset.type === objectType
      );
    });
    objectViewTitle.textContent = `${owner}.${objectName} (${objectType})`;
    objectViewCode.textContent = t('loadingLabel');

    try {
      const res = await fetch(
        `/api/object-ddl?owner=${encodeURIComponent(owner)}&objectName=${encodeURIComponent(objectName)}&objectType=${encodeURIComponent(objectType)}`
      );
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        objectViewCode.textContent = data.message;
        return;
      }
      objectViewCode.textContent = data.ddl;
    } catch (err) {
      objectViewCode.textContent = t('objectViewDdlLoadFailed', { msg: err.message });
    }
  }

  objectViewOwnerSelect.addEventListener('change', () => loadObjectViewList(objectViewOwnerSelect.value));
  objectViewTypeSelect.addEventListener('change', renderObjectViewTree);
  objectViewFilterInput.addEventListener('input', renderObjectViewTree);

  objectViewTree.addEventListener('click', (e) => {
    const btn = e.target.closest('.objectview-item');
    if (!btn) return;
    loadObjectViewDdl(btn.dataset.owner, btn.dataset.name, btn.dataset.type);
  });

  logoutBtn.addEventListener('click', async () => {
    logoutBtn.disabled = true;
    autoRefreshTimers.forEach(clearInterval);
    try {
      await fetch('/api/logout', { method: 'POST' });
    } catch (err) {
      // Redirect to the login screen even if session termination fails
    }
    window.location.href = '/';
  });

  // Language switcher (English / Korean), to the right of the Disconnect
  // button. Default language is English (see currentLang's fallback above);
  // whichever language is picked here is persisted to localStorage so it's
  // restored automatically next time the app is opened. Static markup is
  // handled by applyStaticI18n() (data-i18n attributes); everything else is
  // JS-rendered from cached data, which rerenderAll() re-runs so switching
  // languages updates already-loaded cards immediately, without a server
  // round-trip (except the one deliberate exception noted in rerenderAll()).
  const langSelect = document.getElementById('langSelect');
  langSelect.value = currentLang;
  langSelect.addEventListener('change', () => {
    currentLang = (langSelect.value === 'ko') ? 'ko' : 'en';
    try {
      localStorage.setItem('orapulseLang', currentLang);
    } catch (_) {
      // localStorage can throw in some restricted browser contexts -- the
      // language still applies for the rest of this session, it just won't
      // be remembered on next launch.
    }
    rerenderAll();
  });

  // Theme switcher (Dark / Light), to the right of the Language select.
  // Doesn't need any re-render logic like the language switch does -- every
  // color in this page is a CSS custom property (see the :root and
  // :root[data-theme="light"] blocks at the top of this file), so flipping
  // the data-theme attribute on <html> is the entire visual change; no card
  // needs to be redrawn.
  const themeSelect = document.getElementById('themeSelect');
  themeSelect.value = currentTheme;
  themeSelect.addEventListener('change', () => {
    currentTheme = (themeSelect.value === 'light') ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);
    try {
      localStorage.setItem('orapulseTheme', currentTheme);
    } catch (_) {
      // localStorage can throw in some restricted browser contexts -- the
      // theme still applies for the rest of this session, it just won't be
      // remembered on next launch.
    }
  });

  // Apply the restored language to the static markup before the first data
  // load, so e.g. a restored 'ko' setting is reflected from the very first
  // paint rather than only after the first card finishes loading.
  applyStaticI18n();
  applyHelpLanguage();

  loadStatus();
  loadTableOwners();
  loadJobFailures();
  loadAccountSecurity();
  loadAlertLog();
