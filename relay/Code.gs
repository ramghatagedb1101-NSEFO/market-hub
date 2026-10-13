/**
 * Kite daily-login relay. Google Apps Script (free). Runs under the owner's Google account.
 *
 * Deploy: Extensions → Apps Script → paste this file → Deploy → New deployment → type "Web app"
 *   Execute as: Me    Who has access: Anyone    → copy the /exec URL.
 *
 * Script properties (Project Settings → Script properties). The owner enters these, never Claude:
 *   KITE_API_KEY      Kite app API key
 *   KITE_API_SECRET   Kite app API secret
 *   GH_PAT            GitHub fine-grained token: this repo, Actions: Read and write
 *   RELAY_KEY         long random string; the daily job sends it to fetch today's token
 *   GH_REPO           ramghatagedb1101-NSEFO/market-hub
 *
 * Flow: Kite login redirects here with request_token → exchange for access_token → store it
 *       for today (IST) → start the daily-forecast workflow.
 * The daily job calls ?mode=token&key=RELAY_KEY to fetch today's access_token. The token never
 * goes into GitHub Secrets or the repo.
 */

function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.mode === 'token') return handleToken_(p);
  if (p.mode === 'quote') return handleQuote_();
  if (p.mode === 'check') return handleCheck_(p);
  if (p.mode === 'admin') return adminPage();
  if (p.mode === 'watchlist') return json_(watchlistForBatch_(p.key || ''));
  if (p.mode === 'watch_check') return json_(watchCheck_(p.key || ''));
  if (p.mode === 'expiry_close') return json_(expiryCloseHook_(p.key || ''));
  if (p.request_token) return handleLogin_(p.request_token);
  return html_('Kite relay is running. Log in with your Kite link to start today\'s run.');
}

/** The daily job posts the admin summary here (mode=publish_admin, with RELAY_KEY). The stock-library
 *  batch posts a new discovery-tier finding here (mode=alert, with RELAY_KEY). The phone app signs in
 *  and reads its data here (mode=app_code, app_verify, app_data, app_logout; see Admin.gs). */
function doPost(e) {
  const p = (e && e.parameter) || {};
  if (p.mode === 'publish_admin') return json_(publishAdmin_(p.key || '', (e.postData && e.postData.contents) || ''));
  if (p.mode === 'alert') return json_(sendDiscoveryAlert_(p.key || '', (e.postData && e.postData.contents) || ''));
  if (p.mode === 'health') return json_(sendHealth_(p.key || '', (e.postData && e.postData.contents) || ''));
  if (p.mode === 'digest') return json_(sendDigest_(p.key || '', (e.postData && e.postData.contents) || ''));
  if (/^app_/.test(p.mode || '')) return json_(appApi_(p.mode, (e.postData && e.postData.contents) || ''));
  return json_({ error: 'unknown mode' });
}

function handleLogin_(requestToken) {
  const props = PropertiesService.getScriptProperties();
  const apiKey = props.getProperty('KITE_API_KEY');
  const secret = props.getProperty('KITE_API_SECRET');
  if (!apiKey || !secret) return html_('Relay is missing KITE_API_KEY or KITE_API_SECRET in script properties.');

  const checksum = sha256Hex_(apiKey + requestToken + secret);
  const res = UrlFetchApp.fetch('https://api.kite.trade/session/token', {
    method: 'post',
    muteHttpExceptions: true,
    headers: { 'X-Kite-Version': '3' },
    payload: { api_key: apiKey, request_token: requestToken, checksum: checksum },
  });
  const body = JSON.parse(res.getContentText());
  if (body.status !== 'success') {
    return html_('Kite login failed: ' + (body.message || 'unknown error') +
                 '. Check that the Zerodha Client ID on the app matches the account you logged in with.');
  }

  props.setProperties({ KITE_ACCESS_TOKEN: body.data.access_token, KITE_TOKEN_DATE: kiteDayIst_() });
  kiteLoginOk_();   // clears a 'login replaced' alarm (KiteWatch.gs)
  const started = startDailyRun_();
  const early = kiteDayIst_() !== todayIst_();   // before 07:35 IST: Kite's morning clear-out can still end this login
  return html_('Logged in for ' + todayIst_() + '. ' +
               (early ? 'Kite clears logins each morning until about 07:30 IST, so this one will stop working; log in again after 07:35 for today\'s market. ' : '') +
               (started ? 'Today\'s daily run has started.' : 'Token saved, but the daily run did not start. Check GH_PAT has Actions: Read and write.'));
}

function handleToken_(p) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey) return json_({ error: 'RELAY_KEY is not set in script properties' });
  if (!p.key || p.key !== relayKey) {
    return json_({ error: 'key does not match RELAY_KEY', key_length_sent: (p.key || '').length,
                   relay_key_length: relayKey.length });
  }
  const token = props.getProperty('KITE_ACCESS_TOKEN');
  const date = props.getProperty('KITE_TOKEN_DATE');
  if (!token || date !== kiteDayIst_()) {
    return json_({ error: 'no Kite token for today; log in with Kite first', token_date: date || null, today: kiteDayIst_() });
  }
  return json_({ access_token: token, date: date });
}

/**
 * Setup check for the owner and the daily job. Reports only whether each script property is set,
 * its length, and whether the key matches. It never returns a value.
 */
function handleCheck_(p) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || !p.key || p.key !== relayKey) return json_({ error: 'forbidden' });
  const names = ['KITE_API_KEY', 'KITE_API_SECRET', 'RELAY_KEY', 'GH_PAT', 'GH_REPO', 'KITE_ACCESS_TOKEN', 'KITE_TOKEN_DATE'];
  const set = {};
  names.forEach(n => {
    const v = props.getProperty(n) || '';
    set[n] = { set: v.length > 0, length: v.length };
  });
  return json_({
    today: todayIst_(),
    properties: set,
    key_sent: p.key !== undefined,
    key_matches: p.key === undefined ? null : (relayKey.length > 0 && p.key === relayKey),
    key_length_sent: (p.key || '').length,
    token_date: props.getProperty('KITE_TOKEN_DATE') || null,
    kite_day: kiteDayIst_(),
    token_ok_for_today: props.getProperty('KITE_TOKEN_DATE') === kiteDayIst_() && !!props.getProperty('KITE_ACCESS_TOKEN'),
  });
}

/**
 * Live index quotes for the phone page. Public on purpose: it returns only three index prices,
 * never the token. Cached for 10 seconds so many visitors cost one Kite call.
 */
function handleQuote_() {
  return json_(quoteData_());
}

/** Dashboard market strip (13 Oct 2026): the same quotes as the phone, behind the dashboard sign-in. */
function adminQuotes(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const q = quoteData_();
  q.overseas = overseasSnapshot_();   // one Yahoo request a minute, not Kite
  return q;
}

// Index, VIX, gold, crude and rupee levels for the strip, the phone and live.json: read from the platform's one
// 10-second Kite snapshot (Market.gs) instead of a Kite call of its own.
function quoteData_() {
  const snap = marketSnapshot_();
  if (snap.error === 'no_login') return { error: 'no token for today; log in with Kite first', kite_login: 'no_login', login_link: kiteLoginLink_() };
  if (snap.error) { const st = kiteStatus_(); return { error: 'Kite: ' + snap.error, kite_login: st.state, login_link: st.login_link || null }; }
  const d = snap.q, front = snap.front || {};
  const pick = (sym, name) => {
    const x = d[sym]; if (!x || x[1] == null) return null;
    const last = x[0], prev = x[1];
    return { name: name, last: Math.round(last * 100) / 100, prev_close: Math.round(prev * 100) / 100,
             change: Math.round((last - prev) * 100) / 100,
             change_pct: prev ? Math.round((last / prev - 1) * 10000) / 100 : null };
  };
  const out = {
    ts: snap.ts,
    indices: { NIFTY: pick('NSE:NIFTY 50', 'NIFTY 50'), BANKNIFTY: pick('NSE:NIFTY BANK', 'BANK NIFTY'),
               SENSEX: pick('BSE:SENSEX', 'SENSEX') },
    india_vix: pick('NSE:INDIA VIX', 'INDIA VIX'),
    extra: {},
  };
  if (front.gold && d['MCX:' + front.gold]) out.extra.gold = Object.assign(pick('MCX:' + front.gold, 'GOLD'), { contract: front.gold });
  if (front.crude && d['MCX:' + front.crude]) out.extra.crude = Object.assign(pick('MCX:' + front.crude, 'CRUDE'), { contract: front.crude });
  if (front.usd && d['CDS:' + front.usd]) out.extra.usd_inr = Object.assign(pick('CDS:' + front.usd, 'USDINR'), { contract: front.usd });
  return out;
}


/**
 * Nearest unexpired monthly futures for MCX GOLD and CRUDEOIL, and CDS USDINR, from Kite's public
 * instrument lists. Cached for 6 hours, so the lists are downloaded rarely.
 */
function frontMonths_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('front_months');
  if (hit) return JSON.parse(hit);
  const today = todayIst_();
  const pickFront = (csv, name) => {
    const rows = Utilities.parseCsv(csv);
    const head = rows[0];
    const iSym = head.indexOf('tradingsymbol'), iName = head.indexOf('name');
    const iExp = head.indexOf('expiry'), iType = head.indexOf('instrument_type');
    let best = null;
    rows.slice(1).forEach(r => {
      if (r[iName] !== name || r[iType] !== 'FUT' || !r[iExp] || r[iExp] < today) return;
      if (!best || r[iExp] < best[iExp]) best = r;
    });
    return best ? best[iSym] : null;
  };
  const out = {};
  try {
    const mcx = UrlFetchApp.fetch('https://api.kite.trade/instruments/MCX', { muteHttpExceptions: true }).getContentText();
    out.gold = pickFront(mcx, 'GOLD');
    out.crude = pickFront(mcx, 'CRUDEOIL');
    const cds = UrlFetchApp.fetch('https://api.kite.trade/instruments/CDS', { muteHttpExceptions: true }).getContentText();
    out.usd = pickFront(cds, 'USDINR');
  } catch (e) { /* leave missing: the page falls back to the daily snapshot */ }
  cache.put('front_months', JSON.stringify(out), 21600);
  return out;
}

function startDailyRun_() {
  const props = PropertiesService.getScriptProperties();
  const repo = props.getProperty('GH_REPO');
  const pat = props.getProperty('GH_PAT');
  if (!repo || !pat) return false;
  const res = UrlFetchApp.fetch(
    'https://api.github.com/repos/' + repo + '/actions/workflows/daily.yml/dispatches', {
      method: 'post',
      muteHttpExceptions: true,
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + pat, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ ref: 'main' }),
    });
  return res.getResponseCode() === 204;
}

function sha256Hex_(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8)
    .map(function (b) { return ('0' + (b & 0xff).toString(16)).slice(-2); })
    .join('');
}

function todayIst_() {
  return Utilities.formatDate(new Date(), 'Asia/Kolkata', 'yyyy-MM-dd');
}

/**
 * The Kite login day (13 Oct 2026). Kite clears access tokens each morning some time between about 05:00 and
 * 07:30 IST (Zerodha's forum: "flushed at 07:30 AM ... try post 07.35"), not at midnight. So a token is dated by
 * the IST day it is valid for: the calendar day shifted back 7 h 35 min. A login before 07:35 is dated the day
 * before, so from 07:35 the app asks for a new login instead of showing a dead one as fine.
 * Evidence: logins at 06:03 on Sat 10 Oct and Tue 13 Oct 2026 worked at first, then Kite refused them by
 * 08:34; a login at 09:21 on Mon 12 Oct worked all day. (First version of this fix used 06:00: too early.)
 */
function kiteDayIst_() {
  return Utilities.formatDate(new Date(Date.now() - (7 * 60 + 35) * 60 * 1000), 'Asia/Kolkata', 'yyyy-MM-dd');
}

function html_(message) {
  return HtmlService.createHtmlOutput(
    '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="font:18px system-ui;padding:24px;max-width:520px">' +
    '<h2>Market Hub</h2><p>' + message + '</p></body>');
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
