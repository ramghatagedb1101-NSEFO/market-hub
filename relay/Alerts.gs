/**
 * Email alerts for the phone (11 Oct 2026), alongside the Kite, discovery and weekly-health emails that
 * already existed:
 *   the day's digest     doPost mode=digest from the library run (hub/digest.py), one email a day
 *   watchlist moves      doGet mode=watch_check from the live-quotes job, every 5 minutes in market hours:
 *                        a move of 4% or more since yesterday's close, once per company per day, and
 *                        again at 8%; several companies in one check share one email
 * Each can be switched off on the dashboard (Overview, "Email alerts"); the switches are the script
 * properties ALERT_DIGEST and ALERT_MOVES ('off' = off, anything else = on).
 */
const MOVE_STEPS = [4, 8];

function alertOn_(name) { return PropertiesService.getScriptProperties().getProperty(name) !== 'off'; }

function alertMail_(subject, body) {
  MailApp.sendEmail(Session.getEffectiveUser().getEmail(), subject, body);
}

function adminAlertSettings(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return { digest: alertOn_('ALERT_DIGEST'), moves: alertOn_('ALERT_MOVES') };
}

function adminAlertToggle(token, name) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const prop = { digest: 'ALERT_DIGEST', moves: 'ALERT_MOVES' }[name];
  if (!prop) return { error: 'unknown alert' };
  PropertiesService.getScriptProperties().setProperty(prop, alertOn_(prop) ? 'off' : 'on');
  return adminAlertSettings(token);
}

/** The library run's digest (hub/digest.py), behind RELAY_KEY. */
function sendDigest_(key, body) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let d;
  try { d = JSON.parse(body); } catch (e) { return { error: 'bad JSON body' }; }
  if (!alertOn_('ALERT_DIGEST')) return { ok: true, sent: false, reason: 'switched off' };
  if (props.getProperty('DIGEST_SENT_DATE') === d.date) return { ok: true, sent: false, reason: 'already sent today' };
  const items = d.items || [];
  props.setProperty('DIGEST_SENT_DATE', d.date || '');
  if (!items.length) return { ok: true, sent: false, reason: 'nothing new' };
  const head = { shortlist: 'Shortlist', filing: 'Filings', move: 'Price moves', upcoming: 'Coming up' };
  const lines = [];
  ['shortlist', 'filing', 'move', 'upcoming'].forEach(k => {
    const xs = items.filter(x => x.type === k);
    if (!xs.length) return;
    lines.push(head[k]);
    xs.forEach(x => lines.push('  ' + x.symbol + ': ' + x.title + (x.detail ? ' (' + x.detail + ')' : '')));
    lines.push('');
  });
  lines.push('Your Shortlist and watchlist only. Details on the phone app, Today tab.');
  const syms = Array.from(new Set(items.map(x => x.symbol))).slice(0, 4).join(', ');
  alertMail_('Market Hub today: ' + items.length + ' update' + (items.length > 1 ? 's' : '') + ' (' + syms + ')', lines.join('\n'));
  return { ok: true, sent: true };
}

/** Watchlist moves; Kite's OHLC quote carries the previous close, so the move is today's. */
function watchCheck_(key) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  if (!alertOn_('ALERT_MOVES')) return { ok: true, skipped: 'switched off' };
  const syms = watchList_().map(w => w.s);
  if (!syms.length) return { ok: true, skipped: 'empty watchlist' };
  const headers = kiteHeaders_();
  if (!headers) return { ok: true, skipped: 'no Kite login today' };
  let body;
  try {
    const qs = syms.map(s => 'i=' + encodeURIComponent('NSE:' + s)).join('&');
    body = JSON.parse(UrlFetchApp.fetch('https://api.kite.trade/quote/ohlc?' + qs, { muteHttpExceptions: true, headers: headers }).getContentText());
  } catch (e) { return { error: String(e).slice(0, 200) }; }
  if (body.status === 'error') { kiteFailed_(body.message); return { error: body.message }; }
  const today = todayIst_();
  let st = {};
  try { st = JSON.parse(props.getProperty('MOVE_ALERTS') || '{}'); } catch (e) { st = {}; }
  if (st.date !== today) st = { date: today, sent: {} };
  const moves = [];
  Object.keys(body.data || {}).forEach(k => {
    const q = body.data[k], sym = k.replace(/^NSE:/, ''), prev = q.ohlc && q.ohlc.close;
    if (!prev || !q.last_price) return;
    const chg = (q.last_price / prev - 1) * 100;
    const step = MOVE_STEPS.filter(s => Math.abs(chg) >= s).pop();
    if (!step || (st.sent[sym] || 0) >= step) return;
    st.sent[sym] = step;
    moves.push({ sym: sym, chg: chg, px: q.last_price });
  });
  if (!moves.length) return { ok: true, sent: 0 };
  const at = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'HH:mm');
  const fmt = m => m.sym + ' ' + (m.chg > 0 ? '+' : '') + m.chg.toFixed(1) + '%';
  alertMail_('Market Hub watchlist: ' + moves.map(fmt).join(', '),
    'Moves since yesterday\'s close, at ' + at + ' IST:\n\n' +
    moves.map(m => '  ' + fmt(m) + ' at Rs ' + m.px.toLocaleString('en-IN')).join('\n') +
    '\n\nEach company alerts once a day at 4% and again at 8%. Switch these off on the dashboard Overview, Email alerts.');
  props.setProperty('MOVE_ALERTS', JSON.stringify(st));
  return { ok: true, sent: moves.length };
}
