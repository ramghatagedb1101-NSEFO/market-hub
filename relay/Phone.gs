/**
 * Phone app additions (11 Oct 2026):
 *   app_stock         the stock sheet: price chart (chartData_) plus documents and AI summaries (docsData_)
 *   app_watch         the watchlist with key figures and return since starred vs NIFTY
 *   app_watch_toggle  star / unstar a company (also used by the dashboard: adminWatch, adminWatchToggle)
 *   ?mode=watchlist   the watched symbols for the daily batch's digest, behind RELAY_KEY
 * The watchlist lives in the script property WATCHLIST: [{s: symbol, d: date starred, p: price, n: NIFTY}].
 * Prices at starring come from Kite when today's login exists; otherwise they are filled in the next
 * time the watchlist is opened with a Kite login.
 */
const WATCH_MAX = 60;
const WATCH_KEYS = ['market_value_bucket', 'pe', 'roe', 'net_margin', 'rev_yoy', 'profit_yoy', 'ret_12m',
                    'profit_consistency_8q', 'promoter_holding', 'fii_holding', 'dii_holding', 'pledge_pct'];

function appStock_(token, symbol, range) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const out = { symbol: sym, chart: chartData_(sym, range || '5Y'), docs: docsData_(sym) };
  out.starred = watchList_().some(w => w.s === sym);
  return out;
}

function watchList_() {
  try { return JSON.parse(PropertiesService.getScriptProperties().getProperty('WATCHLIST') || '[]'); } catch (e) { return []; }
}

function watchSave_(list) {
  PropertiesService.getScriptProperties().setProperty('WATCHLIST', JSON.stringify(list.slice(0, WATCH_MAX)));
}

// Latest prices for NSE symbols and NIFTY from Kite, or {} without today's login.
function kiteLtp_(syms) {
  const headers = kiteHeaders_();
  if (!headers || !syms.length) return {};
  const qs = syms.map(s => 'i=' + encodeURIComponent('NSE:' + s)).concat(['i=' + encodeURIComponent('NSE:NIFTY 50')]).join('&');
  try {
    const body = JSON.parse(UrlFetchApp.fetch('https://api.kite.trade/quote/ltp?' + qs, { muteHttpExceptions: true, headers: headers }).getContentText());
    const out = {};
    Object.keys(body.data || {}).forEach(k => { out[k === 'NSE:NIFTY 50' ? '__NIFTY' : k.replace(/^NSE:/, '')] = body.data[k].last_price; });
    return out;
  } catch (e) { return {}; }
}

function adminWatchToggle(token, symbol) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const list = watchList_();
  const i = list.findIndex(w => w.s === sym);
  if (i >= 0) { list.splice(i, 1); watchSave_(list); return { ok: true, starred: false }; }
  if (list.length >= WATCH_MAX) return { error: 'The watchlist holds up to ' + WATCH_MAX + ' companies.' };
  const px = kiteLtp_([sym]);
  list.unshift({ s: sym, d: todayIst_(), p: px[sym] || null, n: px.__NIFTY || null });
  watchSave_(list);
  return { ok: true, starred: true };
}

function adminWatch(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const list = watchList_();
  if (!list.length) return { items: [] };
  const px = kiteLtp_(list.map(w => w.s));
  let changed = false;
  list.forEach(w => { if (w.p == null && px[w.s]) { w.p = px[w.s]; w.n = px.__NIFTY || w.n; changed = true; } });
  if (changed) watchSave_(list);
  // Key figures from the dashboard's compact library copy.
  const lib = {}, names = {};
  try {
    const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
    const d = JSON.parse(privateRaw_(readToken, 'library_compact.json').getContentText());
    const want = {}; list.forEach(w => { want[w.s] = 1; });
    const idx = {}; (d.pids || []).forEach((k, i) => { idx[k] = i; });
    (d.stocks || []).forEach(s => {
      if (!want[s.symbol] || !s.v) return;
      const o = {}; WATCH_KEYS.forEach(k => { if (idx[k] != null && s.s[idx[k]] !== 'x') o[k] = s.v[idx[k]]; });
      lib[s.symbol] = o;
    });
    Object.keys(want).forEach(k => { if (d.names && d.names[k]) names[k] = d.names[k]; });
  } catch (e) { /* figures are optional */ }
  return { live: !!px.__NIFTY, items: list.map(w => {
    const now = px[w.s] || null, nNow = px.__NIFTY || null;
    const ret = now && w.p ? (now / w.p - 1) * 100 : null, nRet = nNow && w.n ? (nNow / w.n - 1) * 100 : null;
    return { symbol: w.s, name: names[w.s] || '', starred_on: w.d, price: now, ret: ret, nifty: nRet,
             excess: ret != null && nRet != null ? ret - nRet : null, figures: lib[w.s] || {} };
  }) };
}

function watchlistForBatch_(key) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  return { symbols: watchList_().map(w => w.s) };
}
