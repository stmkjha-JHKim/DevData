// public/js/connect.js -- DB registration screen (public/index.html).
(function () {
  const resultBox = document.getElementById('result');
  const submitBtn = document.getElementById('submitBtn');
  const submitBtnLabel = document.getElementById('submitBtnLabel');
  const connectTypeSelect = document.getElementById('connectType');
  const sidLabel = document.getElementById('sidLabel');
  const sidInput = document.getElementById('sid');
  const registeredStrip = document.getElementById('registeredStrip');

  const CONNECT_TYPE_META = {
    sid: { label: 'SID / Instance', placeholder: 'ORCL', charClass: /[^a-zA-Z0-9_$#]/g },
    service_name: { label: 'Service Name', placeholder: 'orclpdb1.example.com', charClass: /[^a-zA-Z0-9_$#.\-]/g },
  };

  function currentMeta() {
    return CONNECT_TYPE_META[connectTypeSelect.value] || CONNECT_TYPE_META.sid;
  }

  function applyConnectTypeUi() {
    const meta = currentMeta();
    sidLabel.textContent = meta.label;
    sidInput.placeholder = meta.placeholder;
  }
  connectTypeSelect.addEventListener('change', applyConnectTypeUi);
  applyConnectTypeUi();

  sidInput.addEventListener('input', () => {
    const cleaned = sidInput.value.replace(currentMeta().charClass, '');
    if (cleaned !== sidInput.value) sidInput.value = cleaned;
  });

  const fields = ['dbName', 'ip', 'port', 'sid', 'account', 'password'];

  function clearErrors() {
    fields.forEach((key) => {
      const el = document.getElementById(key);
      const err = document.getElementById('err-' + key);
      el.classList.remove('invalid');
      if (err) err.textContent = '';
    });
  }

  function validate() {
    clearErrors();
    let ok = true;
    const checks = {
      dbName: (v) => (!v.trim() ? 'DB 별칭을 입력하세요.' : ''),
      ip: (v) => (!v.trim() ? 'IP 주소를 입력하세요.' : ''),
      port: (v) => (!/^\d+$/.test(v) ? '포트는 숫자만 입력하세요.' : ''),
      sid: (v) => (!v.trim() ? '값을 입력하세요.' : ''),
      account: (v) => (!v.trim() ? '계정을 입력하세요.' : ''),
      password: (v) => (!v ? '비밀번호를 입력하세요.' : ''),
    };
    fields.forEach((key) => {
      const el = document.getElementById(key);
      const msg = checks[key](el.value);
      if (msg) {
        ok = false;
        el.classList.add('invalid');
        const err = document.getElementById('err-' + key);
        if (err) err.textContent = msg;
      }
    });
    return ok;
  }

  function showResult(state, title, message) {
    resultBox.className = 'result show ' + state;
    resultBox.innerHTML = `<strong>${title}</strong>${message}`;
  }

  async function loadRegisteredDbs() {
    try {
      const res = await fetch('/api/dbs');
      const data = await res.json();
      const dbs = (data.success && data.dbs) || [];
      registeredStrip.innerHTML = dbs
        .map((d) => `<span class="registered-chip" data-id="${d.id}"><span class="dot"></span>${escapeHtml(d.name)}</span>`)
        .join('');
      registeredStrip.querySelectorAll('.registered-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
          window.location.href = '/dashboard.html?db=' + encodeURIComponent(chip.dataset.id);
        });
      });
    } catch (err) {
      // Non-critical -- an empty strip just means "no registered DBs yet".
    }
  }

  function escapeHtml(v) {
    return String(v).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  async function submit() {
    if (!validate()) {
      showResult('error', '✕ 입력 오류', '입력값을 확인하세요.');
      return;
    }
    const payload = {
      name: document.getElementById('dbName').value.trim(),
      ip: document.getElementById('ip').value.trim(),
      port: document.getElementById('port').value.trim(),
      connectType: connectTypeSelect.value,
      sid: sidInput.value.trim(),
      account: document.getElementById('account').value.trim(),
      password: document.getElementById('password').value,
    };
    submitBtn.disabled = true;
    submitBtnLabel.textContent = '연결 확인 중...';
    showResult('pending', '⏳ 연결 확인 중...', 'DB 서버에 연결해 접속 정보를 확인하고 있습니다.');
    try {
      const res = await fetch('/api/dbs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.success) {
        showResult('success', '✓ 등록 완료', `${escapeHtml(payload.name)} 등록을 완료했습니다. 잠시 후 대시보드로 이동합니다...`);
        submitBtnLabel.textContent = '이동 중...';
        setTimeout(() => {
          window.location.href = '/dashboard.html?db=' + encodeURIComponent(data.db.id);
        }, 700);
        return;
      }
      showResult('error', '✕ 등록 실패', escapeHtml(data.message || '알 수 없는 오류입니다.'));
    } catch (err) {
      showResult('error', '✕ 요청 실패', `서버에 연결할 수 없습니다: ${escapeHtml(err.message)}`);
    } finally {
      submitBtn.disabled = false;
      submitBtnLabel.textContent = 'DB 등록하고 백업 관리 시작';
    }
  }

  submitBtn.addEventListener('click', submit);
  document.getElementById('dbForm').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !submitBtn.disabled) {
      e.preventDefault();
      submit();
    }
  });

  (async function loadAppVersion() {
    try {
      const res = await fetch('/api/version');
      const data = await res.json();
      if (data.success && data.version) {
        document.getElementById('appVersion').textContent = `v${data.version}`;
      }
    } catch (err) {
      /* non-critical */
    }
  })();

  loadRegisteredDbs();
})();
