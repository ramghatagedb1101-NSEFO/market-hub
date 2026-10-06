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
  if (p.request_token) return handleLogin_(p.request_token);
  return html_('Kite relay is running. Log in with your Kite link to start today\'s run.');
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

  props.setProperties({ KITE_ACCESS_TOKEN: body.data.access_token, KITE_TOKEN_DATE: todayIst_() });
  const started = startDailyRun_();
  return html_('Logged in for ' + todayIst_() + '. ' +
               (started ? 'Today\'s daily run has started.' : 'Token saved, but the daily run did not start. Check GH_PAT has Actions: Read and write.'));
}

function handleToken_(p) {
  const props = PropertiesService.getScriptProperties();
  if (!p.key || p.key !== props.getProperty('RELAY_KEY')) return json_({ error: 'forbidden' });
  const token = props.getProperty('KITE_ACCESS_TOKEN');
  const date = props.getProperty('KITE_TOKEN_DATE');
  if (!token || date !== todayIst_()) return json_({ error: 'no token for today; log in with Kite first' });
  return json_({ access_token: token, date: date });
}

/**
 * Live index quotes for the phone page. Public on purpose: it returns only three index prices,
 * never the token. Cached for 10 seconds so many visitors cost one Kite call.
 */
function handleQuote_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('quotes');
  if (hit) return json_(JSON.parse(hit));

  const props = PropertiesService.getScriptProperties();
  const token = props.getProperty('KITE_ACCESS_TOKEN');
  const date = props.getProperty('KITE_TOKEN_DATE');
  const apiKey = props.getProperty('KITE_API_KEY');
  if (!token || date !== todayIst_() || !apiKey) return json_({ error: 'no token for today; log in with Kite first' });

  const symbols = ['NSE:NIFTY 50', 'NSE:NIFTY BANK', 'BSE:SENSEX'];
  const qs = symbols.map(s => 'i=' + encodeURIComponent(s)).join('&');
  const res = UrlFetchApp.fetch('https://api.kite.trade/quote/ohlc?' + qs, {
    method: 'get',
    muteHttpExceptions: true,
    headers: { 'X-Kite-Version': '3', 'Authorization': 'token ' + apiKey + ':' + token },
  });
  const body = JSON.parse(res.getContentText());
  if (body.status !== 'success') return json_({ error: 'Kite: ' + (body.message || 'quote failed') });

  const d = body.data;
  const pick = (sym, name) => {
    const q = d[sym];
    const last = q.last_price, prev = q.ohlc.close;
    return { name: name, last: Math.round(last * 100) / 100, prev_close: Math.round(prev * 100) / 100,
             change: Math.round((last - prev) * 100) / 100,
             change_pct: Math.round((last / prev - 1) * 10000) / 100 };
  };
  const out = {
    ts: Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm:ssXXX"),
    indices: { NIFTY: pick('NSE:NIFTY 50', 'NIFTY 50'), BANKNIFTY: pick('NSE:NIFTY BANK', 'BANK NIFTY'),
               SENSEX: pick('BSE:SENSEX', 'SENSEX') },
  };
  cache.put('quotes', JSON.stringify(out), 10);
  return json_(out);
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

function html_(message) {
  return HtmlService.createHtmlOutput(
    '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<body style="font:18px system-ui;padding:24px;max-width:520px">' +
    '<h2>Market Hub</h2><p>' + message + '</p></body>');
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
