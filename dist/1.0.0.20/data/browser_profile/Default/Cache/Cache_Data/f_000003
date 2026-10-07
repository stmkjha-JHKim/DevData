// public/js/dashboard.js -- tab switching + all four tabs' data loading,
// wired to the FastAPI routes under backend/routes_*.py.
(function () {
  const params = new URLSearchParams(window.location.search);
  let currentDbId = params.get('db') || '';
  let dbNameById = {};
  const loadedTabs = new Set();
  let previousActiveTab = 'main';

  function escapeHtml(v) {
    if (v === null || v === undefined) return '';
    return String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function fmtBytes(n) {
    if (n === null || n === undefined) return '-';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let v = n, i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function fmtDuration(sec) {
    if (sec === null || sec === undefined) return '-';
    const m = Math.floor(sec / 60), s = Math.round(sec % 60);
    return m > 0 ? `${m}분 ${s}초` : `${s}초`;
  }

  function statusChip(status) {
    const map = {
      SUCCESS: ['success', '성공'], FAILED: ['error', '실패'], RUNNING: ['running', '진행 중'],
      PENDING: ['warn', '대기'], NEVER: ['off', '미실행'],
    };
    const [cls, label] = map[status] || ['off', status || '-'];
    return `<span class="chip ${cls}">${label}</span>`;
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    return res.json();
  }

  function showBanner(msg) {
    const el = document.getElementById('banner');
    if (!msg) { el.style.display = 'none'; return; }
    el.textContent = msg;
    el.style.display = 'block';
  }

  // ---- top bar: DB selector ----
  async function loadDbSelect() {
    const data = await api('/api/dbs');
    const dbs = (data.success && data.dbs) || [];
    dbNameById = {};
    dbs.forEach((d) => { dbNameById[d.id] = d.name; });
    const select = document.getElementById('dbSelect');
    select.innerHTML = '<option value="">대상 DB: 전체</option>' +
      dbs.map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('');
    select.value = currentDbId;
  }
  document.getElementById('dbSelect').addEventListener('change', (e) => {
    currentDbId = e.target.value;
    const url = new URL(window.location.href);
    if (currentDbId) url.searchParams.set('db', currentDbId); else url.searchParams.delete('db');
    window.history.replaceState({}, '', url);
    loadedTabs.clear();
    loadActiveTab();
  });
  document.getElementById('newDbBtn').addEventListener('click', () => { window.location.href = '/index.html'; });
  document.getElementById('refreshBtn').addEventListener('click', () => { loadedTabs.clear(); loadActiveTab(); });

  // ---- tabs ----
  const tabButtons = Array.from(document.querySelectorAll('.tab-btn'));
  const tabPanels = {
    main: document.getElementById('tabPanelMain'),
    manual: document.getElementById('tabPanelManual'),
    history: document.getElementById('tabPanelHistory'),
  };
  function activeTabName() {
    return (tabButtons.find((b) => b.classList.contains('active')) || tabButtons[0]).dataset.tab;
  }
  function showTab(name) {
    const current = activeTabName();
    if (current !== name) previousActiveTab = current;
    tabButtons.forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    Object.entries(tabPanels).forEach(([key, el]) => { el.hidden = key !== name; });
    loadActiveTab();
  }
  tabButtons.forEach((btn) => btn.addEventListener('click', () => showTab(btn.dataset.tab)));

  function loadActiveTab() {
    const name = activeTabName();
    if (loadedTabs.has(name)) return;
    loadedTabs.add(name);
    if (name === 'main') loadMain();
    else if (name === 'manual') loadManual();
    else if (name === 'history') loadHistory();
  }

  // ---- 개요 ----
  async function loadMain() {
    const data = await api('/api/dashboard/summary');
    if (!data.success) return;
    document.getElementById('sumDbCount').textContent = data.dbCount;
    document.getElementById('sumDbSub').textContent = data.dbCount === 0 ? 'DB를 등록해 시작하세요' : '';
    document.getElementById('sumPolicyCount').textContent = data.activePolicyCount;
    const sc = data.scopeCounts || {};
    document.getElementById('sumPolicySub').textContent =
      `Full ${sc.FULL || 0} · Schema ${sc.SCHEMA || 0} · Table ${sc.TABLE || 0}`;
    document.getElementById('sumFailCount').textContent = data.failuresLast24h;
    document.getElementById('sumFailSub').textContent = data.failuresLast24h > 0 ? '아래 경고 목록 참고' : '정상';
    const last = data.recentRuns && data.recentRuns[0];
    document.getElementById('sumLastRun').textContent = last ? last.status : '-';
    document.getElementById('sumLastRunSub').textContent = last ? `${last.policyName} · ${last.startedAt}` : '아직 실행 이력 없음';

    const dbTable = document.getElementById('dbStatusTable');
    if (!data.dbs.length) {
      dbTable.innerHTML = '<div class="empty-msg">등록된 DB가 없습니다. 상단의 "+ DB 등록" 버튼으로 추가하세요.</div>';
    } else {
      dbTable.innerHTML = `<div class="sess-table-wrap"><table class="sess-table">
        <thead><tr><th>DB</th><th>최근 백업</th><th>결과</th></tr></thead>
        <tbody>${data.dbs.map((d) => `<tr><td>${escapeHtml(d.name)}</td><td>${d.lastBackupAt || '-'}</td><td>${statusChip(d.lastBackupStatus || 'NEVER')}</td></tr>`).join('')}</tbody>
      </table></div>`;
    }

    const runsTable = document.getElementById('recentRunsTable');
    if (!data.recentRuns.length) {
      runsTable.innerHTML = '<div class="empty-msg">아직 실행 이력이 없습니다.</div>';
    } else {
      runsTable.innerHTML = `<div class="sess-table-wrap"><table class="sess-table">
        <thead><tr><th>정책</th><th>DB</th><th>상태</th><th>소요시간</th><th>덤프 크기</th><th>시작 시각</th></tr></thead>
        <tbody>${data.recentRuns.map((r) => `<tr><td>${escapeHtml(r.policyName)}</td><td>${escapeHtml(r.dbName)}</td><td>${statusChip(r.status)}</td><td>${fmtDuration(r.durationSeconds)}</td><td>${fmtBytes(r.dumpSizeBytes)}</td><td>${r.startedAt || '-'}</td></tr>`).join('')}</tbody>
      </table></div>`;
    }

    const warnList = document.getElementById('warningsList');
    if (!data.warnings.length) {
      warnList.innerHTML = '<div class="empty-msg">확인이 필요한 항목이 없습니다.</div>';
    } else {
      warnList.innerHTML = `<div style="display:flex; flex-direction:column; gap:12px;">${data.warnings.map((w) => `<div class="alert-row"><span class="chip warn">${escapeHtml(w.kind)}</span><span>${escapeHtml(w.text)}</span></div>`).join('')}</div>`;
    }
  }

  // ---- 메뉴얼 백업 ----
  async function loadManual() {
    const dbsRes = await api('/api/dbs');
    const dbs = (dbsRes.success && dbsRes.dbs) || [];
    if (!dbs.length) {
      document.getElementById('mb_directory').innerHTML = '<option value="">-</option>';
      showBanner('등록된 DB가 없습니다. 상단의 "+ DB 등록" 버튼으로 추가하세요.');
      return;
    }
    // No DB picker of its own -- this tab just uses whatever the top bar's
    // "대상 DB" selector has chosen (falling back to the first registered DB
    // when that's set to "전체"). Changing the top selector clears
    // loadedTabs and reloads the active tab, so this always re-runs with
    // the new DB instead of going stale.
    const dbId = (currentDbId && dbs.some((d) => d.id === currentDbId)) ? currentDbId : dbs[0].id;

    const scopeSelect = document.getElementById('mb_scope');
    const scopeHint = document.getElementById('mb_scopeHint');
    const schemaTargetWrap = document.getElementById('mb_schemaTargetWrap');
    const schemaMultiSelect = document.getElementById('mb_schemaSelect');
    const tableTargetWrap = document.getElementById('mb_tableTargetWrap');
    const tableSchemaSelect = document.getElementById('mb_tableSchema');
    const tableGridWrap = document.getElementById('mb_tableGridWrap');
    const tableGridBody = document.getElementById('mb_tableGridBody');
    const tableSelectAll = document.getElementById('mb_tableSelectAll');
    let schemasLoadedForDb = null;

    let manualPollTimer = null;
    const progressLine = document.getElementById('mb_progressLine');
    const scriptCard = document.getElementById('mb_scriptCard');
    const scriptBody = document.getElementById('mb_scriptBody');
    const resultCard = document.getElementById('mb_resultCard');
    const resultBody = document.getElementById('mb_resultBody');

    function hideManualOutputs() {
      if (manualPollTimer) { clearInterval(manualPollTimer); manualPollTimer = null; }
      scriptCard.style.display = 'none';
      resultCard.style.display = 'none';
      progressLine.style.display = 'none';
    }

    function fmtStatNum(n) { return (n === null || n === undefined) ? '-' : Number(n).toLocaleString(); }

    async function loadSchemas() {
      // Populates both schema pickers from the one schema list -- TABLE
      // scope's single-select (mb_tableSchema, which then loads that one
      // schema's tables) and SCHEMA scope's multi-select (mb_schemaSelect,
      // used directly as the backup target) -- so switching between the
      // two scopes doesn't re-fetch the same list twice.
      tableSchemaSelect.innerHTML = '<option value="">불러오는 중...</option>';
      schemaMultiSelect.innerHTML = '<option value="">불러오는 중...</option>';
      tableGridWrap.style.display = 'none';
      tableGridBody.innerHTML = '';
      const res = await api(`/api/manual/${dbId}/schemas`);
      if (!res.success || !(res.schemas || []).length) {
        tableSchemaSelect.innerHTML = '<option value="">스키마를 찾을 수 없습니다</option>';
        schemaMultiSelect.innerHTML = '';
        if (!res.success) showBanner(`스키마 목록을 가져오지 못했습니다: ${res.message || ''}`);
        return;
      }
      const options = res.schemas.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join('');
      tableSchemaSelect.innerHTML = options;
      schemaMultiSelect.innerHTML = options;
      schemasLoadedForDb = dbId;
      if (scopeSelect.value === 'TABLE') await loadTables(tableSchemaSelect.value);
    }

    async function loadTables(schema) {
      tableSelectAll.checked = false;
      if (!schema) { tableGridWrap.style.display = 'none'; tableGridBody.innerHTML = ''; return; }
      tableGridWrap.style.display = '';
      tableGridBody.innerHTML = '<tr><td colspan="5" class="empty-msg">불러오는 중...</td></tr>';
      const res = await api(`/api/manual/${dbId}/tables?schema=${encodeURIComponent(schema)}`);
      if (!res.success || !(res.tables || []).length) {
        tableGridBody.innerHTML = '<tr><td colspan="5" class="empty-msg">테이블이 없습니다.</td></tr>';
        if (!res.success) showBanner(`테이블 목록을 가져오지 못했습니다: ${res.message || ''}`);
        return;
      }
      tableGridBody.innerHTML = res.tables.map((t) => `
        <tr>
          <td><input type="checkbox" class="mb-table-check" value="${escapeHtml(t.name)}"></td>
          <td>${escapeHtml(t.name)}</td>
          <td>${fmtStatNum(t.numRows)}</td>
          <td>${fmtStatNum(t.blocks)}</td>
          <td>${fmtStatNum(t.sampleSize)}</td>
        </tr>`).join('');
    }

    tableSchemaSelect.addEventListener('change', () => loadTables(tableSchemaSelect.value));
    tableSelectAll.addEventListener('change', () => {
      tableGridBody.querySelectorAll('.mb-table-check').forEach((cb) => { cb.checked = tableSelectAll.checked; });
    });

    // Called once a TABLE-scope backup finishes (success or failure) so the
    // just-backed-up tables aren't still checked for the next run.
    function uncheckAllTables() {
      tableGridBody.querySelectorAll('.mb-table-check:checked').forEach((cb) => { cb.checked = false; });
      tableSelectAll.checked = false;
    }

    function syncScopeHint() {
      const isTable = scopeSelect.value === 'TABLE';
      const isSchema = scopeSelect.value === 'SCHEMA';
      // This tab's own hint text, not the shared SCOPE_HINT (that one still
      // describes the 백업 정책 tab's free-text inputs -- this tab no longer
      // has any, both remaining scopes are pick-from-a-list).
      scopeHint.textContent = isSchema
        ? '아래 목록에서 백업할 스키마를 선택하세요 (여러 개 선택 가능).'
        : '아래에서 스키마를 고르면 테이블 목록이 나타납니다. 백업할 테이블을 체크하세요.';
      schemaTargetWrap.style.display = isSchema ? '' : 'none';
      tableTargetWrap.style.display = isTable ? '' : 'none';
      // Only show the table grid for TABLE scope, and even then only once a
      // schema is actually picked -- loadTables() re-shows it once rows come
      // back. Without this, switching from TABLE to SCHEMA left the grid
      // (and whatever was checked in it) visible since nothing else hid it.
      tableGridWrap.style.display = (isTable && tableSchemaSelect.value) ? '' : 'none';
      if ((isTable || isSchema) && schemasLoadedForDb !== dbId) loadSchemas();
    }
    scopeSelect.addEventListener('change', () => { hideManualOutputs(); syncScopeHint(); });
    syncScopeHint();

    const dirSelect = document.getElementById('mb_directory');
    const dirPath = document.getElementById('mb_directoryPath');
    let directories = [];

    function syncDirPath() {
      const dir = directories.find((d) => d.name === dirSelect.value);
      dirPath.value = dir ? dir.path : '';
    }
    dirSelect.addEventListener('change', syncDirPath);

    async function loadDirectories() {
      dirSelect.innerHTML = '<option value="">불러오는 중...</option>';
      dirPath.value = '';
      const res = await api(`/api/manual/${dbId}/directories`);
      if (!res.success) {
        dirSelect.innerHTML = '<option value="">-</option>';
        showBanner(`디렉토리 목록을 가져오지 못했습니다: ${res.message || ''}`);
        return;
      }
      directories = res.directories || [];
      if (!directories.length) {
        dirSelect.innerHTML = '<option value="">READ/WRITE 권한이 있는 디렉토리가 없습니다</option>';
        dirPath.value = '';
        return;
      }
      dirSelect.innerHTML = directories.map((d) => `<option value="${escapeHtml(d.name)}">${escapeHtml(d.name)}</option>`).join('');
      syncDirPath();
    }

    await loadDirectories();

    if (!directories.length) {
      alert('백업 가능한 디렉토리(READ/WRITE 권한이 있는 Directory Object)가 없습니다. DB 계정의 디렉토리 권한을 확인한 뒤 다시 시도하세요.');
      loadedTabs.delete('manual');
      showTab(previousActiveTab);
      return;
    }

    hideManualOutputs();

    // runs.length > 1 only happens for TABLE scope with several tables
    // checked -- the backend starts one DBMS_DATAPUMP job per table (see
    // backend/jobs.py's _manual_run_targets), so each needs its own label
    // in the combined script/result display to tell them apart.
    function renderScriptText(runs) {
      if (runs.length === 1) return runs[0].scriptText || '';
      return runs.map((r) => `-- ${r.label} --\n${r.scriptText || '(시작 실패 -- 스크립트 없음)'}`).join('\n\n');
    }

    function renderResults(runs) {
      return runs.map((r) => {
        const header = runs.length > 1
          ? `${statusChip(r.status)}<span><strong>${escapeHtml(r.label)}</strong> — ${escapeHtml(r.message || '')}</span>`
          : `${statusChip(r.status)}<span>${escapeHtml(r.message || '')}</span>`;
        return `
          <div class="alert-row" style="margin-bottom:10px;">${header}</div>
          ${r.dumpFile ? `<div class="field-hint" style="margin:-4px 0 14px 2px;">덤프 파일: ${escapeHtml(r.dumpFile)} (${fmtBytes(r.dumpSizeBytes)}) · 소요시간 ${fmtDuration(r.durationSeconds)}</div>` : ''}
        `;
      }).join('');
    }

    document.getElementById('mb_runBtn').onclick = async () => {
      const msgEl = document.getElementById('mb_msg');
      const directory = dirSelect.value;
      if (!directory) {
        msgEl.className = 'form-msg show error';
        msgEl.textContent = '백업 디렉토리를 선택하세요.';
        return;
      }
      let scopeValue;
      if (scopeSelect.value === 'TABLE') {
        const schema = tableSchemaSelect.value;
        const tables = Array.from(tableGridBody.querySelectorAll('.mb-table-check:checked')).map((cb) => cb.value);
        if (!schema || !tables.length) {
          msgEl.className = 'form-msg show error';
          msgEl.textContent = '스키마와 백업할 테이블을 1개 이상 선택하세요.';
          return;
        }
        scopeValue = `${schema}:${tables.join(',')}`;
      } else {
        const schemas = Array.from(schemaMultiSelect.selectedOptions).map((o) => o.value).filter(Boolean);
        if (!schemas.length) {
          msgEl.className = 'form-msg show error';
          msgEl.textContent = '백업할 스키마를 1개 이상 선택하세요.';
          return;
        }
        scopeValue = schemas.join(',');
      }

      hideManualOutputs();

      const btn = document.getElementById('mb_runBtn');
      btn.disabled = true;
      btn.textContent = '시작 중...';
      msgEl.className = 'form-msg';
      msgEl.textContent = '';

      const payload = { scope: scopeSelect.value, scope_value: scopeValue, directory };
      const res = await api(`/api/manual/${dbId}/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const runs = res.runs || [];

      if (!runs.length) {
        btn.disabled = false;
        btn.textContent = '지금 백업';
        resultCard.style.display = '';
        resultBody.innerHTML = renderResults([{ status: 'FAILED', message: res.message || '백업 시작에 실패했습니다.' }]);
        return;
      }

      const scriptText = renderScriptText(runs);
      if (scriptText) {
        scriptCard.style.display = '';
        scriptBody.textContent = scriptText;
      }

      // A run whose job never even started (e.g. ORA-39001 on a bad table
      // name) is already terminal -- only the ones that started need polling.
      const total = runs.length;
      if (!runs.some((r) => r.status === 'RUNNING')) {
        btn.disabled = false;
        btn.textContent = '지금 백업';
        resultCard.style.display = '';
        resultBody.innerHTML = renderResults(runs);
        uncheckAllTables();
        loadedTabs.delete('main');
        loadedTabs.delete('history');
        return;
      }

      btn.textContent = '백업 진행 중...';
      progressLine.style.display = '';

      function renderProgressLine() {
        if (total === 1) {
          const r = runs[0];
          const extra = r.jobState
            ? ` (${escapeHtml(r.jobState)}${r.percentDone != null ? ', ' + r.percentDone + '%' : ''})`
            : '';
          progressLine.innerHTML = `${statusChip('RUNNING')}<span>백업이 진행 중입니다${extra}...</span>`;
        } else {
          const doneCount = runs.filter((r) => r.status !== 'RUNNING').length;
          progressLine.innerHTML = `${statusChip('RUNNING')}<span>${total}개 중 ${doneCount}개 완료, 진행 중...</span>`;
        }
      }
      renderProgressLine();

      manualPollTimer = setInterval(async () => {
        const pending = runs.filter((r) => r.status === 'RUNNING');
        await Promise.all(pending.map(async (r) => {
          const prog = await api(`/api/manual/runs/${r.runId}/progress`);
          if (prog.success) Object.assign(r, prog);
        }));

        if (runs.some((r) => r.status === 'RUNNING')) {
          renderProgressLine();
          return;
        }

        clearInterval(manualPollTimer);
        manualPollTimer = null;
        progressLine.style.display = 'none';
        btn.disabled = false;
        btn.textContent = '지금 백업';
        resultCard.style.display = '';
        resultBody.innerHTML = renderResults(runs);
        uncheckAllTables();
        loadedTabs.delete('main');
        loadedTabs.delete('history');
      }, 1500);
    };
  }

  // ---- 백업 정책 ----
  const SCOPE_HINT = {
    FULL: '전체 DB를 백업합니다. 범위 값은 비워 둡니다.',
    SCHEMA: '콤마로 구분한 스키마 목록. 예: MES,MES_HIST',
    TABLE: "'스키마:테이블1,테이블2' 형식. 예: MES:EQP_LOG,EQP_STATUS (하나의 스키마만 지원)",
  };

  async function loadPolicies() {
    const [policiesRes, dbsRes] = await Promise.all([api('/api/policies'), api('/api/dbs')]);
    const policies = (policiesRes.success && policiesRes.policies) || [];
    const dbs = (dbsRes.success && dbsRes.dbs) || [];
    const filtered = currentDbId ? policies.filter((p) => p.dbId === currentDbId) : policies;

    document.getElementById('policyListCount').textContent = `정책 목록 (${filtered.length})`;
    const listEl = document.getElementById('policyList');
    if (!filtered.length) {
      listEl.innerHTML = '<div class="empty-msg">등록된 정책이 없습니다.</div>';
    } else {
      const groups = {};
      filtered.forEach((p) => { (groups[p.dbName] = groups[p.dbName] || []).push(p); });
      listEl.innerHTML = Object.entries(groups).map(([dbName, items]) => `
        <div class="policy-group-label">${escapeHtml(dbName)}</div>
        ${items.map((p) => `
          <div class="policy-item" data-id="${p.id}">
            <span class="pname">${escapeHtml(p.name)}</span>
            <span class="pmeta">${p.scope} · ${escapeHtml(scheduleSummary(p))} ${p.enabled ? (p.lastRunStatus ? statusChip(p.lastRunStatus === 'SUCCESS' ? 'SUCCESS' : p.lastRunStatus) : '') : statusChip('off')}</span>
          </div>`).join('')}
      `).join('');
      listEl.querySelectorAll('.policy-item').forEach((el) => {
        el.addEventListener('click', () => renderPolicyDetail(filtered.find((p) => p.id === el.dataset.id), dbs));
      });
    }

    document.getElementById('newPolicyBtn').onclick = () => renderPolicyForm(null, dbs);
  }

  function scheduleSummary(p) {
    if (p.scheduleKind === 'INTERVAL_HOURS') return `${p.intervalHours || '?'}시간마다`;
    if (p.scheduleKind === 'WEEKLY') {
      const days = ['월', '화', '수', '목', '금', '토', '일'];
      return `매주 ${days[p.scheduleWeekday || 0]} ${p.scheduleTime || ''}`;
    }
    return `매일 ${p.scheduleTime || ''}`;
  }

  function renderPolicyDetail(p, dbs) {
    document.querySelectorAll('.policy-item').forEach((el) => el.classList.toggle('active', el.dataset.id === p.id));
    const viewer = document.getElementById('policyViewer');
    viewer.innerHTML = `
      <div class="policy-viewer-title">
        <span>${escapeHtml(p.name)}</span>
        <div class="viewer-actions">
          <button type="button" class="sess-filter-reset" id="runNowBtn">${p.enabled ? '지금 실행' : '정책이 비활성 상태입니다'}</button>
          <button type="button" class="sess-filter-reset" id="deleteBtn">삭제</button>
        </div>
      </div>
      <div class="policy-viewer-body" id="policyFormBody"></div>`;
    buildPolicyForm(document.getElementById('policyFormBody'), p, dbs);
    document.getElementById('runNowBtn').addEventListener('click', async () => {
      const btn = document.getElementById('runNowBtn');
      btn.disabled = true;
      btn.textContent = '실행 중...';
      const res = await api(`/api/policies/${p.id}/run`, { method: 'POST' });
      showBanner(res.success ? '' : `백업 실행 실패: ${res.message || ''}`);
      btn.disabled = false;
      btn.textContent = '지금 실행';
      loadedTabs.delete('policies');
      loadedTabs.delete('main');
      loadPolicies();
    });
    document.getElementById('deleteBtn').addEventListener('click', async () => {
      if (!confirm(`"${p.name}" 정책을 삭제할까요?`)) return;
      await api(`/api/policies/${p.id}`, { method: 'DELETE' });
      loadedTabs.delete('policies');
      loadPolicies();
    });
  }

  function renderPolicyForm(existing, dbs) {
    document.querySelectorAll('.policy-item').forEach((el) => el.classList.remove('active'));
    const viewer = document.getElementById('policyViewer');
    viewer.innerHTML = `
      <div class="policy-viewer-title"><span>새 백업 정책</span></div>
      <div class="policy-viewer-body" id="policyFormBody"></div>`;
    buildPolicyForm(document.getElementById('policyFormBody'), null, dbs);
  }

  function buildPolicyForm(container, p, dbs) {
    const v = p || {
      name: '', dbId: dbs[0] ? dbs[0].id : '', scope: 'FULL', scopeValue: '',
      directoryObject: 'DATA_PUMP_DIR', dumpFilePattern: '%POLICY%_%DATE%.dmp',
      compression: 'METADATA_ONLY', parallelDegree: 1, content: 'ALL',
      scheduleKind: 'DAILY', scheduleTime: '03:00', scheduleWeekday: 0, intervalHours: 24,
      retentionDays: 14, rpoTier: 'TIER2', notifyEmail: '', enabled: true,
    };
    container.innerHTML = `
      <div class="toggle-row">
        <div><div class="t-label">정책 활성화</div><div class="t-sub">비활성화 시 스케줄러가 이 정책을 실행하지 않습니다.</div></div>
        <input type="checkbox" id="f_enabled" ${v.enabled ? 'checked' : ''} style="width:18px;height:18px;">
      </div>

      <div class="form-section-label">기본</div>
      <div class="field"><label>정책 이름</label><input id="f_name" value="${escapeHtml(v.name)}" placeholder="MES_PROD_FULL_DAILY"></div>
      <div class="row-split">
        <div class="field"><label>대상 DB</label>
          <select id="f_dbId">${dbs.map((d) => `<option value="${d.id}" ${d.id === v.dbId ? 'selected' : ''}>${escapeHtml(d.name)}</option>`).join('')}</select>
        </div>
        <div class="field"><label>백업 범위</label>
          <select id="f_scope">
            <option value="FULL" ${v.scope === 'FULL' ? 'selected' : ''}>전체 DB (Full)</option>
            <option value="SCHEMA" ${v.scope === 'SCHEMA' ? 'selected' : ''}>스키마 단위 (Schema)</option>
            <option value="TABLE" ${v.scope === 'TABLE' ? 'selected' : ''}>테이블 단위 (Table)</option>
          </select>
        </div>
      </div>
      <div class="field"><label>범위 값</label><input id="f_scopeValue" value="${escapeHtml(v.scopeValue || '')}">
        <div class="field-hint" id="f_scopeHint"></div>
      </div>

      <div class="form-section-label">Data Pump 옵션</div>
      <div class="row-split">
        <div class="field"><label>Directory Object</label><input id="f_directoryObject" value="${escapeHtml(v.directoryObject)}"></div>
        <div class="field"><label>파일명 패턴</label><input id="f_dumpFilePattern" value="${escapeHtml(v.dumpFilePattern)}">
          <div class="field-hint">%POLICY%, %DATE% 를 실제 값으로 치환합니다.</div>
        </div>
      </div>
      <div class="row-split">
        <div class="field"><label>압축 (COMPRESSION)</label>
          <select id="f_compression">${['NONE', 'METADATA_ONLY', 'DATA_ONLY', 'ALL'].map((c) => `<option value="${c}" ${c === v.compression ? 'selected' : ''}>${c}</option>`).join('')}</select>
        </div>
        <div class="field"><label>병렬도 (PARALLEL)</label><input id="f_parallelDegree" type="number" min="1" value="${v.parallelDegree}"></div>
        <div class="field"><label>CONTENT</label>
          <select id="f_content">${['ALL', 'DATA_ONLY', 'METADATA_ONLY'].map((c) => `<option value="${c}" ${c === v.content ? 'selected' : ''}>${c}</option>`).join('')}</select>
        </div>
      </div>

      <div class="form-section-label">스케줄 &amp; 보관</div>
      <div class="row-split">
        <div class="field"><label>실행 주기</label>
          <select id="f_scheduleKind">
            <option value="DAILY" ${v.scheduleKind === 'DAILY' ? 'selected' : ''}>매일</option>
            <option value="WEEKLY" ${v.scheduleKind === 'WEEKLY' ? 'selected' : ''}>매주</option>
            <option value="INTERVAL_HOURS" ${v.scheduleKind === 'INTERVAL_HOURS' ? 'selected' : ''}>N시간마다</option>
          </select>
        </div>
        <div class="field" id="f_scheduleTimeWrap"><label>실행 시각</label><input id="f_scheduleTime" value="${escapeHtml(v.scheduleTime || '03:00')}" placeholder="03:00"></div>
        <div class="field" id="f_scheduleWeekdayWrap" style="display:none;"><label>요일</label>
          <select id="f_scheduleWeekday">${['월', '화', '수', '목', '금', '토', '일'].map((d, i) => `<option value="${i}" ${i === (v.scheduleWeekday || 0) ? 'selected' : ''}>${d}</option>`).join('')}</select>
        </div>
        <div class="field" id="f_intervalHoursWrap" style="display:none;"><label>주기 (시간)</label><input id="f_intervalHours" type="number" min="1" value="${v.intervalHours || 24}"></div>
      </div>
      <div class="row-split">
        <div class="field"><label>보관 기간 (일)</label><input id="f_retentionDays" type="number" min="1" value="${v.retentionDays}"></div>
        <div class="field"><label>RPO / RTO 등급</label>
          <select id="f_rpoTier">
            <option value="TIER1" ${v.rpoTier === 'TIER1' ? 'selected' : ''}>Tier1 (≤1h / ≤4h)</option>
            <option value="TIER2" ${v.rpoTier === 'TIER2' ? 'selected' : ''}>Tier2 (≤24h / ≤24h)</option>
          </select>
        </div>
      </div>
      <div class="field"><label>실패 시 알림 이메일 (선택)</label><input id="f_notifyEmail" value="${escapeHtml(v.notifyEmail || '')}"></div>

      <button type="button" class="primary" id="savePolicyBtn" style="margin-top:6px;">${p ? '저장' : '정책 만들기'}</button>
      <div class="form-msg" id="policyFormMsg"></div>
    `;

    function syncScopeHint() { document.getElementById('f_scopeHint').textContent = SCOPE_HINT[document.getElementById('f_scope').value]; }
    document.getElementById('f_scope').addEventListener('change', syncScopeHint);
    syncScopeHint();

    function syncScheduleFields() {
      const kind = document.getElementById('f_scheduleKind').value;
      document.getElementById('f_scheduleTimeWrap').style.display = kind === 'INTERVAL_HOURS' ? 'none' : '';
      document.getElementById('f_scheduleWeekdayWrap').style.display = kind === 'WEEKLY' ? '' : 'none';
      document.getElementById('f_intervalHoursWrap').style.display = kind === 'INTERVAL_HOURS' ? '' : 'none';
    }
    document.getElementById('f_scheduleKind').addEventListener('change', syncScheduleFields);
    syncScheduleFields();

    document.getElementById('savePolicyBtn').addEventListener('click', async () => {
      const payload = {
        name: document.getElementById('f_name').value.trim(),
        db_id: document.getElementById('f_dbId').value,
        scope: document.getElementById('f_scope').value,
        scope_value: document.getElementById('f_scopeValue').value.trim() || null,
        directory_object: document.getElementById('f_directoryObject').value.trim(),
        dump_file_pattern: document.getElementById('f_dumpFilePattern').value.trim(),
        compression: document.getElementById('f_compression').value,
        parallel_degree: parseInt(document.getElementById('f_parallelDegree').value, 10) || 1,
        content: document.getElementById('f_content').value,
        schedule_kind: document.getElementById('f_scheduleKind').value,
        schedule_time: document.getElementById('f_scheduleTime').value.trim() || '03:00',
        schedule_weekday: parseInt(document.getElementById('f_scheduleWeekday').value, 10) || 0,
        interval_hours: parseInt(document.getElementById('f_intervalHours').value, 10) || 24,
        retention_days: parseInt(document.getElementById('f_retentionDays').value, 10) || 14,
        rpo_tier: document.getElementById('f_rpoTier').value,
        notify_email: document.getElementById('f_notifyEmail').value.trim() || null,
        enabled: document.getElementById('f_enabled').checked,
      };
      const msgEl = document.getElementById('policyFormMsg');
      if (!payload.name || !payload.db_id) {
        msgEl.className = 'form-msg show error';
        msgEl.textContent = '정책 이름과 대상 DB는 필수입니다.';
        return;
      }
      const res = p
        ? await api(`/api/policies/${p.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        : await api('/api/policies', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (res.success) {
        msgEl.className = 'form-msg show success';
        msgEl.textContent = '저장했습니다.';
        loadedTabs.delete('policies');
        loadPolicies();
      } else {
        msgEl.className = 'form-msg show error';
        msgEl.textContent = res.message || '저장에 실패했습니다.';
      }
    });
  }

  // ---- 실행 이력 ----
  async function loadHistory() {
    const status = document.getElementById('historyStatusFilter').value;
    const qs = new URLSearchParams();
    if (currentDbId) qs.set('db_id', currentDbId);
    if (status) qs.set('status', status);
    const data = await api('/api/history?' + qs.toString());
    const runs = (data.success && data.runs) || [];
    const tbody = document.querySelector('#historyTable tbody');
    if (!runs.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-msg">실행 이력이 없습니다.</td></tr>';
    } else {
      tbody.innerHTML = runs.map((r) => `
        <tr class="clickable" data-id="${r.id}">
          <td>${r.startedAt || '-'}</td><td>${escapeHtml(r.policyName)}</td><td>${escapeHtml(r.dbName)}</td>
          <td>${r.runType}</td><td>${r.trigger === 'SCHEDULED' ? '자동' : '수동'}</td><td>${statusChip(r.status)}</td>
          <td>${fmtDuration(r.durationSeconds)}</td><td>${escapeHtml(r.dumpFile || '-')}</td><td>${fmtBytes(r.dumpSizeBytes)}</td>
        </tr>`).join('');
      tbody.querySelectorAll('tr[data-id]').forEach((tr) => {
        tr.addEventListener('click', async () => {
          tbody.querySelectorAll('tr').forEach((t) => t.classList.remove('selected'));
          tr.classList.add('selected');
          const detail = await api(`/api/history/${tr.dataset.id}`);
          if (!detail.success) return;
          const run = detail.run;
          document.getElementById('logCard').style.display = '';
          document.getElementById('logTitle').textContent = `로그 — ${run.policyName} · ${run.startedAt}`;
          document.getElementById('logBody').textContent = (run.errorText ? run.errorText + '\n\n' : '') + (run.logText || '(로그가 비어 있습니다)');
        });
      });
    }
  }
  document.getElementById('historyStatusFilter').addEventListener('change', () => { loadedTabs.delete('history'); loadHistory(); });
  document.getElementById('historyRefreshBtn').addEventListener('click', () => { loadedTabs.delete('history'); loadHistory(); });

  // ---- 복구 검증 ----
  async function loadRecovery() {
    const data = await api('/api/recovery');
    const checks = (data.success && data.checks) || [];
    const tbody = document.querySelector('#recoveryTable tbody');
    if (!checks.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-msg">등록된 DB가 없습니다.</td></tr>';
      return;
    }
    tbody.innerHTML = checks.map((c) => `
      <tr>
        <td>${escapeHtml(c.dbName)}</td><td>${c.lastCheckedAt || '-'}</td><td>${statusChip(c.result)}</td>
        <td>${c.measuredRtoSeconds ? fmtDuration(c.measuredRtoSeconds) : '-'}</td>
        <td><button type="button" class="sess-filter-reset run-recovery-btn" data-db="${c.dbId}" style="padding:6px 12px; font-size:12px;">지금 검증</button></td>
      </tr>`).join('');
    tbody.querySelectorAll('.run-recovery-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const res = await api(`/api/recovery/${btn.dataset.db}/run`, { method: 'POST' });
        showBanner(res.message || '');
        loadedTabs.delete('recovery');
        loadRecovery();
      });
    });
  }

  (async function loadAppVersion() {
    const data = await api('/api/version');
    if (data.success && data.version) document.getElementById('appVersion').textContent = `v${data.version}`;
  })();

  loadDbSelect().then(loadActiveTab);
})();
