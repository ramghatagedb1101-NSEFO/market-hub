/**
 * Admin dashboard for the owner. Paste into the same Apps Script project as Code.gs.
 *
 * Login: a six-digit code is emailed to the account that owns this script (Session.getEffectiveUser).
 * The code lasts 10 minutes and can be requested once a minute. A correct code starts a session
 * that lasts six hours, kept in the browser's session storage and checked on every data call.
 *
 * Data: the daily job posts the admin summary to the relay (mode=publish_admin, RELAY_KEY). It is
 * stored in a private file in the owner's Google Drive, never in the public repository.
 *
 * Functions called from the page (google.script.run) must not end in an underscore, or the page
 * cannot call them, so these names are public on purpose and each one checks the session.
 */

const ADMIN_FILE = 'market-hub-admin.json';
const ADMIN_SESSION_SECONDS = 21600;   // six hours, the cache maximum
const ADMIN_CODE_SECONDS = 600;        // ten minutes

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
  cache.put('admin_rate', '1', 60);
  const to = Session.getEffectiveUser().getEmail();
  MailApp.sendEmail(to, 'Market Hub admin code',
    'Your Market Hub admin code is ' + code + '. It expires in 10 minutes. If you did not ask for it, ignore this email.');
  return { sent: true };
}

function adminVerify(code) {
  const cache = CacheService.getScriptCache();
  const stored = cache.get('admin_code');
  if (!stored || String(code || '').trim() !== stored) return { ok: false, error: 'Code not recognised.' };
  cache.remove('admin_code');
  const token = Utilities.getUuid() + Utilities.getUuid();
  cache.put('admin_session_' + token, '1', ADMIN_SESSION_SECONDS);
  return { ok: true, token: token };
}

function adminData(token) {
  const cache = CacheService.getScriptCache();
  if (!token || !cache.get('admin_session_' + token)) return { error: 'session_expired' };
  const files = DriveApp.getFilesByName(ADMIN_FILE);
  if (!files.hasNext()) return { error: 'No data published yet. The next daily run will send it.' };
  return JSON.parse(files.next().getBlob().getDataAsString());
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

const ADMIN_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font:16px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:720px;margin:auto;color:#111;background:#fff}
h1{font-size:22px;font-weight:500;margin:4px 0 12px}
h2{font-size:18px;font-weight:500;margin:20px 0 8px}
input,button{font:inherit;padding:10px 12px;border:1px solid #bbb;border-radius:8px}
button{background:#111;color:#fff;border-color:#111;cursor:pointer}
button.alt{background:#fff;color:#111}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{border-bottom:1px solid #e5e5e5;padding:6px 4px;text-align:left;vertical-align:top}
.muted{color:#666;font-size:14px}
.err{color:#b00020;font-size:14px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0}
.tabs button{padding:6px 10px;font-size:14px}
.tabs button.on{background:#111;color:#fff}
.card{border:1px solid #e5e5e5;border-radius:12px;padding:12px;margin:8px 0}
</style></head>
<body>
<h1>Market Hub admin</h1>
<div id="login">
  <p class="muted">A six-digit code is emailed to the owner's Google account. It expires in 10 minutes.</p>
  <button id="send" onclick="sendCode()">Email me a code</button>
  <div id="codebox" style="display:none;margin-top:12px">
    <input id="code" inputmode="numeric" maxlength="6" placeholder="6-digit code" style="width:160px">
    <button onclick="verify()">Sign in</button>
  </div>
  <p id="lmsg" class="err"></p>
</div>
<div id="app" style="display:none">
  <p class="muted">Signed in. Data from the last daily run. <button class="alt" onclick="logout()">Sign out</button></p>
  <div class="tabs" id="tabs"></div>
  <div id="view"></div>
</div>
<script>
let token = sessionStorage.getItem('mh_admin_token') || '';
let data = null;
let tab = 'status';

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
const TABS = [['status','Status'],['params','Parameters'],['registry','Registry'],['bulk','Bulk deals'],['tests','Back-tests']];
function drawTabs(){
  document.getElementById('tabs').innerHTML = TABS.map(([k,l]) =>
    '<button class="' + (k===tab?'on':'') + '" data-k="' + k + '" onclick="pick(this.dataset.k)">' + l + '</button>').join('');
}
function pick(k){ tab = k; drawTabs(); draw(); }
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function draw(){
  const v = document.getElementById('view');
  const d = data;
  if (tab === 'status') {
    const s = d.status || {};
    v.innerHTML = '<div class="card"><b>Last daily run</b><br>' + esc(s.daily_ts || 'unknown') + '</div>' +
      '<div class="card"><b>Parameters</b><br>' + esc((s.parameters||{}).total) + ' total. ' + esc(JSON.stringify((s.parameters||{}).by_status || {})) + '</div>' +
      '<div class="card"><b>Bulk deals stored</b><br>' + esc((d.bulk_deals||{}).days_stored || 0) + ' days, from ' + esc((d.bulk_deals||{}).first_day || '-') + '</div>' +
      '<div class="card"><b>Multi-bagger ratings</b><br>' + esc((d.multibagger||{}).rated || 0) + ' rated. ' + esc((d.multibagger||{}).turnarounds || 0) + ' turnarounds.</div>';
  } else if (tab === 'params') {
    const rows = (d.parameters || []).map(p => '<tr><td>' + esc(p.id) + '</td><td>' + esc(p.family) + '</td><td>' + esc(p.status) + '</td><td class="muted">' + esc(p.definition) + '</td></tr>').join('');
    v.innerHTML = '<table><tr><th>Id</th><th>Family</th><th>Status</th><th>Definition</th></tr>' + rows + '</table>';
  } else if (tab === 'registry') {
    const rows = (d.registry || []).map(r => '<tr><td>' + esc(r.name) + '</td><td>' + esc(r.type) + '</td><td>' + esc(r.status) + '</td><td class="muted">' + esc((r.aliases||[]).join(', ')) + '</td></tr>').join('');
    v.innerHTML = '<table><tr><th>Name</th><th>Type</th><th>Status</th><th>Aliases</th></tr>' + rows + '</table>';
  } else if (tab === 'bulk') {
    const days = (d.bulk_deals || {}).by_day || {};
    const rows = Object.keys(days).sort().reverse().map(k => '<tr><td>' + esc(k) + '</td><td>' + days[k].deals + '</td><td>' + days[k].buys + '</td><td>' + days[k].sells + '</td><td>' + days[k].registry_buys + '</td></tr>').join('');
    v.innerHTML = '<table><tr><th>Day</th><th>Deals</th><th>Buys</th><th>Sells</th><th>Registry buys</th></tr>' + rows + '</table>';
  } else if (tab === 'tests') {
    const t = d.tests || {};
    let html = '';
    for (const k of Object.keys(t)) {
      html += '<div class="card"><b>' + esc(k) + '</b><pre style="white-space:pre-wrap;font-size:13px">' + esc(JSON.stringify(t[k], null, 1)) + '</pre></div>';
    }
    v.innerHTML = html || '<p class="muted">No back-test results yet.</p>';
  }
}
if (token) { show(); }
</script>
</body></html>`;
