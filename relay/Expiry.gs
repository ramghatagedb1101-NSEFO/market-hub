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
 * Expected close = F + k*(MP - F) + m*(W - F) + e*F*EU% + u*F*US% + v*(NW - F), per index, where
 *   F  = forward from put-call parity at the ATM strike (strike + call - put): the market's own expected settlement;
 *   MP = max pain (settlement where option buyers collect least);
 *   W  = midpoint of the call wall and the put wall (top OI strikes at/above and at/below the ATM strike);
 *   EU% / US% = average move today of the European indices / US index futures (Market.gs), only once they trade today;
 *   NW = midpoint of the NEXT expiry's call and put walls (13 Oct 2026, owner: on expiry day sellers roll into next week,
 *        and where they write it shows the range they plan to defend).
 * Each index has its own k, m, e, u, v: starting values in EXP_START, re-fitted after every expiry from what the meter said
 * during the day against the actual close (Bayesian ridge, see expiryModel_: one expiry only nudges them). Since 14 Oct 2026
 * the wall and max-pain weights (k, m, v) are pinned at 0 -- 399 expiries showed they add nothing beyond the forward -- so
 * the expected close is the forward plus the overseas terms, and the range is what the meter adds.
 * A signal with no track record (overseas, next week's walls) starts at 0 and earns weight only if past expiries show it helps.
 *
 * Sellers' positions, tracked through the day (13 Oct 2026, owner: "we update every 10 seconds but do not track these
 * values"): every minute from 09:15 to 15:30, per index, the walls (strike and open interest), max pain, total OI, what
 * sellers would pay at settlement here and per step up or down, and the same walls for the next expiry. The OI at the
 * day's first reading (before 09:15 that is the previous close's) is the baseline for every "change since" shown.
 * Kite's OI is in units (shares), so OI x points = rupees.
 *
 * Storage per index: per-minute points in the script cache (prediction chart exph_<IDX>_<date>, sellers' record
 * expw_<IDX>_<date>, 6 hours); the baseline in script property EXPB_<IDX>_<date> (today's only); a reading at least
 * 5 minutes apart in EXPD_<IDX>_<date> (with its ATM straddle, the reading's uncertainty, from 15 Oct 2026) and closes in EXP_CLOSES_<IDX> (learning, track record; last 30 expiries). After
 * the close the GitHub job expiry-tape.yml copies the whole day (?mode=expiry_tape) to the private repository
 * (state/expiry/), where it is kept for good. The close is recorded after 15:45 IST by the first call.
 */
const EXP_RANGE_PCT = 3, EXP_KEEP = 30;
// Starting weights per index [k, m, e, u, v] (13 Oct 2026, owner: "set the weights to the history fit"): the fit of
// hub/expiry_history.py on 158 NIFTY, 82 BANK NIFTY (NSE end-of-day files) and 158 SENSEX expiries (BSE's, added 14 Oct
// 2026), Oct 2023 - Oct 2026 (walls and max
// pain from the evening before, the open as the 09:15 forward; state/expiry_history/summary.json in the private repo).
// Before: 0.30 / 0.20 for every index, guesses. Caveats: fitted at the open, not on readings through the day, and even
// fitted the formula did not beat the open on history (NIFTY 50.2 bp vs 49.9 walk-forward); live expiries re-fit them.
// Europe and US (e, u) were not in the history: 0.
// 14 Oct 2026 (owner: "set meter wall weights to zero"): k, m and v are now 0 for every index, and pinned there by
// EXP_SPREAD below. hub/expiry_intraday_test.py replayed 399 expiries minute by minute (Oct 2023 - Oct 2026): from every
// reading time 10:00-15:15, on every index, pulling toward max pain, the wall midpoint or next week's wall midpoint did
// no better than the current level (the forward), often slightly worse; next week's walls hurt NIFTY at several times.
// Was (history fit, 13 Oct): NIFTY [0.18, -0.13, 0, 0, 0.17], BANK NIFTY [-0.23, 0.19, 0, 0, 0.04], SENSEX [0.18, 0.10, 0, 0, -0.13].
const EXP_START = {
  NIFTY: [0, 0, 0, 0, 0],
  BANKNIFTY: [0, 0, 0, 0, 0],
  SENSEX: [0, 0, 0, 0, 0],
};
const EXP_IDX = [
  { id: 'NIFTY', label: 'NIFTY 50', exch: 'NFO', spot: 'NSE:NIFTY 50', step: 50, wd: 2, weekly: true },
  { id: 'SENSEX', label: 'SENSEX', exch: 'BFO', spot: 'BSE:SENSEX', step: 100, wd: 4, weekly: true },
  { id: 'BANKNIFTY', label: 'BANK NIFTY', exch: 'NFO', spot: 'NSE:NIFTY BANK', step: 100, wd: 2, weekly: false },
];

// since = "yyyy-MM-dd HH:mm" of the last minute the page already has: only newer chart rows are sent (a full day of
// rows is about 70 KB per index; every 10 seconds that would be resent for nothing).
function adminExpiry(token, since) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const out = expiryNow_(), cache = CacheService.getScriptCache(), s = String(since || '');
  out.sliced = !!s && s.slice(0, 10) === out.date;
  // Market hours only (13 Oct 2026, owner: after the close there is nothing to track): Version 60 wrote chart rows at
  // any hour, and those after-close minutes were all the chart showed that evening.
  const cut = rows => rows.filter(r => r[0] >= '09:15' && r[0] <= '15:30' && (!out.sliced || r[0] > s.slice(11)));
  (out.indices || []).forEach(x => {
    if (x.error) return;
    x.history = cut(JSON.parse(cache.get('exph_' + x.id + '_' + out.date) || '[]'));
    x.tape = cut(JSON.parse(cache.get('expw_' + x.id + '_' + out.date) || '[]'));
  });
  out.tape_fields = EXP_TAPE_FIELDS;
  return out;
}

function istNow_() {
  const d = new Date();
  return { date: Utilities.formatDate(d, 'Asia/Kolkata', 'yyyy-MM-dd'), hm: Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm'),
           ts: Utilities.formatDate(d, 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm:ssXXX") };
}

// Today's contracts, the next expiry and its contracts for every index, from Kite's NFO and BFO lists (one download
// per exchange a day). Never cache an empty list (13 Oct 2026: the first version did, and said "no expiry" on an expiry
// day); a failed download is remembered 10 minutes so it is not repeated on every 10-second build.
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
  const cache = CacheService.getScriptCache(), key = 'expl2_' + ex + '_' + date;
  const hit = cache.get(key) || cache.get(key + '_fail');
  if (hit) { const r = JSON.parse(hit); ids.forEach(id => { if (r[id]) { r[id].today = expiryUnpack_(r[id].today); r[id].nextList = expiryUnpack_(r[id].nextList); } }); return r; }
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
  ids.forEach(id => res[id] = { today: [], next: null, nextList: [], source: 'list' });
  if (iSym >= 0 && iExp >= 0) for (let n = 1; n < lines.length; n++) {
    const L = lines[n];
    if (!ids.some(id => L.indexOf('"' + id + '"') >= 0 || L.indexOf(',' + id + ',') >= 0)) continue;
    const c = L.split(','), id = (c[iName] || '').replace(/"/g, '');
    if (!res[id] || (c[iType] !== 'CE' && c[iType] !== 'PE')) continue;
    seen++;
    const e = c[iExp], R = res[id], o = [c[iSym], Number(c[iStrike]), c[iType], c[iTok]];
    if (e === date) R.today.push(o);
    else if (e > date) {                                // the next expiry's contracts: restart the list on a nearer date
      if (!R.next || e < R.next) { R.next = e; R.nextList = [o]; }
      else if (e === R.next) R.nextList.push(o);
    }
  }
  if (!seen) {
    const fail = {}; ids.forEach(id => fail[id] = { today: null, next: null, nextList: null, source: 'unavailable', diag: diag });
    try { cache.put(key + '_fail', JSON.stringify(fail), 600); } catch (e) {}
    return fail;
  }
  // Packed (strike, call token, put token; names rebuilt from the common prefix): four lists of 300+ strikes would pass
  // the cache's 100 KB limit unpacked, and an uncached list would be downloaded again on every build.
  const packed = {};
  ids.forEach(id => packed[id] = Object.assign({}, res[id], { today: expiryPack_(res[id].today), nextList: expiryPack_(res[id].nextList) }));
  try { cache.put(key, JSON.stringify(packed), 21600); }
  catch (e) { ids.forEach(id => packed[id].nextList = []); try { cache.put(key, JSON.stringify(packed), 21600); } catch (x) {} }   // today's matter most
  return res;
}

function expiryPack_(rows) {
  if (!rows || !rows.length) return rows;
  const f = rows[0], suf = String(f[1]) + f[2], root = f[0].slice(-suf.length) === suf ? f[0].slice(0, -suf.length) : '';
  const by = {}, x = [];
  rows.forEach(o => {
    if (!root || !o[3] || o[0] !== root + String(o[1]) + o[2]) { x.push(o); return; }
    const b = by[o[1]] || (by[o[1]] = [o[1], 0, 0]);
    b[o[2] === 'CE' ? 1 : 2] = Number(o[3]);
  });
  return { r: root, s: Object.keys(by).map(k => by[k]), x: x };
}

function expiryUnpack_(p) {
  if (!p || Array.isArray(p)) return p;
  const out = p.x.slice();
  p.s.forEach(b => { if (b[1]) out.push([p.r + b[0] + 'CE', b[0], 'CE', String(b[1])]); if (b[2]) out.push([p.r + b[0] + 'PE', b[0], 'PE', String(b[2])]); });
  return out;
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

// Fit of the five weights for one index from every stored reading against its expiry's close: a Bayesian ridge.
// 13 Oct 2026 (dry run before the first real expiry): an unweighted fit let one expiry with 2 readings swing k from
// 0.30 to -1.64, because the close differs from any reading mostly by the market's own later move (noise), and a
// least-squares fit reads that noise as signal. Now each reading carries the noise it really has (EXP_NOISE_PCT of the
// level, about the expiry-day remaining move), each expiry counts once, and every weight has a prior (start value and
// spread): one expiry can only nudge the weights; about a dozen consistent expiries are needed to move them
// substantially. Weights are also kept within sane bounds.
const EXP_NOISE_PCT = 0.4;
// Uncertainty of a reading (13 Oct 2026): the ATM straddle is about 0.8 standard deviations of the move left to expiry
// (E|move| = 0.8 sd), so sd = straddle / 0.8, with a floor so a near-zero straddle in the last minutes is not read as
// certainty. Readings stored before 15 Oct 2026 have no straddle and keep EXP_NOISE_PCT of the level.
const EXP_SD_PER_STRADDLE = 1 / 0.8, EXP_SD_FLOOR_PCT = 0.05;
function expirySd_(F, straddle) { return straddle ? Math.max(straddle * EXP_SD_PER_STRADDLE, F * EXP_SD_FLOOR_PCT / 100) : F * EXP_NOISE_PCT / 100; }
// Prior spread for k, m, e, u, v; starts in EXP_START. k, m and v are pinned (14 Oct 2026): a near-zero spread means a
// few live expiries cannot pull them off 0 -- one expiry moved m by 0.26 on 13 Oct, noise that 399 expiries outweigh.
// Re-open them only if the monthly intraday test (expiry-intraday.yml) shows a real gain. Europe/US still learn.
const EXP_SPREAD = [0.001, 0.001, 0.3, 0.3, 0.001];
const EXP_BOUNDS = [[-0.5, 1.5], [-0.5, 1.5], [-1, 1], [-1, 1], [-0.5, 1]];
function expiryModel_(id) {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES_' + id) || '{}');
  const X = [], Y = [], Wt = [];
  Object.keys(closes).forEach(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + id + '_' + d) || '[]');
    if (!pts.length) return;
    // Within an expiry, each reading counts by its own uncertainty (p[8] = ATM straddle, stored from 15 Oct 2026): a 15:00
    // reading with ~25 points left to move counts far more than a 10:00 one with ~120. Across expiries each still counts
    // as much as before (total weight of one expiry = 1 / (0.4% of its level)^2): the day's readings share one close, so
    // they are not independent, and taking the late readings' small noise at face value would let one expiry outweigh
    // the prior (see CHANGELOG 13 Oct 2026 for the dry run).
    const inv = pts.map(p => 1 / Math.pow(expirySd_(p[1], p[8]), 2)), tot = inv.reduce((a, b) => a + b, 0);
    const Fm = pts.reduce((a, p) => a + p[1], 0) / pts.length, sd0 = Fm * EXP_NOISE_PCT / 100;
    pts.forEach((p, i) => {
      const F = p[1];
      // p[7] (next expiry's wall midpoint) exists from 14 Oct 2026; older readings carry no information on v.
      X.push([p[2] - F, p[3] - F, F * (p[5] || 0) / 100, F * (p[6] || 0) / 100, p[7] != null ? p[7] - F : 0]); Y.push(closes[d] - F);
      Wt.push(inv[i] / tot / (sd0 * sd0));
    });
  });
  const P = 5, n = X.length;
  const S0 = EXP_START[id] || EXP_START.NIFTY;
  const out = { k: S0[0], m: S0[1], e: S0[2], u: S0[3], v: S0[4], start: S0, expiries: Object.keys(closes).length, samples: n };
  if (!n) return out;
  const A = [], r = [];
  for (let a = 0; a < P; a++) {
    A.push([]);
    const prec = 1 / (EXP_SPREAD[a] * EXP_SPREAD[a]);
    for (let b = 0; b < P; b++) A[a].push(X.reduce((t, x, i) => t + Wt[i] * x[a] * x[b], 0) + (a === b ? prec : 0));
    r.push(X.reduce((t, x, i) => t + Wt[i] * x[a] * Y[i], 0) + prec * S0[a]);
  }
  for (let c = 0; c < P; c++) {                      // Gaussian elimination with partial pivoting
    let piv = c; for (let i = c + 1; i < P; i++) if (Math.abs(A[i][c]) > Math.abs(A[piv][c])) piv = i;
    [A[c], A[piv]] = [A[piv], A[c]]; [r[c], r[piv]] = [r[piv], r[c]];
    if (!A[c][c]) return out;
    for (let i = c + 1; i < P; i++) { const f = A[i][c] / A[c][c]; for (let k = c; k < P; k++) A[i][k] -= f * A[c][k]; r[i] -= f * r[c]; }
  }
  const w = [0, 0, 0, 0, 0];
  for (let c = P - 1; c >= 0; c--) { let t = r[c]; for (let k = c + 1; k < P; k++) t -= A[c][k] * w[k]; w[c] = t / A[c][c]; }
  const r3 = (x, a) => Math.round(Math.max(EXP_BOUNDS[a][0], Math.min(EXP_BOUNDS[a][1], x)) * 1000) / 1000;
  return Object.assign(out, { k: r3(w[0], 0), m: r3(w[1], 1), e: r3(w[2], 2), u: r3(w[3], 3), v: r3(w[4], 4) });
}

function expiryAccuracy_(id) {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES_' + id) || '{}');
  return Object.keys(closes).sort().reverse().slice(0, 12).map(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + id + '_' + d) || '[]');
    // Each time's last reading: the meter's expected close (p[4], at..) and the market's forward at that moment (p[1],
    // f..). The forward is the bar to beat (13 Oct 2026): at 15:00 the move left is ~20-30 NIFTY points, so being within
    // 25 bp of the close says little unless the meter is closer than the market's own estimate.
    const last = hm => pts.filter(x => x[0] <= hm).pop() || null;
    const o = { date: d, close: closes[d], readings: pts.length };
    [['10', '10:00'], ['12', '12:00'], ['14', '14:00'], ['15', '15:00']].forEach(([k, hm]) => { const p = last(hm); o['at' + k] = p ? p[4] : null; o['f' + k] = p ? p[1] : null; });
    return o;
  });
}

// Model and track record read every stored expiry from script properties (quota 50,000 reads a day): cached an hour,
// cleared when a close is recorded.
function expiryTrack_(id) {
  const cache = CacheService.getScriptCache(), key = 'exp_ma2_' + id;
  const hit = cache.get(key);
  if (hit) return JSON.parse(hit);
  const t = { model: expiryModel_(id), accuracy: expiryAccuracy_(id) };
  try { cache.put(key, JSON.stringify(t), 3600); } catch (e) {}
  return t;
}

// How index options settle (checked 13 Oct 2026). At NSE and at BSE, NIFTY, BANK NIFTY and SENSEX options settle at the
// index's official close on expiry day, and the index close is built from its stocks' closing prices. Since 3 Aug 2026
// (SEBI) every stock with F&O contracts -- which includes every NIFTY 50, BANK NIFTY and SENSEX stock -- gets its closing
// price from a closing auction, 15:15-15:35, at one auction price, at both exchanges; before that both used each stock's
// volume-weighted price over 15:00-15:30. Averaging the index level through the last half hour therefore does NOT match
// today's rule for either exchange: under the auction the forward (options trade through it) is the market's estimate,
// and the meter states the rule instead of blending. SEBI's consultation (Sep 2026, comments closed 3 Oct) proposes
// settling derivatives on a 30-minute average of continuous trading again; reports expect a circular in Oct 2026. When
// it lands, set method 'average' and the window it names (e.g. '15:00'-'15:30', or '14:45'-'15:15' if continuous
// trading still stops at 15:15): the meter then blends expected close = (elapsed / window) x average so far +
// (left / window) x model, and narrows the range to the part still unknown.
const EXP_SETTLE = { method: 'auction', from: '15:15', to: '15:35', since: '3 Aug 2026' };
function expMins_(hm) { return Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3, 5)); }

// Settlement averaging (method 'average' only): the index level once per minute of the window, kept in the cache per
// index and day (under 1 KB); returns the blend weight, the average so far and the blended expected close.
function expirySettle_(id, now, spot, model) {
  const S = EXP_SETTLE, out = { method: S.method, from: S.from, to: S.to, since: S.since || null };
  if (S.method !== 'average' || now.hm < S.from) return out;
  const cache = CacheService.getScriptCache(), key = 'exps_' + id + '_' + now.date;
  const m = JSON.parse(cache.get(key) || '{}');
  if (now.hm < S.to && m[now.hm] == null) {
    m[now.hm] = Math.round(spot * 100) / 100;
    const lock = LockService.getScriptLock();
    if (lock.tryLock(1000)) {
      try {
        const cur = JSON.parse(cache.get(key) || '{}');          // another call may have written this minute already
        if (cur[now.hm] == null) cur[now.hm] = m[now.hm];
        Object.assign(m, cur);
        cache.put(key, JSON.stringify(cur), 21600);
      } finally { lock.releaseLock(); }
    }
  }
  const v = Object.keys(m).filter(k => k >= S.from && k < S.to).map(k => m[k]);
  if (!v.length) return out;
  const span = expMins_(S.to) - expMins_(S.from), w = Math.max(0, Math.min(1, (expMins_(now.hm) - expMins_(S.from)) / span));
  const avg = v.reduce((a, b) => a + b, 0) / v.length;
  return Object.assign(out, { avg: Math.round(avg * 100) / 100, minutes: v.length, weight: Math.round(w * 1000) / 1000,
                              blended: w * avg + (1 - w) * model });
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

// One expiry's chain from a snapshot's option list: strikes within pct% of spot, call and put price and open interest.
function expiryChain_(opts, q, ix, spot, pct) {
  const ch = {};
  (opts || []).forEach(s => { if (s[4] !== ix.id) return;
    const x = q[ix.exch + ':' + s[0]]; if (!x || Math.abs(s[1] / spot - 1) * 100 > pct) return;
    const r = ch[s[1]] || (ch[s[1]] = { strike: s[1], ce: null, pe: null, ce_oi: 0, pe_oi: 0 });
    if (s[2] === 'CE') { r.ce = x[0]; r.ce_oi = x[2] || 0; } else { r.pe = x[0]; r.pe_oi = x[2] || 0; } });
  return Object.keys(ch).map(Number).sort((a, b) => a - b).map(s => ch[s]);
}

// Walls, max pain and sellers' settlement payout for one chain. payout(x) = what option sellers pay buyers if the index
// settles at x (OI in units x points in the money = rupees), within the chain's strikes.
function expiryWalls_(rows, spot) {
  const atm = rows.reduce((b, r) => Math.abs(r.strike - spot) < Math.abs(b.strike - spot) ? r : b);
  // The ATM strike counts on both sides (review, 13 Oct 2026): with strict above/below, a pinned strike flipped from
  // call wall to put wall as spot crossed it and the expected close jumped up to ~100 points on a 3-point move.
  const above = rows.filter(r => r.strike >= atm.strike), below = rows.filter(r => r.strike <= atm.strike);
  const cw = above.slice().sort((a, b) => b.ce_oi - a.ce_oi), pw = below.slice().sort((a, b) => b.pe_oi - a.pe_oi);
  const payout = x => rows.reduce((t, r) => t + r.ce_oi * Math.max(0, x - r.strike) + r.pe_oi * Math.max(0, r.strike - x), 0);
  return { atm: atm, cw: cw, pw: pw, callWall: cw.length ? cw[0].strike : atm.strike, putWall: pw.length ? pw[0].strike : atm.strike,
           MP: rows.reduce((b, r) => payout(r.strike) < payout(b.strike) ? r : b).strike, payout: payout,
           F: atm.strike + (atm.ce || 0) - (atm.pe || 0), straddle: (atm.ce || 0) + (atm.pe || 0),
           ceAll: rows.reduce((t, r) => t + r.ce_oi, 0), peAll: rows.reduce((t, r) => t + r.pe_oi, 0) };
}

// Open interest per strike at the day's first reading, for today's chain (c) and the next expiry's (n): the baseline of
// every "change since" (before 09:15 it is the previous close's OI). Written once per chain; old days are removed.
function expiryBaseline_(id, date, hm, rows, nrows, nexp) {
  const cache = CacheService.getScriptCache(), props = PropertiesService.getScriptProperties(), key = 'EXPB_' + id + '_' + date;
  let b = JSON.parse(cache.get(key) || 'null');
  if (!b) { b = JSON.parse(props.getProperty(key) || 'null'); if (b) cache.put(key, JSON.stringify(b), 21600); }
  const pack = rs => { const o = {}; rs.forEach(r => o[r.strike] = [r.ce_oi, r.pe_oi]); return o; };
  const live = rs => rs.length >= 5 && rs.some(r => r.ce_oi || r.pe_oi);     // never a baseline of zeros
  const want = (!b && live(rows)) || (b && !b.n && live(nrows));
  if (!want) return b;
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(2000)) return b;
  try {
    b = JSON.parse(props.getProperty(key) || 'null');                       // another call may have just written it
    if (!b && live(rows)) {
      b = { hm: hm, c: pack(rows) };
      props.getKeys().forEach(k => { if (/^EXPB_/.test(k) && k.slice(-10) < date) props.deleteProperty(k); });
    }
    if (b && !b.n && live(nrows)) { b.n = pack(nrows); b.nhm = hm; b.nexp = nexp; }
    if (b) { props.setProperty(key, JSON.stringify(b)); cache.put(key, JSON.stringify(b), 21600); }
  } finally { lock.releaseLock(); }
  return b;
}

// Columns of the sellers' record (one row a minute). OI in lakh units; money in rupees crore.
const EXP_TAPE_FIELDS = ['time', 'spot', 'forward', 'straddle', 'max_pain', 'call_wall', 'call_wall_oi_lakh', 'put_wall', 'put_wall_oi_lakh',
  'calls_oi_lakh', 'puts_oi_lakh', 'sellers_pay_here_cr', 'cost_step_up_cr', 'cost_step_down_cr',
  'next_call_wall', 'next_call_wall_oi_lakh', 'next_put_wall', 'next_put_wall_oi_lakh', 'next_max_pain', 'next_calls_oi_lakh', 'next_puts_oi_lakh'];

// One index's reading from the shared snapshot; also its chart point, its sellers' record row, its learning sample and,
// after 15:45, its close.
function expiryIndex_(ix, snap, now, M, ov) {
  const q = snap.q, sx = q[ix.spot];
  if (!sx) return { id: ix.id, label: ix.label, error: 'Kite did not return the ' + ix.label + ' level.' };
  const spot = sx[0];
  if (now.hm >= '15:45') expiryRecordClose_(ix.id, now.date, spot);   // needs only the index level, not the chain
  const rows = expiryChain_(snap.opts, q, ix, spot, EXP_RANGE_PCT);
  if (!rows.length) return null;                       // name guess found nothing: not expiring today
  if (rows.length < 5) return { id: ix.id, label: ix.label, error: 'Too few ' + ix.label + ' strikes quoted.' };
  const C = expiryWalls_(rows, spot), F = C.F, MP = C.MP, W = (C.callWall + C.putWall) / 2;

  // The next expiry's chain (Market.gs reads it once a minute on expiry days, in its own request).
  const nx = snap.nx || null, nexp = nx && nx.expiry ? nx.expiry[ix.id] : null;
  const nrows = nx && !nx.error ? expiryChain_(nx.opts, nx.q, ix, spot, EXP_RANGE_PCT) : [];
  const N = nrows.length >= 5 ? expiryWalls_(nrows, spot) : null;
  const NW = N ? (N.callWall + N.putWall) / 2 : null;

  const eu = ov.eu, us = ov.us;   // null when not trading today or unavailable
  const model = F + M.k * (MP - F) + M.m * (W - F) + (M.e || 0) * F * (eu || 0) / 100 + (M.u || 0) * F * (us || 0) / 100 + (NW != null ? (M.v || 0) * (NW - F) : 0);
  const r2 = x => Math.round(x * 100) / 100, L = x => x == null ? null : Math.round(x / 1e3) / 100, cr = x => Math.round(x / 1e5) / 100;
  // From the settlement window on (method 'average' only) the average so far carries its share of the expected close;
  // the likely range is one standard deviation of the move left (straddle / 0.8), narrowed to the part not yet averaged.
  const ST = expirySettle_(ix.id, now, spot, model), pred = ST.blended != null ? ST.blended : model;
  const sd = expirySd_(F, C.straddle) * (1 - (ST.weight || 0));

  // Changes since the day's first reading.
  const B = expiryBaseline_(ix.id, now.date, now.hm, rows, nrows, nexp);
  const chg = (b, r, i) => b && b[r.strike] ? (i ? r.pe_oi : r.ce_oi) - b[r.strike][i] : null;
  const walls = (list, b, i) => list.slice(0, 3).map(r => [r.strike, i ? r.pe_oi : r.ce_oi, chg(b, r, i)]);
  const sumChg = (rs, b, i) => { if (!b) return null; let t = 0, n = 0; rs.forEach(r => { const c = chg(b, r, i); if (c != null) { t += c; n++; } }); return n ? t : null; };
  const top = (rs, b, i, sign) => rs.map(r => [r.strike, chg(b, r, i)]).filter(x => x[1] != null && x[1] * sign > 0)
    .sort((a, c) => (c[1] - a[1]) * sign).slice(0, 3);
  const Bc = B ? B.c : null, Bn = B && B.n && B.nexp === nexp ? B.n : null;
  const pay = C.payout;
  const near = rs => rs.filter(r => Math.abs(r.strike / spot - 1) * 100 <= 1.5);

  const out = {
    id: ix.id, label: ix.label, spot: r2(spot), forward: r2(F), max_pain: MP, wall_mid: W, call_wall: C.callWall, put_wall: C.putWall,
    call_walls: walls(C.cw, Bc, 0), put_walls: walls(C.pw, Bc, 1), step: ix.step,
    atm: C.atm.strike, straddle: r2(C.straddle), range: [r2(pred - C.straddle), r2(pred + C.straddle)], prediction: r2(pred),
    // likely = +-1 sd (about 2 in 3); range (+-straddle, about 3 in 5) is kept as it was for the phone's straddle row.
    sd: r2(sd), likely: [r2(pred - sd), r2(pred + sd)], model_close: r2(model), settle: ST,
    pcr: C.ceAll ? Math.round(C.peAll / C.ceAll * 100) / 100 : null, model: M, strikes: rows.length,
    rows: near(rows).map(r => [r.strike, r.ce_oi, r.pe_oi, chg(Bc, r, 0), chg(Bc, r, 1)]),
    oi: { calls: C.ceAll, puts: C.peAll, calls_chg: sumChg(rows, Bc, 0), puts_chg: sumChg(rows, Bc, 1), since: B ? B.hm : null,
          writing: { calls: top(rows, Bc, 0, 1), puts: top(rows, Bc, 1, 1) }, covering: { calls: top(rows, Bc, 0, -1), puts: top(rows, Bc, 1, -1) } },
    // What option sellers pay at settlement (within +-3% of spot): here, at max pain, and the extra for one step up or down.
    sellers: { here: cr(pay(spot)), at_max_pain: cr(pay(MP)), step_up: cr(pay(spot + ix.step) - pay(spot)), step_down: cr(pay(spot - ix.step) - pay(spot)) },
    next: !nexp ? null : !N ? { expiry: nexp, error: nx && nx.error ? 'Next expiry\'s chain not read: ' + String(nx.error).slice(0, 80) : 'Next expiry\'s chain not read yet.' } : {
      expiry: nexp, as_of: nx.hm, call_wall: N.callWall, put_wall: N.putWall, wall_mid: NW, max_pain: N.MP, atm: N.atm.strike, straddle: r2(N.straddle),
      call_walls: walls(N.cw, Bn, 0), put_walls: walls(N.pw, Bn, 1), pcr: N.ceAll ? Math.round(N.peAll / N.ceAll * 100) / 100 : null,
      oi: { calls: N.ceAll, puts: N.peAll, calls_chg: sumChg(nrows, Bn, 0), puts_chg: sumChg(nrows, Bn, 1), since: Bn ? B.nhm : null,
            writing: { calls: top(nrows, Bn, 0, 1), puts: top(nrows, Bn, 1, 1) } },
      rows: near(nrows).map(r => [r.strike, r.ce_oi, r.pe_oi, chg(Bn, r, 0), chg(Bn, r, 1)]) }
  };

  // After 15:30 the meter stops tracking (13 Oct 2026, owner): it shows its last market-hours reading and, once recorded
  // after 15:45, the actual close.
  if (now.hm > '15:30') {
    const H = JSON.parse(CacheService.getScriptCache().get('exph_' + ix.id + '_' + now.date) || '[]').filter(r => r[0] >= '09:15' && r[0] <= '15:30');
    const P = JSON.parse(PropertiesService.getScriptProperties().getProperty('EXPD_' + ix.id + '_' + now.date) || '[]');
    const lh = H.length ? H[H.length - 1] : null, lp = P.length ? P[P.length - 1] : null;
    out.final = lh && (!lp || lh[0] >= lp[0]) ? { hm: lh[0], prediction: lh[1], forward: lh[3] } : lp ? { hm: lp[0], prediction: lp[4], forward: lp[1] } : null;
    out.closed = JSON.parse(PropertiesService.getScriptProperties().getProperty('EXP_CLOSES_' + ix.id) || '{}')[now.date] || null;
  }
  // Per-minute chart point and sellers' record row (cache), and a reading at least 5 minutes apart (property, for
  // learning); market hours only.
  if (now.hm < '09:15' || now.hm > '15:30') return out;
  const cache = CacheService.getScriptCache(), lock = LockService.getScriptLock();
  const hk = 'exph_' + ix.id + '_' + now.date, wk = 'expw_' + ix.id + '_' + now.date;
  if (lock.tryLock(2000)) {
    try {
      const hist = JSON.parse(cache.get(hk) || '[]');
      if (!hist.length || hist[hist.length - 1][0] !== now.hm) { hist.push([now.hm, r2(pred), r2(spot), r2(F), MP, W]); cache.put(hk, JSON.stringify(hist), 21600); }
      const tape = JSON.parse(cache.get(wk) || '[]');
      if (!tape.length || tape[tape.length - 1][0] !== now.hm) {
        tape.push([now.hm, r2(spot), r2(F), r2(C.straddle), MP, C.callWall, L(C.cw.length ? C.cw[0].ce_oi : null), C.putWall, L(C.pw.length ? C.pw[0].pe_oi : null),
                   L(C.ceAll), L(C.peAll), out.sellers.here, out.sellers.step_up, out.sellers.step_down,
                   N ? N.callWall : null, N && N.cw.length ? L(N.cw[0].ce_oi) : null, N ? N.putWall : null, N && N.pw.length ? L(N.pw[0].pe_oi) : null,
                   N ? N.MP : null, N ? L(N.ceAll) : null, N ? L(N.peAll) : null]);
        cache.put(wk, JSON.stringify(tape), 21600);
      }
      const mins = hm => Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3));
      const lk = 'exp_last_' + ix.id + '_' + now.date, lastSample = cache.get(lk);
      if (!lastSample || mins(now.hm) - mins(lastSample) >= 5) {
        const props = PropertiesService.getScriptProperties(), pk = 'EXPD_' + ix.id + '_' + now.date;
        const pts = JSON.parse(props.getProperty(pk) || '[]');
        cache.put(lk, now.hm, 21600);
        if (!pts.length || mins(now.hm) - mins(pts[pts.length - 1][0]) >= 5) { pts.push([now.hm, r2(F), MP, W, r2(pred), eu, us, NW, r2(C.straddle)]); props.setProperty(pk, JSON.stringify(pts)); }
      }
    } finally { lock.releaseLock(); }
  }
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
  CacheService.getScriptCache().remove('exp_ma2_' + id);   // re-fit with the new close on the next call
}

/** live.yml (every 5 minutes) and expiry-tape.yml (every minute on expiry days) call ?mode=expiry_close&key=RELAY_KEY:
 *  readings (from 09:05: the first one sets the OI baseline; recorded 09:15-15:30) and closes (after 15:45) are kept
 *  even if nobody opens the meter, and the answer (no chart rows) is what live.yml writes to docs/data/expiry.json for
 *  the phone -- so neither job makes a Kite call of its own. Outside reading times it says which indices expire today. */
function expiryCloseHook_(key) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  const now = istNow_();
  if (now.hm < '09:05' || (now.hm > '15:30' && now.hm < '15:45')) {
    const lists = expiryLists_(now.date);
    return { ok: true, note: 'outside reading times', date: now.date,
             listed: EXP_IDX.filter(ix => lists[ix.id].today && lists[ix.id].today.length).map(ix => ix.id),
             lists_ok: EXP_IDX.every(ix => lists[ix.id].today !== null) };
  }
  if (now.hm >= '15:45') CacheService.getScriptCache().remove('exp_now2');
  const out = JSON.parse(JSON.stringify(expiryNow_()));
  (out.indices || []).forEach(x => delete x.history);
  out.ok = true;
  return out;
}

/** expiry-tape.yml, after 15:45 IST (?mode=expiry_tape&key=RELAY_KEY): the whole day of every index that expired today
 *  -- sellers' record, prediction chart, OI baseline, learning readings, close -- for the private repository, where it
 *  is kept for good (the cache keeps it 6 hours, the script properties only the 5-minute readings). */
function expiryTapeHook_(key) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  const now = istNow_(), cache = CacheService.getScriptCache(), out = { ok: true, date: now.date, ts: now.ts, indices: [] };
  EXP_IDX.forEach(ix => {
    const g = k => JSON.parse(cache.get(k + '_' + ix.id + '_' + now.date) || 'null');
    const hours = a => a ? a.filter(r => r[0] >= '09:15' && r[0] <= '15:30') : a;
    const tape = hours(g('expw')), hist = hours(g('exph')), samples = JSON.parse(props.getProperty('EXPD_' + ix.id + '_' + now.date) || 'null');
    if (!tape && !hist && !samples) return;
    const base = JSON.parse(props.getProperty('EXPB_' + ix.id + '_' + now.date) || 'null');
    const closes = JSON.parse(props.getProperty('EXP_CLOSES_' + ix.id) || '{}');
    out.indices.push({ id: ix.id, label: ix.label, expiry: now.date, next_expiry: base ? base.nexp || null : null, close: closes[now.date] || null,
      model_after_close: expiryTrack_(ix.id).model, tape_fields: EXP_TAPE_FIELDS, tape: tape || [],
      history_fields: ['time', 'expected_close', 'spot', 'forward', 'max_pain', 'wall_mid'], history: hist || [],
      sample_fields: ['time', 'forward', 'max_pain', 'wall_mid', 'expected_close', 'europe_pct', 'us_pct', 'next_wall_mid', 'straddle'], samples: samples || [],
      settle: EXP_SETTLE, settle_minutes: JSON.parse(cache.get('exps_' + ix.id + '_' + now.date) || 'null'),
      baseline: base });
  });
  return out;
}
