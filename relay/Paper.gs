/**
 * Paper trading (16 Oct 2026; v2 17 Oct 2026, design review section 7, owner: "more realistic to show that i am
 * actually trading"). A virtual account at live Kite prices, with real charges and margin; no order ever reaches Kite.
 *  - Account: starting capital (₹10,00,000 unless set), cash, margin blocked, booked and open P&L, all derived from fills.
 *  - Orders: market (fills now at the live price), limit, stop-loss (SL) and SL-M (wait; checked when the page opens and
 *    every 5 minutes in market hours by the live job, mode=paper_check). Day orders: cancelled at the session's close.
 *  - Trailing stop-loss (21 Oct 2026, owner: "yes add it"; Kite has none): exits an open position. It keeps the best price
 *    seen at the checks and its stop a fixed distance (points or %) behind, moving only in the position's favour; exits at
 *    the live price when the stop is hit. Stays working until filled, cancelled, the position is gone or the option expires.
 *  - Charges on every fill: Kite's own figures (order-margin call) when logged in, else Zerodha's published rates
 *    (PAPER_RATES, checked on zerodha.com/charges on Sat 17 Oct 2026).
 *  - Margin: selling an option blocks Kite's margin figure; refused when cash is short or Kite cannot be asked.
 *  - Index options still open after expiry settle at the index close (in-the-money buyers pay STT on the intrinsic value).
 *  - Typed prices and deleting a trade stay (owner's choice). Old trades keep working; the phone reads the same list.
 * Kept in the relay's own script properties (no Drive permission): trades PAPER_*, orders PORD_*, account PAPER_ACCT.
 */
const PAPER_LOT = { NIFTY: 65, BANKNIFTY: 30, SENSEX: 20 };
const PAPER_MAX = 400, PAPER_ORD_MAX = 200;
const PAPER_CHUNK = 8000;                                   // a property holds at most 9 KB: a list is split into parts
const PAPER_CAPITAL = 1000000;
// Zerodha's charges, as published on zerodha.com/charges (checked Sat 17 Oct 2026). Fractions of turnover.
const PAPER_RATES = {
  asof: '17 Oct 2026',
  option: { brokerage: 20, stt_sell: 0.0015, stt_exercise: 0.0015, txn: { NSE: 0.0003553, BSE: 0.000325 }, stamp_buy: 0.00003 },
  delivery: { brokerage: 0, stt: 0.001, txn: { NSE: 0.0000307, BSE: 0.0000375 }, stamp_buy: 0.00015, dp_sell: 15.34 },
  intraday: { brokerage_pct: 0.0003, brokerage_max: 20, stt_sell: 0.00025, txn: { NSE: 0.0000307, BSE: 0.0000375 }, stamp_buy: 0.00003 },
  sebi: 0.000001, gst: 0.18
};

function paperStoreLoad_(prefix) {
  const all = PropertiesService.getScriptProperties().getProperties(), n = Number(all[prefix + 'N']) || 0;
  let body = '';
  for (let i = 0; i < n; i++) body += all[prefix + i] || '';
  try { const v = JSON.parse(body || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; }
}
function paperStoreSave_(prefix, list, max, clean) {
  const lock = LockService.getScriptLock(); lock.waitLock(10000);
  try {
    const props = PropertiesService.getScriptProperties(), old = Number(props.getProperty(prefix + 'N')) || 0;
    const body = JSON.stringify(list.slice(-max).map(clean || (x => x))), parts = {};
    let n = 0;
    for (let i = 0; i < body.length; i += PAPER_CHUNK) parts[prefix + (n++)] = body.slice(i, i + PAPER_CHUNK);
    parts[prefix + 'N'] = String(n);
    props.setProperties(parts);
    for (let i = n; i < old; i++) props.deleteProperty(prefix + i);
  } finally { lock.releaseLock(); }
}
function paperLoad_() { return paperStoreLoad_('PAPER_'); }
function paperSave_(list) { paperStoreSave_('PAPER_', list, PAPER_MAX, t => { const c = Object.assign({}, t); delete c.ltp; delete c.pnl; delete c.gross; return c; }); }
function paperOrders_() { return paperStoreLoad_('PORD_'); }
function paperOrdersSave_(list) { paperStoreSave_('PORD_', list, PAPER_ORD_MAX); }
function paperAccount_() {
  let a = {}; try { a = JSON.parse(PropertiesService.getScriptProperties().getProperty('PAPER_ACCT') || '{}'); } catch (e) {}
  return { capital: Number(a.capital) > 0 ? Number(a.capital) : PAPER_CAPITAL, started: a.started || null };
}
function paperNow_() { return Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm"); }

// The Kite instrument for a trade: NSE:SYMBOL for a stock, NFO:/BFO: tradingsymbol for an index option.
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

// Charges for one fill. Kite's order-margin call gives the exact figures (and the margin) when logged in; otherwise the
// published rates. side 'buy'|'sell'; product NRML|MIS|CNC; exercise = in-the-money option settled at expiry.
function paperChargesTable_(t, side, price, qty, exercise) {
  const R = PAPER_RATES, exch = t.kind === 'option' && t.idx === 'SENSEX' ? 'BSE' : 'NSE', turn = price * qty;
  let brokerage = 0, stt = 0, txn = 0, stamp = 0, dp = 0;
  if (t.kind === 'option') {
    if (exercise) { stt = turn * R.option.stt_exercise; }
    else { brokerage = R.option.brokerage; stt = side === 'sell' ? turn * R.option.stt_sell : 0; txn = turn * R.option.txn[exch]; stamp = side === 'buy' ? turn * R.option.stamp_buy : 0; }
  } else if (t.product === 'MIS') {
    brokerage = Math.min(R.intraday.brokerage_max, turn * R.intraday.brokerage_pct); stt = side === 'sell' ? turn * R.intraday.stt_sell : 0;
    txn = turn * R.intraday.txn[exch]; stamp = side === 'buy' ? turn * R.intraday.stamp_buy : 0;
  } else {
    stt = turn * R.delivery.stt; txn = turn * R.delivery.txn[exch]; stamp = side === 'buy' ? turn * R.delivery.stamp_buy : 0; dp = side === 'sell' ? R.delivery.dp_sell : 0;
  }
  const sebi = exercise ? 0 : turn * R.sebi, gst = (brokerage + txn + sebi) * R.gst;
  const r2 = x => Math.round(x * 100) / 100;
  const items = { brokerage: r2(brokerage), stt: r2(stt), exchange: r2(txn), sebi: r2(sebi), gst: r2(gst), stamp: r2(stamp), dp: r2(dp) };
  return { items, total: r2(Object.values(items).reduce((a, b) => a + b, 0)), source: 'rates as of ' + R.asof };
}
function paperKiteMargin_(t, side, price, qty, otype, trigger) {
  const headers = kiteHeaders_(), key = paperInstrument_(t);
  if (!headers || !key) return null;
  const [exchange, tradingsymbol] = key.split(':');
  try {
    const res = UrlFetchApp.fetch('https://api.kite.trade/margins/orders', { method: 'post', contentType: 'application/json', muteHttpExceptions: true, headers: headers,
      payload: JSON.stringify([{ exchange, tradingsymbol, transaction_type: side === 'sell' ? 'SELL' : 'BUY', variety: 'regular', product: t.product || (t.kind === 'option' ? 'NRML' : 'CNC'),
        order_type: otype === 'SL' || otype === 'SL-M' ? otype : 'LIMIT', quantity: qty, price: price, trigger_price: trigger || 0 }]) });
    const d = (JSON.parse(res.getContentText()).data || [])[0];
    if (!d) return null;
    const c = d.charges || {}, r2 = x => Math.round((Number(x) || 0) * 100) / 100;
    const items = { brokerage: r2(c.brokerage), stt: r2(c.transaction_tax), exchange: r2(c.exchange_turnover_charge), sebi: r2(c.sebi_turnover_charge), gst: r2((c.gst || {}).total), stamp: r2(c.stamp_duty), dp: 0 };
    if (t.kind === 'stock' && side === 'sell' && t.product !== 'MIS') items.dp = PAPER_RATES.delivery.dp_sell;
    return { margin: r2(d.total), charges: { items, total: r2(Object.values(items).reduce((a, b) => a + b, 0)), source: 'Kite' } };
  } catch (e) { return null; }
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

function paperCharge_(t) { return (t.charges ? t.charges.total : 0) + (t.exitCharges ? t.exitCharges.total : 0); }
// Cash: capital plus booked P&L, less what open positions tie up (long cost, short margin) and their entry charges.
function paperMoney_(list) {
  const A = paperAccount_();
  let booked = 0, tied = 0, openCh = 0, chargesPaid = 0;
  list.forEach(t => {
    chargesPaid += paperCharge_(t);
    if (t.status === 'closed') booked += (t.side === 'sell' ? -1 : 1) * (t.exit - t.entry) * t.qty - paperCharge_(t);
    else { tied += t.side === 'sell' ? (t.margin || 0) : t.entry * t.qty; openCh += t.charges ? t.charges.total : 0; }
  });
  return { capital: A.capital, started: A.started, booked: Math.round(booked), tied: Math.round(tied), cash: Math.round(A.capital + booked - tied - openCh), charges: Math.round(chargesPaid) };
}

function paperOppositeQty_(list, o) {
  return list.filter(x => x.status === 'open' && x.kind === o.kind && x.side !== o.side && (o.kind === 'stock' ? x.sym === o.sym : x.idx === o.idx && x.expiry === o.expiry && Number(x.strike) === Number(o.strike) && x.type === o.type)).reduce((a, x) => a + x.qty, 0);
}
function paperTrailAt_(o, p) { return o.trail_unit === '%' ? p * o.trail / 100 : o.trail; }
function paperMarketHours_() {
  const d = new Date(), wd = Number(Utilities.formatDate(d, 'Asia/Kolkata', 'u')), hm = Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm');
  return wd <= 5 && hm >= '09:15' && hm <= '15:30';
}
// A day order lives until the close of the session it was placed for (placed after the close or at a weekend: the next).
function paperValidTill_(created) {
  const d = new Date(created + ':00+05:30');
  const hm = created.slice(11, 16), day = s => Number(Utilities.formatDate(s, 'Asia/Kolkata', 'u'));
  let x = d; if (hm > '15:30' || day(x) > 5) { do { x = new Date(x.getTime() + 86400000); } while (day(x) > 5); }
  return Utilities.formatDate(x, 'Asia/Kolkata', 'yyyy-MM-dd');
}

// Fill one order at a price: becomes a trade (or closes open trades on the other side of the same contract).
function paperFill_(o, price, list, how) {
  const at = paperNow_(), qty = o.qty;
  const k = paperKiteMargin_(o, o.side, price, qty, 'LIMIT');
  const ch = k ? k.charges : paperChargesTable_(o, o.side, price, qty);
  o.status = 'filled'; o.filled_at = at; o.fill_price = price; o.charges = ch;
  // Exit first: open trades on the other side of the same contract, oldest first.
  const same = t => t.status === 'open' && t.kind === o.kind && t.side !== o.side && (o.kind === 'stock' ? t.sym === o.sym : t.idx === o.idx && t.expiry === o.expiry && Number(t.strike) === Number(o.strike) && t.type === o.type);
  let left = qty;
  list.filter(same).sort((a, b) => a.created < b.created ? -1 : 1).forEach(t => {
    if (left <= 0) return;
    const part = Math.min(left, t.qty);
    if (part < t.qty) {                                     // partial exit: split the trade, close the exited part
      const rest = Object.assign({}, t, { id: Utilities.getUuid().slice(0, 8), qty: t.qty - part, lots: t.lots ? (t.qty - part) / (PAPER_LOT[t.idx] || 1) : undefined,
        charges: t.charges ? Object.assign({}, t.charges, { total: Math.round(t.charges.total * (t.qty - part) / t.qty * 100) / 100 }) : undefined,
        margin: t.margin ? Math.round(t.margin * (t.qty - part) / t.qty) : undefined });
      if (t.charges) t.charges = Object.assign({}, t.charges, { total: Math.round(t.charges.total * part / t.qty * 100) / 100 });
      if (t.margin) t.margin = Math.round(t.margin * part / t.qty);
      t.qty = part; if (t.lots) t.lots = part / (PAPER_LOT[t.idx] || 1); list.push(rest);
    }
    t.exit = price; t.exitAt = at; t.exitHow = how; t.status = 'closed'; t.exitOrder = o.id;
    t.exitCharges = { items: ch.items, total: Math.round(ch.total * part / qty * 100) / 100, source: ch.source };
    left -= part;
  });
  if (left > 0) {
    const t = { id: Utilities.getUuid().slice(0, 8), created: at, kind: o.kind, side: o.side, note: o.note || '', status: 'open', product: o.product, order: o.id,
                entry: price, entryHow: how, qty: left, charges: { items: ch.items, total: Math.round(ch.total * left / qty * 100) / 100, source: ch.source } };
    if (o.kind === 'stock') t.sym = o.sym; else { t.idx = o.idx; t.expiry = o.expiry; t.strike = Number(o.strike); t.type = o.type; t.lots = left / PAPER_LOT[o.idx]; }
    if (o.side === 'sell') t.margin = o.margin || (k ? k.margin : 0);
    list.push(t);
  }
}

// Expired options settle; day orders past their session are cancelled; working orders whose price is reached fill.
function paperHousekeep_(list, orders) {
  const today = todayIst_(), now = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm');
  let changed = false, ochanged = false;
  list.forEach(t => {
    if (t.status !== 'open' || t.kind !== 'option') return;
    if (t.expiry < today || (t.expiry === today && now >= '15:40')) {
      const close = paperIndexClose_(t.idx, t.expiry);
      if (close == null) return;
      t.exit = Math.max(0, t.type === 'CE' ? close - t.strike : t.strike - close);
      t.exitAt = paperNow_(); t.exitHow = 'settled at ' + close; t.status = 'closed'; changed = true;
      t.exitCharges = t.side === 'buy' && t.exit > 0 ? paperChargesTable_(t, 'sell', t.exit, t.qty, true) : { items: {}, total: 0, source: 'expiry' };
    }
  });
  const work = orders.filter(o => o.status === 'working');
  work.forEach(o => { if (today > o.valid_till || (today === o.valid_till && now > '15:30')) { o.status = 'cancelled'; o.reason = 'end of day'; ochanged = true; } });
  const live = orders.filter(o => o.status === 'working');
  if (live.length && paperMarketHours_()) {
    const keys = {}; live.forEach(o => { const k = paperInstrument_(o); if (k) keys[o.id] = k; });
    const ltp = paperLtp_(Object.values(keys));
    live.forEach(o => {
      const p = keys[o.id] ? ltp[keys[o.id]] : null; if (p == null) return;
      const buy = o.side === 'buy';
      if (o.otype === 'TSL') {
        const open = paperOppositeQty_(list, o);
        if (!open) { o.status = 'cancelled'; o.reason = 'position closed'; ochanged = true; return; }
        // A sell stop trails the highest price seen; a buy stop (protecting a short) trails the lowest.
        if (buy ? p < o.best : p > o.best) { o.best = p; o.trigger = Math.round((buy ? p + paperTrailAt_(o, p) : p - paperTrailAt_(o, p)) * 100) / 100; ochanged = true; }
        if (buy ? p >= o.trigger : p <= o.trigger) { o.qty = Math.min(o.qty, open); if (o.lots) o.lots = o.qty / (PAPER_LOT[o.idx] || 1); paperFill_(o, p, list, 'trailing stop at ' + o.trigger + ' (best ' + o.best + ')'); changed = ochanged = true; }
      } else if (o.otype === 'SL' || o.otype === 'SL-M') {
        if (!o.triggered && (buy ? p >= o.trigger : p <= o.trigger)) { o.triggered = paperNow_(); ochanged = true; }
        if (!o.triggered) return;
        if (o.otype === 'SL-M' || (buy ? p <= o.price : p >= o.price)) { paperFill_(o, p, list, 'stop at ' + o.trigger); changed = ochanged = true; }
      } else if (o.otype === 'LIMIT' && (buy ? p <= o.price : p >= o.price)) { paperFill_(o, p, list, 'limit ' + o.price); changed = ochanged = true; }
    });
  }
  return { changed, ochanged };
}

function paperView_() {
  const list = paperLoad_(), orders = paperOrders_();
  const h = paperHousekeep_(list, orders);
  if (h.changed) paperSave_(list);
  if (h.ochanged) paperOrdersSave_(orders);
  const open = list.filter(t => t.status === 'open');
  const keys = {}; open.forEach(t => { const k = paperInstrument_(t); if (k) keys[t.id] = k; });
  const wk = {}; orders.filter(o => o.status === 'working').forEach(o => { const k = paperInstrument_(o); if (k) wk[o.id] = k; });
  const ltp = paperLtp_([...new Set(Object.values(keys).concat(Object.values(wk)))]);
  let openPnl = 0, dayStart = 0;
  list.forEach(t => {
    const sign = t.side === 'sell' ? -1 : 1;
    if (t.status === 'open') { t.ltp = keys[t.id] ? (ltp[keys[t.id]] ?? null) : null; t.gross = t.ltp == null ? null : sign * (t.ltp - t.entry) * t.qty; t.pnl = t.gross == null ? null : t.gross - paperCharge_(t); if (t.pnl != null) openPnl += t.pnl; }
    else { t.gross = sign * (t.exit - t.entry) * t.qty; t.pnl = t.gross - paperCharge_(t); }
  });
  orders.forEach(o => { if (o.status === 'working') o.ltp = wk[o.id] ? (ltp[wk[o.id]] ?? null) : null; });
  const M = paperMoney_(list);
  return { trades: list.slice().reverse(), orders: orders.slice().reverse(), lots: PAPER_LOT, kite: !!kiteHeaders_(), at: paperAt_(),
           account: Object.assign(M, { open_pnl: Math.round(openPnl), value: Math.round(M.capital + M.booked + openPnl) }), rates: PAPER_RATES.asof };
}

// Clean an order request from the page (or the phone's older add form).
function paperOrderOf_(t) {
  if (!t || (t.kind !== 'stock' && t.kind !== 'option')) return { error: 'Choose a stock or an index option.' };
  const o = { id: Utilities.getUuid().slice(0, 8), created: paperNow_(), kind: t.kind, side: t.side === 'sell' ? 'sell' : 'buy', note: String(t.note || '').slice(0, 140),
              otype: ['LIMIT', 'SL', 'SL-M', 'TSL'].includes(t.otype) ? t.otype : 'MARKET' };
  if (t.kind === 'stock') {
    o.sym = String(t.sym || '').toUpperCase().replace(/[^A-Z0-9&_-]/g, '').slice(0, 20);
    if (!o.sym) return { error: 'Enter a symbol.' };
    o.qty = Math.max(1, Math.round(Number(t.qty) || 1)); o.product = t.product === 'MIS' ? 'MIS' : 'CNC';
  } else {
    if (!PAPER_LOT[t.idx]) return { error: 'Choose NIFTY, BANKNIFTY or SENSEX.' };
    o.idx = t.idx; o.expiry = String(t.expiry || '').slice(0, 10); o.strike = Number(t.strike); o.type = t.type === 'PE' ? 'PE' : 'CE';
    o.lots = Math.max(1, Math.round(Number(t.lots) || 1)); o.qty = o.lots * PAPER_LOT[t.idx]; o.product = t.product === 'MIS' ? 'MIS' : 'NRML';
    if (!/^\d{4}-\d{2}-\d{2}$/.test(o.expiry) || !(o.strike > 0)) return { error: 'Choose an expiry and a strike.' };
  }
  o.price = Number(t.price) > 0 ? Number(t.price) : null;
  o.trigger = Number(t.trigger) > 0 ? Number(t.trigger) : null;
  if (o.otype === 'LIMIT' && !o.price) return { error: 'Enter the limit price.' };
  if ((o.otype === 'SL' || o.otype === 'SL-M') && !o.trigger) return { error: 'Enter the trigger price.' };
  if (o.otype === 'SL' && !o.price) return { error: 'Enter the limit price for the stop-loss.' };
  if (o.otype === 'TSL') {
    o.trail_unit = t.trail_unit === '%' ? '%' : 'pts'; o.trail = Number(t.trail); o.price = null;
    if (!(o.trail > 0) || (o.trail_unit === '%' && o.trail >= 50)) return { error: o.trail_unit === '%' ? 'Enter a trail between 0 and 50%.' : 'Enter the trail in points.' };
  }
  return o;
}

// What the order would cost: price, value, charges, margin, cash after; and whether it can go through.
function paperPreview_(t) {
  const o = paperOrderOf_(t); if (o.error) return o;
  const key = paperInstrument_(o);
  if (!key) return { error: 'Contract not found for that expiry and strike.' };
  const ltp = paperLtp_([key])[key] ?? null;
  let stop = null;
  if (o.otype === 'TSL') {
    if (ltp == null) return { error: 'No live price: a trailing stop needs the Kite login.' };
    stop = Math.round((o.side === 'buy' ? ltp + paperTrailAt_(o, ltp) : ltp - paperTrailAt_(o, ltp)) * 100) / 100;
    if (stop <= 0) return { error: 'The trail is larger than the price.' };
  }
  const price = o.otype === 'MARKET' ? (o.price || ltp) : o.otype === 'TSL' ? stop : (o.otype === 'SL-M' ? o.trigger : o.price);
  if (price == null) return { error: 'No live price (log in to Kite), or type a price.' };
  const list = paperLoad_(), M = paperMoney_(list);
  if (o.otype === 'TSL' && !paperOppositeQty_(list, o)) return { error: 'A trailing stop exits an open position: ' + (o.side === 'sell' ? 'buy' : 'sell') + ' first, or use Trail on the position.' };
  const opposite = list.filter(x => x.status === 'open' && x.kind === o.kind && x.side !== o.side && (o.kind === 'stock' ? x.sym === o.sym : x.idx === o.idx && x.expiry === o.expiry && Number(x.strike) === Number(o.strike) && x.type === o.type)).reduce((a, x) => a + x.qty, 0);
  const exiting = Math.min(opposite, o.qty), fresh = o.qty - exiting;
  const k = paperKiteMargin_(o, o.side, price, o.qty, o.otype, o.trigger);
  const charges = k ? k.charges : paperChargesTable_(o, o.side, price, o.qty);
  let need = 0, msg = '', ok = true;
  if (fresh > 0) {
    if (o.side === 'buy') need = price * fresh;
    else if (o.kind === 'option' || o.product === 'MIS') {
      if (!k) { ok = false; msg = 'Log in to Kite to sell: the margin cannot be checked.'; }
      else need = Math.round(k.margin * fresh / o.qty);
    } else { ok = false; msg = 'You do not hold ' + o.sym + ': a delivery sell needs the shares.'; }
  }
  const after = M.cash - need - charges.total + (exiting ? 0 : 0);
  if (ok && after < 0) { ok = false; msg = 'Not enough cash: short by ₹' + Math.round(-after).toLocaleString('en-IN') + '.'; }
  if (ok) msg = exiting ? (fresh ? 'Exits ' + exiting + ' and opens ' + fresh + '.' : 'Exits your open position.') : 'Enough cash.';
  if (o.otype === 'TSL' && exiting < o.qty) { o.qty = exiting; }
  return { ok, msg, key, ltp, price, stop, qty: o.otype === 'TSL' ? exiting : o.qty, value: Math.round(price * o.qty * 100) / 100, charges, margin: Math.round(need), cash: M.cash, cash_after: Math.round(after),
           exiting, fills: o.otype === 'MARKET' ? (paperMarketHours_() ? 'Fills now at the live price.' : 'Market closed: fills at the last price.')
             : o.otype === 'TSL' ? 'Starts with the stop at ' + stop + ' and moves it ' + (o.side === 'sell' ? 'up' : 'down') + ' with the price; exits at the live price when hit. Stays until filled or cancelled.'
             : 'Waits until the price is reached; cancelled at the close.', at: paperAt_() };
}

function paperOrder_(t) {
  const pv = paperPreview_(t); if (pv.error) return pv;
  if (!pv.ok) return { error: pv.msg };
  const o = paperOrderOf_(t), list = paperLoad_(), orders = paperOrders_();
  if (o.side === 'sell' && pv.margin) o.margin = pv.margin;
  o.valid_till = paperValidTill_(o.created);
  if (o.otype === 'TSL') { o.best = pv.ltp; o.trigger = pv.stop; o.qty = pv.qty; if (o.lots) o.lots = o.qty / (PAPER_LOT[o.idx] || 1);
    o.valid_till = o.kind === 'option' ? o.expiry : Utilities.formatDate(new Date(Date.now() + 365 * 86400000), 'Asia/Kolkata', 'yyyy-MM-dd'); }
  if (o.otype === 'MARKET') paperFill_(o, pv.price, list, o.price ? 'typed' : 'live');
  else o.status = 'working';
  orders.push(o); paperOrdersSave_(orders); paperSave_(list);
  const A = paperAccount_(); if (!A.started) PropertiesService.getScriptProperties().setProperty('PAPER_ACCT', JSON.stringify({ capital: A.capital, started: o.created.slice(0, 10) }));
  return paperView_();
}

// The older add form (phone) places a market order.
function paperAdd_(t) { return paperOrder_(Object.assign({}, t, { otype: 'MARKET' })); }

// Exit one open trade (or every open trade of the same contract when all is set) at the live or a typed price.
function paperClose_(id, price, all) {
  const list = paperLoad_(), t = list.find(x => x.id === id);
  if (!t || t.status !== 'open') return { error: 'Trade not open.' };
  const same = all ? list.filter(x => x.status === 'open' && x.side === t.side && x.kind === t.kind && (t.kind === 'stock' ? x.sym === t.sym : x.idx === t.idx && x.expiry === t.expiry && Number(x.strike) === Number(t.strike) && x.type === t.type)) : [t];
  const qty = same.reduce((a, x) => a + x.qty, 0);
  const req = { kind: t.kind, side: t.side === 'buy' ? 'sell' : 'buy', sym: t.sym, idx: t.idx, expiry: t.expiry, strike: t.strike, type: t.type, product: t.product,
                qty: qty, lots: t.kind === 'option' ? qty / PAPER_LOT[t.idx] : undefined, price: Number(price) > 0 ? Number(price) : null, otype: 'MARKET', note: 'exit' };
  const o = paperOrderOf_(req); if (o.error) return o;
  const key = paperInstrument_(o), live = key ? paperLtp_([key])[key] : null, px = o.price || live;
  if (px == null) return { error: 'No live price — type the exit price.' };
  const orders = paperOrders_(); o.valid_till = paperValidTill_(o.created);
  paperFill_(o, px, list, o.price ? 'typed' : 'live');
  orders.push(o); paperOrdersSave_(orders); paperSave_(list);
  return paperView_();
}

function paperCancel_(id) {
  const orders = paperOrders_(), o = orders.find(x => x.id === id);
  if (!o || o.status !== 'working') return { error: 'Order not working.' };
  o.status = 'cancelled'; o.reason = 'cancelled by you'; o.cancelled_at = paperNow_();
  paperOrdersSave_(orders); return paperView_();
}
function paperSetCapital_(cap) {
  const c = Math.round(Number(cap));
  if (!(c >= 10000 && c <= 1e10)) return { error: 'Enter a capital between ₹10,000 and ₹1,000 crore.' };
  const A = paperAccount_();
  PropertiesService.getScriptProperties().setProperty('PAPER_ACCT', JSON.stringify({ capital: c, started: A.started }));
  return paperView_();
}
function paperDelete_(id) { paperSave_(paperLoad_().filter(x => x.id !== id)); return paperView_(); }

// The live job's 5-minute call in market hours: fill working orders whose price is reached.
function paperCheck_(key) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  const orders = paperOrders_();
  if (!orders.some(o => o.status === 'working')) return { ok: true, working: 0 };
  const list = paperLoad_(), h = paperHousekeep_(list, orders);
  if (h.changed) paperSave_(list);
  if (h.ochanged) paperOrdersSave_(orders);
  return { ok: true, working: orders.filter(o => o.status === 'working').length };
}

function adminPaper(token) { return sessionValid_(token) ? paperView_() : { error: 'session_expired' }; }
function adminPaperAdd(token, t) { return sessionValid_(token) ? paperAdd_(t) : { error: 'session_expired' }; }
function adminPaperClose(token, id, price, all) { return sessionValid_(token) ? paperClose_(id, price, all) : { error: 'session_expired' }; }
function adminPaperDelete(token, id) { return sessionValid_(token) ? paperDelete_(id) : { error: 'session_expired' }; }
function adminPaperPreview(token, t) { return sessionValid_(token) ? paperPreview_(t) : { error: 'session_expired' }; }
function adminPaperOrder(token, t) { return sessionValid_(token) ? paperOrder_(t) : { error: 'session_expired' }; }
function adminPaperCancel(token, id) { return sessionValid_(token) ? paperCancel_(id) : { error: 'session_expired' }; }
function adminPaperCapital(token, cap) { return sessionValid_(token) ? paperSetCapital_(cap) : { error: 'session_expired' }; }

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
