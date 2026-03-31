/* Pokerthon API Playground — Main JS */
'use strict';

// ---------------------------------------------------------------------------
// Shared State
// ---------------------------------------------------------------------------
const state = {
  creds: { apiKey: '', secretKey: '' },
  lastState: null,        // last private state response
  lastHandId: null,
  currentEndpoint: null,
  history: [],            // [{method, path, status, ts, response}]
};

// ---------------------------------------------------------------------------
// Credentials (shared by Explorer + Quickstart)
// ---------------------------------------------------------------------------
function loadCreds() {
  try {
    const c = JSON.parse(localStorage.getItem('pg_creds') || '{}');
    state.creds.apiKey    = c.apiKey || '';
    state.creds.secretKey = c.secretKey || '';
  } catch (_) {}
}

function saveCreds() {
  state.creds.apiKey    = document.getElementById('cred-api-key')?.value.trim()    || state.creds.apiKey;
  state.creds.secretKey = document.getElementById('cred-secret-key')?.value.trim() || state.creds.secretKey;
  localStorage.setItem('pg_creds', JSON.stringify(state.creds));
}

function qsSaveCreds() {
  state.creds.apiKey    = document.getElementById('qs-api-key')?.value.trim()    || state.creds.apiKey;
  state.creds.secretKey = document.getElementById('qs-secret-key')?.value.trim() || state.creds.secretKey;
  localStorage.setItem('pg_creds', JSON.stringify(state.creds));
}

// ---------------------------------------------------------------------------
// Proxy call helper
// ---------------------------------------------------------------------------
async function proxyCall(method, path, queryParams = {}, body = null) {
  const payload = {
    api_key:      state.creds.apiKey,
    secret_key:   state.creds.secretKey,
    method,
    path,
    query_params: queryParams,
  };
  if (body !== null) payload.body = typeof body === 'string' ? body : JSON.stringify(body);

  const start = Date.now();
  const resp = await fetch('/playground/api/proxy', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  });
  const data = await resp.json();
  const elapsed = Date.now() - start;
  return { ...data, elapsed };
}

async function publicCall(method, path, queryParams = {}, body = null) {
  const url = new URL(path, window.location.origin);
  Object.entries(queryParams).forEach(([k, v]) => url.searchParams.set(k, v));

  const opts = { method };
  if (body !== null) {
    opts.body    = typeof body === 'string' ? body : JSON.stringify(body);
    opts.headers = { 'Content-Type': 'application/json' };
  }
  const start = Date.now();
  const resp  = await fetch(url.toString(), opts);
  let rb;
  try { rb = await resp.json(); } catch (_) { rb = await resp.text(); }
  return { status_code: resp.status, response_body: rb, elapsed: Date.now() - start };
}

// ---------------------------------------------------------------------------
// Endpoint catalog
// ---------------------------------------------------------------------------
const ENDPOINTS = {
  'me': {
    method: 'GET', path: '/v1/private/me',
    desc:   '내 계정 정보 조회 (wallet_balance, current_table_no 등)',
    priv:   true,
    pathParams: [], queryParams: [], hasBody: false,
  },
  'public-tables': {
    method: 'GET', path: '/v1/public/tables',
    desc:   '전체 테이블 목록 (public)',
    priv:   false,
    pathParams: [], queryParams: [], hasBody: false,
  },
  'public-table': {
    method: 'GET', path: '/v1/public/tables/{table_no}',
    desc:   '특정 테이블 공개 상태 (좌석별 stack, nickname 등)',
    priv:   false,
    pathParams: ['table_no'], queryParams: [], hasBody: false,
  },
  'public-state': {
    method: 'GET', path: '/v1/public/tables/{table_no}/state',
    desc:   '테이블 공개 게임 상태 (홀카드 제외)',
    priv:   false,
    pathParams: ['table_no'], queryParams: [
      { name: 'wait',    placeholder: 'false', hint: 'true = Long-Poll' },
      { name: 'version', placeholder: '',      hint: 'Long-Poll 기준 버전' },
    ], hasBody: false,
  },
  'sit': {
    method: 'POST', path: '/v1/private/tables/{table_no}/sit',
    desc:   '테이블 착석 (40칩 차감)',
    priv:   true,
    pathParams: ['table_no'], queryParams: [], hasBody: true,
    bodyPresets: { default: '{"seat_no": 1}' },
  },
  'stand': {
    method: 'POST', path: '/v1/private/tables/{table_no}/stand',
    desc:   '이석 요청 (핸드 중이면 핸드 종료 후 처리)',
    priv:   true,
    pathParams: ['table_no'], queryParams: [], hasBody: false,
  },
  'private-state': {
    method: 'GET', path: '/v1/private/tables/{table_no}/state',
    desc:   '내 홀카드 + legal_actions 포함 게임 상태',
    priv:   true,
    pathParams: ['table_no'], queryParams: [
      { name: 'wait',    placeholder: 'false', hint: 'true = Long-Poll' },
      { name: 'version', placeholder: '',      hint: 'Long-Poll 기준 버전' },
    ], hasBody: false,
  },
  'action': {
    method: 'POST', path: '/v1/private/tables/{table_no}/action',
    desc:   '액션 제출 (FOLD / CALL / CHECK / RAISE_TO / ALL_IN)',
    priv:   true,
    pathParams: ['table_no'], queryParams: [], hasBody: true,
    bodyPresets: {
      FOLD:     '{"hand_id": 0, "action": {"type": "FOLD"}, "idempotency_key": "auto"}',
      CALL:     '{"hand_id": 0, "action": {"type": "CALL"}, "idempotency_key": "auto"}',
      CHECK:    '{"hand_id": 0, "action": {"type": "CHECK"}, "idempotency_key": "auto"}',
      RAISE_TO: '{"hand_id": 0, "action": {"type": "RAISE_TO", "amount": 10}, "idempotency_key": "auto"}',
      ALL_IN:   '{"hand_id": 0, "action": {"type": "ALL_IN"}, "idempotency_key": "auto"}',
    },
  },
  'hands': {
    method: 'GET', path: '/v1/public/tables/{table_no}/hands',
    desc:   '핸드 목록 (페이지네이션)',
    priv:   false,
    pathParams: ['table_no'], queryParams: [
      { name: 'limit',  placeholder: '20', hint: '최대 100' },
      { name: 'cursor', placeholder: '',   hint: '이전 페이지 next_cursor 값' },
    ], hasBody: false,
  },
  'hand-detail': {
    method: 'GET', path: '/v1/public/tables/{table_no}/hands/{hand_id}',
    desc:   '핸드 상세 (쇼다운 결과, 플레이어별 스택 변화)',
    priv:   false,
    pathParams: ['table_no', 'hand_id'], queryParams: [], hasBody: false,
  },
  'hand-actions': {
    method: 'GET', path: '/v1/public/tables/{table_no}/hands/{hand_id}/actions',
    desc:   '핸드 액션 로그 전체',
    priv:   false,
    pathParams: ['table_no', 'hand_id'], queryParams: [], hasBody: false,
  },
  'my-hands': {
    method: 'GET', path: '/v1/private/me/hands',
    desc:   '내가 참가한 핸드 목록',
    priv:   true,
    pathParams: [], queryParams: [
      { name: 'limit',  placeholder: '20', hint: '최대 100' },
      { name: 'cursor', placeholder: '',   hint: 'next_cursor 값' },
    ], hasBody: false,
  },
  'leaderboard': {
    method: 'GET', path: '/v1/public/leaderboard',
    desc:   '플레이어 리더보드',
    priv:   false,
    pathParams: [], queryParams: [
      { name: 'sort_by', placeholder: 'chips', hint: 'chips | profit | win_rate | hands_played' },
      { name: 'limit',   placeholder: '50',    hint: '최대 200' },
    ], hasBody: false,
  },
};

// ---------------------------------------------------------------------------
// Explorer
// ---------------------------------------------------------------------------
function initExplorer() {
  loadCreds();
  const ak = document.getElementById('cred-api-key');
  const sk = document.getElementById('cred-secret-key');
  if (ak) ak.value = state.creds.apiKey;
  if (sk) sk.value = state.creds.secretKey;

  loadExplorerHistory();
  selectEndpoint('public-tables');
}

function selectEndpoint(key) {
  state.currentEndpoint = key;
  const ep = ENDPOINTS[key];
  if (!ep) return;

  // Sidebar highlight
  document.querySelectorAll('.sidebar-item').forEach(el => {
    el.classList.toggle('active', el.dataset.endpoint === key);
  });

  // Endpoint bar
  const methodBadge = document.getElementById('ep-method');
  methodBadge.textContent = ep.method;
  methodBadge.className   = `method-badge method-${ep.method.toLowerCase()}`;
  document.getElementById('ep-path').textContent = ep.path;
  document.getElementById('ep-desc').textContent  = ep.desc;

  // Params card
  const pathSection  = document.getElementById('path-params-section');
  const querySection = document.getElementById('query-params-section');
  const bodySection  = document.getElementById('body-section');

  // Path params
  if (ep.pathParams.length) {
    pathSection.innerHTML = `<h3>Path 파라미터</h3>` + ep.pathParams.map(p =>
      `<div class="form-group"><label>${p}</label><input type="text" id="pp-${p}" placeholder="${p}" class="path-param" data-param="${p}"></div>`
    ).join('');
  } else {
    pathSection.innerHTML = '';
  }

  // Query params
  if (ep.queryParams.length) {
    querySection.innerHTML = `<h3 class="mt-2">Query 파라미터</h3>` + ep.queryParams.map(q =>
      `<div class="form-group">
        <label>${q.name} <span class="text-xs text-muted">${q.hint || ''}</span></label>
        <input type="text" id="qp-ex-${q.name}" placeholder="${q.placeholder || ''}" class="query-param" data-param="${q.name}">
       </div>`
    ).join('');
  } else {
    querySection.innerHTML = '';
  }

  // Body
  if (ep.hasBody) {
    bodySection.classList.remove('hidden');
    const presets = ep.bodyPresets || {};
    const defaultBody = presets.default || Object.values(presets)[0] || '{}';

    // Update preset buttons
    const btnRow = bodySection.querySelector('.flex');
    btnRow.innerHTML = Object.keys(presets).map(k =>
      k === 'default' ? '' : `<button class="btn btn-secondary btn-sm" onclick="setPreset('${k}')">${k}</button>`
    ).join('');

    document.getElementById('req-body').value = defaultBody;
  } else {
    bodySection.classList.add('hidden');
  }

  // Warning for private with no creds
  const warn = document.getElementById('creds-warn');
  if (ep.priv && !state.creds.apiKey) {
    if (!warn) {
      const w = document.createElement('div');
      w.id = 'creds-warn';
      w.className = 'badge badge-warn mb-2';
      w.textContent = 'Private 엔드포인트입니다. 상단에 API Key와 Secret Key를 입력하세요.';
      document.getElementById('params-card').prepend(w);
    }
  } else if (warn) {
    warn.remove();
  }

  // Clear response
  document.getElementById('resp-panel').innerHTML =
    '<div class="resp-header"><span class="text-muted text-sm">응답이 여기에 표시됩니다</span></div>';
}

function setPreset(name) {
  const ep = ENDPOINTS[state.currentEndpoint];
  if (!ep?.bodyPresets) return;
  const body = ep.bodyPresets[name] || ep.bodyPresets.default || '{}';
  document.getElementById('req-body').value = body;
}

function buildPath(template, pathParams) {
  let p = template;
  for (const [k, v] of Object.entries(pathParams)) {
    p = p.replace(`{${k}}`, encodeURIComponent(v));
  }
  return p;
}

async function sendRequest() {
  const ep = ENDPOINTS[state.currentEndpoint];
  if (!ep) return;

  // Gather path params
  const pathParams = {};
  ep.pathParams.forEach(p => {
    const el = document.getElementById(`pp-${p}`);
    pathParams[p] = el ? el.value.trim() : '';
  });

  // Gather query params
  const queryParams = {};
  ep.queryParams.forEach(q => {
    const el = document.getElementById(`qp-ex-${q.name}`);
    if (el && el.value.trim()) queryParams[q.name] = el.value.trim();
  });

  // Body
  let body = null;
  if (ep.hasBody) {
    let raw = document.getElementById('req-body').value.trim();
    if (raw) {
      // Replace hand_id: 0 with actual hand_id if available
      if (state.lastHandId && raw.includes('"hand_id": 0')) {
        raw = raw.replace('"hand_id": 0', `"hand_id": ${state.lastHandId}`);
      }
      // Replace idempotency_key: "auto" with uuid
      if (raw.includes('"auto"')) {
        raw = raw.replace('"auto"', `"${crypto.randomUUID()}"`);
      }
      body = raw;
    }
  }

  const path = buildPath(ep.path, pathParams);

  const btn = document.getElementById('btn-send');
  btn.disabled = true;
  btn.textContent = 'Sending...';

  const panel = document.getElementById('resp-panel');
  panel.innerHTML = '<div class="resp-header"><span class="text-muted text-sm">요청 중...</span></div>';

  try {
    let result;
    if (ep.priv) {
      if (!state.creds.apiKey || !state.creds.secretKey) {
        panel.innerHTML = renderError('API Key와 Secret Key를 입력하세요.');
        return;
      }
      result = await proxyCall(ep.method, path, queryParams, body);
    } else {
      result = await publicCall(ep.method, path, queryParams, body);
    }

    // Cache state
    if (result.response_body && typeof result.response_body === 'object') {
      if (result.response_body.hand) {
        state.lastHandId = result.response_body.hand?.hand_id || state.lastHandId;
        state.lastState  = result.response_body;
      }
    }

    renderResponse(panel, result, ep.priv);
    addToHistory(ep.method, path, result.status_code, result);
  } catch (err) {
    panel.innerHTML = renderError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Send Request';
  }
}

function renderResponse(panel, result, showDebug) {
  const sc = result.status_code;
  let cls = 'badge-info';
  if (sc >= 200 && sc < 300) cls = 'badge-success';
  else if (sc >= 400)        cls = 'badge-danger';

  const bodyStr = JSON.stringify(result.response_body, null, 2);

  let debugHtml = '';
  let authHintHtml = '';
  const detailMsg = (result.response_body && result.response_body.detail && result.response_body.detail.message)
    ? String(result.response_body.detail.message)
    : '';

  if (showDebug && sc === 401) {
    authHintHtml = `
      <div class="resp-debug mt-2">
        <div class="text-xs text-muted mb-1">401 인증 실패 점검</div>
        <div class="code-block" style="font-size:.75rem;white-space:pre-wrap">message: ${escHtml(detailMsg || '(없음)')}
1) X-TIMESTAMP가 현재 시각 기준 ±300초인지
2) X-NONCE를 재사용하지 않았는지
3) signing_key = SHA-256(secret_key)로 계산했는지
4) method/path/query/body hash가 canonical string과 완전히 일치하는지</div>
      </div>`;
  }

  if (showDebug && result.request_debug) {
    const d = result.request_debug;
    const authHeaders = Object.entries(result.headers || {}).map(([k,v]) =>
      `<tr><td>${k}</td><td>${v}</td></tr>`
    ).join('');
    debugHtml = `
      <div class="resp-debug">
        <details>
          <summary>인증 헤더 및 서명 디버그 펼치기</summary>
          <div class="mt-2">
            <div class="text-xs text-muted mb-1">전송된 헤더</div>
            <table class="headers-table">${authHeaders}</table>
            <div class="text-xs text-muted mt-2 mb-1">Canonical String</div>
            <div class="code-block" style="font-size:.75rem;white-space:pre">${escHtml(d.canonical_string || '')}</div>
            <div class="text-xs text-muted mt-2 mb-1">Signing Key (sha256 of secret)</div>
            <div class="code-block" style="font-size:.75rem">${escHtml(d.signing_key || '')}</div>
          </div>
        </details>
      </div>`;
  }

  panel.innerHTML = `
    <div class="resp-header">
      <span class="badge ${cls}">${sc}</span>
      <span class="text-muted text-sm">${result.error || ''}</span>
      <span class="resp-time">${result.elapsed || 0}ms</span>
    </div>
    <div class="resp-body">
      <pre class="code-block" style="max-height:400px;overflow:auto;cursor:pointer"
           onclick="copyToClip(this)">${syntaxHighlight(bodyStr)}</pre>
      <div class="text-xs text-muted mt-1">응답 JSON 클릭 시 클립보드 복사</div>
    </div>
    ${authHintHtml}
    ${debugHtml}`;
}

function renderError(msg) {
  return `<div class="resp-header"><span class="badge badge-danger">Error</span> <span class="text-sm">${escHtml(msg)}</span></div>`;
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------
function addToHistory(method, path, status, result) {
  state.history.unshift({ method, path, status, ts: new Date().toLocaleTimeString(), result });
  if (state.history.length > 20) state.history.pop();
  renderHistory();
  saveExplorerHistory();
}

function renderHistory() {
  const list = document.getElementById('history-list');
  const card = document.getElementById('history-card');
  if (!list) return;
  if (!state.history.length) { if (card) card.style.display = 'none'; return; }
  if (card) card.style.display = '';
  const cnt = document.getElementById('history-count');
  if (cnt) cnt.textContent = state.history.length;

  list.innerHTML = state.history.map((h, i) => {
    let cls = 'badge-info';
    if (h.status >= 200 && h.status < 300) cls = 'badge-success';
    else if (h.status >= 400)              cls = 'badge-danger';
    return `<div class="history-item" onclick="restoreHistory(${i})">
      <span class="badge ${cls}">${h.status || '?'}</span>
      <span class="method-badge method-${h.method.toLowerCase()}">${h.method}</span>
      <span class="history-path">${h.path}</span>
      <span class="text-xs text-muted">${h.ts}</span>
    </div>`;
  }).join('');
}

function restoreHistory(i) {
  const h = state.history[i];
  if (!h) return;
  const panel = document.getElementById('resp-panel');
  if (panel) renderResponse(panel, h.result, true);
}

function saveExplorerHistory() {
  try { localStorage.setItem('pg_history', JSON.stringify(state.history.slice(0, 20))); } catch (_) {}
}

function loadExplorerHistory() {
  try {
    const h = JSON.parse(localStorage.getItem('pg_history') || '[]');
    state.history = h;
    renderHistory();
  } catch (_) {}
}

// ---------------------------------------------------------------------------
// Quickstart
// ---------------------------------------------------------------------------
const QS_STEPS = [
  { n: 1, label: '인증 확인' },
  { n: 2, label: '테이블 확인' },
  { n: 3, label: '착석' },
  { n: 4, label: '상태 확인' },
  { n: 5, label: '액션 제출' },
  { n: 6, label: '이석' },
];

const qsState = {
  done:     new Set(),
  tableNo:  null,
};

function initQuickstart() {
  loadCreds();
  const ak = document.getElementById('qs-api-key');
  const sk = document.getElementById('qs-secret-key');
  if (ak) ak.value = state.creds.apiKey;
  if (sk) sk.value = state.creds.secretKey;
  renderQsStepper();
}

function renderQsStepper() {
  const el = document.getElementById('qs-stepper');
  if (!el) return;
  el.innerHTML = QS_STEPS.map(s => {
    const isDone = qsState.done.has(s.n);
    return `<div class="qs-step-item ${isDone ? 'done' : ''}" onclick="scrollToQsStep(${s.n})">
      <div class="dot">${isDone ? '✓' : s.n}</div>
      <div class="qs-step-label">${s.label}</div>
    </div>`;
  }).join('');
}

function scrollToQsStep(n) {
  document.getElementById(`qs-step-${n}`)?.scrollIntoView({ behavior: 'smooth' });
}

function qsMarkDone(n) {
  qsState.done.add(n);
  renderQsStepper();
  const num = document.getElementById(`qs-num-${n}`);
  if (num) { num.textContent = '✓'; num.classList.add('done'); }
}

function qsLog(msg, cls = 'info') {
  const c = document.getElementById('qs-console');
  if (!c) return;
  const ts = new Date().toLocaleTimeString();
  const entry = document.createElement('div');
  entry.className = `console-entry ${cls}`;
  entry.innerHTML = `<span class="ts">${ts}</span><span class="msg">${escHtml(msg)}</span>`;
  c.prepend(entry);
}

async function qsStep1() {
  try {
    const r = await proxyCall('GET', '/v1/private/me');
    const box = document.getElementById('qs-r1');
    box.classList.remove('hidden');
    if (r.status_code === 200) {
      const d = r.response_body;
      box.className = 'result-box success mt-3';
      box.innerHTML = `<div class="text-success mb-1">✓ 인증 성공</div>
        <div class="text-sm">닉네임: <strong>${escHtml(d.nickname || '')}</strong></div>
        <div class="text-sm">지갑: <strong>${d.wallet_balance ?? '?'} 칩</strong></div>
        <div class="text-sm">현재 테이블: <strong>${d.current_table_no ?? '없음'}</strong></div>`;
      qsMarkDone(1);
      qsLog('GET /v1/private/me → 200 OK', 'ok');
    } else {
      box.className = 'result-box error mt-3';
      box.innerHTML = `<div class="text-danger mb-1">✗ 인증 실패 (${r.status_code})</div>
        <pre class="code-block" style="font-size:.75rem">${escHtml(JSON.stringify(r.response_body, null, 2))}</pre>
        <details class="mt-2"><summary class="text-xs text-muted">서명 디버그</summary>
        <pre class="code-block" style="font-size:.75rem">${escHtml(JSON.stringify(r.request_debug, null, 2))}</pre></details>`;
      qsLog(`GET /v1/private/me → ${r.status_code}`, 'err');
    }
  } catch (e) { qsLog('오류: ' + e.message, 'err'); }
}

async function qsStep2() {
  try {
    const r = await publicCall('GET', '/v1/public/tables');
    const box = document.getElementById('qs-r2');
    box.classList.remove('hidden');
    if (r.status_code === 200) {
      const tables = r.response_body || [];
      box.className = 'result-box success mt-3';
      const sel = document.getElementById('qs-table-no');
      sel.innerHTML = '';
      tables.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.table_no;
        opt.textContent = `테이블 ${t.table_no} — ${t.status} (${t.seated_count}/${t.max_seats}명)`;
        sel.appendChild(opt);
      });
      box.innerHTML = `<div class="text-success mb-2">✓ 테이블 ${tables.length}개 조회됨</div>` +
        tables.map(t => `<div class="text-sm">테이블 ${t.table_no}: ${t.status} — ${t.seated_count}/${t.max_seats}석</div>`).join('');
      qsMarkDone(2);
      qsLog(`GET /v1/public/tables → ${tables.length}개`, 'ok');
    } else {
      box.className = 'result-box error mt-3';
      box.innerHTML = `<div class="text-danger">✗ 오류 (${r.status_code})</div>`;
      qsLog(`GET /v1/public/tables → ${r.status_code}`, 'err');
    }
  } catch (e) { qsLog('오류: ' + e.message, 'err'); }
}

async function qsStep3() {
  const tableNo = document.getElementById('qs-table-no').value;
  const seatNo  = document.getElementById('qs-seat-no').value;
  if (!tableNo) { alert('테이블을 선택하세요 (Step 2 먼저 실행)'); return; }

  const body = seatNo ? JSON.stringify({ seat_no: parseInt(seatNo) }) : '{}';
  const path = `/v1/private/tables/${tableNo}/sit`;
  try {
    const r = await proxyCall('POST', path, {}, body);
    const box = document.getElementById('qs-r3');
    box.classList.remove('hidden');
    if (r.status_code === 200) {
      qsState.tableNo = parseInt(tableNo);
      const d = r.response_body;
      box.className = 'result-box success mt-3';
      box.innerHTML = `<div class="text-success mb-1">✓ 착석 성공</div>
        <div class="text-sm">테이블: ${tableNo}, 좌석: ${d.seat_no ?? '?'}, 스택: ${d.stack ?? '?'}칩</div>`;
      qsMarkDone(3);
      qsLog(`POST ${path} → 200`, 'ok');
    } else {
      box.className = 'result-box error mt-3';
      box.innerHTML = `<div class="text-danger">✗ 착석 실패 (${r.status_code})</div>
        <pre class="code-block" style="font-size:.75rem">${escHtml(JSON.stringify(r.response_body, null, 2))}</pre>`;
      qsLog(`POST ${path} → ${r.status_code}`, 'err');
    }
  } catch (e) { qsLog('오류: ' + e.message, 'err'); }
}

async function qsStep4() {
  const tableNo = qsState.tableNo;
  if (!tableNo) { alert('먼저 테이블에 착석하세요 (Step 3)'); return; }
  const path = `/v1/private/tables/${tableNo}/state`;
  try {
    const r = await proxyCall('GET', path);
    const box = document.getElementById('qs-r4');
    box.classList.remove('hidden');
    if (r.status_code === 200) {
      const d = r.response_body;
      state.lastState  = d;
      state.lastHandId = d.hand?.hand_id ?? null;
      const board  = (d.board || []).join(' ') || '(없음)';
      const hole   = (d.hole_cards || []).join(' ') || '(없음/대기 중)';
      const legal  = d.legal_actions || [];
      box.className = 'result-box success mt-3';
      box.innerHTML = `<div class="text-success mb-2">✓ 상태 조회 성공</div>
        <div class="text-sm">Hand ID: ${d.hand?.hand_id ?? '없음'}</div>
        <div class="text-sm">Street: ${d.hand?.street ?? '없음'}</div>
        <div class="text-sm">보드: ${board}</div>
        <div class="text-sm">홀카드: <strong>${hole}</strong></div>
        <div class="text-sm">팟: ${d.pot ?? '?'} 칩</div>
        <div class="text-sm">내 턴: <strong>${d.is_my_turn ? 'YES ← 지금 액션 제출 가능!' : 'NO'}</strong></div>`;

      // Populate step 5 legal actions
      const laDiv = document.getElementById('qs-legal-actions');
      if (legal.length) {
        laDiv.innerHTML = '<div class="text-sm text-muted mb-2">가능한 액션:</div>' +
          legal.map(a => {
            const extra = a.amount != null ? ` (${a.amount}칩)` : '';
            const rangeHint = (a.min != null && a.max != null) ? ` [min:${a.min} max:${a.max}]` : '';
            return `<button class="btn btn-secondary btn-sm" style="margin:.2rem"
              onclick="qsSelectAction('${a.type}', ${a.min ?? 'null'}, ${a.max ?? 'null'})">${a.type}${extra}${rangeHint}</button>`;
          }).join('');
      } else if (d.is_my_turn) {
        laDiv.innerHTML = '<div class="text-muted text-sm">legal_actions가 없습니다 (상태 확인 필요)</div>';
      } else {
        laDiv.innerHTML = '<div class="text-muted text-sm">지금은 내 턴이 아닙니다. 대기 중...</div>';
      }

      qsMarkDone(4);
      qsLog(`GET ${path} → 200`, 'ok');
    } else {
      box.className = 'result-box error mt-3';
      box.innerHTML = `<div class="text-danger">✗ 오류 (${r.status_code})</div>`;
      qsLog(`GET ${path} → ${r.status_code}`, 'err');
    }
  } catch (e) { qsLog('오류: ' + e.message, 'err'); }
}

function qsSelectAction(type, min, max) {
  const raiseGrp = document.getElementById('qs-raise-group');
  if (type === 'RAISE_TO' || type === 'BET_TO') {
    raiseGrp.style.display = 'block';
    const inp = document.getElementById('qs-raise-amount');
    if (min) inp.min = min;
    if (max) inp.max = max;
    inp.value = min || '';
    inp.placeholder = `min: ${min ?? '?'}, max: ${max ?? '?'}`;
  } else {
    raiseGrp.style.display = 'none';
  }
  // Confirm and submit
  const confirmed = confirm(`액션 "${type}"을 제출할까요?`);
  if (!confirmed) return;
  qsSubmitAction(type, min, max);
}

async function qsSubmitAction(type, min, max) {
  const tableNo = qsState.tableNo;
  const handId  = state.lastHandId;
  if (!tableNo || !handId) { alert('테이블 상태를 다시 조회하세요'); return; }

  let action = { type };
  if (type === 'RAISE_TO' || type === 'BET_TO') {
    const amt = parseInt(document.getElementById('qs-raise-amount').value);
    if (isNaN(amt)) { alert('금액을 입력하세요'); return; }
    action.amount = amt;
  }

  const body = JSON.stringify({
    hand_id: handId,
    action,
    idempotency_key: crypto.randomUUID(),
  });

  const path = `/v1/private/tables/${tableNo}/action`;
  try {
    const r = await proxyCall('POST', path, {}, body);
    const box = document.getElementById('qs-r5');
    box.classList.remove('hidden');
    if (r.status_code === 200) {
      box.className = 'result-box success mt-3';
      box.innerHTML = `<div class="text-success">✓ 액션 제출 성공: ${type}</div>`;
      qsMarkDone(5);
      qsLog(`POST ${path} → 200 (${type})`, 'ok');
    } else {
      box.className = 'result-box error mt-3';
      box.innerHTML = `<div class="text-danger">✗ 오류 (${r.status_code})</div>
        <pre class="code-block" style="font-size:.75rem">${escHtml(JSON.stringify(r.response_body, null, 2))}</pre>`;
      qsLog(`POST ${path} → ${r.status_code}`, 'err');
    }
  } catch (e) { qsLog('오류: ' + e.message, 'err'); }
}

async function qsStep6() {
  const tableNo = qsState.tableNo;
  if (!tableNo) { alert('테이블에 착석 후 이석할 수 있습니다'); return; }
  const path = `/v1/private/tables/${tableNo}/stand`;
  try {
    const r = await proxyCall('POST', path);
    const box = document.getElementById('qs-r6');
    box.classList.remove('hidden');
    if (r.status_code === 200) {
      box.className = 'result-box success mt-3';
      box.innerHTML = `<div class="text-success mb-1">✓ 이석 완료</div>
        <pre class="code-block" style="font-size:.75rem">${escHtml(JSON.stringify(r.response_body, null, 2))}</pre>`;
      qsMarkDone(6);
      qsState.tableNo = null;
      qsLog(`POST ${path} → 200`, 'ok');
    } else {
      box.className = 'result-box error mt-3';
      box.innerHTML = `<div class="text-danger">✗ 오류 (${r.status_code})</div>
        <pre class="code-block" style="font-size:.75rem">${escHtml(JSON.stringify(r.response_body, null, 2))}</pre>`;
      qsLog(`POST ${path} → ${r.status_code}`, 'err');
    }
  } catch (e) { qsLog('오류: ' + e.message, 'err'); }
}

// ---------------------------------------------------------------------------
// Code tab switching (quickstart)
// ---------------------------------------------------------------------------
function switchTab(el, panelId) {
  const parent = el.closest('.qs-card-body, details');
  if (!parent) return;
  parent.querySelectorAll('.code-tab').forEach(t => t.classList.remove('active'));
  parent.querySelectorAll('.code-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  const panel = document.getElementById(panelId);
  if (panel) panel.classList.add('active');
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
function escHtml(s) {
  if (typeof s !== 'string') s = String(s ?? '');
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function copyToClip(el) {
  const text = el.textContent;
  navigator.clipboard.writeText(text).then(() => showToast('복사됨'));
}

function showToast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = 'position:fixed;bottom:1.5rem;right:1.5rem;background:var(--success);color:#000;padding:.5rem 1rem;border-radius:6px;font-size:.875rem;font-weight:600;z-index:9999';
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2000);
}

function syntaxHighlight(json) {
  if (!json) return '';
  return escHtml(json)
    .replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, match => {
      let cls = 'color:var(--warn)';   // number
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'color:var(--accent)' : 'color:var(--text)';
      } else if (/true|false/.test(match)) {
        cls = 'color:var(--success)';
      } else if (/null/.test(match)) {
        cls = 'color:var(--text-muted)';
      }
      return `<span style="${cls}">${match}</span>`;
    });
}
