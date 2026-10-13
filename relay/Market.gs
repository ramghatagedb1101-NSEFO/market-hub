/**
 * One Kite request for the whole live platform (13 Oct 2026). Owner: "one Kite request should be used for multiple
 * data points; never multiple calls for multiple data points."
 *
 * marketSnapshot_() asks Kite once per 10 seconds (script cache, shared by every caller) for everything the live
 * pages show: NIFTY 50, NIFTY BANK, SENSEX, INDIA VIX, front-month MCX gold and crude, CDS USD/INR, and on a NIFTY
 * expiry day the options of every index expiring today (NIFTY, SENSEX, BANK NIFTY; nearest strikes first within 3% of
 * spot, as many as fit one request), and every watchlist company. Everything else reads this snapshot:
 *   quoteData_  (Code.gs)   -> dashboard market strip, phone (?mode=quote), GitHub live job (live.json)
 *   expiryNow_  (Expiry.gs) -> dashboard expiry meter, phone expiry panel, its learning store
 *   watchCheck_ (Alerts.gs), kiteLtp_ (Phone.gs) -> watchlist move emails, watchlist returns, price when starring
 * A script lock makes simultaneous callers wait for the one fetch instead of each calling Kite.
 * Request count: 1 per 10 s while anyone is looking (2 on the first call of an expiry day, to learn the spots);
 * the options are trimmed to fit, so a second request happens only if indices plus watchlist alone pass the URL limit.
 */
const SNAP_BASE = ['NSE:NIFTY 50', 'NSE:NIFTY BANK', 'BSE:SENSEX', 'NSE:INDIA VIX'];
const SNAP_TTL = 10;

function marketSnapshot_() {
  const cache = CacheService.getScriptCache();
  let hit = cache.get('snap');
  if (hit) return JSON.parse(hit);
  const lock = LockService.getScriptLock();
  const got = lock.tryLock(10000);
  try {
    hit = cache.get('snap');
    if (hit) return JSON.parse(hit);           // another caller fetched it while this one waited
    if (!got) { const prev = cache.get('snap_prev'); if (prev) return JSON.parse(prev); }   // a slow build is running: no second fetch
    const err = cache.get('snap_err');
    if (err) return JSON.parse(err);           // a failure is remembered 30 s (the public quote URL must not retry Kite per call)
    const headers = kiteHeaders_();
    const fail = e => { try { cache.put('snap_err', JSON.stringify(e), 30); } catch (x) {} return e; };
    if (!headers) return fail({ error: 'no_login' });
    const now = istNow_();
    const front = frontMonths_();               // contract names only; cached 6 h, no Kite login used
    const lists = expiryLists_(now.date);       // today's contracts per index (Expiry.gs); cached for the day
    const expiring = EXP_IDX.filter(ix => lists[ix.id].today === null || lists[ix.id].today.length > 0);
    const base = SNAP_BASE.concat(['MCX:' + front.gold, 'MCX:' + front.crude, 'CDS:' + front.usd].filter(s => !/:(undefined|null)$/.test(s)));

    const spots = {}; EXP_IDX.forEach(ix => spots[ix.id] = Number(cache.get('exp_spot_' + ix.id) || 0));
    let q = {};
    if (expiring.some(ix => !spots[ix.id])) {   // first call of an expiry day: learn the spots to pick strikes
      const r = snapFetch_(base, headers);
      if (r.error) return fail(r);
      q = r.data;
      EXP_IDX.forEach(ix => { if (q[ix.spot]) spots[ix.id] = q[ix.spot].last_price; });
      Utilities.sleep(1100);                    // Kite: 1 quote request a second
    }
    // The watchlist rides along (move alerts, star-time prices, phone watchlist): no separate Kite calls for it.
    const watch = watchList_().map(w => w.s), wtok = watchTokens_(watch, now.date);
    // Kite accepts its numeric instrument token in place of EXCHANGE:SYMBOL (probe, 13 Oct 2026); tokens are about a
    // third as long. Indices and the watchlist go first; then today's options for every expiring index, nearest strike
    // first, taken in turn per index, until the URL budget is used -- so even a double or triple expiry day is one
    // Kite request (13 Oct 2026, multi-index meter).
    const ask = base.map(n => [n, n]).concat(watch.map(w => [wtok[w] || 'NSE:' + w, 'NSE:' + w]));
    const len = a => ('i=' + encodeURIComponent(a)).length + 1;
    let used = 'https://api.kite.trade/quote?'.length + ask.reduce((t, a) => t + len(a[0]), 0);
    const queues = expiring.filter(ix => spots[ix.id]).map(ix => {
      const sp = spots[ix.id], byStrike = {};
      (lists[ix.id].today || expiryGuessSyms_(ix, now.date, sp))
        .filter(o => Math.abs(o[1] / sp - 1) * 100 <= EXP_RANGE_PCT + 0.2)
        .forEach(o => (byStrike[o[1]] = byStrike[o[1]] || []).push(o));
      const pairs = Object.keys(byStrike).map(Number).sort((a, b) => Math.abs(a - sp) - Math.abs(b - sp)).map(k => byStrike[k]);
      return { ix: ix, pairs: pairs };
    });
    const opts = []; let trimmed = false, more = true;
    while (more) {
      more = false;
      queues.forEach(qd => {
        const p = qd.pairs.shift(); if (!p) return;
        const cost = p.reduce((t, o) => t + len(o[3] || qd.ix.exch + ':' + o[0]), 0);
        if (used + cost > 1900) { trimmed = true; qd.pairs = []; return; }
        used += cost; more = true;
        p.forEach(o => { opts.push([o[0], o[1], o[2], o[3], qd.ix.id]); ask.push([o[3] || qd.ix.exch + ':' + o[0], qd.ix.exch + ':' + o[0]]); });
      });
    }
    const r = snapFetch_(ask.map(a => a[0]), headers);
    if (r.error) return fail(r);
    q = r.data;

    // Keep only what the pages use, keyed by EXCHANGE:SYMBOL: last price, previous close, open interest.
    const nameOf = {}; ask.forEach(a => nameOf[a[0]] = a[1]);
    const slim = {};
    Object.keys(q).forEach(k => { const x = q[k]; slim[nameOf[k] || k] = [x.last_price, x.ohlc ? x.ohlc.close : null, x.oi || 0]; });
    EXP_IDX.forEach(ix => { if (slim[ix.spot]) cache.put('exp_spot_' + ix.id, String(slim[ix.spot][0]), 21600); });
    const snap = { ts: now.ts, hm: now.hm, date: now.date, q: slim, front: front, opts: opts, opts_trimmed: trimmed,
                   expiring: expiring.map(ix => ix.id), requests: r.requests };
    try { const j = JSON.stringify(snap); cache.put('snap', j, SNAP_TTL); cache.put('snap_prev', j, 120); } catch (e) { /* over 100 KB: serve uncached */ }
    return snap;
  } finally { if (got) lock.releaseLock(); }
}

// One logical quote request; split only if the URL would be too long, then sent one a second.
function snapFetch_(symbols, headers) {
  const params = symbols.map(s => 'i=' + encodeURIComponent(s));
  const reqs = []; let cur = [];
  params.forEach(p => { if (cur.length && ('https://api.kite.trade/quote?' + cur.concat(p).join('&')).length > 1900) { reqs.push(cur); cur = []; } cur.push(p); });
  if (cur.length) reqs.push(cur);
  const data = {};
  for (let n = 0; n < reqs.length; n++) {
    if (n) Utilities.sleep(1100);
    const get = () => UrlFetchApp.fetch('https://api.kite.trade/quote?' + reqs[n].join('&'), { muteHttpExceptions: true, headers: headers });
    let res = get();
    if (res.getResponseCode() === 429) { Utilities.sleep(1100); res = get(); }
    let body;
    try { body = JSON.parse(res.getContentText()); } catch (e) { return { error: 'Kite answered HTTP ' + res.getResponseCode() }; }
    if (body.status !== 'success') { kiteFailed_(body.message); return { error: body.message || 'quote failed' }; }
    Object.assign(data, body.data);
  }
  return { data: data, requests: reqs.length };
}

/**
 * Overseas markets (13 Oct 2026). Owner: Europe (open during Indian afternoon hours) and the US move Indian markets.
 * One free Yahoo Finance request for all of them, cached 60 s: DAX, FTSE 100, Euro Stoxx 50, CAC 40, and S&P 500,
 * Nasdaq 100 and Dow futures (they trade around the clock). Not Kite, not BharatStock. Shown on the strip and the
 * expiry meter, and recorded with each meter reading so the learning can test whether they help (weight starts at 0).
 */
const OVS = [['^GDAXI', 'DAX', 'eu'], ['^FTSE', 'FTSE 100', 'eu'], ['^STOXX50E', 'Euro Stoxx 50', 'eu'], ['^FCHI', 'CAC 40', 'eu'],
             ['ES=F', 'S&P 500 fut', 'us'], ['NQ=F', 'Nasdaq fut', 'us'], ['YM=F', 'Dow fut', 'us']];
function overseasSnapshot_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('ovs');
  if (hit) return JSON.parse(hit);
  let out = { items: [], eu: null, us: null };
  try {
    const url = 'https://query1.finance.yahoo.com/v8/finance/spark?symbols=' + encodeURIComponent(OVS.map(o => o[0]).join(',')) + '&range=1d&interval=5m';
    const j = JSON.parse(UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } }).getContentText());
    const grp = { eu: [], us: [] };
    OVS.forEach(([sym, name, g]) => {
      const v = j[sym]; if (!v) return;
      const c = (v.close || []).filter(x => x != null), prev = v.chartPreviousClose, last = c.length ? c[c.length - 1] : null;
      if (last == null || !prev) return;
      const pct = Math.round((last / prev - 1) * 10000) / 100, t = (v.timestamp || []).slice(-1)[0];
      // Only today's trading counts (audit, 13 Oct 2026): before Europe opens, Yahoo's day is yesterday's session,
      // whose move is already in NIFTY's open.
      const today = t && Utilities.formatDate(new Date(t * 1000), 'Asia/Kolkata', 'yyyy-MM-dd') === Utilities.formatDate(new Date(), 'Asia/Kolkata', 'yyyy-MM-dd');
      out.items.push({ sym: sym, name: name, group: g, last: Math.round(last * 100) / 100, change_pct: pct, today: !!today,
                       at: t ? Utilities.formatDate(new Date(t * 1000), 'Asia/Kolkata', today ? 'HH:mm' : 'dd MMM HH:mm') : null });
      if (today) grp[g].push(pct);
    });
    const avg = a => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length * 100) / 100 : null;
    out.eu = avg(grp.eu); out.us = avg(grp.us);
  } catch (e) { out.error = String(e).slice(0, 120); }
  cache.put('ovs', JSON.stringify(out), out.items.length ? 60 : 20);
  return out;
}

// NSE instrument tokens for the watchlist (from Kite's public NSE list, once a day); missing ones go by name.
function watchTokens_(syms, date) {
  if (!syms.length) return {};
  const cache = CacheService.getScriptCache(), key = 'wtok_' + date;
  const have = JSON.parse(cache.get(key) || '{}');
  if (syms.every(s => s in have)) return have;
  try {
    const res = UrlFetchApp.fetch('https://api.kite.trade/instruments/NSE', { muteHttpExceptions: true });
    const blob = res.getBlob(), bytes = blob.getBytes();
    const text = (bytes.length > 1 && (bytes[0] & 255) === 0x1f && (bytes[1] & 255) === 0x8b)
      ? Utilities.ungzip(blob.setContentType('application/x-gzip')).getDataAsString() : res.getContentText();
    const want = {}; syms.forEach(s => want[s] = true);
    const lines = text.split('\n'), head = lines[0].split(','), iTok = head.indexOf('instrument_token'), iSym = head.indexOf('tradingsymbol'), iSeg = head.indexOf('segment');
    for (let n = 1; n < lines.length; n++) {
      const c = lines[n].split(',');
      if (want[c[iSym]] && c[iSeg] === 'NSE') have[c[iSym]] = c[iTok];
    }
    syms.forEach(s => { if (!(s in have)) have[s] = ''; });      // remembered as "go by name"
    cache.put(key, JSON.stringify(have), 21600);
  } catch (e) {        // by name, and not retried for 10 minutes (audit)
    syms.forEach(s => { if (!(s in have)) have[s] = ''; });
    try { cache.put(key, JSON.stringify(have), 600); } catch (x) {}
  }
  return have;
}
