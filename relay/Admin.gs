/**
 * Admin dashboard for the owner. Paste into the same Apps Script project as Code.gs.
 *
 * Login: a six-digit code is emailed to the account that owns this script (Session.getEffectiveUser).
 * The code lasts 10 minutes and can be requested once a minute. A correct code starts a session
 * that lasts six hours, kept in the browser's session storage and checked on every data call.
 *
 * Data: the daily job writes the admin summary to the private repository market-hub-private. The page
 * reads it with a read-only token kept in the script properties (ADMIN_READ_TOKEN), never in the public repository.
 *
 * Functions called from the page (google.script.run) must not end in an underscore, or the page
 * cannot call them, so these names are public on purpose and each one checks the session.
 */

const ADMIN_FILE = 'market-hub-admin.json';   // legacy Drive file, no longer read by the dashboard
const ADMIN_REPO = 'ramghatagedb1101-NSEFO/market-hub-private';
const ADMIN_PATH = 'admin.json';
const ADMIN_SESSION_SECONDS = 21600;   // six hours, the cache maximum
const ADMIN_CODE_SECONDS = 600;        // ten minutes
const ADMIN_MAX_TRIES = 5;
// Phone app data: the files the daily jobs keep in the private repo's site/ folder (hub/site_data.py).
const APP_DIR = 'site';
const APP_FILES = ['feed', 'brief', 'context', 'stocks', 'fno', 'multibagger', 'backtest_multibagger'];

function adminPage() {
  return HtmlService.createHtmlOutput(ADMIN_HTML)
    .setTitle('Market Hub admin')
    .addMetaTag('viewport', 'width=device-width,initial-scale=1');
}

function adminRequestCode() {
  const cache = CacheService.getScriptCache();
  if (cache.get('admin_rate')) return { error: 'Wait a minute before asking for another code.' };
  const code = String(Math.floor(100000 + Math.random() * 900000));
  cache.put('admin_code', code, ADMIN_CODE_SECONDS);
  cache.remove('admin_tries');
  cache.put('admin_rate', '1', 60);
  const to = Session.getEffectiveUser().getEmail();
  MailApp.sendEmail(to, 'Market Hub admin code',
    'Your Market Hub admin code is ' + code + '. It expires in 10 minutes. If you did not ask for it, ignore this email.');
  return { sent: true };
}

function adminVerify(code) {
  const cache = CacheService.getScriptCache();
  const stored = cache.get('admin_code');
  if (!stored || String(code || '').trim() !== stored) {
    // Five wrong tries cancel the code, so it cannot be guessed (the dashboard and the phone app both
    // reach this from the public web address).
    if (stored) {
      const tries = Number(cache.get('admin_tries') || 0) + 1;
      if (tries >= ADMIN_MAX_TRIES) {
        cache.removeAll(['admin_code', 'admin_tries']);
        return { ok: false, error: 'Too many wrong codes. Ask for a new one.' };
      }
      cache.put('admin_tries', String(tries), ADMIN_CODE_SECONDS);
    }
    return { ok: false, error: 'Code not recognised.' };
  }
  cache.removeAll(['admin_code', 'admin_tries']);
  const token = Utilities.getUuid() + Utilities.getUuid();
  cache.put('admin_session_' + token, '1', ADMIN_SESSION_SECONDS);
  return { ok: true, token: token };
}

function adminData(token) {
  const cache = CacheService.getScriptCache();
  if (!token || !cache.get('admin_session_' + token)) return { error: 'session_expired' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + ADMIN_REPO + '/contents/' + ADMIN_PATH,
    { muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
  if (res.getResponseCode() === 404) return { error: 'No data published yet. The next daily run will send it.' };
  if (res.getResponseCode() !== 200) return { error: 'GitHub returned ' + res.getResponseCode() + ' for the private data.' };
  return JSON.parse(res.getContentText());
}

/** Called by the daily job through doPost. Checks the relay key first, then replaces the private file. */
function publishAdmin_(key, body) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  saveAdminFile_(body);
  return { ok: true };
}

function saveAdminFile_(body) {
  const files = DriveApp.getFilesByName(ADMIN_FILE);
  if (files.hasNext()) {
    files.next().setContent(body);
  } else {
    DriveApp.createFile(ADMIN_FILE, body, MimeType.PLAIN_TEXT);
  }
  return true;
}

/**
 * Called by the stock-library batch (hub/library.py, hub/alerts.py) through doPost when it finds a
 * stock newly worth a "discovery" alert: thin mutual-fund ownership (mf_discovery_tier 1 or 2)
 * alongside strong library/multi-bagger fundamentals. Body is JSON: {findings: [{symbol, tier, met,
 * testable, data_quality_pct, mb_score}]}. One email per call, however many findings it carries.
 */
function sendDiscoveryAlert_(key, body) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let payload;
  try { payload = JSON.parse(body); } catch (err) { return { error: 'bad JSON body' }; }
  const findings = payload.findings || [];
  if (!findings.length) return { ok: true, sent: 0 };
  const tierLabel = { 1: 'Tier 1 -- pounce (fewer than 5 mutual fund schemes hold it)',
                      2: 'Tier 2 -- watch (5-20 schemes)' };
  const lines = findings.map(function (f) {
    return f.symbol + ': ' + (tierLabel[f.tier] || ('tier ' + f.tier)) +
      ' -- library ' + f.met + '/' + f.testable + ' gates met (' + f.data_quality_pct + '% data quality)' +
      (f.mb_score != null ? ', multi-bagger score ' + f.mb_score + '/4' : '');
  });
  const subject = 'Market Hub: ' + findings.length + ' new discovery-tier stock' + (findings.length > 1 ? 's' : '');
  const body_ = 'New this batch (' + todayIst_() + '):\n\n' + lines.join('\n') +
    '\n\nFewer mutual fund schemes holding a stock is the bullish read here: the market has not ' +
    'found it yet. Check the admin dashboard\'s Library tab for the full parameter breakdown before acting.';
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), subject, body_);
  return { ok: true, sent: findings.length };
}

/**
 * The phone app (docs/index.html) signs in with the same email code and session as this dashboard.
 * It is a separate web page, so it cannot use google.script.run: it posts here through doPost
 * (mode=app_code, app_verify, app_data) with a JSON body sent as text/plain.
 */
function appApi_(mode, body) {
  let p = {};
  try { p = JSON.parse(body || '{}'); } catch (err) { return { error: 'bad JSON body' }; }
  if (mode === 'app_code') return adminRequestCode();
  if (mode === 'app_verify') return adminVerify(p.code);
  if (mode === 'app_data') return appData_(p.token, p.files);
  return { error: 'unknown mode' };
}

/** Returns the requested phone-app files for a signed-in session, fetched from the private repo in parallel. */
function appData_(token, files) {
  const cache = CacheService.getScriptCache();
  if (!token || !cache.get('admin_session_' + token)) return { error: 'session_expired' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const names = (Array.isArray(files) ? files : APP_FILES).filter(function (n) { return APP_FILES.indexOf(n) >= 0; });
  const responses = UrlFetchApp.fetchAll(names.map(function (n) {
    return { url: 'https://api.github.com/repos/' + ADMIN_REPO + '/contents/' + APP_DIR + '/' + n + '.json',
             muteHttpExceptions: true,
             headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } };
  }));
  const out = {};
  names.forEach(function (n, i) {
    const res = responses[i];
    const code = res.getResponseCode();
    if (code === 404) { out[n] = { error: 'not published yet' }; return; }
    if (code !== 200) { out[n] = { error: 'GitHub returned ' + code }; return; }
    try { out[n] = JSON.parse(res.getContentText()); } catch (err) { out[n] = { error: 'not valid JSON' }; }
  });
  return { files: out };
}

/** Reads the stock library (library.json) from the private repo for the signed-in owner. */
function adminLibrary(token) {
  const cache = CacheService.getScriptCache();
  if (!token || !cache.get('admin_session_' + token)) return { error: 'session_expired' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + ADMIN_REPO + '/contents/library.json',
    { muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
  if (res.getResponseCode() === 404) return { error: 'The stock library has not been published yet.' };
  if (res.getResponseCode() !== 200) return { error: 'GitHub returned ' + res.getResponseCode() + ' for the library.' };
  return JSON.parse(res.getContentText());
}

const ADMIN_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{
  --bg:#f4f5f7; --card:#ffffff; --border:#e4e6eb; --border-soft:#edeef2;
  --text:#14161c; --muted:#70757f;
  --accent:#2563eb; --accent-dark:#1d4ed8;
  --success:#059669; --success-bg:#e9f9f1;
  --danger:#dc2626; --danger-bg:#fdedec;
  --warn:#b45309; --warn-bg:#fef3e0;
  --neutral:#6b7280; --neutral-bg:#f0f1f3;
}
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  margin:0;padding:0;color:var(--text);background:var(--bg);font-size:14px;line-height:1.5}
#shell{max-width:980px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:18px;font-weight:700;margin:0;display:flex;align-items:center;gap:10px;letter-spacing:-.01em}
h1 svg{flex:none;border-radius:8px}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-bottom:16px;margin-bottom:18px;border-bottom:1px solid var(--border)}
.topbar .sub{color:var(--muted);font-size:12px;margin-top:2px}
input,select,button{font:inherit;color:inherit}
input,select{padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--card)}
input:focus,select:focus{outline:2px solid #bfdbfe;outline-offset:0;border-color:var(--accent)}
button{padding:9px 16px;border:1px solid var(--border);border-radius:8px;background:var(--card);cursor:pointer;font-weight:600;font-size:13px;color:var(--text);transition:background .12s,border-color .12s}
button:hover{border-color:#c7cad1}
button:disabled{opacity:.55;cursor:default}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
button.primary:hover{background:var(--accent-dark)}
button.alt{background:transparent;border-color:transparent;color:var(--muted);padding:6px 10px}
button.alt:hover{color:var(--text);border-color:var(--border)}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden}
th{text-align:left;padding:9px 12px;background:#fafbfc;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700;border-bottom:1px solid var(--border)}
td{padding:9px 12px;border-bottom:1px solid var(--border-soft);vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#fafbfe}
.muted{color:var(--muted)}
.err{color:var(--danger);font-size:13px;margin-top:10px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
.tabs button{padding:7px 14px;border-radius:20px;font-size:13px;font-weight:600;color:var(--muted);background:var(--card)}
.tabs button.on{background:var(--text);border-color:var(--text);color:#fff}
.card{border:1px solid var(--border);background:var(--card);border-radius:12px;padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.card b{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:700;margin-bottom:6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media (max-width:620px){.grid2{grid-template-columns:1fr}}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:700;white-space:nowrap}
.badge-met{background:var(--success-bg);color:var(--success)}
.badge-bad{background:var(--danger-bg);color:var(--danger)}
.badge-warn{background:var(--warn-bg);color:var(--warn)}
.badge-neutral{background:var(--neutral-bg);color:var(--neutral)}
.num-met{color:var(--success);font-weight:700}
.num-bad{color:var(--danger);font-weight:700}
.num-warn{color:var(--warn);font-weight:700}
.toolbar{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px}
@media (max-width:700px){.toolbar{grid-template-columns:repeat(2,1fr)}}
@media (max-width:460px){.toolbar{grid-template-columns:1fr}}
.toolbar label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.toolbar label input{text-transform:none;font-weight:400;font-size:13px}
.toolbar input,.toolbar select{width:100%}
#login-card{max-width:420px;margin:60px auto 0}
pre{white-space:pre-wrap;font-size:12px;background:#fafbfc;border-radius:8px;padding:10px;margin:0}
</style></head>
<body>
<div id="shell">
<div id="login">
  <div class="card" id="login-card">
    <h1 style="margin-bottom:14px"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="36" height="36"><rect width="96" height="96" rx="20" fill="#0b1220"/><polyline points="14,64 34,44 48,54 70,28 82,36" fill="none" stroke="#60a5fa" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="82" cy="36" r="5" fill="#22c55e"/></svg>Market Hub admin</h1>
    <p class="muted" style="margin:0 0 14px">A six-digit code is emailed to the owner's Google account. It expires in 10 minutes.</p>
    <button id="send" class="primary" onclick="sendCode()" style="width:100%">Email me a code</button>
    <div id="codebox" style="display:none;margin-top:14px">
      <div style="display:flex;gap:8px">
        <input id="code" inputmode="numeric" maxlength="6" placeholder="6-digit code" style="flex:1">
        <button class="primary" onclick="verify()">Sign in</button>
      </div>
    </div>
    <p id="lmsg" class="err"></p>
  </div>
</div>
<div id="app" style="display:none">
  <div class="topbar">
    <h1><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="30" height="30"><rect width="96" height="96" rx="20" fill="#0b1220"/><polyline points="14,64 34,44 48,54 70,28 82,36" fill="none" stroke="#60a5fa" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="82" cy="36" r="5" fill="#22c55e"/></svg>Market Hub admin</h1>
    <div style="text-align:right">
      <div class="sub">Signed in &middot; data from the last daily run</div>
      <button class="alt" onclick="logout()">Sign out</button>
    </div>
  </div>
  <div class="tabs" id="tabs"></div>
  <div id="view"></div>
</div>
</div>
<script>
let token = sessionStorage.getItem('mh_admin_token') || '';
let data = null;
let tab = 'status';
let lib = null;
let libPage = 0;
const LIB_PAGE_SIZE = 100;
function onLibFilterChange(){ libPage = 0; drawLibTable(); }

function sendCode(){
  document.getElementById('send').disabled = true;
  google.script.run.withSuccessHandler(r => {
    if (r.error) { lmsg(r.error); document.getElementById('send').disabled = false; return; }
    document.getElementById('codebox').style.display = 'block';
    lmsg('Code sent. Check your email.');
  }).withFailureHandler(e => { lmsg('Could not send the code: ' + e.message); document.getElementById('send').disabled = false; }).adminRequestCode();
}
function verify(){
  const c = document.getElementById('code').value;
  google.script.run.withSuccessHandler(r => {
    if (!r.ok) { lmsg(r.error || 'Code not recognised.'); return; }
    token = r.token; sessionStorage.setItem('mh_admin_token', token);
    show();
  }).withFailureHandler(e => lmsg(e.message)).adminVerify(c);
}
function lmsg(t){ document.getElementById('lmsg').textContent = t; }
function logout(){ sessionStorage.removeItem('mh_admin_token'); token=''; location.reload(); }

function show(){
  document.getElementById('login').style.display = 'none';
  document.getElementById('app').style.display = 'block';
  load();
}
function load(){
  google.script.run.withSuccessHandler(d => {
    if (d.error === 'session_expired') { logout(); return; }
    if (d.error) { document.getElementById('view').innerHTML = '<p class="err">' + esc(d.error) + '</p>'; return; }
    data = d; drawTabs(); draw();
  }).withFailureHandler(e => { document.getElementById('view').innerHTML = '<p class="err">' + esc(e.message) + '</p>'; }).adminData(token);
}
const TABS = [['status','Status'],['library','Library'],['params','Parameters'],['registry','Registry'],['bulk','Bulk deals'],['tests','Back-tests']];
function drawTabs(){
  document.getElementById('tabs').innerHTML = TABS.map(([k,l]) =>
    '<button class="' + (k===tab?'on':'') + '" data-k="' + k + '" onclick="pick(this.dataset.k)">' + l + '</button>').join('');
}
function pick(k){ tab = k; drawTabs(); draw(); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
const BADGE_CLASS = { met:'met', available:'met', confirmed:'met', not_met:'bad', gap:'bad',
  to_build:'warn', collecting:'warn', unconfirmed:'warn', annual_only:'neutral', not_testable:'neutral' };
function badge(status){
  const cls = BADGE_CLASS[status] || 'neutral';
  const label = String(status == null ? '-' : status).replace(/_/g, ' ');
  return '<span class="badge badge-' + cls + '">' + esc(label) + '</span>';
}
function dqClass(pct){ return pct >= 70 ? 'num-met' : (pct >= 40 ? 'num-warn' : 'muted'); }
function draw(){
  const v = document.getElementById('view');
  const d = data;
  if (tab === 'status') {
    const s = d.status || {};
    v.innerHTML = '<div class="grid2">' +
      '<div class="card"><b>Last daily run</b>' + esc(s.daily_ts || 'unknown') + '</div>' +
      '<div class="card"><b>Parameters</b>' + esc((s.parameters||{}).total) + ' total &middot; ' + esc(JSON.stringify((s.parameters||{}).by_status || {})) + '</div>' +
      '<div class="card"><b>Bulk deals stored</b>' + esc((d.bulk_deals||{}).days_stored || 0) + ' days, from ' + esc((d.bulk_deals||{}).first_day || '-') + '</div>' +
      '<div class="card"><b>Multi-bagger ratings</b>' + esc((d.multibagger||{}).rated || 0) + ' rated &middot; ' + esc((d.multibagger||{}).turnarounds || 0) + ' turnarounds</div>' +
      '</div>';
  } else if (tab === 'params') {
    const rows = (d.parameters || []).map(p => '<tr><td>' + esc(p.id) + '</td><td>' + esc(p.family) + '</td><td>' + badge(p.status) + '</td><td class="muted">' + esc(p.definition) + '</td></tr>').join('');
    v.innerHTML = '<table><tr><th>Id</th><th>Family</th><th>Status</th><th>Definition</th></tr>' + rows + '</table>';
  } else if (tab === 'registry') {
    const rows = (d.registry || []).map(r => '<tr><td>' + esc(r.name) + '</td><td>' + esc(r.type) + '</td><td>' + badge(r.status) + '</td><td class="muted">' + esc((r.aliases||[]).join(', ')) + '</td></tr>').join('');
    v.innerHTML = '<table><tr><th>Name</th><th>Type</th><th>Status</th><th>Aliases</th></tr>' + rows + '</table>' +
      '<div class="sec" style="margin-top:18px">Candidate matches to review</div>' +
      '<p class="muted" style="margin:0 0 10px">A name on an official NSE shareholding filing lining up with a registry alias. Not automatic: confirm an investor in hub/registry.json before it counts toward any parameter.</p>' +
      '<div id="matchesbox"><p class="muted">Loading…</p></div>';
    if (!lib) { loadLib(); } else { drawMatches(); }
  } else if (tab === 'bulk') {
    const days = (d.bulk_deals || {}).by_day || {};
    const rows = Object.keys(days).sort().reverse().map(k => '<tr><td>' + esc(k) + '</td><td>' + days[k].deals + '</td><td>' + days[k].buys + '</td><td>' + days[k].sells + '</td><td>' + days[k].registry_buys + '</td></tr>').join('');
    v.innerHTML = '<table><tr><th>Day</th><th>Deals</th><th>Buys</th><th>Sells</th><th>Registry buys</th></tr>' + rows + '</table>';
  } else if (tab === 'library') {
    if (!lib) { v.innerHTML = '<p class="muted">Loading the library...</p>'; loadLib(); return; }
    if (lib.error) { v.innerHTML = '<p class="err">' + esc(lib.error) + '</p>'; return; }
    if (!document.getElementById('libctl')) {
      const opts = Object.keys(lib.rules || {}).map(k => '<option value="' + esc(k) + '">' + esc(k) + '</option>').join('');
      v.innerHTML = '<p class="muted" id="libinfo" style="margin:0 0 12px"></p>' +
        '<div class="card"><div id="libctl" class="toolbar">' +
        '<label>Search symbol<input id="libq" placeholder="e.g. TCS" oninput="onLibFilterChange()"></label>' +
        '<label>Sort<select id="libsort" onchange="onLibFilterChange()"><option value="met">Most parameters met</option><option value="data">Data quality</option><option value="symbol">Symbol</option></select></label>' +
        '<label>Min parameters met<input id="libmin" type="number" min="0" max="30" value="0" oninput="onLibFilterChange()"></label>' +
        '<label>Min data quality %<input id="libdq" type="number" min="0" max="100" value="0" oninput="onLibFilterChange()"></label>' +
        '<label>Parameter<select id="libp" onchange="onLibFilterChange()"><option value="">Any parameter</option>' + opts + '</select></label>' +
        '<label>Parameter is<select id="libst" onchange="onLibFilterChange()"><option value="met">Met</option><option value="not_met">Not met</option><option value="not_testable">Not testable</option></select></label>' +
        '</div><p class="muted" id="libinfo2" style="margin:10px 0 0"></p></div>' +
        '<div id="libpage" style="display:flex;align-items:center;gap:10px;margin-bottom:10px"></div>' +
        '<div id="libtable"></div>' +
        '<div id="libpage2" style="display:flex;align-items:center;gap:10px;margin-top:10px"></div>' +
        '<div id="stockdetail"></div>';
      document.getElementById('libinfo').textContent = 'Generated ' + (lib.generated || '') + (lib.partial ? ' (partial run)' : '') + ' · ' + (lib.stocks || []).length + ' companies.';
    }
    drawLibTable();
  } else if (tab === 'tests') {
    const t = d.tests || {};
    let html = '';
    for (const k of Object.keys(t)) {
      html += '<div class="card"><b>' + esc(k) + '</b><pre style="white-space:pre-wrap;font-size:13px">' + esc(JSON.stringify(t[k], null, 1)) + '</pre></div>';
    }
    v.innerHTML = html || '<p class="muted">No back-test results yet.</p>';
  }
}
function loadLib(){
  google.script.run.withSuccessHandler(d => {
    if (d.error === 'session_expired') { logout(); return; }
    lib = d; draw();
  }).withFailureHandler(e => { lib = { error: e.message }; draw(); }).adminLibrary(token);
}
function drawMatches(){
  const el = document.getElementById('matchesbox');
  if (!el) return;
  if (lib.error) { el.innerHTML = '<p class="err">' + esc(lib.error) + '</p>'; return; }
  const statusByInvestor = {};
  (data.registry || []).forEach(r => { statusByInvestor[r.name] = r.status; });
  const rows = [];
  Object.keys(lib.investor_matches || {}).forEach(sym => {
    (lib.investor_matches[sym] || []).forEach(m => rows.push({ sym, ...m }));
  });
  if (!rows.length) { el.innerHTML = '<p class="muted">No candidate matches found yet.</p>'; return; }
  rows.sort((a, b) => a.investor < b.investor ? -1 : a.investor > b.investor ? 1 : 0);
  const body = rows.map(r => '<tr><td><b>' + esc(r.sym) + '</b></td><td>' + esc(r.investor) + '</td><td>' +
    badge(statusByInvestor[r.investor] || 'unconfirmed') + '</td><td class="muted">' + esc(r.alias_matched) + '</td><td>' +
    esc(r.holder_name) + '</td><td>' + (r.shares != null ? r.shares.toLocaleString('en-IN') : '-') + '</td><td>' +
    (r.pct != null ? r.pct + '%' : '-') + '</td></tr>').join('');
  el.innerHTML = '<table><tr><th>Symbol</th><th>Investor</th><th>Status</th><th>Alias matched</th><th>Name on filing</th><th>Shares</th><th>%</th></tr>' + body + '</table>';
}
function drawLibTable(){
  const el = document.getElementById('libtable');
  if (!el || !lib || !lib.stocks) return;
  const q = document.getElementById('libq').value.trim().toUpperCase();
  const sort = document.getElementById('libsort').value;
  const minMet = Number(document.getElementById('libmin').value || 0);
  const minDq = Number(document.getElementById('libdq').value || 0);
  const p = document.getElementById('libp').value;
  const st = document.getElementById('libst').value;
  let rows = lib.stocks.filter(s => s.symbol && s.symbol.indexOf(q) >= 0 && (s.met || 0) >= minMet &&
    (s.data_quality_pct || 0) >= minDq && (!p || (s.cells && s.cells[p] && s.cells[p].status === st)));
  rows.sort((a, b) => sort === 'symbol' ? (a.symbol < b.symbol ? -1 : 1) :
    sort === 'data' ? (b.data_quality_pct || 0) - (a.data_quality_pct || 0) : (b.met || 0) - (a.met || 0));
  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total / LIB_PAGE_SIZE));
  if (libPage >= pages) libPage = pages - 1;
  if (libPage < 0) libPage = 0;
  const from = libPage * LIB_PAGE_SIZE;
  const pageRows = rows.slice(from, from + LIB_PAGE_SIZE);
  const body = pageRows.map(s => '<tr style="cursor:pointer" data-s="' + esc(s.symbol) + '" onclick="showStock(this.dataset.s)"><td><b>' +
    esc(s.symbol) + '</b></td><td><span class="num-met">' + (s.met || 0) + '</span></td><td><span class="num-bad">' + (s.not_met || 0) +
    '</span></td><td class="muted">' + (s.not_testable || 0) + '</td><td><span class="' + dqClass(s.data_quality_pct || 0) + '">' +
    (s.data_quality_pct || 0) + '%</span></td></tr>').join('');
  const shownFrom = total === 0 ? 0 : from + 1;
  const shownTo = Math.min(from + LIB_PAGE_SIZE, total);
  document.getElementById('libinfo2').textContent = total + ' companies match · showing ' + shownFrom + '–' + shownTo + ' · tap a row for detail';
  el.innerHTML = '<table><tr><th>Symbol</th><th>Met</th><th>Not met</th><th>Not testable</th><th>Data</th></tr>' + body + '</table>';
  const pageOpts = [];
  for (let i = 0; i < pages; i++) {
    const pFrom = i * LIB_PAGE_SIZE + 1;
    const pTo = Math.min((i + 1) * LIB_PAGE_SIZE, total);
    pageOpts.push('<option value="' + i + '"' + (i === libPage ? ' selected' : '') + '>' + pFrom + '–' + pTo + '</option>');
  }
  const pager = '<button' + (libPage === 0 ? ' disabled' : '') + ' onclick="libGoPage(' + (libPage - 1) + ')">← Prev</button>' +
    '<select onchange="libGoPage(Number(this.value))">' + pageOpts.join('') + '</select>' +
    '<span class="muted">of ' + total + '</span>' +
    '<button' + (libPage >= pages - 1 ? ' disabled' : '') + ' onclick="libGoPage(' + (libPage + 1) + ')">Next →</button>';
  document.getElementById('libpage').innerHTML = pager;
  document.getElementById('libpage2').innerHTML = pager;
}
function libGoPage(p){ libPage = p; drawLibTable(); window.scrollTo({top: 0, behavior: 'smooth'}); }
function showStock(sym){
  const s = (lib.stocks || []).find(x => x.symbol === sym);
  const el = document.getElementById('stockdetail');
  if (!s || !el) return;
  if (s.error) {
    el.innerHTML = '<div class="card" style="margin-top:12px"><b style="font-size:14px;text-transform:none;letter-spacing:0;color:var(--text)">' +
      esc(sym) + '</b><p class="err" style="margin:8px 0 0">' + esc(s.error) + '</p></div>';
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  const rows = Object.keys(s.cells || {}).map(k => {
    const c = s.cells[k];
    return '<tr><td>' + esc(k) + '</td><td>' + esc(c.value == null ? '-' : c.value) + '</td><td>' + badge(c.status) + '</td><td class="muted">' + esc(c.rule) + '</td></tr>';
  }).join('');
  el.innerHTML = '<div class="card" style="margin-top:12px"><b style="font-size:14px;text-transform:none;letter-spacing:0;color:var(--text)">' +
    esc(sym) + ' <span class="muted" style="font-weight:400">(' + esc(s.latest_period || '-') + ')</span></b><table>' +
    '<tr><th>Parameter</th><th>Value</th><th>Result</th><th>Rule</th></tr>' + rows + '</table></div>';
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
if (token) { show(); }
</script>
</body></html>`;
