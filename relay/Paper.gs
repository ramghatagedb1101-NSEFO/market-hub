/**
 * Paper-trade journal (16 Oct 2026, owner: "build all of them"; the "watch, not participate" stage). An idea or a
 * trade is logged at the live Kite price (or a price typed in when there is no login), marked to market while open,
 * and an index option still open after its expiry settles itself at the index close (the recorder's day file in the
 * private repo, else the live index level after the close). Kept in one Drive file; no order ever reaches Kite.
 */
const PAPER_FILE = 'market_hub_paper_trades.json';
const PAPER_LOT = { NIFTY: 65, BANKNIFTY: 30, SENSEX: 20 };
const PAPER_MAX = 400;

function paperLoad_() {
  const f = DriveApp.getFilesByName(PAPER_FILE);
  if (!f.hasNext()) return [];
  try { const v = JSON.parse(f.next().getBlob().getDataAsString()); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}

function paperSave_(list) {
  const body = JSON.stringify(list.slice(-PAPER_MAX));
  const f = DriveApp.getFilesByName(PAPER_FILE);
  if (f.hasNext()) f.next().setContent(body); else DriveApp.createFile(PAPER_FILE, body, MimeType.PLAIN_TEXT);
}

// The Kite instrument for a trade: NSE:SYMBOL for a stock, NFO:/BFO: tradingsymbol for an index option (today's or the
// next expiry, from the meter's contract lists).
function paperInstrument_(t) {
  if (t.kind === 'stock') return 'NSE:' + t.sym;
  const ix = EXP_IDX.find(i => i.id === t.idx);
  if (!ix) return null;
  const lists = expiryLists_(todayIst_()), L = lists[ix.id] || {};
  const pool = t.expiry === todayIst_() ? (L.today || []) : (L.next === t.expiry ? (L.nextList || []) : []);
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
