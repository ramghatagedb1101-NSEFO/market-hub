/**
 * NIFTY expiry meter (13 Oct 2026). On a NIFTY expiry day the dashboard's Analysis -> Expiry meter page asks
 * for this every 10 seconds; the answer is computed from a live Kite quote of today's NIFTY options (cached
 * 10 s, so many viewers cost one Kite call).
 *
 * Expected close = F + k*(MP - F) + m*(W - F), where
 *   F  = forward from put-call parity at the ATM strike (strike + call - put): the market's own expected settlement;
 *   MP = max pain (settlement where option buyers collect least);
 *   W  = midpoint of the call wall and the put wall (top OI strikes above / below spot).
 * k and m start at 0.30 / 0.20 and are re-fitted after every expiry from what the meter said during the day
 * against the actual close (least squares, pulled towards the starting values while there are few expiries).
 *
 * Storage: today's per-minute points in the script cache (chart); a sample at least 5 minutes apart per expiry in script
 * property EXPD_<date> and closes in EXP_CLOSES (learning and the accuracy table); last 30 expiries kept.
 * The close is recorded after 15:45 IST by the first call (live.yml calls mode=expiry_close every run).
 */
const EXP_K0 = 0.30, EXP_M0 = 0.20, EXP_PRIOR_SAMPLES = 20, EXP_RANGE_PCT = 4, EXP_KEEP = 30;

function adminExpiry(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return expiryNow_();
}

function istNow_() {
  const d = new Date();
  return { date: Utilities.formatDate(d, 'Asia/Kolkata', 'yyyy-MM-dd'), hm: Utilities.formatDate(d, 'Asia/Kolkata', 'HH:mm'),
           ts: Utilities.formatDate(d, 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm:ssXXX") };
}

// Today's (or the next) NIFTY option contracts from Kite's public instrument list; cached for the day.
function expirySyms_(date) {
  const cache = CacheService.getScriptCache(), key = 'exps_' + date;
  const hit = cache.get(key);
  if (hit) return JSON.parse(hit);
  const csv = UrlFetchApp.fetch('https://api.kite.trade/instruments/NFO', { muteHttpExceptions: true }).getContentText();
  const lines = csv.split('\n');
  const head = lines[0].split(','), iSym = head.indexOf('tradingsymbol'), iName = head.indexOf('name'),
        iExp = head.indexOf('expiry'), iStrike = head.indexOf('strike'), iType = head.indexOf('instrument_type');
  let next = null; const todays = [];
  for (let n = 1; n < lines.length; n++) {
    const L = lines[n];
    if (L.indexOf('"NIFTY"') < 0 && L.indexOf(',NIFTY,') < 0) continue;
    const c = L.split(',');
    if (c[iName].replace(/"/g, '') !== 'NIFTY' || (c[iType] !== 'CE' && c[iType] !== 'PE')) continue;
    const e = c[iExp];
    if (e === date) todays.push([c[iSym], Number(c[iStrike]), c[iType]]);
    else if (e > date && (!next || e < next)) next = e;
  }
  const out = { today: todays, next: next };
  try { cache.put(key, JSON.stringify(out), 21600); } catch (e) { /* too big: refetch next time */ }
  return out;
}

function expiryModel_() {
  const props = PropertiesService.getScriptProperties();
  const closes = JSON.parse(props.getProperty('EXP_CLOSES') || '{}');
  let s11 = 0, s12 = 0, s22 = 0, s1y = 0, s2y = 0, n = 0, scale = 0;
  Object.keys(closes).forEach(d => {
    const pts = JSON.parse(props.getProperty('EXPD_' + d) || '[]');
    pts.forEach(p => { const F = p[1], x1 = p[2] - F, x2 = p[3] - F, y = closes[d] - F;
      s11 += x1 * x1; s12 += x1 * x2; s22 += x2 * x2; s1y += x1 * y; s2y += x2 * y; scale += (x1 * x1 + x2 * x2) / 2; n++; });
  });
  if (!n) return { k: EXP_K0, m: EXP_M0, expiries: 0, samples: 0 };
  const lam = EXP_PRIOR_SAMPLES * scale / n;
  const a = s11 + lam, b = s12, c = s22 + lam, r1 = s1y + lam * EXP_K0, r2 = s2y + lam * EXP_M0, det = a * c - b * b;
  if (!det) return { k: EXP_K0, m: EXP_M0, expiries: Object.keys(closes).length, samples: n };
  const k = (r1 * c - b * r2) / det, m = (a * r2 - b * r1) / det;
  return { k: Math.round(k * 1000) / 1000, m: Math.round(m * 1000) / 1000, expiries: Object.keys(closes).length, samples: n };
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
  const headers = kiteHeaders_();
  const syms = expirySyms_(now.date);
  const base = { ts: now.ts, date: now.date, next_expiry: syms.next, model: expiryModel_(), accuracy: expiryAccuracy_() };
  if (!syms.today.length) return Object.assign(base, { expiry_today: false });
  if (!headers) return Object.assign(base, { expiry_today: true, error: 'No Kite login for today: log in with the Kite link.' });

  // One quote call: spot + options within the range (spot range from yesterday's cached spot or all strikes).
  const lastSpot = Number(cache.get('exp_spot') || 0);
  const pick = syms.today.filter(s => !lastSpot || Math.abs(s[1] / lastSpot - 1) * 100 <= EXP_RANGE_PCT).slice(0, 480);
  const url = 'https://api.kite.trade/quote?' + ['NSE:NIFTY 50'].concat(pick.map(s => 'NFO:' + s[0])).map(s => 'i=' + encodeURIComponent(s)).join('&');
  const body = JSON.parse(UrlFetchApp.fetch(url, { muteHttpExceptions: true, headers: headers }).getContentText());
  if (body.status !== 'success') { kiteFailed_(body.message); return Object.assign(base, { expiry_today: true, error: kiteReason_(body.message) }); }
  const q = body.data, spot = q['NSE:NIFTY 50'].last_price;
  cache.put('exp_spot', String(spot), 21600);

  const ch = {};
  pick.forEach(s => { const x = q['NFO:' + s[0]]; if (!x || Math.abs(s[1] / spot - 1) * 100 > EXP_RANGE_PCT) return;
    const r = ch[s[1]] || (ch[s[1]] = { strike: s[1], ce: null, pe: null, ce_oi: 0, pe_oi: 0 });
    if (s[2] === 'CE') { r.ce = x.last_price; r.ce_oi = x.oi || 0; } else { r.pe = x.last_price; r.pe_oi = x.oi || 0; } });
  const rows = Object.keys(ch).map(Number).sort((a, b) => a - b).map(s => ch[s]);
  if (rows.length < 5) return Object.assign(base, { expiry_today: true, error: 'Too few NIFTY strikes quoted.' });
  const atm = rows.reduce((b, r) => Math.abs(r.strike - spot) < Math.abs(b.strike - spot) ? r : b);
  const F = atm.strike + (atm.ce || 0) - (atm.pe || 0);
  const straddle = (atm.ce || 0) + (atm.pe || 0);
  const above = rows.filter(r => r.strike > spot), below = rows.filter(r => r.strike < spot);
  const cw = above.slice().sort((a, b) => b.ce_oi - a.ce_oi), pw = below.slice().sort((a, b) => b.pe_oi - a.pe_oi);
  const callWall = cw.length ? cw[0].strike : atm.strike, putWall = pw.length ? pw[0].strike : atm.strike;
  const payout = x => rows.reduce((t, r) => t + r.ce_oi * Math.max(0, x - r.strike) + r.pe_oi * Math.max(0, r.strike - x), 0);
  const MP = rows.reduce((b, r) => payout(r.strike) < payout(b.strike) ? r : b).strike;
  const W = (callWall + putWall) / 2;
  const M = base.model;
  const pred = F + M.k * (MP - F) + M.m * (W - F);
  const ceAll = rows.reduce((t, r) => t + r.ce_oi, 0), peAll = rows.reduce((t, r) => t + r.pe_oi, 0);
  const r2 = x => Math.round(x * 100) / 100;

  const out = Object.assign(base, {
    expiry_today: true, spot: r2(spot), forward: r2(F), max_pain: MP, wall_mid: W, call_wall: callWall, put_wall: putWall,
    call_walls: cw.slice(0, 3).map(r => [r.strike, r.ce_oi]), put_walls: pw.slice(0, 3).map(r => [r.strike, r.pe_oi]),
    atm: atm.strike, straddle: r2(straddle), range: [r2(pred - straddle), r2(pred + straddle)], prediction: r2(pred),
    pcr: ceAll ? Math.round(peAll / ceAll * 100) / 100 : null,
    rows: rows.filter(r => Math.abs(r.strike / spot - 1) * 100 <= 1.5).map(r => [r.strike, r.ce_oi, r.pe_oi])
  });

  // History: per-minute points (cache, for the chart) and a 5-minute sample (property, for learning).
  const lock = LockService.getScriptLock();
  if (lock.tryLock(2000)) {
    try {
      const hk = 'exph_' + now.date;
      const hist = JSON.parse(cache.get(hk) || '[]');
      if (!hist.length || hist[hist.length - 1][0] !== now.hm) { hist.push([now.hm, r2(pred), r2(spot), r2(F), MP, W]); cache.put(hk, JSON.stringify(hist), 21600); }
      if (now.hm >= '09:15' && now.hm <= '15:30') {
        const props = PropertiesService.getScriptProperties(), pk = 'EXPD_' + now.date;
        const pts = JSON.parse(props.getProperty(pk) || '[]');
        const mins = hm => Number(hm.slice(0, 2)) * 60 + Number(hm.slice(3));
        if (!pts.length || mins(now.hm) - mins(pts[pts.length - 1][0]) >= 5) { pts.push([now.hm, r2(F), MP, W, r2(pred)]); props.setProperty(pk, JSON.stringify(pts)); }
      }
    } finally { lock.releaseLock(); }
  }
  out.history = JSON.parse(cache.get('exph_' + now.date) || '[]');
  if (now.hm >= '15:45') expiryRecordClose_(now.date, spot);
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
