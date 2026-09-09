  // The Help tab's manual is two full static blocks (English/Korean)
  // rather than short i18n dictionary strings -- there's simply too much
  // prose for that to stay readable -- so a language switch just toggles
  // which one is visible instead of re-rendering anything.
  function applyHelpLanguage() {
    const en = document.getElementById('helpContentEn');
    const ko = document.getElementById('helpContentKo');
    if (en) en.hidden = currentLang !== 'en';
    if (ko) ko.hidden = currentLang !== 'ko';
    // A search highlighted into the block that's about to be hidden would
    // otherwise sit there stale (and pointing at the wrong language) --
    // simplest correct behavior is to just reset the search on every
    // language switch, same as re-opening the tab fresh.
    if (typeof resetHelpSearch === 'function') resetHelpSearch();
  }

  // --- Help tab: search within the manual ---
  // Finds every occurrence of the typed term inside whichever language
  // block is currently visible, wraps each in <mark>, and lets Enter (or
  // the up/down buttons) step through them -- rebuilt from scratch on
  // every keystroke rather than maintained incrementally, since the
  // manual is only a dozen short sections and this is plenty fast for that.
  const helpSearchInput = document.getElementById('helpSearchInput');
  const helpSearchCount = document.getElementById('helpSearchCount');
  const helpSearchPrevBtn = document.getElementById('helpSearchPrevBtn');
  const helpSearchNextBtn = document.getElementById('helpSearchNextBtn');
  const helpSearchClearBtn = document.getElementById('helpSearchClearBtn');
  let helpSearchMatches = [];
  let helpSearchCurrentIndex = -1;

  function helpSearchContainer() {
    return document.getElementById(currentLang === 'ko' ? 'helpContentKo' : 'helpContentEn');
  }

  function clearHelpSearchHighlights() {
    // Clears both language blocks, not just whichever is visible right
    // now -- a language switch flips currentLang (and so which container
    // helpSearchContainer() points at) before this runs, so "just the
    // current one" would miss marks left behind in the block being hidden.
    ['helpContentEn', 'helpContentKo'].forEach(id => {
      const container = document.getElementById(id);
      if (!container) return;
      container.querySelectorAll('mark.help-search-hit').forEach(mark => {
        const parent = mark.parentNode;
        if (!parent) return;
        parent.replaceChild(document.createTextNode(mark.textContent), mark);
        parent.normalize();
      });
    });
    helpSearchMatches = [];
    helpSearchCurrentIndex = -1;
  }

  function updateHelpSearchCount() {
    if (!helpSearchCount || !helpSearchInput) return;
    if (!helpSearchInput.value) {
      helpSearchCount.textContent = '';
    } else if (helpSearchMatches.length === 0) {
      helpSearchCount.textContent = t('helpSearchNoMatches');
    } else {
      helpSearchCount.textContent = t('helpSearchMatchCount', { current: helpSearchCurrentIndex + 1, total: helpSearchMatches.length });
    }
  }

  function focusHelpSearchMatch() {
    helpSearchMatches.forEach((mark, i) => mark.classList.toggle('help-search-hit-current', i === helpSearchCurrentIndex));
    const current = helpSearchMatches[helpSearchCurrentIndex];
    if (current) current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    updateHelpSearchCount();
  }

  function runHelpSearch(term) {
    clearHelpSearchHighlights();
    const container = helpSearchContainer();
    if (!container || !term) {
      updateHelpSearchCount();
      return;
    }
    const lowerTerm = term.toLowerCase();
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode: node => (node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT)
    });
    const textNodes = [];
    let node;
    while ((node = walker.nextNode())) textNodes.push(node);

    textNodes.forEach(textNode => {
      const text = textNode.nodeValue;
      const lowerText = text.toLowerCase();
      if (!lowerText.includes(lowerTerm)) return;
      const frag = document.createDocumentFragment();
      let lastIndex = 0;
      let idx = lowerText.indexOf(lowerTerm, lastIndex);
      while (idx !== -1) {
        if (idx > lastIndex) frag.appendChild(document.createTextNode(text.slice(lastIndex, idx)));
        const mark = document.createElement('mark');
        mark.className = 'help-search-hit';
        mark.textContent = text.slice(idx, idx + term.length);
        frag.appendChild(mark);
        helpSearchMatches.push(mark);
        lastIndex = idx + term.length;
        idx = lowerText.indexOf(lowerTerm, lastIndex);
      }
      if (lastIndex < text.length) frag.appendChild(document.createTextNode(text.slice(lastIndex)));
      textNode.parentNode.replaceChild(frag, textNode);
    });

    if (helpSearchMatches.length) {
      helpSearchCurrentIndex = 0;
      focusHelpSearchMatch();
    } else {
      updateHelpSearchCount();
    }
  }

  function goToHelpMatch(delta) {
    if (!helpSearchMatches.length) return;
    helpSearchCurrentIndex = (helpSearchCurrentIndex + delta + helpSearchMatches.length) % helpSearchMatches.length;
    focusHelpSearchMatch();
  }

  function resetHelpSearch() {
    if (helpSearchInput) helpSearchInput.value = '';
    clearHelpSearchHighlights();
    updateHelpSearchCount();
  }

  if (helpSearchInput) {
    let helpSearchDebounce = null;
    helpSearchInput.addEventListener('input', () => {
      clearTimeout(helpSearchDebounce);
      const term = helpSearchInput.value.trim();
      helpSearchDebounce = setTimeout(() => runHelpSearch(term), 150);
    });
    helpSearchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        goToHelpMatch(e.shiftKey ? -1 : 1);
      }
    });
    helpSearchPrevBtn.addEventListener('click', () => goToHelpMatch(-1));
    helpSearchNextBtn.addEventListener('click', () => goToHelpMatch(1));
    helpSearchClearBtn.addEventListener('click', () => resetHelpSearch());
  }

  function rerenderAll() {
    applyStaticI18n();
    applyHelpLanguage();

    if (lastDbStatusData) {
      renderInstance(lastDbStatusData.instance);
      renderCombo(lastDbStatusData.cpu, lastDbStatusData.memory);
      renderSessionCountBadge(lastDbStatusData.sessionCount);
      renderSessionList(lastDbStatusData.sessionList);
      renderBlockingSessions(lastDbStatusData.blockingSessions);
      renderLongRunningOps(lastDbStatusData.longRunningOps);
    }
    if (lastJobFailuresData) {
      renderJobFailures(lastJobFailuresData);
    }
    if (lastAccountSecurityData) {
      renderAccountSecurity(lastAccountSecurityData);
    }
    if (lastAlertLogData) {
      renderAlertLog(lastAlertLogData);
    }
    if (lastOpsUsageData) {
      renderTopQueries(lastOpsUsageData.topQueries);
      renderTopQueriesCpu(lastOpsUsageData.topQueriesCpu);
      renderTopQueriesGets(lastOpsUsageData.topQueriesBufferGets);
      renderTopWaitEvents(lastOpsUsageData.topWaitEvents);
      renderInstanceEfficiency(lastOpsUsageData.instanceEfficiency);
      renderLoadProfile(lastOpsUsageData.loadProfile);
      renderTablespaceIo(lastOpsUsageData.tablespaceIo);
      renderKeyParams(lastOpsUsageData.keyParameters);
      renderUndoConfig(lastOpsUsageData.undoConfig, lastOpsUsageData.undoStatus);
      renderTempTablespaceUsage(lastOpsUsageData.tempTablespaceUsage);
      renderTempSessionUsage(lastOpsUsageData.tempSessionUsage);
      renderDatafileAutoextend(lastOpsUsageData.datafileAutoextend);
      renderRedoLog(lastOpsUsageData.redoLogStatus);
    }
    if (lastRecoveryUsageData) {
      renderRecoveryDestUsage(lastRecoveryUsageData.destUsage);
      renderRecoveryTypeUsage(lastRecoveryUsageData.typeUsage);
      renderRecentDml(lastRecoveryUsageData.recentDml);
    }
    if (lastTuningData) {
      renderTuningResult(lastTuningData);
    }
    if (lastTableStatsOwner) {
      // The table itself has no locally-cached raw data (only the rendered
      // HTML), so re-render it by re-requesting the same owner's stats --
      // a small extra round-trip, but it keeps this in sync with the DB
      // rather than risking a stale table on screen.
      loadTableStats(lastTableStatsOwner);
    } else {
      const placeholderOpt = tableStatsOwnerSelect.querySelector('option[value=""]');
      if (placeholderOpt) placeholderOpt.textContent = t('selectUserPlaceholder');
      if (!tableStatsOwnerSelect.value) {
        boxTableStats.innerHTML = TABLE_STATS_EMPTY_MSG();
      }
    }
    if (lastSqlRunnerData) {
      renderSqlRunnerResult(lastSqlRunnerData);
    } else {
      boxSqlRunner.innerHTML = `<div class="empty-msg">${t('sqlRunnerIdle')}</div>`;
    }
  }

  const banner = document.getElementById('banner');
  const refreshBtn = document.getElementById('refreshBtn');
  const reportBtn = document.getElementById('reportBtn');
  const logoutBtn = document.getElementById('logoutBtn');

  function setDot(key, state) {
    const el = document.getElementById(`dot-${key}`);
    el.classList.remove('loading', 'error');
    if (state === 'error') el.classList.add('error');
    if (state === 'loading') el.classList.add('loading');
  }

  function showBanner(message) {
    banner.textContent = message;
    banner.classList.add('show');
  }

  function hideBanner() {
    banner.classList.remove('show');
    banner.textContent = '';
  }

  function renderInstance(section) {
    setDot('instance', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-instance');
    const titleNameEl = document.getElementById('instanceNameTitle');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${section.message}</div>`;
      instanceUptimeBaseSeconds = null;
      instanceUptimeBaseAt = null;
      if (titleNameEl) titleNameEl.textContent = '';
      return;
    }
    const d = section.data;
    box.innerHTML = `
      <dl class="kv">
        <dt>${t('instanceNameLabel')}</dt><dd><strong>${escapeHtml(d.INSTANCE_NAME ?? '-')}</strong></dd>
        <dt>${t('statusLabel')}</dt><dd>${escapeHtml(d.STATUS ?? '-')}</dd>
        <dt>${t('hostLabel')}</dt><dd>${escapeHtml(d.HOST_NAME ?? '-')}</dd>
        <dt>${t('versionLabel')}</dt><dd>${escapeHtml(d.VERSION ?? '-')}</dd>
        <dt>${t('startupTimeLabel')}</dt><dd>${escapeHtml(d.STARTUP_TIME ?? '-')}</dd>
        <dt>${t('uptimeLabel')}</dt><dd class="uptime-clock" id="uptimeClock">-</dd>
      </dl>`;
    // Shown next to the OraPulse title too (top-left), so which DB you're
    // looking at stays visible without having to scroll back up to this
    // card -- easy to lose track of otherwise, especially with several
    // OraPulse windows open against different databases at once.
    if (titleNameEl) titleNameEl.textContent = d.INSTANCE_NAME ? ` - ${d.INSTANCE_NAME}` : '';

    // Based on the uptime (in seconds) at the moment the server responded, the client
    // then adds to it every second on its own to display it like a live clock.
    if (typeof d.UPTIME_SECONDS === 'number' && !Number.isNaN(d.UPTIME_SECONDS)) {
      instanceUptimeBaseSeconds = d.UPTIME_SECONDS;
      instanceUptimeBaseAt = Date.now();
    } else {
      instanceUptimeBaseSeconds = null;
      instanceUptimeBaseAt = null;
    }
    tickUptimeClock();
  }

  // Split uptime (seconds) into days/hours/minutes/seconds and format as a string
  function formatUptime(totalSeconds) {
    const sec = Math.max(0, Math.floor(totalSeconds));
    const days = Math.floor(sec / 86400);
    const hours = Math.floor((sec % 86400) / 3600);
    const minutes = Math.floor((sec % 3600) / 60);
    const seconds = sec % 60;
    return `${days}d ${String(hours).padStart(2, '0')}h ${String(minutes).padStart(2, '0')}m ${String(seconds).padStart(2, '0')}s`;
  }

  let instanceUptimeBaseSeconds = null;
  let instanceUptimeBaseAt = null;

  // Called every second to update the uptime display in the Instance Information card like a live clock
  function tickUptimeClock() {
    const el = document.getElementById('uptimeClock');
    if (!el) return;
    if (instanceUptimeBaseSeconds === null) {
      el.textContent = '-';
      return;
    }
    const elapsedSinceBase = (Date.now() - instanceUptimeBaseAt) / 1000;
    el.textContent = formatUptime(instanceUptimeBaseSeconds + elapsedSinceBase);
  }

  // Independent of the 15-second full refresh cycle, only the uptime display is updated every second
  setInterval(tickUptimeClock, 1000);

  function renderSessionCountBadge(section) {
    const badge = document.getElementById('sessionCountBadge');
    if (section.ok) {
      badge.textContent = t('sessionCountConnected', { n: section.data });
      badge.classList.remove('error');
      badge.title = t('sessionCountTooltip');
    } else {
      badge.textContent = t('sessionCountNoPermission');
      badge.classList.add('error');
      badge.title = section.message;
    }
  }

  function renderCombo(cpuSection, memorySection) {
    const allFailed = !cpuSection.ok && !memorySection.ok;
    setDot('combo', allFailed ? 'error' : 'ok');
    const box = document.getElementById('box-combo');

    const cpuHtml = cpuSection.ok
      ? (() => {
          const pct = Number(cpuSection.data.pct);
          return `<div class="combo-value">${pct.toFixed(1)}%</div>
                  ${renderMeter(pct)}
                  <div class="combo-meta">${t('comboCpuUtilLabel')}</div>`;
        })()
      : `<div class="empty-msg">${cpuSection.message}</div>`;

    const memoryHtml = memorySection.ok
      ? (() => {
          const d = memorySection.data;
          if (d.pct === null) {
            return `<div class="combo-value">${d.usedMb.toLocaleString()} MB</div>
                    <div class="combo-meta">${t('comboMemUnknownPct', { sga: d.sgaMb.toLocaleString(), pga: d.pgaMb.toLocaleString() })}</div>`;
          }
          return `<div class="combo-value">${d.pct.toFixed(1)}%</div>
                  ${renderMeter(d.pct)}
                  <div class="combo-meta">${t('comboMemWithPct', { used: d.usedMb.toLocaleString(), sga: d.sgaMb.toLocaleString(), pga: d.pgaMb.toLocaleString(), target: d.targetMb.toLocaleString() })}</div>`;
        })()
      : `<div class="empty-msg">${memorySection.message}</div>`;

    box.innerHTML = `
      <div class="combo-row">
        <div class="combo-item">
          <div class="combo-label">${t('comboCpuLabel')}</div>
          ${cpuHtml}
        </div>
        <div class="combo-item">
          <div class="combo-label">${t('comboMemLabel')}</div>
          ${memoryHtml}
        </div>
      </div>`;
  }

  let latestSessionSection = null;

  function renderSessionList(section) {
    latestSessionSection = section;
    setDot('sessionlist', section.ok ? 'ok' : 'error');
    applySessionFilters();
  }

  function populateFilterSelect(selectEl, values, label) {
    const unique = Array.from(new Set(values.filter(v => v))).sort((a, b) => a.localeCompare(b));
    const previous = selectEl.value;

    selectEl.innerHTML =
      `<option value="">${t('filterAllOption', { label })}</option>` +
      unique.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');

    // Even if the option list changes on refresh, keep the previously selected value if it still exists
    selectEl.value = unique.includes(previous) ? previous : '';
  }

  function applySessionFilters() {
    const section = latestSessionSection;
    const box = document.getElementById('box-sessionlist');
    if (!section) return;

    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${section.message}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('sessionListEmpty')}</div>`;
      return;
    }

    const statusSelect = document.getElementById('filterStatus');
    const machineSelect = document.getElementById('filterMachine');
    const programSelect = document.getElementById('filterProgram');

    populateFilterSelect(statusSelect, section.data.map(r => r.STATUS), t('filterLabelStatus'));
    populateFilterSelect(machineSelect, section.data.map(r => r.MACHINE), t('filterLabelMachine'));
    populateFilterSelect(programSelect, section.data.map(r => r.PROGRAM), t('filterLabelProgram'));

    const statusFilter = statusSelect.value;
    const machineFilter = machineSelect.value;
    const programFilter = programSelect.value;

    const filtered = section.data.filter(row => {
      const statusOk = !statusFilter || (row.STATUS || '') === statusFilter;
      const machineOk = !machineFilter || (row.MACHINE || '') === machineFilter;
      const programOk = !programFilter || (row.PROGRAM || '') === programFilter;
      return statusOk && machineOk && programOk;
    });

    if (!filtered.length) {
      box.innerHTML = `<div class="empty-msg">${t('sessionListNoMatch')}</div>`;
      return;
    }

    const rows = filtered.map(row => {
      const statusRaw = (row.STATUS || '').toUpperCase();
      const statusCls = statusRaw === 'ACTIVE' ? 'active' : 'inactive';
      return `
        <tr class="clickable-row" data-sid="${escapeHtml(row.SID)}" data-serial="${escapeHtml(row.SERIAL_NUM)}" data-sqlid="${escapeHtml(row.SQL_ID || '')}" title="${escapeHtml(t('sessionRowTooltip'))}">
          <td>${escapeHtml(row.SID)}</td>
          <td>${escapeHtml(row.SERIAL_NUM)}</td>
          <td><span class="status-tag ${statusCls}">${escapeHtml(row.STATUS || '-')}</span></td>
          <td>${escapeHtml(row.MACHINE || '-')}</td>
          <td>${escapeHtml(row.PROGRAM || '-')}</td>
          <td>${escapeHtml(row.LOGON_TIME_STR || '-')}</td>
          <td>${escapeHtml(row.SQL_ID || '-')}</td>
        </tr>`;
    }).join('');

    const count = (statusFilter || machineFilter || programFilter)
      ? `<div class="sess-filter-count">${t('filteredCount', { n: filtered.length, m: section.data.length })}</div>`
      : '';

    const note = section.truncated
      ? `<div class="sess-table-note">${t('sessionListTruncatedNote')}</div>`
      : '';

    box.innerHTML = `
      ${count}
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead>
            <tr>
              <th>SID</th><th>SERIAL#</th><th>${t('statusHeader')}</th><th>${t('machineHeader')}</th><th>${t('programHeader')}</th><th>${t('logonTimeHeader')}</th><th>SQL_ID</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${note}`;
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatElapsed(sec) {
    const n = Number(sec) || 0;
    if (n < 60) return `${n}s`;
    const m = Math.floor(n / 60);
    const s = n % 60;
    return `${m}m ${s}s`;
  }

  function pctClass(pct) {
    if (pct >= 90) return 'danger';
    if (pct >= 75) return 'warn';
    return '';
  }

  function renderBlockingSessions(section) {
    setDot('blocking', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-blocking');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${section.message}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('blockingEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.WAITER_SID)} / ${escapeHtml(row.WAITER_SERIAL)}</td>
        <td>${escapeHtml(row.WAITER_USER || '-')}</td>
        <td>${escapeHtml(row.WAITER_MACHINE || '-')}</td>
        <td>${escapeHtml(row.BLOCKER_SID)} / ${escapeHtml(row.BLOCKER_SERIAL)}</td>
        <td>${escapeHtml(row.BLOCKER_USER || '-')}</td>
        <td>${escapeHtml(row.WAIT_CLASS || '-')}</td>
        <td>${formatElapsed(row.WAIT_SECONDS)}</td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead>
            <tr>
              <th>${t('waitingSessionHeader')}</th><th>${t('waitingUserHeader')}</th><th>${t('waitingMachineHeader')}</th>
              <th>${t('blockingSessionParenHeader')}</th><th>${t('blockingUserHeader')}</th><th>${t('waitClassHeader')}</th><th>${t('waitTimeHeader')}</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  function renderLongRunningOps(section) {
    setDot('longops', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-longops');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${section.message}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('longOpsEmpty')}</div>`;
      return;
    }
    box.innerHTML = section.data.map(row => {
      const pct = Number(row.PCT_COMPLETE ?? 0);
      const cls = pctClass(pct);
      const opname = escapeHtml(row.OPNAME || '-');
      const target = row.TARGET ? ` (${escapeHtml(row.TARGET)})` : '';
      return `
        <div class="ts-row">
          <div class="ts-row-head">
            <span class="name">SID ${escapeHtml(row.SID)}/${escapeHtml(row.SERIAL_NUM)} · ${opname}${target}</span>
            <span class="pct">${pct.toFixed(1)}%</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill ${cls}" style="width:${Math.min(pct, 100)}%"></div>
          </div>
          <div class="ts-meta">${t('longOpsElapsedRemaining', { elapsed: formatElapsed(row.ELAPSED_SECONDS), remaining: formatElapsed(row.TIME_REMAINING) })}</div>
        </div>`;
    }).join('');
  }

  function renderTopWaitEvents(section) {
    setDot('waitevent', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-waitevent');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${section.message}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('waitEventsEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => {
      const timeWaitedSec = Number(row.TIME_WAITED || 0) / 100;
      const avgWaitMs = Number(row.AVERAGE_WAIT || 0) * 10;
      return `
        <tr>
          <td>${escapeHtml(row.EVENT)}</td>
          <td>${escapeHtml(row.WAIT_CLASS || '-')}</td>
          <td>${Number(row.TOTAL_WAITS || 0).toLocaleString()}</td>
          <td>${timeWaitedSec.toLocaleString(undefined, { maximumFractionDigits: 1 })}s</td>
          <td>${avgWaitMs.toLocaleString(undefined, { maximumFractionDigits: 1 })}ms</td>
        </tr>`;
    }).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead>
            <tr><th>${t('eventHeader')}</th><th>${t('waitClassHeader')}</th><th>${t('totalWaitsHeader')}</th><th>${t('totalWaitTimeHeader')}</th><th>${t('averageWaitTimeHeader')}</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('waitEventsNote')}</div>`;
  }

  // Scheduler/Job Failures card (sits right above Alert Log Analysis, same
  // lazy-load-once + manual-refresh pattern, not part of the 15-second
  // auto-refresh cycle): two independent sub-sections in one card --
  // DBMS_SCHEDULER run history (any outcome other than SUCCEEDED) and a
  // live snapshot of broken/failing legacy DBMS_JOB jobs (see
  // /api/job-failures in backend/routes_jobs.py for why the legacy section
  // is a snapshot, not a history). One Schema filter applies to both
  // sub-tables at once, client-side only, same populateFilterSelect()
  // pattern as the Current Session List / Recent DML filters above.
  const jobFailuresRefreshBtn = document.getElementById('jobFailuresRefreshBtn');
  let latestJobFailuresData = null;

  function applyJobFailuresFilters() {
    const data = latestJobFailuresData;
    const box = document.getElementById('box-jobfailures');
    if (!data) return;

    if (!data.success) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(data.message || t('jobFailuresLoadFailed'))}</div>`;
      return;
    }

    const scheduler = data.schedulerFailures;
    const legacy = data.legacyJobFailures;
    const schemaSelect = document.getElementById('filterJobSchema');
    const schemaValues = [
      ...((scheduler && scheduler.ok) ? scheduler.data.map(r => r.OWNER) : []),
      ...((legacy && legacy.ok) ? legacy.data.map(r => r.SCHEMA_USER) : [])
    ];
    populateFilterSelect(schemaSelect, schemaValues, t('filterLabelSchema'));
    const schemaFilter = schemaSelect.value;

    let schedulerHtml;
    if (!scheduler || !scheduler.ok) {
      schedulerHtml = `<div class="empty-msg">${escapeHtml((scheduler && scheduler.message) || t('jobFailuresLoadFailed'))}</div>`;
    } else if (!scheduler.data.length) {
      schedulerHtml = `<div class="empty-msg">${t('schedulerFailuresEmpty', { days: data.days })}</div>`;
    } else {
      const filtered = scheduler.data.filter(r => !schemaFilter || (r.OWNER || '') === schemaFilter);
      if (!filtered.length) {
        schedulerHtml = `<div class="empty-msg">${t('jobFailuresNoMatch')}</div>`;
      } else {
        const rows = filtered.map(row => {
          const statusCls = row.STATUS === 'FAILED' ? 'critical' : 'warning';
          return `
          <tr>
            <td>${escapeHtml(row.OWNER)}</td>
            <td>${escapeHtml(row.JOB_NAME)}</td>
            <td><span class="alertlog-sev ${statusCls}">${escapeHtml(row.STATUS)}</span></td>
            <td>${escapeHtml(row['ERROR#'] ?? '-')}</td>
            <td>${escapeHtml(row.LOG_DATE || '-')}</td>
            <td>${row.RUN_DURATION_SEC != null ? Number(row.RUN_DURATION_SEC).toLocaleString() : '-'}</td>
            <td class="alertlog-msg">${escapeHtml(row.ADDITIONAL_INFO || '-')}</td>
          </tr>`;
        }).join('');
        schedulerHtml = `
          <div class="sess-table-wrap">
            <table class="sess-table">
              <thead><tr>
                <th>${t('schemaHeader')}</th><th>${t('jobNameHeader')}</th><th>${t('statusHeader')}</th><th>${t('errorCodeHeader')}</th><th>${t('timeHeader')}</th><th>${t('durationSecHeader')}</th><th>${t('messageHeader')}</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>`;
      }
    }

    let legacyHtml;
    if (!legacy || !legacy.ok) {
      legacyHtml = `<div class="empty-msg">${escapeHtml((legacy && legacy.message) || t('jobFailuresLoadFailed'))}</div>`;
    } else if (!legacy.data.length) {
      legacyHtml = `<div class="empty-msg">${t('legacyJobsEmpty')}</div>`;
    } else {
      const filtered = legacy.data.filter(r => !schemaFilter || (r.SCHEMA_USER || '') === schemaFilter);
      if (!filtered.length) {
        legacyHtml = `<div class="empty-msg">${t('jobFailuresNoMatch')}</div>`;
      } else {
        const rows = filtered.map(row => `
          <tr>
            <td>${escapeHtml(row.SCHEMA_USER)}</td>
            <td>${escapeHtml(row.JOB)}</td>
            <td>${escapeHtml(row.BROKEN)}</td>
            <td>${escapeHtml(row.FAILURES)}</td>
            <td>${escapeHtml(row.LAST_DATE || '-')}</td>
            <td>${escapeHtml(row.NEXT_DATE || '-')}</td>
            <td class="alertlog-msg">${escapeHtml(row.WHAT || '-')}</td>
          </tr>`).join('');
        legacyHtml = `
          <div class="sess-table-wrap">
            <table class="sess-table">
              <thead><tr>
                <th>${t('schemaHeader')}</th><th>${t('jobIdHeader')}</th><th>${t('brokenHeader')}</th><th>${t('failuresHeader')}</th><th>${t('lastRunHeader')}</th><th>${t('nextRunHeader')}</th><th>${t('whatHeader')}</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>`;
      }
    }

    box.innerHTML = `
      <div class="modal-section-title">${t('schedulerFailuresTitle')}</div>
      ${schedulerHtml}
      <div class="modal-section-title" style="margin-top:16px">${t('legacyJobsTitle')}</div>
      ${legacyHtml}
      <div class="info-note">${t('jobFailuresNote', { days: data.days })}</div>`;
  }

  function renderJobFailures(data) {
    latestJobFailuresData = data;
    setDot('jobfailures', data.success ? 'ok' : 'error');
    applyJobFailuresFilters();
  }

  async function loadJobFailures() {
    setDot('jobfailures', 'loading');
    jobFailuresRefreshBtn.disabled = true;
    const box = document.getElementById('box-jobfailures');
    box.classList.add('skeleton');
    try {
      const res = await fetch('/api/job-failures');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      lastJobFailuresData = data;
      renderJobFailures(data);
    } catch (err) {
      setDot('jobfailures', 'error');
      box.innerHTML = `<div class="empty-msg">${t('networkError', { msg: escapeHtml(err.message) })}</div>`;
    } finally {
      box.classList.remove('skeleton');
      jobFailuresRefreshBtn.disabled = false;
    }
  }

  jobFailuresRefreshBtn.addEventListener('click', loadJobFailures);
  document.getElementById('filterJobSchema').addEventListener('change', applyJobFailuresFilters);
  document.getElementById('filterJobResetBtn').addEventListener('click', () => {
    document.getElementById('filterJobSchema').value = '';
    applyJobFailuresFilters();
  });

  // Account Security card (DashBoard tab, same lazy-load-once +
  // manual-refresh pattern as Job Failures above): two independent
  // sub-sections sourced from DBA_USERS -- currently locked accounts, and
  // accounts whose password has already expired or is expiring within the
  // requested window. No filter row (unlike Job Failures) since there was
  // no request for one.
  const accountSecurityRefreshBtn = document.getElementById('accountSecurityRefreshBtn');

  function renderAccountSecurity(data) {
    const box = document.getElementById('box-accountsecurity');
    setDot('accountsecurity', data.success ? 'ok' : 'error');

    if (!data.success) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(data.message || t('accountSecurityLoadFailed'))}</div>`;
      return;
    }

    const locked = data.lockedAccounts;
    const expiring = data.expiringPasswords;

    let lockedHtml;
    if (!locked || !locked.ok) {
      lockedHtml = `<div class="empty-msg">${escapeHtml((locked && locked.message) || t('accountSecurityLoadFailed'))}</div>`;
    } else if (!locked.data.length) {
      lockedHtml = `<div class="empty-msg">${t('lockedAccountsEmpty')}</div>`;
    } else {
      const rows = locked.data.map(row => `
        <tr>
          <td>${escapeHtml(row.USERNAME)}</td>
          <td><span class="alertlog-sev warning">${escapeHtml(row.ACCOUNT_STATUS)}</span></td>
          <td>${escapeHtml(row.PROFILE)}</td>
          <td>${escapeHtml(row.LOCK_DATE || '-')}</td>
        </tr>`).join('');
      lockedHtml = `
        <div class="sess-table-wrap">
          <table class="sess-table">
            <thead><tr>
              <th>${t('usernameHeader')}</th><th>${t('accountStatusHeader')}</th><th>${t('profileHeader')}</th><th>${t('lockDateHeader')}</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    }

    let expiringHtml;
    if (!expiring || !expiring.ok) {
      expiringHtml = `<div class="empty-msg">${escapeHtml((expiring && expiring.message) || t('accountSecurityLoadFailed'))}</div>`;
    } else if (!expiring.data.length) {
      expiringHtml = `<div class="empty-msg">${t('expiringPasswordsEmpty', { days: data.days })}</div>`;
    } else {
      const rows = expiring.data.map(row => {
        const statusCls = row.DAYS_UNTIL_EXPIRY < 0 ? 'critical' : 'warning';
        return `
        <tr>
          <td>${escapeHtml(row.USERNAME)}</td>
          <td>${escapeHtml(row.ACCOUNT_STATUS)}</td>
          <td>${escapeHtml(row.PROFILE)}</td>
          <td>${escapeHtml(row.EXPIRY_DATE || '-')}</td>
          <td><span class="alertlog-sev ${statusCls}">${escapeHtml(row.DAYS_UNTIL_EXPIRY)}</span></td>
        </tr>`;
      }).join('');
      expiringHtml = `
        <div class="sess-table-wrap">
          <table class="sess-table">
            <thead><tr>
              <th>${t('usernameHeader')}</th><th>${t('accountStatusHeader')}</th><th>${t('profileHeader')}</th><th>${t('expiryDateHeader')}</th><th>${t('daysUntilExpiryHeader')}</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    }

    box.innerHTML = `
      <div class="modal-section-title">${t('lockedAccountsTitle')}</div>
      ${lockedHtml}
      <div class="modal-section-title" style="margin-top:16px">${t('expiringPasswordsTitle')}</div>
      ${expiringHtml}
      <div class="info-note">${t('accountSecurityNote', { days: data.days })}</div>`;
  }

  async function loadAccountSecurity() {
    setDot('accountsecurity', 'loading');
    accountSecurityRefreshBtn.disabled = true;
    const box = document.getElementById('box-accountsecurity');
    box.classList.add('skeleton');
    try {
      const res = await fetch('/api/account-security');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      lastAccountSecurityData = data;
      renderAccountSecurity(data);
    } catch (err) {
      setDot('accountsecurity', 'error');
      box.innerHTML = `<div class="empty-msg">${t('networkError', { msg: escapeHtml(err.message) })}</div>`;
    } finally {
      box.classList.remove('skeleton');
      accountSecurityRefreshBtn.disabled = false;
    }
  }

  accountSecurityRefreshBtn.addEventListener('click', loadAccountSecurity);

  // Alert Log Analysis card: unlike the other cards, this is NOT part of the
  // 15-second auto-refresh cycle (loadStatus()). V$DIAG_ALERT_EXT can be
  // noticeably slower to query than the other dynamic performance views, so
  // it is loaded once when the page opens and again only when the user
  // clicks this card's own "Refresh" button.
  const alertLogRefreshBtn = document.getElementById('alertLogRefreshBtn');

  // MESSAGE_TYPE values from V$DIAG_ALERT_EXT: 2 = Incident Error, 3 = Error,
  // 4 = Warning. Anything else falls back to "info" styling.
  function classifyAlertLogSeverity(row) {
    const type = Number(row.MESSAGE_TYPE);
    if (type === 2 || row.ORA_CODE) return { label: t('alertSevIncident'), cls: 'critical' };
    if (type === 3) return { label: t('alertSevError'), cls: 'critical' };
    if (type === 4) return { label: t('alertSevWarning'), cls: 'warning' };
    return { label: t('alertSevNotice'), cls: 'info' };
  }

  function renderAlertLog(section) {
    setDot('alertlog', section.success ? 'ok' : 'error');
    const box = document.getElementById('box-alertlog');
    if (!section.success) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('alertLogLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('alertLogEmpty', { days: section.days })}</div>`;
      return;
    }
    const rows = section.data.map(row => {
      const sev = classifyAlertLogSeverity(row);
      const codePrefix = row.ORA_CODE ? `<span class="alertlog-code">${escapeHtml(row.ORA_CODE)}</span> ` : '';
      return `
      <tr>
        <td>${escapeHtml(row.LOG_TIME || '-')}</td>
        <td><span class="alertlog-sev ${sev.cls}">${sev.label}</span></td>
        <td class="alertlog-msg">${codePrefix}${escapeHtml(row.MESSAGE_TEXT || '')}</td>
      </tr>`;
    }).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr><th>${t('timeHeader')}</th><th>${t('severityHeader')}</th><th>${t('messageHeader')}</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('alertLogNote', { days: section.days })}</div>`;
  }

  async function loadAlertLog() {
    setDot('alertlog', 'loading');
    alertLogRefreshBtn.disabled = true;
    const box = document.getElementById('box-alertlog');
    box.classList.add('skeleton');
    try {
      const res = await fetch('/api/alert-log');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      lastAlertLogData = data;
      renderAlertLog(data);
    } catch (err) {
      setDot('alertlog', 'error');
      box.innerHTML = `<div class="empty-msg">${t('networkError', { msg: escapeHtml(err.message) })}</div>`;
    } finally {
      box.classList.remove('skeleton');
      alertLogRefreshBtn.disabled = false;
    }
  }

  alertLogRefreshBtn.addEventListener('click', loadAlertLog);

  // Ops tab: operational/performance-tuning views loosely modeled on a
  // handful of AWR report sections that don't need an actual AWR/Statspack
  // snapshot to produce (see the /api/ops-usage comment in main.js for the
  // full mapping). Lazy-loaded the first time the Ops tab is opened (see
  // the tab-switch handler below), and reloaded via its own "Refresh"
  // button -- like Temp/Recovery, this is not part of the 15-second
  // auto-refresh cycle (see the SQL tab's comment above for why re-running
  // things on a timer isn't always the right default). All six cards below
  // come from the single /api/ops-usage response.
  const opsUsageRefreshBtn = document.getElementById('opsUsageRefreshBtn');
  const boxTopQueries = document.getElementById('box-topqueries');
  const boxTopQueriesCpu = document.getElementById('box-topqueriescpu');
  const boxTopQueriesGets = document.getElementById('box-topqueriesgets');
  const boxWaitEvent = document.getElementById('box-waitevent');
  const boxInstanceEff = document.getElementById('box-instanceeff');
  const boxLoadProfile = document.getElementById('box-loadprofile');
  const boxTablespaceIo = document.getElementById('box-tablespaceio');
  const boxKeyParams = document.getElementById('box-keyparams');
  const boxUndoConfig = document.getElementById('box-undoconfig');
  const boxTempSpace = document.getElementById('box-tempspace');
  const boxTempSession = document.getElementById('box-tempsession');
  const boxAutoextend = document.getElementById('box-autoextend');
  const boxRedoLog = document.getElementById('box-redolog');
  const OPS_BOXES = [boxTopQueries, boxTopQueriesCpu, boxTopQueriesGets, boxWaitEvent, boxInstanceEff, boxLoadProfile, boxTablespaceIo, boxKeyParams, boxUndoConfig, boxTempSpace, boxTempSession, boxAutoextend, boxRedoLog];
  const OPS_DOT_KEYS = ['topqueries', 'topqueriescpu', 'topqueriesgets', 'waitevent', 'instanceeff', 'loadprofile', 'tablespaceio', 'keyparams', 'undoconfig', 'tempspace', 'tempsession', 'autoextend', 'redolog'];

  // Shared row-lead cells (rank + clickable SQL_ID + schema + executions)
  // for the three "Top 5 SQL by <metric>" rankings below -- each just
  // appends its own metric-specific trailing columns after this.
  function sqlRankRowCells(rank, row) {
    return `
        <td><span class="topquery-rank">${rank}</span></td>
        <td><a class="sqlid-link" data-sqlid="${escapeHtml(row.SQL_ID)}" title="${escapeHtml(t('sqlTextPreviewTooltip'))}">${escapeHtml(row.SQL_ID)}</a></td>
        <td>${escapeHtml(row.PARSING_SCHEMA_NAME || '-')}</td>
        <td>${escapeHtml(row.EXECUTIONS ?? '-')}</td>`;
  }

  function renderTopQueries(section) {
    setDot('topqueries', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxTopQueries.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      boxTopQueries.innerHTML = `<div class="empty-msg">${t('topQueriesEmpty')}</div>`;
      return;
    }
    const rows = section.data.map((row, i) => `
      <tr>
        ${sqlRankRowCells(i + 1, row)}
        <td>${row.ELAPSED_SEC != null ? Number(row.ELAPSED_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</td>
        <td>${row.CPU_SEC != null ? Number(row.CPU_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</td>
        <td>${escapeHtml(row.LAST_ACTIVE_TIME || '-')}</td>
      </tr>`).join('');
    boxTopQueries.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('rankHeader')}</th><th>SQL_ID</th><th>${t('schemaHeader')}</th><th>${t('executionsHeader')}</th><th>${t('elapsedTimeHeader')}</th><th>${t('cpuTimeHeader')}</th><th>${t('lastActiveHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('topQueriesNote')}</div>`;
  }

  // AWR's "SQL ordered by CPU Time" -- same shape as renderTopQueries
  // above, ranked by cpu_time instead of elapsed_time (a query can be
  // CPU-bound without being the single slowest in wall-clock terms, so
  // this surfaces ones the elapsed-time ranking would miss).
  function renderTopQueriesCpu(section) {
    setDot('topqueriescpu', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxTopQueriesCpu.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      boxTopQueriesCpu.innerHTML = `<div class="empty-msg">${t('topQueriesEmpty')}</div>`;
      return;
    }
    const rows = section.data.map((row, i) => `
      <tr>
        ${sqlRankRowCells(i + 1, row)}
        <td>${row.ELAPSED_SEC != null ? Number(row.ELAPSED_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</td>
        <td>${row.CPU_SEC != null ? Number(row.CPU_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</td>
        <td>${escapeHtml(row.LAST_ACTIVE_TIME || '-')}</td>
      </tr>`).join('');
    boxTopQueriesCpu.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('rankHeader')}</th><th>SQL_ID</th><th>${t('schemaHeader')}</th><th>${t('executionsHeader')}</th><th>${t('elapsedTimeHeader')}</th><th>${t('cpuTimeHeader')}</th><th>${t('lastActiveHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('topQueriesCpuNote')}</div>`;
  }

  // AWR's "SQL ordered by Gets" (logical reads) -- catches queries that are
  // logically inefficient (e.g. a missing index causing far more block
  // visits than necessary) even when they aren't currently the slowest in
  // wall-clock or CPU terms.
  function renderTopQueriesGets(section) {
    setDot('topqueriesgets', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxTopQueriesGets.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      boxTopQueriesGets.innerHTML = `<div class="empty-msg">${t('topQueriesEmpty')}</div>`;
      return;
    }
    const rows = section.data.map((row, i) => `
      <tr>
        ${sqlRankRowCells(i + 1, row)}
        <td>${Number(row.BUFFER_GETS ?? 0).toLocaleString()}</td>
        <td>${row.ELAPSED_SEC != null ? Number(row.ELAPSED_SEC).toLocaleString() + ' ' + t('secUnit') : '-'}</td>
        <td>${escapeHtml(row.LAST_ACTIVE_TIME || '-')}</td>
      </tr>`).join('');
    boxTopQueriesGets.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('rankHeader')}</th><th>SQL_ID</th><th>${t('schemaHeader')}</th><th>${t('executionsHeader')}</th><th>${t('bufferGetsHeader')}</th><th>${t('elapsedTimeHeader')}</th><th>${t('lastActiveHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('topQueriesGetsNote')}</div>`;
  }

  // Unlike pctClass() (used for disk/memory usage, where a HIGH percentage
  // is bad), a hit ratio is the opposite: a HIGH percentage is good. Same
  // 90/75 thresholds, inverted.
  function efficiencyPctClass(pct) {
    if (pct >= 90) return '';
    if (pct >= 75) return 'warn';
    return 'danger';
  }

  // AWR's "Instance Efficiency Percentages" -- standard hit-ratio formulas,
  // computed cumulative since instance startup (there's no snapshot-to-
  // snapshot delta available without an actual AWR/Statspack snapshot,
  // which needs the Diagnostics Pack license this app doesn't assume).
  function renderInstanceEfficiency(section) {
    setDot('instanceeff', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxInstanceEff.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    const d = section.data || {};
    const metrics = [
      { label: t('bufferHitRatioLabel'), value: d.BUFFER_HIT_RATIO },
      { label: t('libraryHitRatioLabel'), value: d.LIBRARY_HIT_RATIO },
      { label: t('softParsePctLabel'), value: d.SOFT_PARSE_PCT },
      { label: t('executeToParsePctLabel'), value: d.EXECUTE_TO_PARSE_PCT }
    ];
    const rowsHtml = metrics.map(m => {
      if (m.value === null || m.value === undefined) {
        return `
          <div class="ts-row">
            <div class="ts-row-head"><span class="name">${escapeHtml(m.label)}</span><span class="pct">-</span></div>
          </div>`;
      }
      const pct = Number(m.value);
      const cls = efficiencyPctClass(pct);
      return `
        <div class="ts-row">
          <div class="ts-row-head"><span class="name">${escapeHtml(m.label)}</span><span class="pct">${pct.toFixed(1)}%</span></div>
          <div class="bar-track">
            <div class="bar-fill ${cls}" style="width:${Math.min(Math.max(pct, 0), 100)}%"></div>
          </div>
        </div>`;
    }).join('');
    boxInstanceEff.innerHTML = `${rowsHtml}<div class="info-note">${t('instanceEfficiencyNote')}</div>`;
  }

  // AWR's "Load Profile," adapted: instead of per-second averaged over one
  // snapshot interval, this is per-second averaged over the entire
  // instance uptime (same source data as the Main tab's Instance
  // Information uptime clock) -- a coarser number, but one that needs no
  // snapshot history to compute.
  function renderLoadProfile(section) {
    setDot('loadprofile', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxLoadProfile.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    const d = section.data || {};
    const fmt = (v) => (v === null || v === undefined) ? '-' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
    boxLoadProfile.innerHTML = `
      <dl class="kv">
        <dt>${t('loadProfileRedoLabel')}</dt><dd>${fmt(d.REDO_SIZE_PER_SEC)}</dd>
        <dt>${t('loadProfileLogicalReadsLabel')}</dt><dd>${fmt(d.LOGICAL_READS_PER_SEC)}</dd>
        <dt>${t('loadProfilePhysicalReadsLabel')}</dt><dd>${fmt(d.PHYSICAL_READS_PER_SEC)}</dd>
        <dt>${t('loadProfileUserCallsLabel')}</dt><dd>${fmt(d.USER_CALLS_PER_SEC)}</dd>
        <dt>${t('loadProfileExecutesLabel')}</dt><dd>${fmt(d.EXECUTES_PER_SEC)}</dd>
        <dt>${t('loadProfileTransactionsLabel')}</dt><dd>${fmt(d.TRANSACTIONS_PER_SEC)}</dd>
      </dl>
      <div class="info-note">${t('loadProfileNote')}</div>`;
  }

  // AWR's "Tablespace IO Stats," at the datafile level (top 10 by total
  // I/O) -- helps spot a single hot datafile that's dragging on overall
  // I/O performance.
  function renderTablespaceIo(section) {
    setDot('tablespaceio', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxTablespaceIo.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      boxTablespaceIo.innerHTML = `<div class="empty-msg">${t('tablespaceIoEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.TABLESPACE_NAME)}</td>
        <td>${escapeHtml(row.FILE_NAME)}</td>
        <td>${Number(row.PHYSICAL_READS ?? 0).toLocaleString()}</td>
        <td>${Number(row.PHYSICAL_WRITES ?? 0).toLocaleString()}</td>
        <td>${row.AVG_READ_MS != null ? Number(row.AVG_READ_MS).toLocaleString() + ' ms' : '-'}</td>
        <td>${row.AVG_WRITE_MS != null ? Number(row.AVG_WRITE_MS).toLocaleString() + ' ms' : '-'}</td>
      </tr>`).join('');
    boxTablespaceIo.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('tablespaceHeader')}</th><th>${t('fileNameHeader')}</th><th>${t('physicalReadsHeader')}</th><th>${t('physicalWritesHeader')}</th><th>${t('avgReadTimeHeader')}</th><th>${t('avgWriteTimeHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('tablespaceIoNote')}</div>`;
  }

  // A handful of initialization parameters DBAs commonly check at a glance
  // (password expiration policy, SPFILE vs. PFILE, auditing, process/
  // session/cursor/datafile limits, undo retention, optimizer mode, redo
  // log buffer size, archiving mode) -- see the /api/ops-usage comment in
  // main.js for exactly where each value comes from. All instance/database-
  // level values, not per-session overrides.
  function renderKeyParams(section) {
    setDot('keyparams', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxKeyParams.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    const d = section.data || {};
    const na = '-';
    const fmtNum = (v) => (v === null || v === undefined) ? na : Number(v).toLocaleString();
    const spfileInUse = d.SPFILE != null && String(d.SPFILE).trim() !== '';
    const rows = [
      [t('keyParamPasswordLifeTime'), d.PASSWORD_LIFE_TIME != null ? String(d.PASSWORD_LIFE_TIME) : na],
      [t('keyParamSpfile'), spfileInUse ? t('keyParamSpfileYes') : t('keyParamSpfileNo')],
      [t('keyParamAuditTrail'), d.AUDIT_TRAIL || na],
      [t('keyParamProcesses'), fmtNum(d.PROCESSES)],
      [t('keyParamSessions'), fmtNum(d.SESSIONS)],
      [t('keyParamOpenCursors'), fmtNum(d.OPEN_CURSORS)],
      [t('keyParamDbFiles'), fmtNum(d.DB_FILES)],
      [t('keyParamUndoRetention'), d.UNDO_RETENTION != null ? `${Number(d.UNDO_RETENTION).toLocaleString()} ${t('secUnit')}` : na],
      [t('keyParamOptimizerMode'), d.OPTIMIZER_MODE || na],
      [t('keyParamLogBuffer'), d.LOG_BUFFER != null ? `${(Number(d.LOG_BUFFER) / 1024 / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} MB` : na],
      [t('keyParamArchiveMode'), d.ARCHIVE_MODE || na]
    ];
    const rowsHtml = rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('');
    boxKeyParams.innerHTML = `<dl class="kv">${rowsHtml}</dl><div class="info-note">${t('keyParamsNote')}</div>`;
  }

  // Undo Configuration & Status, combined into one card/one flat list: the
  // instance-level settings (automatic vs. manual management, which
  // tablespace undo lives in, the configured retention window, whether
  // that retention is actually enforced via RETENTION GUARANTEE) followed
  // by how full that tablespace actually is (same used/total% approach as
  // the Temp tab's tablespace usage card, just for a permanent tablespace)
  // and what Oracle is actually achieving for undo retention right now
  // (V$UNDOSTAT's TUNED_UNDORETENTION, worth comparing against the
  // configured Undo Retention above it). These come from two independent
  // queries in /api/ops-usage (configSection, statusSection) -- each can
  // fail on its own (e.g. missing privilege on one dictionary view but not
  // the other), so whichever one succeeded is still shown rather than
  // blanking the whole card. Raw Oracle values (AUTO/MANUAL, GUARANTEE/
  // NOGUARANTEE) are shown as-is, same convention as Key Instance
  // Parameters' AUDIT_TRAIL/OPTIMIZER_MODE/ARCHIVE_MODE.
  function renderUndoConfig(configSection, statusSection) {
    const configOk = configSection && configSection.ok;
    const statusOk = statusSection && statusSection.ok;
    setDot('undoconfig', (configOk || statusOk) ? 'ok' : 'error');

    if (!configOk && !statusOk) {
      const msg = (configSection && configSection.message) || (statusSection && statusSection.message) || t('opsUsageLoadFailed');
      boxUndoConfig.innerHTML = `<div class="empty-msg">${escapeHtml(msg)}</div>`;
      return;
    }

    const na = '-';
    const rows = [];
    if (configOk) {
      const d = configSection.data || {};
      rows.push(
        [t('undoManagementLabel'), d.UNDO_MANAGEMENT || na],
        [t('undoTablespaceLabel'), d.UNDO_TABLESPACE || na],
        [t('undoConfigRetentionLabel'), d.UNDO_RETENTION != null ? `${Number(d.UNDO_RETENTION).toLocaleString()} ${t('secUnit')}` : na],
        [t('undoConfigGuaranteeLabel'), d.RETENTION_GUARANTEE || na]
      );
    }
    if (statusOk) {
      const d = statusSection.data || {};
      rows.push(
        [t('undoStatusTotalLabel'), d.TOTAL_MB != null ? Number(d.TOTAL_MB).toLocaleString() : na],
        [t('undoStatusUsedLabel'), d.USED_MB != null ? Number(d.USED_MB).toLocaleString() : na],
        [t('undoStatusUsedPctLabel'), d.USED_PCT != null ? `${Number(d.USED_PCT).toFixed(1)}%` : na],
        [t('undoStatusTunedRetentionLabel'), d.TUNED_UNDO_RETENTION_SEC != null ? `${Number(d.TUNED_UNDO_RETENTION_SEC).toLocaleString()} ${t('secUnit')}` : na]
      );
    }
    const rowsHtml = rows.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd>`).join('');
    const partialFailureNote = !configOk || !statusOk
      ? `<div class="empty-msg">${escapeHtml((!configOk ? configSection.message : statusSection.message) || t('opsUsageLoadFailed'))}</div>`
      : '';
    boxUndoConfig.innerHTML = `<dl class="kv">${rowsHtml}</dl>${partialFailureNote}<div class="info-note">${t('undoConfigStatusNote')}</div>`;
  }

  // Redo Log Status -- one row per redo log group, straight from V$LOG
  // (MEMBERS/ARCHIVED/STATUS are already columns there, no join needed).
  function renderRedoLog(section) {
    setDot('redolog', section.ok ? 'ok' : 'error');
    if (!section.ok) {
      boxRedoLog.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('opsUsageLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      boxRedoLog.innerHTML = `<div class="empty-msg">${t('redoLogEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row['GROUP#'] ?? '-')}</td>
        <td>${escapeHtml(row.STATUS || '-')}</td>
        <td>${escapeHtml(row.MEMBERS ?? '-')}</td>
        <td>${row.SIZE_MB != null ? Number(row.SIZE_MB).toLocaleString() : '-'}</td>
        <td>${escapeHtml(row.ARCHIVED || '-')}</td>
        <td>${escapeHtml(row.FIRST_TIME || '-')}</td>
      </tr>`).join('');
    boxRedoLog.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('redoGroupHeader')}</th><th>${t('statusHeader')}</th><th>${t('redoMembersHeader')}</th><th>${t('redoSizeMbHeader')}</th><th>${t('redoArchivedHeader')}</th><th>${t('redoFirstTimeHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('redoLogNote')}</div>`;
  }

  // Clicking any SQL_ID (in any of the three ranking tables above) opens
  // the same full-text modal used by the session list's "View Running
  // Query" menu item and Recovery's Recent DML table -- these tables only
  // have a SQL_ID (no SID), so it's opened with sid = null. Delegated at
  // the tab-panel level (rather than once per table) since all three
  // tables' SQL_ID links behave identically.
  document.getElementById('tabPanelOps').addEventListener('click', (e) => {
    const link = e.target.closest('.sqlid-link');
    if (!link) return;
    const sqlId = link.getAttribute('data-sqlid');
    if (sqlId) openSessionQueryDetail(null, sqlId);
  });

  async function loadOpsUsage() {
    OPS_DOT_KEYS.forEach(key => setDot(key, 'loading'));
    opsUsageRefreshBtn.disabled = true;
    OPS_BOXES.forEach(box => box.classList.add('skeleton'));
    try {
      const res = await fetch('/api/ops-usage');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        OPS_DOT_KEYS.forEach(key => setDot(key, 'error'));
        const msg = `<div class="empty-msg">${escapeHtml(data.message || t('opsUsageLoadFailed'))}</div>`;
        OPS_BOXES.forEach(box => { box.innerHTML = msg; });
        return;
      }
      lastOpsUsageData = data;
      renderTopQueries(data.topQueries);
      renderTopQueriesCpu(data.topQueriesCpu);
      renderTopQueriesGets(data.topQueriesBufferGets);
      renderTopWaitEvents(data.topWaitEvents);
      renderInstanceEfficiency(data.instanceEfficiency);
      renderLoadProfile(data.loadProfile);
      renderTablespaceIo(data.tablespaceIo);
      renderKeyParams(data.keyParameters);
      renderUndoConfig(data.undoConfig, data.undoStatus);
      renderTempTablespaceUsage(data.tempTablespaceUsage);
      renderTempSessionUsage(data.tempSessionUsage);
      renderDatafileAutoextend(data.datafileAutoextend);
      renderRedoLog(data.redoLogStatus);
    } catch (err) {
      OPS_DOT_KEYS.forEach(key => setDot(key, 'error'));
      const msg = `<div class="empty-msg">${t('networkError', { msg: escapeHtml(err.message) })}</div>`;
      OPS_BOXES.forEach(box => { box.innerHTML = msg; });
    } finally {
      OPS_BOXES.forEach(box => box.classList.remove('skeleton'));
      opsUsageRefreshBtn.disabled = false;
    }
  }

  opsUsageRefreshBtn.addEventListener('click', loadOpsUsage);

  // TEMP Tablespace Usage / TEMP Usage by Session -- formerly their own
  // "Temp" tab; folded into the Ops tab (see the /api/ops-usage comment in
  // main.js) so they lazy-load and refresh together with everything else
  // here instead of needing a separate tab and refresh cycle.
  function renderTempTablespaceUsage(section) {
    setDot('tempspace', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-tempspace');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('tempSpaceLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('tempSpaceEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.TABLESPACE_NAME)}</td>
        <td>${Number(row.USED_GB).toLocaleString()} GB</td>
        <td>${Number(row.FREE_GB).toLocaleString()} GB</td>
        <td>${Number(row.TOTAL_GB).toLocaleString()} GB</td>
        <td class="ts-meter-cell">
          <span class="ts-meter-pct">${Number(row.USED_PCT).toLocaleString()}%</span>
          ${renderMeter(row.USED_PCT)}
        </td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('tablespaceHeader')}</th><th>${t('usedHeader')}</th><th>${t('freeHeader')}</th><th>${t('totalHeader')}</th><th>${t('usedPctHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('tempSpaceNote')}</div>`;
  }

  function renderTempSessionUsage(section) {
    setDot('tempsession', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-tempsession');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('tempSessionLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('tempSessionEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.SID)}</td>
        <td>${escapeHtml(row.SERIAL_NUM)}</td>
        <td>${escapeHtml(row.USERNAME || '-')}</td>
        <td>${escapeHtml(row.MACHINE || '-')}</td>
        <td>${escapeHtml(row.PROGRAM || '-')}</td>
        <td>${escapeHtml(row.SQL_ID || '-')}</td>
        <td>${Number(row.TEMP_MB).toLocaleString()} MB</td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>SID</th><th>SERIAL#</th><th>${t('usernameHeader')}</th><th>${t('machineHeader')}</th><th>${t('programHeader')}</th><th>SQL_ID</th><th>${t('tempUsedHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('tempSessionNote')}</div>`;
  }

  function renderDatafileAutoextend(section) {
    setDot('autoextend', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-autoextend');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('autoextendLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('autoextendEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.TABLESPACE_NAME)}</td>
        <td>${escapeHtml(row.FILE_NAME)}</td>
        <td>${escapeHtml(row.AUTOEXTENSIBLE || '-')}</td>
        <td>${Number(row.CURRENT_MB).toLocaleString()} MB</td>
        <td>${row.MAX_GB != null ? Number(row.MAX_GB).toLocaleString() + ' GB' : '-'}</td>
        <td class="ts-meter-cell">
          ${row.USED_PCT_OF_MAX != null
            ? `<span class="ts-meter-pct">${Number(row.USED_PCT_OF_MAX).toLocaleString()}%</span>${renderMeter(row.USED_PCT_OF_MAX)}`
            : '-'}
        </td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('tablespaceHeader')}</th><th>${t('fileNameHeader')}</th><th>${t('autoextensibleHeader')}</th><th>${t('currentSizeHeader')}</th><th>${t('maxSizeHeader')}</th><th>${t('usedPctOfMaxHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('autoextendNote')}</div>`;
  }

  // Recovery tab: Fast Recovery Area (FRA) usage. Same lazy-load-once /
  // manual-refresh pattern as the Temp tab above.
  const recoveryUsageRefreshBtn = document.getElementById('recoveryUsageRefreshBtn');

  function renderRecoveryDestUsage(section) {
    setDot('recoverydest', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-recoverydest');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('recoveryDestLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('recoveryDestEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.NAME)}</td>
        <td>${Number(row.SPACE_LIMIT_GB).toLocaleString()} GB</td>
        <td>${Number(row.SPACE_USED_GB).toLocaleString()} GB</td>
        <td>${Number(row.SPACE_RECLAIMABLE_GB).toLocaleString()} GB</td>
        <td>${escapeHtml(row.NUMBER_OF_FILES)}</td>
        <td class="ts-meter-cell">
          <span class="ts-meter-pct">${row.USED_PCT_NET != null ? Number(row.USED_PCT_NET).toLocaleString() + '%' : '-'}</span>
          ${row.USED_PCT_NET != null ? renderMeter(row.USED_PCT_NET) : ''}
        </td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('destinationHeader')}</th><th>${t('spaceLimitHeader')}</th><th>${t('usedHeader')}</th><th>${t('reclaimableHeader')}</th><th>${t('filesHeader')}</th><th>${t('usedPctNetHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('recoveryDestNote')}</div>`;
  }

  function renderRecoveryTypeUsage(section) {
    setDot('recoverytype', section.ok ? 'ok' : 'error');
    const box = document.getElementById('box-recoverytype');
    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('recoveryTypeLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('recoveryTypeEmpty')}</div>`;
      return;
    }
    const rows = section.data.map(row => `
      <tr>
        <td>${escapeHtml(row.FILE_TYPE)}</td>
        <td>${escapeHtml(row.NUMBER_OF_FILES)}</td>
        <td class="ts-meter-cell">
          <span class="ts-meter-pct">${Number(row.PERCENT_SPACE_USED).toLocaleString()}%</span>
          ${renderMeter(row.PERCENT_SPACE_USED)}
        </td>
        <td>${Number(row.PERCENT_SPACE_RECLAIMABLE).toLocaleString()}%</td>
      </tr>`).join('');
    box.innerHTML = `
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('fileTypeHeader')}</th><th>${t('filesHeader')}</th><th>${t('pctSpaceUsedHeader')}</th><th>${t('pctReclaimableHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('recoveryTypeNote')}</div>`;
  }

  function dmlTagClass(commandName) {
    const c = (commandName || '').toUpperCase();
    if (c === 'INSERT') return 'insert';
    if (c === 'UPDATE') return 'update';
    if (c === 'DELETE') return 'delete';
    return '';
  }

  // Filterable like the Current Session List above -- section data is kept
  // around so the Type/Schema filters can re-render client-side without a
  // server round-trip (same pattern as latestSessionSection/applySessionFilters).
  let latestDmlSection = null;

  function renderRecentDml(section) {
    latestDmlSection = section;
    setDot('recentdml', section.ok ? 'ok' : 'error');
    applyDmlFilters();
  }

  function applyDmlFilters() {
    const section = latestDmlSection;
    const box = document.getElementById('box-recentdml');
    if (!section) return;

    if (!section.ok) {
      box.innerHTML = `<div class="empty-msg">${escapeHtml(section.message || t('dmlLoadFailed'))}</div>`;
      return;
    }
    if (!section.data.length) {
      box.innerHTML = `<div class="empty-msg">${t('dmlEmptyPool')}</div>`;
      return;
    }

    const typeSelect = document.getElementById('filterDmlType');
    const schemaSelect = document.getElementById('filterDmlSchema');

    populateFilterSelect(typeSelect, section.data.map(r => r.COMMAND_NAME), t('filterLabelType'));
    populateFilterSelect(schemaSelect, section.data.map(r => r.PARSING_SCHEMA_NAME), t('filterLabelSchema'));

    const typeFilter = typeSelect.value;
    const schemaFilter = schemaSelect.value;

    const filtered = section.data.filter(row => {
      const typeOk = !typeFilter || (row.COMMAND_NAME || '') === typeFilter;
      const schemaOk = !schemaFilter || (row.PARSING_SCHEMA_NAME || '') === schemaFilter;
      return typeOk && schemaOk;
    });

    if (!filtered.length) {
      box.innerHTML = `<div class="empty-msg">${t('dmlNoMatch')}</div>`;
      return;
    }

    const rows = filtered.map(row => `
      <tr>
        <td><span class="dml-tag ${dmlTagClass(row.COMMAND_NAME)}">${escapeHtml(row.COMMAND_NAME)}</span></td>
        <td>${escapeHtml(row.SQL_ID)}</td>
        <td>${escapeHtml(row.PARSING_SCHEMA_NAME || '-')}</td>
        <td>${escapeHtml(row.EXECUTIONS ?? '-')}</td>
        <td>${escapeHtml(row.LAST_ACTIVE_TIME || '-')}</td>
        <td>
          <span class="sql-text-preview" data-sqlid="${escapeHtml(row.SQL_ID)}" title="${escapeHtml(t('sqlTextPreviewTooltip'))}">
            ${escapeHtml(row.SQL_TEXT || t('sqlTextEmptyPlaceholder'))}
          </span>
        </td>
      </tr>`).join('');

    const count = (typeFilter || schemaFilter)
      ? `<div class="sess-filter-count">${t('filteredCount', { n: filtered.length, m: section.data.length })}</div>`
      : '';

    box.innerHTML = `
      ${count}
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>
            <th>${t('filterLabelType')}</th><th>SQL_ID</th><th>${t('schemaHeader')}</th><th>${t('executionsHeader')}</th><th>${t('lastActiveHeader')}</th><th>${t('sqlTextHeader')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="info-note">${t('dmlNote')}</div>`;
  }

  document.getElementById('filterDmlType').addEventListener('change', applyDmlFilters);
  document.getElementById('filterDmlSchema').addEventListener('change', applyDmlFilters);
  document.getElementById('filterDmlResetBtn').addEventListener('click', () => {
    document.getElementById('filterDmlType').value = '';
    document.getElementById('filterDmlSchema').value = '';
    applyDmlFilters();
  });

  // Clicking a row's truncated SQL text preview opens the same full-text
  // modal used by the session list's "View Running Query" menu item --
  // this table only has a SQL_ID (no SID), so it's opened with sid = null.
  document.getElementById('box-recentdml').addEventListener('click', (e) => {
    const preview = e.target.closest('.sql-text-preview');
    if (!preview) return;
    const sqlId = preview.getAttribute('data-sqlid');
    if (sqlId) openSessionQueryDetail(null, sqlId);
  });

  async function loadRecoveryUsage() {
    setDot('recoverydest', 'loading');
    setDot('recoverytype', 'loading');
    setDot('recentdml', 'loading');
    recoveryUsageRefreshBtn.disabled = true;
    const destBox = document.getElementById('box-recoverydest');
    const typeBox = document.getElementById('box-recoverytype');
    const dmlBox = document.getElementById('box-recentdml');
    destBox.classList.add('skeleton');
    typeBox.classList.add('skeleton');
    dmlBox.classList.add('skeleton');
    try {
      const res = await fetch('/api/recovery-usage');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('recoverydest', 'error');
        setDot('recoverytype', 'error');
        setDot('recentdml', 'error');
        const msg = `<div class="empty-msg">${escapeHtml(data.message || t('recoveryUsageLoadFailed'))}</div>`;
        destBox.innerHTML = msg;
        typeBox.innerHTML = msg;
        dmlBox.innerHTML = msg;
        return;
      }
      lastRecoveryUsageData = data;
      renderRecoveryDestUsage(data.destUsage);
      renderRecoveryTypeUsage(data.typeUsage);
      renderRecentDml(data.recentDml);
    } catch (err) {
      setDot('recoverydest', 'error');
      setDot('recoverytype', 'error');
      setDot('recentdml', 'error');
      const msg = `<div class="empty-msg">${t('networkError', { msg: escapeHtml(err.message) })}</div>`;
      destBox.innerHTML = msg;
      typeBox.innerHTML = msg;
      dmlBox.innerHTML = msg;
    } finally {
      destBox.classList.remove('skeleton');
      typeBox.classList.remove('skeleton');
      dmlBox.classList.remove('skeleton');
      recoveryUsageRefreshBtn.disabled = false;
    }
  }

  recoveryUsageRefreshBtn.addEventListener('click', loadRecoveryUsage);

  // --- Tuning tab: rule-based health check, no history needed for most
  // checks but "rate" checks (hit ratios, hard parsing, wait events) are
  // computed as the *increase* since the previous check (statspack-style),
  // so they may show "not enough history yet" on the very first check for
  // a database -- see tuning.py/tuning.js for the full reasoning. Loads
  // lazily the first time this tab is opened (like Ops/Recovery), and
  // again via its own Refresh button; never part of the 15s auto-refresh.
  const tuningRefreshBtn = document.getElementById('tuningRefreshBtn');

  const TUNING_SEV_KEY = { critical: 'tuningSevCritical', warning: 'tuningSevWarning', info: 'tuningSevInfo' };
  const TUNING_CATEGORY_KEY = {
    memory: 'tuningCatMemory', sql: 'tuningCatSql', storage: 'tuningCatStorage',
    object: 'tuningCatObject', lock: 'tuningCatLock', wait_event: 'tuningCatWaitEvent'
  };

  function tuningSevBadge(sev) {
    return `<span class="alertlog-sev ${sev}">${t(TUNING_SEV_KEY[sev] || 'tuningSevInfo')}</span>`;
  }

  // Rule ids fall into two shapes: a single scalar value per check (a
  // title + one-line message), or a *group* of same-type occurrences
  // (multiple over-threshold tablespaces, multiple slow SQL, etc.) --
  // those render as one item with a table of rows instead of a separate
  // item per occurrence, so e.g. 3 nearly-full tablespaces show up
  // together rather than as 3 near-duplicate cards.
  function tuningFindingBody(f) {
    switch (f.ruleId) {
      case 'buffer_cache_hit_ratio':
        return { title: t('tuningTitleBufferCacheHitRatio'), html: `<div class="tuning-item-msg">${escapeHtml(t('tuningMsgBufferCacheHitRatio', { value: f.value }))}</div>` };
      case 'library_cache_hit_ratio':
        return { title: t('tuningTitleLibraryCacheHitRatio'), html: `<div class="tuning-item-msg">${escapeHtml(t('tuningMsgLibraryCacheHitRatio', { value: f.value }))}</div>` };
      case 'hard_parse_ratio':
        return { title: t('tuningTitleHardParseRatio'), html: `<div class="tuning-item-msg">${escapeHtml(t('tuningMsgHardParseRatio', { value: f.value }))}</div>` };
      case 'disk_sort':
        return { title: t('tuningTitleDiskSort'), html: `<div class="tuning-item-msg">${escapeHtml(t('tuningMsgDiskSort', { count: f.count }))}</div>` };

      case 'tablespace_usage': {
        const rows = f.rows.map(r => `
          <tr>
            <td>${escapeHtml(r.tablespaceName)}</td>
            <td>${r.value}%</td>
            <td>${tuningSevBadge(r.severity)}</td>
          </tr>`).join('');
        return {
          title: t('tuningTitleTablespaceUsage'),
          html: `
            <div class="tuning-item-msg">${escapeHtml(t('tuningMsgTablespaceUsageGeneric'))}</div>
            <div class="sess-table-wrap"><table class="sess-table">
              <thead><tr><th>${t('tuningColTablespace')}</th><th>${t('tuningColUsage')}</th><th>${t('severityHeader')}</th></tr></thead>
              <tbody>${rows}</tbody>
            </table></div>`
        };
      }

      case 'invalid_objects': {
        const rows = f.rows.map(r => `
          <tr><td>${escapeHtml(r.owner)}</td><td>${escapeHtml(r.objectName)}</td><td>${escapeHtml(r.objectType)}</td></tr>`).join('');
        const note = f.truncated ? `<div class="sess-table-note">${t('tuningTruncatedNote', { n: f.count })}</div>` : '';
        return {
          title: t('tuningTitleInvalidObjects', { count: f.count }),
          html: `
            <div class="tuning-item-msg">${escapeHtml(t('tuningMsgInvalidObjectsGeneric'))}</div>
            <div class="sess-table-wrap"><table class="sess-table">
              <thead><tr><th>${t('ownerHeader')}</th><th>${t('objectNameHeader')}</th><th>${t('typeHeader')}</th></tr></thead>
              <tbody>${rows}</tbody>
            </table></div>${note}`
        };
      }

      case 'blocking_session': {
        const rows = f.rows.map(r => `
          <tr>
            <td>${r.waiterSid} / ${escapeHtml(r.waiterUser || '-')}</td>
            <td>${r.blockerSid} / ${escapeHtml(r.blockerUser || '-')}</td>
            <td>${r.waitSeconds}</td>
          </tr>`).join('');
        return {
          title: t('tuningTitleBlockingSession', { count: f.count }),
          html: `
            <div class="tuning-item-msg">${escapeHtml(t('tuningMsgBlockingSessionGeneric'))}</div>
            <div class="sess-table-wrap"><table class="sess-table">
              <thead><tr><th>${t('tuningColWaiter')}</th><th>${t('tuningColBlocker')}</th><th>${t('secondsInWaitHeader')}</th></tr></thead>
              <tbody>${rows}</tbody>
            </table></div>`
        };
      }

      case 'wait_event_top': {
        const rows = f.rows.map(r => `
          <tr>
            <td>#${r.rank}</td>
            <td>${escapeHtml(r.event)}</td>
            <td>${r.seconds}s</td>
            <td>${escapeHtml(t(r.hintKey))}</td>
          </tr>`).join('');
        return {
          title: t('tuningTitleWaitEvent'),
          html: `<div class="sess-table-wrap"><table class="sess-table">
              <thead><tr><th>#</th><th>${t('eventHeader')}</th><th>${t('tuningColIncrease')}</th><th>${t('tuningColHint')}</th></tr></thead>
              <tbody>${rows}</tbody>
            </table></div>`
        };
      }

      case 'slow_sql': {
        const rows = f.rows.map(r => `
          <tr>
            <td><a class="sqlid-link" data-sqlid="${escapeHtml(r.sqlId)}" title="${escapeHtml(t('sqlTextPreviewTooltip'))}">${escapeHtml(r.sqlId)}</a></td>
            <td>${r.avgElapsedSec}s</td>
            <td>${r.executions}</td>
          </tr>`).join('');
        return {
          title: t('tuningTitleSlowSql'),
          html: `<div class="sess-table-wrap"><table class="sess-table">
              <thead><tr><th>SQL_ID</th><th>${t('tuningColAvgElapsed')}</th><th>${t('executionsHeader')}</th></tr></thead>
              <tbody>${rows}</tbody>
            </table></div>`
        };
      }

      default:
        return { title: f.ruleId, html: '' };
    }
  }

  function fmtTuningTime(ms) {
    const d = new Date(ms);
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function renderTuningResult(data) {
    const box = document.getElementById('box-tuning');
    const counts = { critical: 0, warning: 0, info: 0 };
    data.findings.forEach(f => { counts[f.severity] = (counts[f.severity] || 0) + 1; });

    const summaryHtml = `
      <div class="tuning-summary">
        <span class="alertlog-sev critical">${t('tuningSevCritical')} ${counts.critical}</span>
        <span class="alertlog-sev warning">${t('tuningSevWarning')} ${counts.warning}</span>
        <span class="alertlog-sev info">${t('tuningSevInfo')} ${counts.info}</span>
      </div>
      <div class="tuning-meta">${t('tuningCheckedAt', { time: escapeHtml(fmtTuningTime(data.checkedAt)) })}${
        data.elapsedSeconds != null ? ' &middot; ' + t('tuningIntervalNote', { sec: Math.round(data.elapsedSeconds) }) : ''
      }</div>`;

    let bodyHtml;
    if (!data.findings.length) {
      bodyHtml = `<div class="empty-msg tuning-clean">${t('tuningNoIssues')}</div>`;
    } else {
      bodyHtml = `<div class="tuning-list">${data.findings.map(f => {
        const { title, html } = tuningFindingBody(f);
        return `
          <div class="tuning-item">
            <div class="tuning-item-head">
              ${tuningSevBadge(f.severity)}
              <span class="tuning-item-category">${t(TUNING_CATEGORY_KEY[f.category] || 'tuningCatSql')}</span>
              <span class="tuning-item-title">${escapeHtml(title)}</span>
            </div>
            ${html}
          </div>`;
      }).join('')}</div>`;
    }

    const noteHtml = (data.insufficientHistory && data.insufficientHistory.length)
      ? `<div class="info-note">${t('tuningInsufficientHistoryNote')}</div>`
      : '';

    box.innerHTML = summaryHtml + bodyHtml + noteHtml;
  }

  async function loadTuningCheck() {
    setDot('tuning', 'loading');
    tuningRefreshBtn.disabled = true;
    const box = document.getElementById('box-tuning');
    box.innerHTML = `<div class="skeleton">${t('loadingLabel')}</div>`;
    try {
      const res = await fetch('/api/tuning-check');
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('tuning', 'error');
        box.innerHTML = `<div class="empty-msg">${escapeHtml(data.message)}</div>`;
        return;
      }
      setDot('tuning', 'ok');
      lastTuningData = data;
      renderTuningResult(data);
    } catch (err) {
      setDot('tuning', 'error');
      box.innerHTML = `<div class="empty-msg">${t('tuningLoadFailedMsg', { msg: escapeHtml(err.message) })}</div>`;
    } finally {
      tuningRefreshBtn.disabled = false;
    }
  }

  tuningRefreshBtn.addEventListener('click', loadTuningCheck);

  // Clicking a SQL_ID in the Slow SQL table opens the same full-text modal
  // used everywhere else a SQL_ID link appears (Ops tab's Top SQL tables,
  // Recovery's Recent DML) -- delegated at the tab-panel level, same
  // pattern as those.
  document.getElementById('tabPanelTuning').addEventListener('click', (e) => {
    const link = e.target.closest('.sqlid-link');
    if (!link) return;
    const sqlId = link.getAttribute('data-sqlid');
    if (sqlId) openSessionQueryDetail(null, sqlId);
  });

  // --- SQL tab: ad-hoc read-only query runner ---
  // Unlike every other card, this one has no "load on tab open" or 15s
  // auto-refresh behavior at all -- it only ever changes when the user
  // explicitly clicks Run (or presses Ctrl/Cmd+Enter). This is deliberate:
  // a query the user typed shouldn't be silently re-executed against a live
  // production instance on a timer, and the result they're looking at
  // shouldn't disappear out from under them while they're reading it.
  const sqlRunnerInput = document.getElementById('sqlRunnerInput');
  const sqlRunnerRunBtn = document.getElementById('sqlRunnerRunBtn');
  const sqlRunnerCancelBtn = document.getElementById('sqlRunnerCancelBtn');
  const sqlRunnerClearBtn = document.getElementById('sqlRunnerClearBtn');
  const boxSqlRunner = document.getElementById('box-sqlrunner');
  // Set while a /api/run-query request is in flight, cleared once it
  // settles -- lets the Cancel button address that exact server-side
  // connection (see main.py/main.js's /api/cancel-query) without racing a
  // second Run click, since Run stays disabled for the same duration.
  let currentSqlRunnerQueryId = null;

  function renderSqlRunnerResult(data) {
    if (!data.columns || data.columns.length === 0) {
      boxSqlRunner.innerHTML = `<div class="empty-msg">${t('sqlRunnerNoColumns')}</div>`;
      return;
    }
    if (!data.rows || data.rows.length === 0) {
      boxSqlRunner.innerHTML = `<div class="empty-msg">${t('sqlRunnerNoRows')}</div>`;
      return;
    }
    const headerHtml = data.columns.map(col => `<th>${escapeHtml(col)}</th>`).join('');
    const rowsHtml = data.rows.map(row => {
      const cellsHtml = data.columns.map(col => {
        const v = row[col];
        if (v === null || v === undefined) {
          return `<td><span class="sql-null">NULL</span></td>`;
        }
        return `<td>${escapeHtml(v)}</td>`;
      }).join('');
      return `<tr>${cellsHtml}</tr>`;
    }).join('');
    const capNoteHtml = data.rows.length >= 200
      ? `<div class="info-note">${t('sqlRunnerCapNote')}</div>`
      : '';
    boxSqlRunner.innerHTML = `
      <div class="info-note">${t('sqlRunnerRowCount', { n: data.rows.length })}</div>
      <div class="sess-table-wrap">
        <table class="sess-table">
          <thead><tr>${headerHtml}</tr></thead>
          <tbody>${rowsHtml}</tbody>
        </table>
      </div>
      ${capNoteHtml}`;
  }

  async function runSqlQuery() {
    const sql = sqlRunnerInput.value.trim();
    if (!sql) {
      boxSqlRunner.innerHTML = `<div class="empty-msg">${t('sqlRunnerEmptyInput')}</div>`;
      return;
    }
    const queryId = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
    currentSqlRunnerQueryId = queryId;
    setDot('sqlrunner', 'loading');
    sqlRunnerRunBtn.disabled = true;
    sqlRunnerCancelBtn.disabled = false;
    const originalLabel = sqlRunnerRunBtn.textContent;
    sqlRunnerRunBtn.textContent = t('sqlRunnerRunningLabel');
    boxSqlRunner.classList.add('skeleton');
    try {
      const res = await fetch('/api/run-query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql, queryId })
      });
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (!data.success) {
        setDot('sqlrunner', 'error');
        lastSqlRunnerData = null;
        const msg = data.cancelled ? t('sqlRunnerCancelled') : (data.message || t('dbStatusLoadFailed'));
        boxSqlRunner.innerHTML = `<div class="empty-msg">${escapeHtml(msg)}</div>`;
        return;
      }
      setDot('sqlrunner', 'ok');
      lastSqlRunnerData = data;
      renderSqlRunnerResult(data);
    } catch (err) {
      setDot('sqlrunner', 'error');
      lastSqlRunnerData = null;
      boxSqlRunner.innerHTML = `<div class="empty-msg">${t('networkError', { msg: escapeHtml(err.message) })}</div>`;
    } finally {
      currentSqlRunnerQueryId = null;
      sqlRunnerRunBtn.disabled = false;
      sqlRunnerCancelBtn.disabled = true;
      sqlRunnerRunBtn.textContent = originalLabel;
      boxSqlRunner.classList.remove('skeleton');
    }
  }

  sqlRunnerRunBtn.addEventListener('click', runSqlQuery);
  sqlRunnerCancelBtn.addEventListener('click', async () => {
    const queryId = currentSqlRunnerQueryId;
    if (!queryId) return;
    sqlRunnerCancelBtn.disabled = true;
    try {
      const res = await fetch('/api/cancel-query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ queryId })
      });
      if (res.status === 401) {
        window.location.href = '/';
        return;
      }
      const data = await res.json();
      if (data.success) {
        showToast(t('sqlRunnerCancelRequested'), 'ok');
      } else {
        showToast(data.message || t('sqlRunnerCancelFailed', { msg: '' }), 'error');
      }
    } catch (err) {
      showToast(t('sqlRunnerCancelFailed', { msg: err.message }), 'error');
    }
  });
  sqlRunnerClearBtn.addEventListener('click', () => {
    sqlRunnerInput.value = '';
    lastSqlRunnerData = null;
    setDot('sqlrunner', 'ok');
    boxSqlRunner.innerHTML = `<div class="empty-msg">${t('sqlRunnerIdle')}</div>`;
  });
  // Ctrl+Enter (Cmd+Enter on Mac) runs the query without leaving the textarea
  sqlRunnerInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      runSqlQuery();
    }
  });

  // Tab switching (Main / Temp / Recovery). The Temp and Recovery tabs'
  // data is fetched lazily, the first time each is opened, rather than on
  // initial page load, since they're secondary views most sessions won't
  // visit every time.
