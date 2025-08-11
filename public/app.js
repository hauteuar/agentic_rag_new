
(() => {
  let API = "/api";
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);
  const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };

  // Tabs
  const tabs = $$("#tabs button");
  function showTab(name) {
    tabs.forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    $$(".tab").forEach(sec => sec.classList.add('hidden'));
    const tgt = document.getElementById(`tab-${name}`);
    if (tgt) tgt.classList.remove('hidden');
    if (name === "dashboard") refreshDashboard();
  }
  tabs.forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));

  // API base
  const apiBaseEl = document.getElementById('apiBase');
  document.getElementById('btnSetApi').onclick = () => { API = apiBaseEl.value || "/api"; };

  // Session state
  const sessionIdEl = document.getElementById('sessionId');

  function addMsg(role, text) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;
    div.textContent = text;
    const chatBox = document.getElementById('chatBox');
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  async function newSession() {
    const r = await fetch(`${API}/session/create`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) });
    const js = await r.json();
    sessionIdEl.value = js.session_id;
    setText('dashSessionId', js.session_id);
    await refreshDashboard();
  }

  async function loadHistory() {
    const sid = sessionIdEl.value.trim();
    if (!sid) return;
    const r = await fetch(`${API}/history/${sid}`);
    const js = await r.json();
    const chatBox = document.getElementById('chatBox');
    chatBox.innerHTML = "";
    let u=0,a=0;
    for (const m of js.history || []) {
      addMsg(m.role, m.content);
      if (m.role === 'user') u++; else if (m.role === 'assistant') a++;
    }
    setText('dashMsgCount', (u+a).toString());
  }

  // Dashboard data
  async function refreshDashboard() {
    const sid = sessionIdEl.value.trim();
    if (!sid) return;

    // Current schema
    try {
      const s = await fetch(`${API}/db2/current-schema`).then(r=>r.json());
      setText('dashSchema', s.schema || "-");
      // Fill placeholders on DB2 tabs
      const ds = document.getElementById('db2Schema');
      const d2 = document.getElementById('diffSchema');
      if (ds && !ds.placeholder) ds.placeholder = s.schema || "";
      if (d2 && !d2.placeholder) d2.placeholder = s.schema || "";
    } catch(e){}

    // Recent chat
    try {
      const h = await fetch(`${API}/history/${sid}`).then(r=>r.json());
      const list = document.getElementById('dashRecentChat');
      list.innerHTML = "";
      const last = (h.history || []).slice(-6);
      last.forEach(m => {
        const p = document.createElement('div');
        p.className = `msg ${m.role}`;
        p.textContent = m.content.slice(0, 240);
        list.appendChild(p);
      });
      setText('dashMsgCount', (h.history||[]).length.toString());
    } catch(e){}

    // Lineage snapshot
    try {
      const lin = await fetch(`${API}/analysis/lineage/${sid}`).then(r=>r.json());
      const files = (lin.lineage || lin || {}).files || {};
      const tables = (lin.lineage || lin || {}).tables || {};
      const fList = document.getElementById('dashFiles'); fList.innerHTML="";
      Object.keys(files).slice(0, 10).forEach(k => {
        const li = document.createElement('li'); li.textContent = k; fList.appendChild(li);
      });
      const tList = document.getElementById('dashTables'); tList.innerHTML="";
      Object.keys(tables).slice(0, 10).forEach(k => {
        const li = document.createElement('li'); li.textContent = k; tList.appendChild(li);
      });
      // Rough artifact proxy: files + tables count
      setText('dashArtifacts', (Object.keys(files).length + Object.keys(tables).length).toString());
    } catch(e){}
  }

  // Upload helpers
  async function upload(endpoint, formData) {
    const r = await fetch(`${API}${endpoint}`, { method: 'POST', body: formData });
    if (!r.ok) throw new Error(await r.text());
    return await r.json();
  }

  // Wire buttons per tab

  // Session
  document.getElementById('btnNewSession').onclick = newSession;
  document.getElementById('btnLoadHistory').onclick = loadHistory;

  // Upload: docs
  document.getElementById('btnIngestDocs').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    if (!sid) return alert("Set session first");
    const files = document.getElementById('docFiles').files;
    if (!files.length) return alert("Choose files");
    const fd = new FormData();
    fd.append('session_id', sid);
    for (const f of files) fd.append('files', f);
    const js = await upload('/upload', fd);
    alert(`Ingested chunks: ${js.ingested_chunks}`);
    refreshDashboard();
  };

  // Upload: code
  document.getElementById('btnIngestCode').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    if (!sid) return alert("Set session first");
    const files = document.getElementById('codeFiles').files;
    if (!files.length) return alert("Choose code files");
    const fd = new FormData();
    fd.append('session_id', sid);
    fd.append('prompt', ''); // no summarization needed
    for (const f of files) fd.append('files', f);
    const js = await upload('/code/summarize', fd);
    alert(`Code uploaded. Citations: ${JSON.stringify(js.citations || [])}`);
    refreshDashboard();
  };

  // Upload: batch zip
  document.getElementById('btnBatchZip').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    if (!sid) return alert("Set session first");
    const zf = document.getElementById('zipFile').files[0];
    if (!zf) return alert("Choose a ZIP");
    const fd = new FormData();
    fd.append('session_id', sid);
    fd.append('archive', zf);
    const js = await upload('/batch/upload-zip', fd);
    alert(`Batch upload: ${js.count_docs} docs, ${js.count_code} code files, ${js.total_chunks} chunks`);
    refreshDashboard();
  };

  // Chat
  document.getElementById('btnSendChat').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    if (!sid) return alert("Set session first");
    const inp = document.getElementById('chatInput');
    const msg = inp.value.trim();
    if (!msg) return;
    addMsg('user', msg);
    inp.value = "";
    const r = await fetch(`${API}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sid, message: msg }) });
    const js = await r.json();
    addMsg('assistant', js.answer || "(no answer)");
    refreshDashboard();
  };

  // DB2 import
  document.getElementById('btnDb2Import').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const schema = document.getElementById('db2Schema').value;
    const table = document.getElementById('db2Table').value;
    const limit = document.getElementById('db2Limit').value;
    const fd = new FormData();
    fd.append('session_id', sid); fd.append('table', table);
    if (schema) fd.append('schema', schema);
    if (+limit>0) fd.append('limit', String(+limit));
    const js = await upload('/db2/import-table', fd);
    alert(`DB2 rows ingested: ${js.rows}`);
    refreshDashboard();
  };

  // Diff
  document.getElementById('btnRunDiff').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const schema = document.getElementById('diffSchema').value;
    const table = document.getElementById('diffTable').value;
    const keys = document.getElementById('diffKeys').value;
    const db2limit = document.getElementById('diffDb2Limit').value;
    const csv = document.getElementById('diffCsv').files[0];
    if (!csv) return alert("Upload CSV");
    const fd = new FormData();
    fd.append('session_id', sid); fd.append('table', table);
    if (schema) fd.append('schema', schema);
    fd.append('key_cols', keys || "");
    fd.append('db2_limit', String(+db2limit));
    fd.append('csv_file', csv);
    const js = await upload('/db2/csv-diff', fd);
    document.getElementById('diffResult').textContent = JSON.stringify(js, null, 2);
  };

  // Summarizer
  document.getElementById('btnSummarize').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const prompt = document.getElementById('codePrompt').value;
    const fd = new FormData();
    fd.append('session_id', sid); fd.append('prompt', prompt);
    const js = await upload('/code/summarize', fd);
    document.getElementById('summary').innerHTML = `<div class="msg assistant">${(js.answer||"").replace(/</g,'&lt;')}</div>`;
  };

  // Lineage JSON
  document.getElementById('btnLineage').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const r = await fetch(`${API}/analysis/lineage/${sid}`);
    const js = await r.json();
    document.getElementById('lineageJson').textContent = JSON.stringify(js, null, 2);
  };
  document.getElementById('btnCrud').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const r = await fetch(`${API}/analysis/crud-map/${sid}`);
    const js = await r.json();
    document.getElementById('lineageJson').textContent = JSON.stringify(js, null, 2);
  };

  // Graphs
  async function showGraph(url) {
    document.getElementById('graphFrame').src = url;
  }
  document.getElementById('btnCrudGraph').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const r = await fetch(`${API}/analysis/graph/crud/${sid}`);
    const js = await r.json();
    if (js.url) showGraph(js.url);
    else if (js.html_path) showGraph(`/data/${js.html_path.split('/').pop()}`);
  };
  document.getElementById('btnDepGraph').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const el = document.getElementById('depElement').value;
    const rad = document.getElementById('depRadius').value;
    const r = await fetch(`${API}/analysis/graph/dependency/${sid}?element=${encodeURIComponent(el)}&radius=${encodeURIComponent(rad)}`);
    const js = await r.json();
    if (js.url) showGraph(js.url);
    else if (js.html_path) showGraph(`/data/${js.html_path.split('/').pop()}`);
  };

  // Field usage
  document.getElementById('btnFieldUsage').onclick = async () => {
    const sid = document.getElementById('sessionId').value.trim();
    const cb = document.getElementById('fldCopybook').value.trim();
    if (!sid || !cb) return alert("Session and copybook required");
    const r = await fetch(`${API}/analysis/fields/${sid}?copybook=${encodeURIComponent(cb)}`);
    const res = await r.json();
    document.getElementById('fldResult').textContent = JSON.stringify(res, null, 2);
  };

  // Export
  document.getElementById('btnExportMd').onclick = async () => {
    const sid = sessionIdEl.value.trim();
    const include = document.getElementById('includeLLM').checked;
    const fd = new FormData();
    fd.append('session_id', sid); fd.append('include_llm', include ? 'true' : 'false');
    const js = await upload('/export/session', fd);
    const p = js.md_path || "";
    const name = p.split('/').pop();
    const link = document.createElement('a');
    link.href = `/data/exports/${name}`;
    link.download = name;
    link.textContent = `Download ${name}`;
    const box = document.getElementById('exportLinks');
    box.innerHTML = "";
    box.appendChild(link);
  };

  // Initialize
  (async function init() {
    await newSession();
    // Try to set schema placeholders
    fetch(`${API}/db2/current-schema`).then(r=>r.json()).then(js=>{
      const ds = document.getElementById('db2Schema');
      const d2 = document.getElementById('diffSchema');
      if (ds) ds.placeholder = js.schema || ds.placeholder;
      if (d2) d2.placeholder = js.schema || d2.placeholder;
      setText('dashSchema', js.schema || "-");
    }).catch(()=>{});
    showTab("dashboard");
  })();
})();
