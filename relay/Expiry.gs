/**
 * NIFTY expiry meter (13 Oct 2026). On a NIFTY expiry day the dashboard's Analysis -> Expiry meter page asks
 * for this every 10 seconds; the answer is computed from a live Kite quote of today's NIFTY options (cached
 * 10 s, so many viewers cost one Kite call).
 *
 * Expected close = F + k*(MP - F) + m*(W - F) + e*F*EU% + u*F*US%, where (EU% / US%: average move today of the
 * European indices / US index futures, Market.gs; e and u start at 0 and are learned like k and m)
 *   F  = forward from put-call parity at the ATM strike (strike + call - put): the market's own expected settlement;
 *   MP = max pain (settlement where option buyers collect least);
 *   W  = midpoint of the call wall and the put wall (top OI strikes above / below spot).
 * k and m start at 0.30 / 0.20 and are re-fitted after every expiry from what the meter said during the day
 * against the actual close (least squares, each expiry counted once, pulled towards the starting values while there are few expiries).
 *
 * Storage: today's per-minute points in the script cache (chart); a sample at least 5 minutes apart per expiry in script
 * property EXPD_<date> and closes in EXP_CLOSES (learning and the accuracy table); last 30 expiries kept.
 * The close is recorded after 15:45 IST by the first call (live.yml calls mode=expiry_close every run).
 */
// Range 3% of spot: today's contracts fit one Kite quote request (Kite allows 1 quote request a second).
const EXP_K0 = 0.30, EXP_M0 = 0.20, EXP_PRIOR_EXPIRIES = 5, EXP_RANGE_PCT = 3, EXP_KEEP = 30;

function adminExpiry(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return expiryNow_();
}

function istNow_() {
  const d = new Date();
  return { date: Utilities.formatDate(d, 'Asia/Kolkata', 'yyyy-MM-dd'), hm: Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm'),
           ts: Utilities.formatDate(d, 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm:ssXXX") };
}

// Today's (or the next) NIFTY option contracts from Kite's instrument list; cached for the day only when it parsed.
// 13 Oct 2026: the first version cached an empty result (the download came back unreadable), so the meter said
// "No NIFTY expiry today" on an expiry day. Now: sent with the Kite login, gzip handled, empty never cached, and
// expiryNow_ falls back to building today's contract names (NIFTY26O13 22500 CE, monthly NIFTY26OCT 22500 CE).
function expirySyms_(date) {
  const cache = CacheService.getScriptCache(), key = 'exps2_' + date;
  const hit = cache.get(key);
  if (hit) return JSON.parse(hit);
  let text = '', diag = '';
  try {
    const res = UrlFetchApp.fetch('https://api.kite.trade/instruments/NFO', { muteHttpExceptions: true, headers: kiteHeaders_() || {} });
    const blob = res.getBlob(), bytes = blob.getBytes();
    text = (bytes.length > 1 && (bytes[0] & 255) === 0x1f && (bytes[1] & 255) === 0x8b)
      ? Utilities.ungzip(blob.setContentType('application/x-gzip')).getDataAsString() : res.getContentText();
    diag = 'HTTP ' + res.getResponseCode() + ', ' + text.length + ' chars';
  } catch (e) { diag = String(e); }
  const lines = text.split('\n');
  const head = (lines[0] || '').split(','), iSym = head.indexOf('tradingsymbol'), iName = head.indexOf('name'),
        iExp = head.indexOf('expiry'), iStrike = head.indexOf('strike'), iType = head.indexOf('instrument_type');
  let next = null, nifty = 0; const todays = [];
  if (iSym >= 0 && iExp >= 0) for (let n = 1; n < lines.length; n++) {
    const L = lines[n];
    if (L.indexOf('"NIFTY"') < 0 && L.indexOf(',NIFTY,') < 0) continue;
    const c = L.split(',');
    if (c[iName].replace(/"/g, '') !== 'NIFTY' || (c[iType] !== 'CE' && c[iType] !== 'PE')) continue;
    nifty++;
    const e = c[iExp];
    if (e === date) todays.push([c[iSym], Number(c[iStrike]), c[iType]]);
    else if (e > date && (!next || e < next)) next = e;
  }
  if (!nifty) return { today: null, next: null, source: 'unavailable', diag: diag };
  const out = { today: todays, next: next, source: 'list' };
  try { cache.put(key, JSON.stringify(out), 21600); } catch (e) { /* too big: refetch next time */ }
  return out;
}

// Fallback: today's contract names from Kite's naming (weekly NIFTY<yy><m><dd>, monthly NIFTY<yy><MON>), strikes every 50.
function expiryGuessSyms_(date, spot) {
  const y = date.slice(2, 4), mo = Number(date.slice(5, 7)), dd = date.slice(8, 10);
  const mc = mo <= 9 ? String(mo) : ['O', 'N', 'D'][mo - 10];
  const mon = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][mo - 1];
  const out = [], lo = Math.ceil(spot * (1 - EXP_RANGE_PCT / 100) / 50) * 50, hi = Math.floor(spot * (1 + EXP_RANGE_PCT / 100) / 50) * 50;
  // Monthly names exist all month (they expire on the month's last expiry), so use them only in the month's last week.
  // Only on the month's last Tuesday (review: the whole last week made the Monday before look like an expiry day).
  const Y = Number(date.slice(0, 4)), D = Number(dd), wd = new Date(Date.UTC(Y, mo - 1, D)).getUTCDay();
  const lastTue = wd === 2 && new Date(Date.UTC(Y, mo - 1, D + 7)).getUTCMonth() !== mo - 1;
  ['NIFTY' + y + mc + dd].concat(lastTue ? ['NIFTY' + y + mon] : []).forEach(root => {
    for (let k = lo; k <= hi; k += 50) ['CE', 'PE'].forEach(t => out.push([root + k + t, k, t]));
  });
  return out;
}

// Fit of the four weights from every stored reading against its expiry's close: ridge least squares pulled towards
// (k0, m0, 0, 0) with a prior worth EXP_PRIOR_EXPIRIES expiries, so a few expiries move the weights only a little and
// the overseas terms count only once the record shows they help. Readings stored before 13 Oct 2026 14:00 have no
// overseas values (taken as 0).
function expiryModel_() {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES') || '{}');
  // Each expiry counts once, however many readings it has (review: counting readings let one fully watched day
  // outweigh the prior); the prior is worth EXP_PRIOR_EXPIRIES expiries.
  const X = [], Y = [], Wt = [];
  Object.keys(closes).forEach(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + d) || '[]');
    pts.forEach(p => {
      const F = p[1];
      X.push([p[2] - F, p[3] - F, F * (p[5] || 0) / 100, F * (p[6] || 0) / 100]); Y.push(closes[d] - F); Wt.push(1 / pts.length);
    });
  });
  const b0 = [EXP_K0, EXP_M0, 0, 0], P = 4, n = X.length;
  const out = { k: EXP_K0, m: EXP_M0, e: 0, u: 0, expiries: Object.keys(closes).length, samples: n };
  if (!n) return out;
  const A = [], r = [];
  for (let a = 0; a < P; a++) {
    A.push([]); r.push(0);
    const sw = Wt.reduce((t, w) => t + w, 0), ms = X.reduce((t, x, i) => t + Wt[i] * x[a] * x[a], 0) / sw || 1, lam = EXP_PRIOR_EXPIRIES * ms;
    for (let b = 0; b < P; b++) A[a].push(X.reduce((t, x, i) => t + Wt[i] * x[a] * x[b], 0) + (a === b ? lam : 0));
    r[a] = X.reduce((t, x, i) => t + Wt[i] * x[a] * Y[i], 0) + lam * b0[a];
  }
  for (let c = 0; c < P; c++) {                      // Gaussian elimination with partial pivoting
    let piv = c; for (let i = c + 1; i < P; i++) if (Math.abs(A[i][c]) > Math.abs(A[piv][c])) piv = i;
    [A[c], A[piv]] = [A[piv], A[c]]; [r[c], r[piv]] = [r[piv], r[c]];
    if (!A[c][c]) return out;
    for (let i = c + 1; i < P; i++) { const f = A[i][c] / A[c][c]; for (let k = c; k < P; k++) A[i][k] -= f * A[c][k]; r[i] -= f * r[c]; }
  }
  const w = [0, 0, 0, 0];
  for (let c = P - 1; c >= 0; c--) { let t = r[c]; for (let k = c + 1; k < P; k++) t -= A[c][k] * w[k]; w[c] = t / A[c][c]; }
  const r3 = x => Math.round(x * 1000) / 1000;
  return Object.assign(out, { k: r3(w[0]), m: r3(w[1]), e: r3(w[2]), u: r3(w[3]) });
}

function expiryAccuracy_() {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES') || '{}');
  return Object.keys(closes).sort().reverse().slice(0, 12).map(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + d) || '[]');
    const at = hm => { const p = pts.filter(x => x[0] <= hm).pop(); return p ? p[4] : null; };
    return { date: d, close: closes[d], at10: at('10:00'), at12: at('12:00'), at14: at('14:00'), at15: at('15:00') };
  });
}

function expiryNow_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('exp_now');
  if (hit) return JSON.parse(hit);
  const now = istNow_();
  // Model and track record read every stored expiry from script properties (quota 50,000 reads a day): cached an hour.
  let ma = JSON.parse(cache.get('exp_ma') || 'null');
  if (!ma) { ma = { model: expiryModel_(), accuracy: expiryAccuracy_() }; cache.put('exp_ma', JSON.stringify(ma), 3600); }
  const syms = expirySyms_(now.date);
  const base = { ts: now.ts, date: now.date, next_expiry: syms.next, model: ma.model, accuracy: ma.accuracy, source: syms.source };
  if (syms.today && !syms.today.length) return Object.assign(base, { expiry_today: false });

  // The platform's one Kite request (Market.gs): spot and today's options come from the shared 10-second snapshot.
  const snap = marketSnapshot_();
  if (snap.error === 'no_login') return Object.assign(base, { expiry_today: !!syms.today, error: 'No Kite login for today: log in with the Kite link.' });
  if (snap.error) return Object.assign(base, { expiry_today: true, error: kiteReason_(snap.error) });
  const q = snap.q, pick = snap.opts || [];
  if (!q['NSE:NIFTY 50']) return Object.assign(base, { expiry_today: true, error: 'Kite did not return the NIFTY 50 level.' });
  const spot = q['NSE:NIFTY 50'][0];
  if (now.hm >= '15:45') expiryRecordClose_(now.date, spot);   // needs only the NIFTY level, not the option chain
  base.ts = snap.ts;

  const ch = {};
  pick.forEach(s => { const x = q['NFO:' + s[0]]; if (!x || Math.abs(s[1] / spot - 1) * 100 > EXP_RANGE_PCT) return;
    const r = ch[s[1]] || (ch[s[1]] = { strike: s[1], ce: null, pe: null, ce_oi: 0, pe_oi: 0 });
    if (s[2] === 'CE') { r.ce = x[0]; r.ce_oi = x[2] || 0; } else { r.pe = x[0]; r.pe_oi = x[2] || 0; } });
  const rows = Object.keys(ch).map(Number).sort((a, b) => a - b).map(s => ch[s]);
  if (!syms.today && !rows.length) return Object.assign(base, { expiry_today: false, note: 'Contract list unavailable (' + syms.diag + '); no contracts expiring today found by name.' });
  if (rows.length < 5) return Object.assign(base, { expiry_today: true, error: 'Too few NIFTY strikes quoted.' });
  const atm = rows.reduce((b, r) => Math.abs(r.strike - spot) < Math.abs(b.strike - spot) ? r : b);
  const F = atm.strike + (atm.ce || 0) - (atm.pe || 0);
  const straddle = (atm.ce || 0) + (atm.pe || 0);
  // The ATM strike counts on both sides (review, 13 Oct 2026): with strict above/below, a pinned strike flipped from
  // call wall to put wall as spot crossed it and the expected close jumped up to ~100 points on a 3-point move.
  const above = rows.filter(r => r.strike >= atm.strike), below = rows.filter(r => r.strike <= atm.strike);
  const cw = above.slice().sort((a, b) => b.ce_oi - a.ce_oi), pw = below.slice().sort((a, b) => b.pe_oi - a.pe_oi);
  const callWall = cw.length ? cw[0].strike : atm.strike, putWall = pw.length ? pw[0].strike : atm.strike;
  const payout = x => rows.reduce((t, r) => t + r.ce_oi * Math.max(0, x - r.strike) + r.pe_oi * Math.max(0, r.strike - x), 0);
  const MP = rows.reduce((b, r) => payout(r.strike) < payout(b.strike) ? r : b).strike;
  const W = (callWall + putWall) / 2;
  const M = base.model;
  const ov = overseasSnapshot_(), eu = ov.eu || 0, us = ov.us || 0;
  const pred = F + M.k * (MP - F) + M.m * (W - F) + (M.e || 0) * F * eu / 100 + (M.u || 0) * F * us / 100;
  const ceAll = rows.reduce((t, r) => t + r.ce_oi, 0), peAll = rows.reduce((t, r) => t + r.pe_oi, 0);
  const r2 = x => Math.round(x * 100) / 100;

  const out = Object.assign(base, {
    expiry_today: true, spot: r2(spot), forward: r2(F), max_pain: MP, wall_mid: W, call_wall: callWall, put_wall: putWall,
    call_walls: cw.slice(0, 3).map(r => [r.strike, r.ce_oi]), put_walls: pw.slice(0, 3).map(r => [r.strike, r.pe_oi]),
    atm: atm.strike, straddle: r2(straddle), range: [r2(pred - straddle), r2(pred + straddle)], prediction: r2(pred),
    pcr: ceAll ? Math.round(peAll / ceAll * 100) / 100 : null, overseas: ov,
    rows: rows.filter(r => Math.abs(r.strike / spot - 1) * 100 <= 1.5).map(r => [r.strike, r.ce_oi, r.pe_oi])
  });

  // History: per-minute points (cache, for the chart) and a 5-minute sample (property, for learning).
  const lock = LockService.getScriptLock();
  if (lock.tryLock(2000)) {
    try {
      const hk = 'exph_' + now.date;
      const hist = JSON.parse(cache.get(hk) || '[]');
      if (!hist.length || hist[hist.length - 1][0] !== now.hm) { hist.push([now.hm, r2(pred), r2(spot), r2(F), MP, W]); cache.put(hk, JSON.stringify(hist), 21600); }
      const mins = hm => Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3));
      const lastSample = cache.get('exp_last_' + now.date);
      if (now.hm >= '09:15' && now.hm <= '15:30' && (!lastSample || mins(now.hm) - mins(lastSample) >= 5)) {
        const props = PropertiesService.getScriptProperties(), pk = 'EXPD_' + now.date;
        const pts = JSON.parse(props.getProperty(pk) || '[]');
        cache.put('exp_last_' + now.date, now.hm, 21600);
        if (!pts.length || mins(now.hm) - mins(pts[pts.length - 1][0]) >= 5) { pts.push([now.hm, r2(F), MP, W, r2(pred), eu, us]); props.setProperty(pk, JSON.stringify(pts)); }
      }
    } finally { lock.releaseLock(); }
  }
  out.history = JSON.parse(cache.get('exph_' + now.date) || '[]');
  cache.put('exp_now', JSON.stringify(out), 10);
  return out;
}

// After 15:45 IST the NIFTY last price is the day's close. Recorded once per expiry; keeps the last 30.
function expiryRecordClose_(date, close) {
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('EXPD_' + date)) return;
  const closes = JSON.parse(props.getProperty('EXP_CLOSES') || '{}');
  if (closes[date]) return;
  closes[date] = Math.round(close * 100) / 100;
  const keep = Object.keys(closes).sort().slice(-EXP_KEEP), kept = {};
  keep.forEach(d => kept[d] = closes[d]);
  Object.keys(closes).forEach(d => { if (!kept[d]) props.deleteProperty('EXPD_' + d); });
  props.setProperty('EXP_CLOSES', JSON.stringify(kept));
  CacheService.getScriptCache().remove('exp_ma');   // re-fit with the new close on the next call
}

/** live.yml calls ?mode=expiry_close&key=RELAY_KEY every run, so readings (09:15-15:30) and the close (after 15:45)
 *  are recorded even if nobody opens the meter. */
function expiryCloseHook_(key) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  const now = istNow_();
  if (now.hm < '09:15' || (now.hm > '15:30' && now.hm < '15:45')) return { ok: true, note: 'outside reading times' };
  if (now.hm >= '15:45') CacheService.getScriptCache().remove('exp_now');
  const r = expiryNow_();
  return { ok: true, expiry_today: r.expiry_today, recorded: !!JSON.parse(PropertiesService.getScriptProperties().getProperty('EXP_CLOSES') || '{}')[now.date] };
}
