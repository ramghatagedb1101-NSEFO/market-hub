/**
 * Research additions to the stock report (11 Oct 2026):
 *   adminChart      price candles for the interactive chart: Kite historical data (included in the paid
 *                   Kite Connect plan that already serves the live quotes); before the day's Kite login,
 *                   a year of NSE daily closes published by the library run (prices branch, free), and
 *                   BharatStock only if those are missing
 *   adminDocs       links to NSE annual reports, call transcripts, presentations and recordings
 *                   (site/docs.json, written by the library batch) and their AI summaries
 *                   (site/summaries.json, written by the ai-summaries workflow)
 *   adminSummarise  starts the ai-summaries workflow for one company (GH_PAT, Actions: write)
 * Nothing here is stored except short-lived caches.
 */
const NIFTY_TOKEN = 256265;   // Kite instrument token for NSE:NIFTY 50
const CHART_RANGES = {
  '1D': { interval: '5minute', days: 5, keepDays: 1 },
  '5D': { interval: '15minute', days: 9, keepDays: 5 },
  '1M': { interval: '60minute', days: 31 },
  '5Y': { interval: 'day', days: 1827 },      // also serves 6M / 1Y / 3Y, sliced in the page
  '10Y': { interval: 'day', days: 3653 },
};

function adminChart(token, symbol, range) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return chartData_(symbol, range);
}

// Shared by the dashboard (adminChart) and the phone (app_stock in Phone.gs).
function chartData_(symbol, range) {
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const spec = CHART_RANGES[range] || CHART_RANGES['5Y'];
  const key = 'ch2_' + sym + '_' + (CHART_RANGES[range] ? range : '5Y');
  const cache = CacheService.getScriptCache();
  const hit = cache.get(key);
  if (hit) return JSON.parse(hit);

  let out = kiteChart_(sym, spec);
  if (out.error) {
    // No Kite login yet today (or Kite refused): NSE's daily closes, free; BharatStock as a last resort.
    const nse = nseChart_(sym);
    if (!nse.error) {
      const why = out.reason === 'no_login' ? 'candles and intraday appear after the morning Kite login' : out.reason;
      nse.note = (spec.interval !== 'day' ? 'showing daily closes; ' : '') + why;
      out = nse;
    } else {
      const fb = bsChart_(sym, spec.days);
      if (!fb.error) {
        fb.note = (spec.interval !== 'day' ? 'showing daily prices; ' : '') + 'NSE closes unavailable: ' + nse.error;
        out = fb;
      } else {
        out = chartDiagnosis_(sym, out, nse, fb);
      }
    }
  }
  if (!out.error) {
    const ttl = out.source === 'kite' ? (spec.interval === 'day' ? 1800 : 120) : 300;
    try { cache.put(key, JSON.stringify(out), ttl); } catch (e) { /* too large: fine */ }
  }
  return out;
}

function kiteHeaders_() {
  const props = PropertiesService.getScriptProperties();
  const tok = props.getProperty('KITE_ACCESS_TOKEN'), apiKey = props.getProperty('KITE_API_KEY');
  if (!tok || !apiKey || props.getProperty('KITE_TOKEN_DATE') !== todayIst_()) return null;
  return { 'X-Kite-Version': '3', 'Authorization': 'token ' + apiKey + ':' + tok };
}

// Kite's refusal in plain words, for the chart's note.
function kiteReason_(msg) {
  msg = String(msg || '');
  if (/api_key|access_token|token/i.test(msg)) return "Kite rejected today's saved login, usually because a newer Kite login replaced it; log in again with the Kite link";
  if (/permission|subscription/i.test(msg)) return 'Kite says historical data needs the paid Kite Connect plan';
  return 'Kite: ' + msg;
}

function kiteToken_(sym, headers) {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('ktok_' + sym);
  if (hit) return Number(hit);
  const r = UrlFetchApp.fetch('https://api.kite.trade/quote/ohlc?i=' + encodeURIComponent('NSE:' + sym),
                              { muteHttpExceptions: true, headers: headers });
  const body = JSON.parse(r.getContentText());
  if (body.status === 'error') throw new Error(body.message || 'quote refused');
  const q = body.data && body.data['NSE:' + sym];
  if (!q || !q.instrument_token) return null;
  cache.put('ktok_' + sym, String(q.instrument_token), 21600);
  return q.instrument_token;
}

function kiteChart_(sym, spec) {
  const headers = kiteHeaders_();
  if (!headers) return { error: 'no Kite login yet today', reason: 'no_login' };
  let itok;
  try { itok = kiteToken_(sym, headers); } catch (e) { return { error: 'Kite: ' + e.message, reason: kiteReason_(e.message) }; }
  if (!itok) return { error: 'Kite does not list NSE:' + sym + '.', reason: 'Kite does not list this company' };
  const fmt = d => Utilities.formatDate(d, 'Asia/Kolkata', 'yyyy-MM-dd HH:mm:ss');
  const now = new Date();
  // Kite caps one request at 2,000 days of daily candles: split longer ranges.
  const spans = [];
  let end = now, left = spec.days;
  while (left > 0) {
    const n = Math.min(left, 1999);
    const start = new Date(end.getTime() - n * 86400000);
    spans.unshift([start, end]);
    end = new Date(start.getTime() - 86400000);
    left -= n + 1;
  }
  const reqs = [];
  spans.forEach(s => {
    [itok, NIFTY_TOKEN].forEach(t => reqs.push({
      url: 'https://api.kite.trade/instruments/historical/' + t + '/' + spec.interval +
           '?from=' + encodeURIComponent(fmt(s[0])) + '&to=' + encodeURIComponent(fmt(s[1])),
      headers: headers, muteHttpExceptions: true }));
  });
  const res = UrlFetchApp.fetchAll(reqs);
  let candles = [], nifty = [];
  for (let i = 0; i < res.length; i++) {
    const body = JSON.parse(res[i].getContentText());
    if (body.status !== 'success') return { error: 'Kite: ' + (body.message || 'historical data refused'), reason: kiteReason_(body.message) };
    const rows = (body.data && body.data.candles) || [];
    if (i % 2 === 0) candles = candles.concat(rows); else nifty = nifty.concat(rows);
  }
  const daily = spec.interval === 'day';
  // Daily: 'YYYY-MM-DD'. Intraday: seconds, shifted to IST so the chart's clock reads Indian time.
  const t = s => daily ? String(s).slice(0, 10) : Math.floor(new Date(s).getTime() / 1000) + 19800;
  let c = candles.map(r => [t(r[0]), r[1], r[2], r[3], r[4], r[5]]);
  let n = nifty.map(r => [t(r[0]), r[4]]);
  if (spec.keepDays) {
    const days = [...new Set(candles.map(r => String(r[0]).slice(0, 10)))].sort().slice(-spec.keepDays);
    const keep = new Set(days);
    c = c.filter((_, i) => keep.has(String(candles[i][0]).slice(0, 10)));
    n = n.filter((_, i) => keep.has(String(nifty[i][0]).slice(0, 10)));
  }
  if (!c.length) return { error: 'Kite returned no candles for ' + sym + '.' };
  return { symbol: sym, source: 'kite', interval: spec.interval, candles: c, nifty: n };
}

// A year of split/bonus-adjusted NSE daily closes (hub/price_shards.py), one small file per first letter.
function nseChart_(sym) {
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'the relay cannot read the private repo (ADMIN_READ_TOKEN is not set)', reason: 'config' };
  const key = /^[A-Z]/.test(sym) ? sym[0] : '0';
  const r = privateRaw_(readToken, 'px/' + key + '.json', 'prices');
  const code = r.getResponseCode();
  if (code === 404) return { error: 'the daily run has not published the NSE closes yet (they are written at 06:15 IST)', reason: 'not_published' };
  if (code === 401 || code === 403) return { error: 'GitHub refused the relay's read token (' + code + '); it may have expired', reason: 'config' };
  if (code !== 200) return { error: 'GitHub returned ' + code + ' when reading the NSE closes', reason: 'github' };
  const d = JSON.parse(r.getContentText()), row = (d.close || {})[sym];
  const last = (d.dates || [])[(d.dates || []).length - 1];
  const listed = (d.listed || {})[sym];
  const nice = iso => Utilities.formatDate(new Date(iso + 'T12:00:00Z'), 'Asia/Kolkata', 'EEE d MMM yyyy');
  if (!row && listed && listed > last) return { error: sym + ' lists on NSE on ' + nice(listed) + '; prices appear after its first trading day', reason: 'not_listed_yet', listed: listed };
  if (!row) return { error: 'NSE has no trades for ' + sym + ' in the last year up to ' + nice(last) + (listed ? ' (listed ' + nice(listed) + ')' : '') + ': suspended, delisted or renamed?', reason: 'no_trades' };
  const c = [];
  (d.dates || []).forEach((day, i) => { if (row[i] != null) c.push([day, null, null, null, row[i], null]); });
  if (!c.length) return { error: 'NSE has no trades for ' + sym + ' in the last year', reason: 'no_trades' };
  return { symbol: sym, source: 'nse', interval: 'day', candles: c, nifty: niftyDaily_(c[0][0]) };
}

// Nothing could draw the chart: say what each source said, and the quickest fix.
function chartDiagnosis_(sym, kite, nse, bs) {
  const kiteWhy = kite.reason === 'no_login' ? "no Kite login yet today" : (kite.reason || kite.error);
  const why = ['Kite: ' + kiteWhy, 'NSE daily closes: ' + nse.error, 'BharatStock: ' + bs.error];
  let fix;
  if (nse.reason === 'not_listed_yet') fix = 'Nothing to fix: ' + sym + ' has not started trading yet. The chart appears after its first day.';
  else if (nse.reason === 'no_trades' && bs.reason === 'no_trades') fix = sym + ' has no recent trading on NSE. Check that the symbol is still current (it may have been renamed, merged or suspended).';
  else if (kite.reason === 'no_login' || /login/.test(kiteWhy)) fix = 'Log in through the Kite link: the chart then uses Kite straight away.';
  else if (nse.reason === 'not_published') fix = 'The NSE closes appear after the next daily run at 06:15 IST.';
  else if (nse.reason === 'config' || bs.reason === 'config') fix = 'A relay setting needs attention: ' + (nse.reason === 'config' ? nse.error : bs.error) + '.';
  else fix = 'Try again in a few minutes.';
  return { error: 'The price chart is not available right now.', why: why, fix: fix };
}

function bsChart_(sym, days) {
  const bsKey = PropertiesService.getScriptProperties().getProperty('BHARATSTOCK_API_KEY') || '';
  if (!bsKey) return { error: 'BHARATSTOCK_API_KEY is not set in the relay', reason: 'config' };
  const from = Utilities.formatDate(new Date(Date.now() - Math.min(days, 1827) * 86400000), 'Asia/Kolkata', 'yyyy-MM-dd');
  let rows = [], page = 1, body;
  do {
    const r = UrlFetchApp.fetch(BHARAT + encodeURIComponent(sym) + '/prices?from=' + from + '&page_size=1000' + (page > 1 ? '&page=' + page : ''),
                                { muteHttpExceptions: true, headers: { 'X-API-Key': bsKey } });
    if (r.getResponseCode() === 429) return { error: 'today's BharatStock allowance is used up (it resets at 05:30 IST)', reason: 'quota' };
    if (r.getResponseCode() === 404) return { error: 'BharatStock has no prices for ' + sym, reason: 'no_trades' };
    if (r.getResponseCode() !== 200) return { error: 'BharatStock returned ' + r.getResponseCode(), reason: 'other' };
    body = JSON.parse(r.getContentText());
    rows = rows.concat(bsRows_(body));
    page++;
  } while (page <= 3 && bsHasNext_(body, page - 1));
  const num = x => x == null || x === '' ? null : Number(x);
  const c = rows.map(x => {
    const close = num(x.adjusted_close != null ? x.adjusted_close : x.close);
    const k = num(x.close) && close ? close / num(x.close) : 1;   // scale O/H/L by the same adjustment
    return [String(x.trade_date || '').slice(0, 10), num(x.open) == null ? null : num(x.open) * k,
            num(x.high) == null ? null : num(x.high) * k, num(x.low) == null ? null : num(x.low) * k, close, num(x.volume)];
  }).filter(r => r[0] && r[4] != null).sort((a, b) => a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);
  if (!c.length) return { error: 'No price history for ' + sym + '.' };
  return { symbol: sym, source: 'bharatstock', interval: 'day', candles: c, nifty: niftyDaily_(from) };
}

function niftyDaily_(from) {
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return [];
  try {
    const r = UrlFetchApp.fetch('https://api.github.com/repos/' + ADMIN_REPO + '/contents/state/prices.json',
      { muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
    const n = JSON.parse(r.getContentText()).NIFTY || {};
    return Object.keys(n).filter(d => d >= from).sort().map(d => [d, n[d]]);
  } catch (e) { return []; }
}

function adminDocs(token, symbol) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return docsData_(symbol);
}

function docsData_(symbol) {
  const sym = String(symbol || '').toUpperCase();
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const get = path => ({ url: 'https://api.github.com/repos/' + ADMIN_REPO + '/contents/' + path, muteHttpExceptions: true,
                         headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
  const res = UrlFetchApp.fetchAll([get('site/docs.json'), get('site/summaries.json')]);
  const out = { symbol: sym, docs: null, summaries: null };
  if (res[0].getResponseCode() === 200) out.docs = (JSON.parse(res[0].getContentText()) || {})[sym] || null;
  else out.docs_note = 'Documents are collected by the daily library run; none published yet.';
  if (res[1].getResponseCode() === 200) out.summaries = (JSON.parse(res[1].getContentText()) || {})[sym] || null;
  const started = CacheService.getScriptCache().get('sum_' + sym);
  if (started) out.summary_started = started;
  return out;
}

function adminSummarise(token, symbol) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return summariseStart_(symbol);
}

function summariseStart_(symbol) {
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const props = PropertiesService.getScriptProperties();
  const repo = props.getProperty('GH_REPO'), pat = props.getProperty('GH_PAT');
  if (!repo || !pat) return { error: 'GH_REPO / GH_PAT are not set in the script properties.' };
  const r = UrlFetchApp.fetch('https://api.github.com/repos/' + repo + '/actions/workflows/summaries.yml/dispatches', {
    method: 'post', muteHttpExceptions: true, contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + pat, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ ref: 'main', inputs: { symbol: sym } }) });
  if (r.getResponseCode() !== 204) return { error: 'GitHub refused to start the summary run (' + r.getResponseCode() + ').' };
  const at = Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm");
  CacheService.getScriptCache().put('sum_' + sym, at, 1800);
  return { ok: true, started: at };
}

/** The Shortlist (site/shortlist.json, written by the daily library run: two lists by style, reasons,
 * weekly persistence and the track record against NIFTY). Small, read on dashboard load. */
function adminShortlist(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const res = privateRaw_(readToken, 'site/shortlist.json');
  if (res.getResponseCode() === 404) return { error: 'The shortlist is published by the daily library run; not yet available.' };
  if (res.getResponseCode() !== 200) return { error: 'GitHub returned ' + res.getResponseCode() + ' for the shortlist.' };
  return JSON.parse(res.getContentText());
}
