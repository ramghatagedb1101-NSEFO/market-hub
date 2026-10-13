/**
 * One Kite request for the whole live platform (13 Oct 2026). Owner: "one Kite request should be used for multiple
 * data points; never multiple calls for multiple data points."
 *
 * marketSnapshot_() asks Kite once per 10 seconds (script cache, shared by every caller) for everything the live
 * pages show: NIFTY 50, NIFTY BANK, SENSEX, INDIA VIX, front-month MCX gold and crude, CDS USD/INR, and on a NIFTY
 * expiry day today's NIFTY options within 3% of spot. Everything else reads this snapshot:
 *   quoteData_  (Code.gs)   -> dashboard market strip, phone (?mode=quote), GitHub live job (live.json)
 *   expiryNow_  (Expiry.gs) -> dashboard expiry meter, phone expiry panel, its learning store
 * A script lock makes simultaneous callers wait for the one fetch instead of each calling Kite.
 * Request count: 1 per 10 s while anyone is looking (2 on the first call of an expiry day, to learn the spot);
 * split into several only if the URL would pass Apps Script's ~2,000-character limit, then one a second.
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
    const headers = kiteHeaders_();
    if (!headers) return { error: 'no_login' };
    const now = istNow_();
    const front = frontMonths_();               // contract names only; cached 6 h, no Kite login used
    const syms = expirySyms_(now.date);         // today's NIFTY contracts; cached for the day
    const maybeExpiry = syms.today === null || syms.today.length > 0;
    const base = SNAP_BASE.concat(['MCX:' + front.gold, 'MCX:' + front.crude, 'CDS:' + front.usd].filter(s => !/:(undefined|null)$/.test(s)));

    let lastSpot = Number(cache.get('exp_spot') || 0), q = {};
    if (maybeExpiry && !lastSpot) {             // first call of an expiry day: learn the spot to pick strikes
      const r = snapFetch_(base, headers);
      if (r.error) return r;
      q = r.data; lastSpot = q['NSE:NIFTY 50'] ? q['NSE:NIFTY 50'].last_price : 0;
      Utilities.sleep(1100);                    // Kite: 1 quote request a second
    }
    const opts = maybeExpiry && lastSpot
      ? (syms.today || expiryGuessSyms_(now.date, lastSpot)).filter(s => Math.abs(s[1] / lastSpot - 1) * 100 <= EXP_RANGE_PCT + 0.2).slice(0, 400)
      : [];
    const r = snapFetch_(base.concat(opts.map(s => 'NFO:' + s[0])), headers);
    if (r.error) return r;
    q = r.data;

    // Keep only what the pages use: last price, previous close, open interest.
    const slim = {};
    Object.keys(q).forEach(k => { const x = q[k]; slim[k] = [x.last_price, x.ohlc ? x.ohlc.close : null, x.oi || 0]; });
    const spot = slim['NSE:NIFTY 50'] ? slim['NSE:NIFTY 50'][0] : null;
    if (spot) cache.put('exp_spot', String(spot), 21600);
    const snap = { ts: now.ts, hm: now.hm, date: now.date, q: slim, front: front, opts: opts,
                   expiry: { listed: syms.today ? syms.today.length > 0 : null, next: syms.next, source: syms.source, diag: syms.diag || null },
                   requests: r.requests };
    try { cache.put('snap', JSON.stringify(snap), SNAP_TTL); } catch (e) { /* over 100 KB: serve uncached */ }
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
      out.items.push({ sym: sym, name: name, group: g, last: Math.round(last * 100) / 100, change_pct: pct,
                       at: t ? Utilities.formatDate(new Date(t * 1000), 'Asia/Kolkata', 'HH:mm') : null });
      grp[g].push(pct);
    });
    const avg = a => a.length ? Math.round(a.reduce((x, y) => x + y, 0) / a.length * 100) / 100 : null;
    out.eu = avg(grp.eu); out.us = avg(grp.us);
  } catch (e) { out.error = String(e).slice(0, 120); }
  cache.put('ovs', JSON.stringify(out), out.items.length ? 60 : 20);
  return out;
}
