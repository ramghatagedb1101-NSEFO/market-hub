/**
 * Expiry meter for NIFTY, SENSEX and BANK NIFTY (13 Oct 2026; NIFTY-only the same morning, all three that evening).
 * The dashboard (Analysis -> Expiry meter) asks every 10 seconds; the answer covers every index expiring today, from
 * the platform's one shared Kite snapshot (Market.gs), so several indices on the same day still cost one Kite request.
 *
 * Which index expires when comes from Kite's contract lists (instruments/NFO, instruments/BFO), so exchange holidays that
 * move an expiry are followed by themselves (NIFTY: Mon 19 Oct and Mon 9 Nov 2026). As of Oct 2026: NIFTY weekly (Tue)
 * and monthly (last Tue); SENSEX weekly (Thu) and monthly (last Thu); BANK NIFTY monthly only (last Tue) -- the 2024
 * exchange rule allows one weekly index per exchange.
 *
 * Expected close = F + k*(MP - F) + m*(W - F) + e*F*EU% + u*F*US%, per index, where
 *   F  = forward from put-call parity at the ATM strike (strike + call - put): the market's own expected settlement;
 *   MP = max pain (settlement where option buyers collect least);
 *   W  = midpoint of the call wall and the put wall (top OI strikes at/above and at/below the ATM strike);
 *   EU% / US% = average move today of the European indices / US index futures (Market.gs), only once they trade today.
 * Each index has its own k, m, e, u: starting at 0.30 / 0.20 / 0 / 0 and re-fitted after every expiry from what the
 * meter said during the day against the actual close (Bayesian ridge, see expiryModel_: one expiry only nudges them).
 *
 * Storage per index: per-minute points in the script cache (chart, exph_<IDX>_<date>); a reading at least 5 minutes
 * apart in script property EXPD_<IDX>_<date> and closes in EXP_CLOSES_<IDX> (learning, track record); last 30 expiries.
 * The close is recorded after 15:45 IST by the first call (live.yml calls mode=expiry_close every run).
 */
const EXP_K0 = 0.30, EXP_M0 = 0.20, EXP_RANGE_PCT = 3, EXP_KEEP = 30;
const EXP_IDX = [
  { id: 'NIFTY', label: 'NIFTY 50', exch: 'NFO', spot: 'NSE:NIFTY 50', step: 50, wd: 2, weekly: true },
  { id: 'SENSEX', label: 'SENSEX', exch: 'BFO', spot: 'BSE:SENSEX', step: 100, wd: 4, weekly: true },
  { id: 'BANKNIFTY', label: 'BANK NIFTY', exch: 'NFO', spot: 'NSE:NIFTY BANK', step: 100, wd: 2, weekly: false },
];

function adminExpiry(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return expiryNow_();
}

function istNow_() {
  const d = new Date();
  return { date: Utilities.formatDate(d, 'Asia/Kolkata', 'yyyy-MM-dd'), hm: Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm'),
           ts: Utilities.formatDate(d, 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm:ssXXX") };
}

// Today's contracts and the next expiry for every index, from Kite's NFO and BFO lists (one download per exchange a day).
// Never cache an empty list (13 Oct 2026: the first version did, and said "no expiry" on an expiry day); a failed
// download is remembered 10 minutes so it is not repeated on every 10-second build.
function expiryLists_(date) {
  const out = {};
  ['NFO', 'BFO'].forEach(ex => {
    const ids = EXP_IDX.filter(i => i.exch === ex).map(i => i.id);
    const r = expiryExchList_(ex, date, ids);
    ids.forEach(id => out[id] = r[id]);
  });
  return out;
}

function expiryExchList_(ex, date, ids) {
  const cache = CacheService.getScriptCache(), key = 'expl_' + ex + '_' + date;
  const hit = cache.get(key) || cache.get(key + '_fail');
  if (hit) return JSON.parse(hit);
  let text = '', diag = '';
  try {
    const res = UrlFetchApp.fetch('https://api.kite.trade/instruments/' + ex, { muteHttpExceptions: true, headers: kiteHeaders_() || {} });
    const blob = res.getBlob(), bytes = blob.getBytes();
    text = (bytes.length > 1 && (bytes[0] & 255) === 0x1f && (bytes[1] & 255) === 0x8b)
      ? Utilities.ungzip(blob.setContentType('application/x-gzip')).getDataAsString() : res.getContentText();
    diag = ex + ' HTTP ' + res.getResponseCode() + ', ' + text.length + ' chars';
  } catch (e) { diag = ex + ': ' + String(e).slice(0, 100); }
  const lines = text.split('\n');
  const head = (lines[0] || '').split(','), iTok = head.indexOf('instrument_token'), iSym = head.indexOf('tradingsymbol'), iName = head.indexOf('name'),
        iExp = head.indexOf('expiry'), iStrike = head.indexOf('strike'), iType = head.indexOf('instrument_type');
  const res = {}; let seen = 0;
  ids.forEach(id => res[id] = { today: [], next: null, source: 'list' });
  if (iSym >= 0 && iExp >= 0) for (let n = 1; n < lines.length; n++) {
    const L = lines[n];
    if (!ids.some(id => L.indexOf('"' + id + '"') >= 0 || L.indexOf(',' + id + ',') >= 0)) continue;
    const c = L.split(','), id = (c[iName] || '').replace(/"/g, '');
    if (!res[id] || (c[iType] !== 'CE' && c[iType] !== 'PE')) continue;
    seen++;
    const e = c[iExp];
    if (e === date) res[id].today.push([c[iSym], Number(c[iStrike]), c[iType], c[iTok]]);
    else if (e > date && (!res[id].next || e < res[id].next)) res[id].next = e;
  }
  if (!seen) {
    const fail = {}; ids.forEach(id => fail[id] = { today: null, next: null, source: 'unavailable', diag: diag });
    try { cache.put(key + '_fail', JSON.stringify(fail), 600); } catch (e) {}
    return fail;
  }
  try { cache.put(key, JSON.stringify(res), 21600); } catch (e) { /* too big: refetch next time */ }
  return res;
}

// Fallback when an exchange's list fails: today's contract names from Kite's naming -- weekly <ID><yy><m><dd>
// (on the index's weekday or the day before, for a holiday move), monthly <ID><yy><MON> (on the month's last weekday
// of that kind only; monthly names exist all month).
function expiryGuessSyms_(ix, date, spot) {
  const y = date.slice(2, 4), mo = Number(date.slice(5, 7)), dd = date.slice(8, 10);
  const mc = mo <= 9 ? String(mo) : ['O', 'N', 'D'][mo - 10];
  const mon = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][mo - 1];
  const Y = Number(date.slice(0, 4)), D = Number(dd), wd = new Date(Date.UTC(Y, mo - 1, D)).getUTCDay();
  const lastOfMonth = wd === ix.wd && new Date(Date.UTC(Y, mo - 1, D + 7)).getUTCMonth() !== mo - 1;
  const roots = [];
  if (ix.weekly && (wd === ix.wd || wd === ix.wd - 1)) roots.push(ix.id + y + mc + dd);
  if (lastOfMonth) roots.push(ix.id + y + mon);
  const out = [], s = ix.step, lo = Math.ceil(spot * (1 - EXP_RANGE_PCT / 100) / s) * s, hi = Math.floor(spot * (1 + EXP_RANGE_PCT / 100) / s) * s;
  roots.forEach(root => { for (let k = lo; k <= hi; k += s) ['CE', 'PE'].forEach(t => out.push([root + k + t, k, t, null])); });
  return out;
}

// One-time move of the NIFTY-only store (13 Oct 2026 morning) to the per-index names.
function expiryMigrate_() {
  const cache = CacheService.getScriptCache();
  if (cache.get('exp_mig')) return;
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('EXP_MIGRATED')) {
    const lock = LockService.getScriptLock();
    if (lock.tryLock(5000)) {
      try {
        if (!props.getProperty('EXP_MIGRATED')) {
          const closes = props.getProperty('EXP_CLOSES');
          if (closes) { props.setProperty('EXP_CLOSES_NIFTY', closes); props.deleteProperty('EXP_CLOSES'); }
          props.getKeys().forEach(k => { const m = k.match(/^EXPD_(\d{4}-\d\d-\d\d)$/);
            if (m) { props.setProperty('EXPD_NIFTY_' + m[1], props.getProperty(k)); props.deleteProperty(k); } });
          props.setProperty('EXP_MIGRATED', '1');
        }
      } finally { lock.releaseLock(); }
    }
  }
  cache.put('exp_mig', '1', 21600);
}

// Fit of the four weights for one index from every stored reading against its expiry's close: a Bayesian ridge.
// 13 Oct 2026 (dry run before the first real expiry): an unweighted fit let one expiry with 2 readings swing k from
// 0.30 to -1.64, because the close differs from any reading mostly by the market's own later move (noise), and a
// least-squares fit reads that noise as signal. Now each reading carries the noise it really has (EXP_NOISE_PCT of the
// level, about the expiry-day remaining move), each expiry counts once, and every weight has a prior (start value and
// spread): one expiry can only nudge the weights; about a dozen consistent expiries are needed to move them
// substantially. Weights are also kept within sane bounds.
const EXP_NOISE_PCT = 0.4;
const EXP_PRIOR = [[EXP_K0, 0.5], [EXP_M0, 0.5], [0, 0.3], [0, 0.3]];       // [start, spread] for k, m, e, u
const EXP_BOUNDS = [[-0.5, 1.5], [-0.5, 1.5], [-1, 1], [-1, 1]];
function expiryModel_(id) {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES_' + id) || '{}');
  const X = [], Y = [], Wt = [];
  Object.keys(closes).forEach(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + id + '_' + d) || '[]');
    pts.forEach(p => {
      const F = p[1], sd = F * EXP_NOISE_PCT / 100;
      X.push([p[2] - F, p[3] - F, F * (p[5] || 0) / 100, F * (p[6] || 0) / 100]); Y.push(closes[d] - F);
      Wt.push(1 / (pts.length * sd * sd));           // each expiry once; each reading weighted by its noise
    });
  });
  const P = 4, n = X.length;
  const out = { k: EXP_K0, m: EXP_M0, e: 0, u: 0, expiries: Object.keys(closes).length, samples: n };
  if (!n) return out;
  const A = [], r = [];
  for (let a = 0; a < P; a++) {
    A.push([]);
    const prec = 1 / (EXP_PRIOR[a][1] * EXP_PRIOR[a][1]);
    for (let b = 0; b < P; b++) A[a].push(X.reduce((t, x, i) => t + Wt[i] * x[a] * x[b], 0) + (a === b ? prec : 0));
    r.push(X.reduce((t, x, i) => t + Wt[i] * x[a] * Y[i], 0) + prec * EXP_PRIOR[a][0]);
  }
  for (let c = 0; c < P; c++) {                      // Gaussian elimination with partial pivoting
    let piv = c; for (let i = c + 1; i < P; i++) if (Math.abs(A[i][c]) > Math.abs(A[piv][c])) piv = i;
    [A[c], A[piv]] = [A[piv], A[c]]; [r[c], r[piv]] = [r[piv], r[c]];
    if (!A[c][c]) return out;
    for (let i = c + 1; i < P; i++) { const f = A[i][c] / A[c][c]; for (let k = c; k < P; k++) A[i][k] -= f * A[c][k]; r[i] -= f * r[c]; }
  }
  const w = [0, 0, 0, 0];
  for (let c = P - 1; c >= 0; c--) { let t = r[c]; for (let k = c + 1; k < P; k++) t -= A[c][k] * w[k]; w[c] = t / A[c][c]; }
  const r3 = (x, a) => Math.round(Math.max(EXP_BOUNDS[a][0], Math.min(EXP_BOUNDS[a][1], x)) * 1000) / 1000;
  return Object.assign(out, { k: r3(w[0], 0), m: r3(w[1], 1), e: r3(w[2], 2), u: r3(w[3], 3) });
}

function expiryAccuracy_(id) {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES_' + id) || '{}');
  return Object.keys(closes).sort().reverse().slice(0, 12).map(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + id + '_' + d) || '[]');
    const at = hm => { const p = pts.filter(x => x[0] <= hm).pop(); return p ? p[4] : null; };
    return { date: d, close: closes[d], at10: at('10:00'), at12: at('12:00'), at14: at('14:00'), at15: at('15:00'), readings: pts.length };
  });
}

// Model and track record read every stored expiry from script properties (quota 50,000 reads a day): cached an hour,
// cleared when a close is recorded.
function expiryTrack_(id) {
  const cache = CacheService.getScriptCache(), key = 'exp_ma_' + id;
  const hit = cache.get(key);
  if (hit) return JSON.parse(hit);
  const t = { model: expiryModel_(id), accuracy: expiryAccuracy_(id) };
  try { cache.put(key, JSON.stringify(t), 3600); } catch (e) {}
  return t;
}

function expiryNow_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get('exp_now2');
  if (hit) return JSON.parse(hit);
  expiryMigrate_();
  const now = istNow_();
  const lists = expiryLists_(now.date);
  const tracks = {}; EXP_IDX.forEach(ix => tracks[ix.id] = expiryTrack_(ix.id));
  const base = { ts: now.ts, date: now.date, tracks: tracks, indices: [],
                 upcoming: EXP_IDX.map(ix => ({ id: ix.id, label: ix.label, today: lists[ix.id].today ? lists[ix.id].today.length > 0 : null,
                                                next: lists[ix.id].next, source: lists[ix.id].source })) };
  const maybe = EXP_IDX.filter(ix => lists[ix.id].today === null || lists[ix.id].today.length > 0);
  base.listed = EXP_IDX.filter(ix => lists[ix.id].today && lists[ix.id].today.length).map(ix => ix.id);
  if (!maybe.length) { base.expiry_today = false; base.source = 'list'; cache.put('exp_now2', JSON.stringify(base), 10); return base; }

  // The platform's one Kite request (Market.gs): spots and today's options for every expiring index.
  const snap = marketSnapshot_();
  if (snap.error === 'no_login') return Object.assign(base, { expiry_today: base.listed.length > 0, error: 'No Kite login for today: log in with the Kite link.' });
  if (snap.error) return Object.assign(base, { expiry_today: true, error: kiteReason_(snap.error) });
  base.ts = snap.ts;
  const ov = overseasSnapshot_();
  maybe.forEach(ix => { const r = expiryIndex_(ix, snap, now, tracks[ix.id].model, ov); if (r) base.indices.push(r); });
  base.expiry_today = base.indices.length > 0;
  if (snap.opts_trimmed) base.note = 'Several indices expire today: strikes nearest each spot were kept so all fit one Kite request.';
  if (!base.expiry_today && maybe.some(ix => lists[ix.id].today === null))
    base.note = 'Contract list unavailable (' + maybe.map(ix => lists[ix.id].diag).filter(Boolean).join('; ') + '); no contracts expiring today found by name.';
  base.source = maybe.some(ix => lists[ix.id].today === null) ? 'guess' : 'list';
  base.overseas = ov;
  cache.put('exp_now2', JSON.stringify(base), 10);
  return base;
}

// One index's reading from the shared snapshot; also its chart point, its learning sample and, after 15:45, its close.
function expiryIndex_(ix, snap, now, M, ov) {
  const q = snap.q, sx = q[ix.spot];
  if (!sx) return { id: ix.id, label: ix.label, error: 'Kite did not return the ' + ix.label + ' level.' };
  const spot = sx[0];
  if (now.hm >= '15:45') expiryRecordClose_(ix.id, now.date, spot);   // needs only the index level, not the chain
  const ch = {};
  (snap.opts || []).forEach(s => { if (s[4] !== ix.id) return;
    const x = q[ix.exch + ':' + s[0]]; if (!x || Math.abs(s[1] / spot - 1) * 100 > EXP_RANGE_PCT) return;
    const r = ch[s[1]] || (ch[s[1]] = { strike: s[1], ce: null, pe: null, ce_oi: 0, pe_oi: 0 });
    if (s[2] === 'CE') { r.ce = x[0]; r.ce_oi = x[2] || 0; } else { r.pe = x[0]; r.pe_oi = x[2] || 0; } });
  const rows = Object.keys(ch).map(Number).sort((a, b) => a - b).map(s => ch[s]);
  if (!rows.length) return null;                       // name guess found nothing: not expiring today
  if (rows.length < 5) return { id: ix.id, label: ix.label, error: 'Too few ' + ix.label + ' strikes quoted.' };
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
  const eu = ov.eu, us = ov.us;   // null when not trading today or unavailable
  const pred = F + M.k * (MP - F) + M.m * (W - F) + (M.e || 0) * F * (eu || 0) / 100 + (M.u || 0) * F * (us || 0) / 100;
  const ceAll = rows.reduce((t, r) => t + r.ce_oi, 0), peAll = rows.reduce((t, r) => t + r.pe_oi, 0);
  const r2 = x => Math.round(x * 100) / 100;
  const out = {
    id: ix.id, label: ix.label, spot: r2(spot), forward: r2(F), max_pain: MP, wall_mid: W, call_wall: callWall, put_wall: putWall,
    call_walls: cw.slice(0, 3).map(r => [r.strike, r.ce_oi]), put_walls: pw.slice(0, 3).map(r => [r.strike, r.pe_oi]),
    atm: atm.strike, straddle: r2(straddle), range: [r2(pred - straddle), r2(pred + straddle)], prediction: r2(pred),
    pcr: ceAll ? Math.round(peAll / ceAll * 100) / 100 : null, model: M, strikes: rows.length,
    rows: rows.filter(r => Math.abs(r.strike / spot - 1) * 100 <= 1.5).map(r => [r.strike, r.ce_oi, r.pe_oi])
  };

  // Per-minute chart point (cache) and a reading at least 5 minutes apart (property, for learning).
  const cache = CacheService.getScriptCache(), lock = LockService.getScriptLock();
  const hk = 'exph_' + ix.id + '_' + now.date;
  if (lock.tryLock(2000)) {
    try {
      const hist = JSON.parse(cache.get(hk) || '[]');
      if (!hist.length || hist[hist.length - 1][0] !== now.hm) { hist.push([now.hm, r2(pred), r2(spot), r2(F), MP, W]); cache.put(hk, JSON.stringify(hist), 21600); }
      const mins = hm => Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3));
      const lk = 'exp_last_' + ix.id + '_' + now.date, lastSample = cache.get(lk);
      if (now.hm >= '09:15' && now.hm <= '15:30' && (!lastSample || mins(now.hm) - mins(lastSample) >= 5)) {
        const props = PropertiesService.getScriptProperties(), pk = 'EXPD_' + ix.id + '_' + now.date;
        const pts = JSON.parse(props.getProperty(pk) || '[]');
        cache.put(lk, now.hm, 21600);
        if (!pts.length || mins(now.hm) - mins(pts[pts.length - 1][0]) >= 5) { pts.push([now.hm, r2(F), MP, W, r2(pred), eu, us]); props.setProperty(pk, JSON.stringify(pts)); }
      }
    } finally { lock.releaseLock(); }
  }
  out.history = JSON.parse(cache.get(hk) || '[]');
  return out;
}

// After 15:45 IST an index's last price is the day's close. Recorded once per expiry per index; keeps the last 30.
function expiryRecordClose_(id, date, close) {
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('EXPD_' + id + '_' + date)) return;
  const closes = JSON.parse(props.getProperty('EXP_CLOSES_' + id) || '{}');
  if (closes[date]) return;
  closes[date] = Math.round(close * 100) / 100;
  const keep = Object.keys(closes).sort().slice(-EXP_KEEP), kept = {};
  keep.forEach(d => kept[d] = closes[d]);
  Object.keys(closes).forEach(d => { if (!kept[d]) props.deleteProperty('EXPD_' + id + '_' + d); });
  props.setProperty('EXP_CLOSES_' + id, JSON.stringify(kept));
  CacheService.getScriptCache().remove('exp_ma_' + id);   // re-fit with the new close on the next call
}

/** live.yml calls ?mode=expiry_close&key=RELAY_KEY every run: readings (09:15-15:30) and closes (after 15:45) are
 *  recorded even if nobody opens the meter, and the answer (no chart history) is what the job writes to
 *  docs/data/expiry.json for the phone -- so the job makes no Kite call of its own. */
function expiryCloseHook_(key) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  const now = istNow_();
  if (now.hm < '09:15' || (now.hm > '15:30' && now.hm < '15:45')) return { ok: true, note: 'outside reading times' };
  if (now.hm >= '15:45') CacheService.getScriptCache().remove('exp_now2');
  const out = JSON.parse(JSON.stringify(expiryNow_()));
  (out.indices || []).forEach(x => delete x.history);
  out.ok = true;
  return out;
}
