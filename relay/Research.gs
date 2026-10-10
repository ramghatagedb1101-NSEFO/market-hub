/**
 * Research additions to the stock report (11 Oct 2026):
 *   adminChart      price candles for the interactive chart: Kite historical data (included in the paid
 *                   Kite Connect plan that already serves the live quotes), BharatStock daily prices
 *                   as the fallback when today's Kite login has not happened
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
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const spec = CHART_RANGES[range] || CHART_RANGES['5Y'];
  const key = 'ch2_' + sym + '_' + (CHART_RANGES[range] ? range : '5Y');
  const cache = CacheService.getScriptCache();
  const hit = cache.get(key);
  if (hit) return JSON.parse(hit);

  let out = kiteChart_(sym, spec);
  if (out.error && spec.interval === 'day') {
    const fb = bsChart_(sym, spec.days);
    fb.kite_note = out.error;
    out = fb;
  }
  if (!out.error) {
    try { cache.put(key, JSON.stringify(out), spec.interval === 'day' ? 1800 : 120); } catch (e) { /* too large: fine */ }
  }
  return out;
}

function kiteHeaders_() {
  const props = PropertiesService.getScriptProperties();
  const tok = props.getProperty('KITE_ACCESS_TOKEN'), apiKey = props.getProperty('KITE_API_KEY');
  if (!tok || !apiKey || props.getProperty('KITE_TOKEN_DATE') !== todayIst_()) return null;
  return { 'X-Kite-Version': '3', 'Authorization': 'token ' + apiKey + ':' + tok };
}

function kiteToken_(sym, headers) {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('ktok_' + sym);
  if (hit) return Number(hit);
  const r = UrlFetchApp.fetch('https://api.kite.trade/quote/ohlc?i=' + encodeURIComponent('NSE:' + sym),
                              { muteHttpExceptions: true, headers: headers });
  const body = JSON.parse(r.getContentText());
  const q = body.data && body.data['NSE:' + sym];
  if (!q || !q.instrument_token) return null;
  cache.put('ktok_' + sym, String(q.instrument_token), 21600);
  return q.instrument_token;
}

function kiteChart_(sym, spec) {
  const headers = kiteHeaders_();
  if (!headers) return { error: 'No Kite login for today yet, so intraday charts are unavailable (daily charts fall back to BharatStock).' };
  const itok = kiteToken_(sym, headers);
  if (!itok) return { error: 'Kite does not list NSE:' + sym + '.' };
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
    if (body.status !== 'success') return { error: 'Kite: ' + (body.message || 'historical data refused') +
      (/permission/i.test(body.message || '') ? ' (historical data needs the paid Kite Connect plan)' : '') };
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

function bsChart_(sym, days) {
  const bsKey = PropertiesService.getScriptProperties().getProperty('BHARATSTOCK_API_KEY') || '';
  if (!bsKey) return { error: 'No Kite login today and BHARATSTOCK_API_KEY is not set, so no price history.' };
  const from = Utilities.formatDate(new Date(Date.now() - Math.min(days, 1827) * 86400000), 'Asia/Kolkata', 'yyyy-MM-dd');
  let rows = [], page = 1, body;
  do {
    const r = UrlFetchApp.fetch(BHARAT + encodeURIComponent(sym) + '/prices?from=' + from + '&page_size=1000' + (page > 1 ? '&page=' + page : ''),
                                { muteHttpExceptions: true, headers: { 'X-API-Key': bsKey } });
    if (r.getResponseCode() === 429) return { error: 'BharatStock daily limit reached and no Kite login today.' };
    if (r.getResponseCode() !== 200) return { error: 'BharatStock returned ' + r.getResponseCode() + ' for prices.' };
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
