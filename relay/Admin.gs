/**
 * Admin dashboard for the owner. Paste into the same Apps Script project as Code.gs.
 *
 * Login: a six-digit code is emailed to the account that owns this script (Session.getEffectiveUser).
 * The code lasts 10 minutes and can be requested once a minute. A correct code starts a session
 * that lasts seven days, checked on every data call. The browser keeps the session token in
 * localStorage; the server keeps only its SHA-256 hash and expiry in the script properties
 * (key "sess_<hash>"), so the token itself never appears in the project settings. Signing out
 * deletes the session on the server.
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
const ADMIN_SESSION_DAYS = 7;          // owner's choice, 9 Oct 2026 (was six hours, CacheService's cap)
const ADMIN_CODE_SECONDS = 600;        // ten minutes
const ADMIN_MAX_TRIES = 5;
// Phone app data: the files the daily jobs keep in the private repo's site/ folder (hub/site_data.py).
const APP_DIR = 'site';
const APP_FILES = ['feed', 'brief', 'context', 'stocks', 'fno', 'multibagger', 'backtest_multibagger'];

/**
 * Sessions live in the script properties, not CacheService: CacheService caps any entry at six hours,
 * which forced a new emailed code at least that often. Each session is stored under the SHA-256 of its
 * token with its expiry time; expired ones are swept whenever a new session starts.
 */
function sessionKey_(token) { return 'sess_' + sha256Hex_(String(token)); }

function sessionCreate_() {
  const props = PropertiesService.getScriptProperties();
  const now = Date.now();
  const all = props.getProperties();
  Object.keys(all).forEach(function (k) {
    if (k.indexOf('sess_') === 0 && !(Number(all[k]) > now)) props.deleteProperty(k);
  });
  const token = Utilities.getUuid() + Utilities.getUuid();
  props.setProperty(sessionKey_(token), String(now + ADMIN_SESSION_DAYS * 86400000));
  return token;
}

function sessionValid_(token) {
  if (!token) return false;
  const props = PropertiesService.getScriptProperties();
  const key = sessionKey_(token);
  const exp = Number(props.getProperty(key) || 0);
  if (exp > Date.now()) return true;
  if (exp) props.deleteProperty(key);
  return false;
}

/** Ends a session on the server (the dashboard's and the phone app's Sign out). Always succeeds. */
function adminLogout(token) {
  if (token) PropertiesService.getScriptProperties().deleteProperty(sessionKey_(token));
  return { ok: true };
}

// The page itself lives in AdminPage.html (a real HTML file in the same Apps Script project), not
// in a template literal here: a stray ' inside the old ADMIN_HTML string broke every button on 9 Oct.
function adminPage() {
  return HtmlService.createHtmlOutputFromFile('AdminPage')
    .setTitle('Market Hub · Research')
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
  return { ok: true, token: sessionCreate_() };
}

function adminData(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
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
 * (mode=app_code, app_verify, app_data, app_logout) with a JSON body sent as text/plain.
 */
function appApi_(mode, body) {
  let p = {};
  try { p = JSON.parse(body || '{}'); } catch (err) { return { error: 'bad JSON body' }; }
  if (mode === 'app_code') return adminRequestCode();
  if (mode === 'app_verify') return adminVerify(p.code);
  if (mode === 'app_data') return appData_(p.token, p.files);
  if (mode === 'app_logout') return adminLogout(p.token);
  return { error: 'unknown mode' };
}

/** Returns the requested phone-app files for a signed-in session, fetched from the private repo in parallel. */
function appData_(token, files) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
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
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  // The dashboard copy (library_compact.json, 11 Oct 2026: ~3.6 MB instead of ~22 MB) when it exists,
  // gzipped for the trip to the browser (~0.7 MB); the page unpacks and rebuilds the full shape.
  let res = privateRaw_(readToken, 'library_compact.json');
  if (res.getResponseCode() === 404) res = privateRaw_(readToken, 'library.json');
  if (res.getResponseCode() === 404) return { error: 'The stock library has not been published yet.' };
  if (res.getResponseCode() !== 200) return { error: 'GitHub returned ' + res.getResponseCode() + ' for the library.' };
  return gzipped_(res);
}

function privateRaw_(readToken, path) {
  return UrlFetchApp.fetch('https://api.github.com/repos/' + ADMIN_REPO + '/contents/' + path,
    { muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
}

// One base64 string instead of a large object: far quicker for google.script.run to carry.
function gzipped_(res) {
  return { gz: Utilities.base64Encode(Utilities.gzip(res.getBlob()).getBytes()) };
}

/** Reads the multi-bagger ranked list (site/multibagger.json) from the private repo for the signed-in
 * owner. Same file the phone app's Multi-bagger screen already reads through appData_ -- this just
 * gives the admin dashboard its own filterable view of it (9 Oct 2026). */
function adminMultibagger(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + ADMIN_REPO + '/contents/site/multibagger.json',
    { muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
  if (res.getResponseCode() === 404) return { error: 'Multi-bagger data has not been published yet.' };
  if (res.getResponseCode() !== 200) return { error: 'GitHub returned ' + res.getResponseCode() + ' for multi-bagger data.' };
  return gzipped_(res);
}
