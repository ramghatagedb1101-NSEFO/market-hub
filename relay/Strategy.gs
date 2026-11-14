/**
 * Strategy builder (14 Nov 2026, owner: "a strategy builder page also on the admin dashboard. defining signals, SL
 * levels, trailing SL levels, GTC order or EOD order"; "one strategy out of each saved strategy can be applied during
 * the market ... depending on the market situation").
 *   Saved strategies: script properties STRAT_* (chunked, as paper trades). The one switched on: STRAT_ACTIVE (or none).
 *   Safety limits for the trading machine (lots per order, day's loss): STRAT_LIMITS.
 *   The algo-sync job reads all three with RELAY_KEY (?mode=strategies) and copies them to the trading machine, which
 *   switches within seconds of the copy (new trades only). A switch, a limits change or an edit of the active strategy
 *   starts that job at once (stratPushNow_), so it lands in a minute or two; it also runs every 10 minutes in market
 *   hours.
 *   Back-tests: a GitHub job (strategy-backtest.yml) per request; results in the private repo state/backtests/<id>.json.
 * The program on the machine checks every field again (trader/strategies/rules.py clean()); this side keeps the
 * stored copy tidy and small.
 */
const STRAT_MAX = 60;

function stratList_() { return paperStoreLoad_('STRAT_'); }
function stratSave_(list) { paperStoreSave_('STRAT_', list, STRAT_MAX); }
function stratActive_() { return PropertiesService.getScriptProperties().getProperty('STRAT_ACTIVE') || ''; }
function stratLimits_() {
  let l = {}; try { l = JSON.parse(PropertiesService.getScriptProperties().getProperty('STRAT_LIMITS') || '{}'); } catch (e) {}
  return { max_lots_per_order: Number(l.max_lots_per_order) || 1, max_daily_loss: Number(l.max_daily_loss) || 10000 };
}
function stratNum_(x, lo, hi, d) { const v = Number(x); return isFinite(v) ? Math.min(Math.max(v, lo), hi) : d; }
function stratTime_(x, d) { x = String(x || ''); return /^\d\d:\d\d$/.test(x) && x >= '09:15' && x <= '15:30' ? x : d; }
const STRAT_SIGNALS = ['price_ma', 'ma_cross', 'rsi', 'orb', 'change', 'dte', 'weekday', 'compare'];
// The general comparison's data points (trader/indicators.py OPERANDS) and comparisons.
const STRAT_OPERANDS = ['price', 'open', 'high', 'low', 'close', 'day_open', 'day_high', 'day_low', 'prev_close', 'prev_high',
  'prev_low', 'orb_high', 'orb_low', 'ema', 'sma', 'rsi', 'atr', 'chg_prev', 'chg_open', 'opt_price', 'dte', 'value'];
const STRAT_OPS = ['>', '<', '>=', '<=', 'crosses_above', 'crosses_below'];
function stratOperand_(o) {
  if (!o || STRAT_OPERANDS.indexOf(o.src) < 0) return null;
  const out = { src: o.src };
  if (o.src === 'value') out.value = stratNum_(o.value, -1e9, 1e9, 0);
  if (['ema', 'sma', 'rsi', 'atr', 'orb_high', 'orb_low'].indexOf(o.src) >= 0) out.n = Math.round(stratNum_(o.n, 1, 500, /^orb/.test(o.src) ? 15 : 14));
  return out;
}
function stratSignal_(x) {
  if (!x || STRAT_SIGNALS.indexOf(x.type) < 0) return null;
  if (x.type === 'compare') {
    const l = stratOperand_(x.left), r = stratOperand_(x.right);
    if (!l || !r) return null;
    let op = STRAT_OPS.indexOf(x.op) >= 0 ? x.op : '>';
    if (/^crosses/.test(op) && (l.src === 'opt_price' || r.src === 'opt_price')) op = op === 'crosses_above' ? '>' : '<';
    return { type: 'compare', left: l, op: op, right: r, tf: [1, 3, 5, 15].indexOf(Number(x.tf)) >= 0 ? Number(x.tf) : 5 };
  }
  const o = { type: x.type };
  ['ma', 'op', 'dir', 'from'].forEach(k => { if (x[k] != null) o[k] = String(x[k]).slice(0, 20); });
  ['period', 'tf', 'fast', 'slow', 'level', 'minutes', 'pct', 'days'].forEach(k => { if (x[k] != null && x[k] !== '' && isFinite(Number(x[k]))) o[k] = Number(x[k]); });
  if (Array.isArray(x.days)) o.days = x.days.map(Number).filter(d => d >= 1 && d <= 5);
  return o;
}

function stratClean_(s) {
  s = s || {};
  const st = s.strike || {}, ex = s.exits || {}, w = s.window || {};
  const style = s.style === 'carry' ? 'carry' : 'intraday';
  const pick = (v, ok, d) => ok.indexOf(v) >= 0 ? v : d;
  // Groups (14 Nov 2026): enter when any / all groups are true, each group all / any of its signals. Older strategies
  // ("match" + "signals") become one group.
  const raw = Array.isArray(s.groups) && s.groups.length ? s.groups : [{ match: s.match, signals: s.signals }];
  const groups = raw.slice(0, 5).map(g => ({ match: (g && g.match) === 'any' ? 'any' : 'all',
    signals: ((g && g.signals) || []).map(stratSignal_).filter(Boolean).slice(0, 8) })).filter(g => g.signals.length);
  return {
    id: /^s_[a-z0-9]{6,20}$/.test(s.id || '') ? s.id : 's_' + Utilities.getUuid().replace(/-/g, '').slice(0, 10),
    name: String(s.name || 'Unnamed strategy').slice(0, 80), notes: String(s.notes || '').slice(0, 500),
    index: pick(s.index, ['NIFTY', 'BANKNIFTY'], 'NIFTY'), side: pick(s.side, ['BUY', 'SELL'], 'BUY'), right: pick(s.right, ['C', 'P'], 'C'),
    strike: st.mode === 'premium' ? { mode: 'premium', near: stratNum_(st.near, 1, 5000, 100) } : { mode: 'atm', steps: Math.round(stratNum_(st.steps, -10, 20, 0)) },
    expiry: pick(s.expiry, ['nearest', 'next', 'monthly'], 'nearest'), lots: Math.round(stratNum_(s.lots, 1, 50, 1)),
    window: { from: stratTime_(w.from, '09:30'), until: stratTime_(w.until, '14:30') },
    groups: groups, groups_match: s.groups_match === 'all' ? 'all' : 'any',
    exits: { sl_type: ex.sl_type === 'points' ? 'points' : 'pct', sl: stratNum_(ex.sl, 0, 1000, 25),
             target_type: ex.target_type === 'points' ? 'points' : 'pct', target: stratNum_(ex.target, 0, 5000, 0),
             trail_after_type: ex.trail_after_type === 'points' ? 'points' : 'pct', trail_after: stratNum_(ex.trail_after, 0, 5000, 20),
             trail_type: ex.trail_type === 'points' ? 'points' : 'pct', trail: stratNum_(ex.trail, 0, 1000, 10),
             exit_by: style === 'intraday' ? stratTime_(ex.exit_by, '15:15') : null, validity: style === 'intraday' ? 'DAY' : 'GTC' },
    style: style, max_trades_day: Math.round(stratNum_(s.max_trades_day, 1, 50, 2)),
    max_loss_day: stratNum_(s.max_loss_day, 0, 1e7, 5000), reentry_gap: Math.round(stratNum_(s.reentry_gap, 0, 375, 15)),
    updated: Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm")
  };
}

/** Starts the algo-sync job now, so a switch reaches the machine in a minute or two instead of at the next 10-minute run. */
function stratPushNow_() {
  const props = PropertiesService.getScriptProperties();
  const repo = props.getProperty('GH_REPO'), pat = props.getProperty('GH_PAT');
  if (!repo || !pat) return false;
  try {
    const r = UrlFetchApp.fetch('https://api.github.com/repos/' + repo + '/actions/workflows/algo-sync.yml/dispatches', {
      method: 'post', muteHttpExceptions: true, contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + pat, Accept: 'application/vnd.github+json' }, payload: JSON.stringify({ ref: 'main' }) });
    return r.getResponseCode() === 204;
  } catch (e) { return false; }
}

function stratView_() {
  const cache = CacheService.getScriptCache();
  const items = stratList_();
  const bt = {}; items.forEach(s => { const v = cache.get('bt_' + s.id); if (v) bt[s.id] = v; });
  // the latest back-test of each strategy (trader/backtest.py keeps state/backtests/_index.json), for the cards
  let backtests = {};
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (readToken) { try { const r = privateRaw_(readToken, 'state/backtests/_index.json'); if (r.getResponseCode() === 200) backtests = JSON.parse(r.getContentText()); } catch (e) {} }
  return { items: items, active: stratActive_(), limits: stratLimits_(), backtest_started: bt, backtests: backtests };
}

function adminStrategies(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return stratView_();
}

function adminStrategySave(token, s) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const c = stratClean_(s), list = stratList_();
  const i = list.findIndex(x => x.id === c.id);
  if (i >= 0) list[i] = c; else { if (list.length >= STRAT_MAX) return { error: 'At most ' + STRAT_MAX + ' strategies.' }; list.push(c); }
  stratSave_(list);
  const v = stratView_(); v.saved = c.id;
  if (c.id === stratActive_()) v.sent = stratPushNow_();          // editing the strategy that is trading
  return v;
}

function adminStrategyDelete(token, id) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  if (id === stratActive_()) return { error: 'Switch this strategy off before deleting it.' };
  stratSave_(stratList_().filter(x => x.id !== id));
  return stratView_();
}

/** Switch one strategy on (id) or all off (''): the machine follows within ~10 minutes, for new trades only. */
function adminStrategyActivate(token, id) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  if (id && !stratList_().some(x => x.id === id)) return { error: 'No such strategy.' };
  const props = PropertiesService.getScriptProperties();
  props.setProperty('STRAT_ACTIVE', id || '');
  props.setProperty('STRAT_CHANGED', Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm"));
  const v = stratView_(); v.sent = stratPushNow_(); return v;
}

function adminStrategyLimits(token, l) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  l = l || {};
  PropertiesService.getScriptProperties().setProperty('STRAT_LIMITS', JSON.stringify({
    max_lots_per_order: Math.round(stratNum_(l.max_lots_per_order, 1, 50, 1)), max_daily_loss: stratNum_(l.max_daily_loss, 500, 1e7, 10000) }));
  const v = stratView_(); v.sent = stratPushNow_(); return v;
}

/** Starts a back-test of one saved strategy on GitHub (strategy-backtest.yml). */
function adminBacktestStart(token, id) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  if (!stratList_().some(x => x.id === id)) return { error: 'Save the strategy first.' };
  const props = PropertiesService.getScriptProperties();
  const repo = props.getProperty('GH_REPO'), pat = props.getProperty('GH_PAT');
  if (!repo || !pat) return { error: 'GH_REPO / GH_PAT are not set in the script properties.' };
  const r = UrlFetchApp.fetch('https://api.github.com/repos/' + repo + '/actions/workflows/strategy-backtest.yml/dispatches', {
    method: 'post', muteHttpExceptions: true, contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + pat, Accept: 'application/vnd.github+json' },
    payload: JSON.stringify({ ref: 'main', inputs: { id: id } }) });
  if (r.getResponseCode() !== 204) return { error: 'Could not start the back-test (' + r.getResponseCode() + ').' };
  const at = Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm");
  CacheService.getScriptCache().put('bt_' + id, at, 3600);
  return { ok: true, started: at };
}

/** The latest back-test result for one strategy (private repo state/backtests/<id>.json). */
function adminBacktestResult(token, id) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  if (!/^s_[a-z0-9]{6,20}$/.test(id || '')) return { error: 'bad id' };
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) return { error: 'ADMIN_READ_TOKEN is not set in the script properties.' };
  const res = privateRaw_(readToken, 'state/backtests/' + id + '.json');
  if (res.getResponseCode() === 404) return { none: true };
  if (res.getResponseCode() !== 200) return { error: 'Could not load the back-test (' + res.getResponseCode() + ').' };
  return JSON.parse(res.getContentText());
}

/** For the algo-sync and back-test jobs (RELAY_KEY): every saved strategy, the active one and the limits. */
function strategiesForBatch_(p) {
  const relayKey = PropertiesService.getScriptProperties().getProperty('RELAY_KEY') || '';
  if (!relayKey || p.key !== relayKey) return { error: 'key does not match RELAY_KEY' };
  return { active: stratActive_() || null, items: stratList_(), limits: stratLimits_(),
           changed: PropertiesService.getScriptProperties().getProperty('STRAT_CHANGED') || null };
}
