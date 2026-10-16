/**
 * Paper-trade journal (16 Oct 2026, owner: "build all of them"; the "watch, not participate" stage). An idea or a
 * trade is logged at the live Kite price (or a price typed in when there is no login), marked to market while open,
 * and an index option still open after its expiry settles itself at the index close (the recorder's day file in the
 * private repo, else the live index level after the close). Kept in the relay's own script properties (no Drive
 * permission needed: the first version used a Drive file and the relay is not allowed to create one); no order ever
 * reaches Kite.
 */
const PAPER_LOT = { NIFTY: 65, BANKNIFTY: 30, SENSEX: 20 };
const PAPER_MAX = 400;
const PAPER_CHUNK = 8000;                                   // a property holds at most 9 KB: the list is split into parts

function paperLoad_() {
  const all = PropertiesService.getScriptProperties().getProperties(), n = Number(all.PAPER_N) || 0;
  let body = '';
  for (let i = 0; i < n; i++) body += all['PAPER_' + i] || '';
  try { const v = JSON.parse(body || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}

function paperSave_(list) {
  const lock = LockService.getScriptLock(); lock.waitLock(10000);
  try {
    const props = PropertiesService.getScriptProperties(), old = Number(props.getProperty('PAPER_N')) || 0;
    const keep = list.slice(-PAPER_MAX).map(t => { const c = Object.assign({}, t); delete c.ltp; delete c.pnl; return c; });
    const body = JSON.stringify(keep), parts = {};
    let n = 0;
    for (let i = 0; i < body.length; i += PAPER_CHUNK) parts['PAPER_' + (n++)] = body.slice(i, i + PAPER_CHUNK);
    parts.PAPER_N = String(n);
    props.setProperties(parts);
    for (let i = n; i < old; i++) props.deleteProperty('PAPER_' + i);
  } finally { lock.releaseLock(); }
}

// The Kite instrument for a trade: NSE:SYMBOL for a stock, NFO:/BFO: tradingsymbol for an index option (today's or the
// next expiry, from the meter's contract lists).
function paperInstrument_(t) {
  if (t.kind === 'stock') return 'NSE:' + t.sym;
  const ix = EXP_IDX.find(i => i.id === t.idx);
  if (!ix) return null;
  const C = paperContracts_(ix.id);                         // the next four expiries; else the meter's today/next lists
  let pool = C && C.c[t.expiry] ? C.c[t.expiry] : null;
  if (!pool) {
    const lists = expiryLists_(todayIst_()), L = lists[ix.id] || {};
    pool = t.expiry === todayIst_() ? (L.today || []) : (L.next === t.expiry ? (L.nextList || []) : []);
  }
  const hit = pool.find(o => o[1] === Number(t.strike) && o[2] === t.type);
  return hit ? ix.exch + ':' + hit[0] : null;
}

function paperLtp_(keys) {
  keys = keys.filter(Boolean);
  const headers = kiteHeaders_();
  if (!keys.length || !headers) return {};
  try {
    const qs = keys.map(k => 'i=' + encodeURIComponent(k)).join('&');
    const body = JSON.parse(UrlFetchApp.fetch('https://api.kite.trade/quote/ltp?' + qs, { muteHttpExceptions: true, headers: headers }).getContentText());
    const out = {};
    Object.keys(body.data || {}).forEach(k => out[k] = body.data[k].last_price);
    return out;
  } catch (e) { return {}; }
}

// Index close on an expiry day: the recorder's day file (private repo, written after 15:46), else today's live level
// once the market has closed.
function paperIndexClose_(idx, day) {
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (readToken) {
    try {
      const res = UrlFetchApp.fetch('https://api.github.com/repos/' + ADMIN_REPO + '/contents/state/expiry/' + day + '_' + idx + '.json',
        { muteHttpExceptions: true, headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
      if (res.getResponseCode() === 200) { const c = JSON.parse(res.getContentText()).close; if (c) return c; }
    } catch (e) {}
  }
  const now = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm');
  if (day === todayIst_() && now >= '15:40') { const q = quoteData_(); const x = q.indices && q.indices[idx]; if (x) return x.last; }
  return null;
}

function paperView_() {
  const list = paperLoad_(), today = todayIst_(), now = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm');
  let changed = false;
  list.forEach(t => {                                       // expired index options settle themselves
    if (t.status !== 'open' || t.kind !== 'option') return;
    if (t.expiry < today || (t.expiry === today && now >= '15:40')) {
      const close = paperIndexClose_(t.idx, t.expiry);
      if (close == null) return;
      t.exit = Math.max(0, t.type === 'CE' ? close - t.strike : t.strike - close);
      t.exitAt = Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm"); t.exitHow = 'settled at ' + close;
      t.status = 'closed'; changed = true;
    }
  });
  if (changed) paperSave_(list);
  const open = list.filter(t => t.status === 'open');
  const keys = {}; open.forEach(t => { const k = paperInstrument_(t); if (k) keys[t.id] = k; });
  const ltp = paperLtp_(Object.values(keys));
  list.forEach(t => {
    const sign = t.side === 'sell' ? -1 : 1;
    if (t.status === 'open') { t.ltp = keys[t.id] ? ltp[keys[t.id]] : null; t.pnl = t.ltp == null ? null : sign * (t.ltp - t.entry) * t.qty; }
    else t.pnl = sign * (t.exit - t.entry) * t.qty;
  });
  return { trades: list.slice().reverse(), lots: PAPER_LOT, kite: !!kiteHeaders_() };
}

function paperAdd_(t) {
  if (!t || (t.kind !== 'stock' && t.kind !== 'option')) return { error: 'Choose a stock or an index option.' };
  const clean = { id: Utilities.getUuid().slice(0, 8), created: Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm"),
                  kind: t.kind, side: t.side === 'sell' ? 'sell' : 'buy', note: String(t.note || '').slice(0, 140), status: 'open' };
  if (t.kind === 'stock') {
    clean.sym = String(t.sym || '').toUpperCase().replace(/[^A-Z0-9&_-]/g, '').slice(0, 20);
    if (!clean.sym) return { error: 'Enter a symbol.' };
    clean.qty = Math.max(1, Math.round(Number(t.qty) || 1));
  } else {
    if (!PAPER_LOT[t.idx]) return { error: 'Choose NIFTY, BANKNIFTY or SENSEX.' };
    clean.idx = t.idx; clean.expiry = String(t.expiry || '').slice(0, 10); clean.strike = Number(t.strike); clean.type = t.type === 'PE' ? 'PE' : 'CE';
    clean.lots = Math.max(1, Math.round(Number(t.lots) || 1)); clean.qty = clean.lots * PAPER_LOT[t.idx];
    if (!/^\d{4}-\d{2}-\d{2}$/.test(clean.expiry) || !(clean.strike > 0)) return { error: 'Choose an expiry and a strike.' };
  }
  const key = paperInstrument_(clean);
  const live = key ? paperLtp_([key])[key] : null;
  clean.entry = Number(t.price) > 0 ? Number(t.price) : live;
  clean.entryHow = Number(t.price) > 0 ? 'typed' : 'live';
  if (clean.entry == null || !(clean.entry >= 0)) return { error: key ? 'No live price (log in to Kite) — type the price instead.' : 'Contract not found for that expiry and strike.' };
  const list = paperLoad_(); list.push(clean); paperSave_(list);
  return paperView_();
}

function paperClose_(id, price) {
  const list = paperLoad_(), t = list.find(x => x.id === id);
  if (!t || t.status !== 'open') return { error: 'Trade not open.' };
  const key = paperInstrument_(t), live = key ? paperLtp_([key])[key] : null;
  t.exit = Number(price) > 0 ? Number(price) : live;
  if (t.exit == null) return { error: 'No live price — type the exit price.' };
  t.exitAt = Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm"); t.exitHow = Number(price) > 0 ? 'typed' : 'live'; t.status = 'closed';
  paperSave_(list);
  return paperView_();
}

function paperDelete_(id) { paperSave_(paperLoad_().filter(x => x.id !== id)); return paperView_(); }

function adminPaper(token) { return sessionValid_(token) ? paperView_() : { error: 'session_expired' }; }
function adminPaperAdd(token, t) { return sessionValid_(token) ? paperAdd_(t) : { error: 'session_expired' }; }
function adminPaperClose(token, id, price) { return sessionValid_(token) ? paperClose_(id, price) : { error: 'session_expired' }; }
function adminPaperDelete(token, id) { return sessionValid_(token) ? paperDelete_(id) : { error: 'session_expired' }; }

// ---- Contract lists and live prices for the trade form (16 Oct 2026, owner: "paper trade needs to give the drop down
// list and latest traded value") ----
// The next four expiries of an index with their strikes, from Kite's public contract file (cached for the day; one key
// per index keeps each under the cache's size limit).
const PAPER_EXPIRIES = 4;
function paperContracts_(idx) {
  const ix = EXP_IDX.find(i => i.id === idx);
  if (!ix) return null;
  const today = todayIst_(), cache = CacheService.getScriptCache(), key = 'ppc1_' + idx + '_' + today;
  const hit = cache.get(key);
  if (hit) return paperUnpackC_(JSON.parse(hit));
  let text = '';
  try {
    const res = UrlFetchApp.fetch('https://api.kite.trade/instruments/' + ix.exch, { muteHttpExceptions: true, headers: kiteHeaders_() || {} });
    const blob = res.getBlob(), bytes = blob.getBytes();
    text = (bytes.length > 1 && (bytes[0] & 255) === 0x1f && (bytes[1] & 255) === 0x8b)
      ? Utilities.ungzip(blob.setContentType('application/x-gzip')).getDataAsString() : res.getContentText();
  } catch (e) { return null; }
  const lines = text.split('\n'), head = (lines[0] || '').split(',');
  const iSym = head.indexOf('tradingsymbol'), iName = head.indexOf('name'), iExp = head.indexOf('expiry'), iStrike = head.indexOf('strike'), iType = head.indexOf('instrument_type');
  if (iSym < 0 || iExp < 0) return null;
  const out = {};                                          // every index on this exchange, so one download serves them all
  EXP_IDX.filter(i => i.exch === ix.exch).forEach(i => out[i.id] = {});
  for (let n = 1; n < lines.length; n++) {
    const c = lines[n].split(','), id = (c[iName] || '').replace(/"/g, '');
    if (!out[id] || (c[iType] !== 'CE' && c[iType] !== 'PE') || !(c[iExp] >= today)) continue;
    (out[id][c[iExp]] = out[id][c[iExp]] || []).push([c[iSym], Number(c[iStrike]), c[iType]]);
  }
  let mine = null;
  Object.keys(out).forEach(id => {
    const exps = Object.keys(out[id]).sort().slice(0, PAPER_EXPIRIES), v = { exps: exps, c: {} };
    exps.forEach(e => v.c[e] = out[id][e]);
    try { cache.put('ppc1_' + id + '_' + today, JSON.stringify(paperPackC_(v)), 6 * 3600); } catch (e) {}
    if (id === idx) mine = v;
  });
  return mine;
}

// Cache form: per expiry the shared name prefix plus [strike, type] (NIFTY24O2123150CE = prefix + 23150 + CE); a list
// whose names do not follow that pattern is kept whole.
function paperPackC_(v) {
  const c = {};
  v.exps.forEach(e => {
    const rows = v.c[e], s0 = rows.length ? rows[0] : null, p = s0 ? s0[0].slice(0, s0[0].length - String(s0[1]).length - 2) : '';
    c[e] = rows.every(r => r[0] === p + r[1] + r[2]) ? { p: p, r: rows.map(r => [r[1], r[2]]) } : rows;
  });
  return { exps: v.exps, c: c };
}
function paperUnpackC_(v) {
  const c = {};
  v.exps.forEach(e => { const x = v.c[e]; c[e] = Array.isArray(x) ? x : x.r.map(r => [x.p + r[0] + r[1], r[0], r[1]]); });
  return { exps: v.exps, c: c };
}

// "Live · 14:58 IST" in market hours, otherwise "Last traded · Fri 16 Oct 2026 · 19:40 IST".
function paperAt_() {
  const d = new Date(), hm = Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm'), wd = Number(Utilities.formatDate(d, 'Asia/Kolkata', 'u'));
  return (wd <= 5 && hm >= '09:15' && hm <= '15:30') ? 'Live · ' + hm + ' IST'
    : 'Last traded · as of ' + Utilities.formatDate(d, 'Asia/Kolkata', 'EEE d MMM yyyy') + ' · ' + hm + ' IST';
}

// Strikes around the index level for one expiry, each with the latest Call and Put price.
function paperChain_(idx, expiry) {
  const ix = EXP_IDX.find(i => i.id === idx), C = paperContracts_(idx);
  if (!ix || !C || !C.exps.length) return { error: 'Contract list not available right now.' };
  const exp = C.exps.indexOf(expiry) >= 0 ? expiry : C.exps[0], rows = C.c[exp] || [];
  const spotQ = paperLtp_([ix.spot]), spot = spotQ[ix.spot] || null;
  const all = [...new Set(rows.map(r => r[1]))].sort((a, b) => a - b);
  let atm = all.length ? all[Math.floor(all.length / 2)] : null;
  if (spot) atm = all.reduce((b, k) => Math.abs(k - spot) < Math.abs(b - spot) ? k : b, all[0]);
  const at = all.indexOf(atm), pick = all.slice(Math.max(0, at - 15), at + 16);
  const sym = {}; rows.forEach(r => { if (pick.indexOf(r[1]) >= 0) sym[r[1] + r[2]] = ix.exch + ':' + r[0]; });
  const ltp = paperLtp_(Object.values(sym));
  return { idx: idx, expiries: C.exps, expiry: exp, spot: spot, atm: atm, lot: PAPER_LOT[idx],
           strikes: pick.map(k => [k, sym[k + 'CE'] ? (ltp[sym[k + 'CE']] ?? null) : null, sym[k + 'PE'] ? (ltp[sym[k + 'PE']] ?? null) : null]),
           at: paperAt_(), kite: !!kiteHeaders_() };
}

function paperQuote_(sym) {
  sym = String(sym || '').toUpperCase().replace(/[^A-Z0-9&_-]/g, '').slice(0, 20);
  if (!sym) return { error: 'Enter a symbol.' };
  const k = 'NSE:' + sym, q = paperLtp_([k]);
  return { sym: sym, ltp: q[k] ?? null, at: paperAt_(), kite: !!kiteHeaders_() };
}

function adminPaperChain(token, idx, expiry) { return sessionValid_(token) ? paperChain_(idx, expiry) : { error: 'session_expired' }; }
function adminPaperQuote(token, sym) { return sessionValid_(token) ? paperQuote_(sym) : { error: 'session_expired' }; }
