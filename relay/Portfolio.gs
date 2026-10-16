/**
 * My portfolio (16 Oct 2026, owner: "build all of them"): the owner's Kite holdings, read-only (Kite Connect
 * /portfolio/holdings, the same daily login; no orders are ever placed). The page works out weights, sector
 * concentration and the 50% warning; the morning insights job gets the last-seen symbols (batch_context) so results
 * dates, filings and alerts cover what is held even before the day's login.
 */
function portfolioView_() {
  const props = PropertiesService.getScriptProperties();
  const cached = (() => { try { return JSON.parse(props.getProperty('HOLDINGS_CACHE') || '{}'); } catch (e) { return {}; } })();
  const headers = kiteHeaders_();
  if (!headers) return { error: 'Not logged in to Kite today.', login_link: kiteLoginLink_(), cached_on: cached.on || null };
  let body;
  try { body = JSON.parse(UrlFetchApp.fetch('https://api.kite.trade/portfolio/holdings', { muteHttpExceptions: true, headers: headers }).getContentText()); }
  catch (e) { return { error: 'Holdings could not be loaded.' }; }
  if (body.status === 'error') { kiteFailed_(body.message); return { error: 'Kite: ' + body.message, login_link: kiteLoginLink_() }; }
  const rows = (body.data || []).map(h => {
    const qty = (h.quantity || 0) + (h.t1_quantity || 0);
    return { s: h.tradingsymbol, ex: h.exchange, q: qty, avg: h.average_price, ltp: h.last_price, close: h.close_price,
             value: qty * h.last_price, cost: qty * h.average_price, pnl: qty * (h.last_price - h.average_price),
             day: qty * (h.last_price - (h.close_price || h.last_price)), day_pct: h.day_change_percentage };
  }).filter(r => r.q > 0);
  try { props.setProperty('HOLDINGS_CACHE', JSON.stringify({ on: todayIst_(), h: rows.map(r => ({ s: r.s, q: r.q })) })); } catch (e) {}
  const q = quoteData_();
  return { ts: Utilities.formatDate(new Date(), 'Asia/Kolkata', "yyyy-MM-dd'T'HH:mm:ss+05:30"), holdings: rows,
           nifty: q.indices && q.indices.NIFTY ? q.indices.NIFTY : null };
}

function adminPortfolio(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  return portfolioView_();
}

/** For the morning insights job (hub/insights.py): watchlist, saved screens and the last-seen holdings. Key-protected. */
function batchContext_(key) {
  const props = PropertiesService.getScriptProperties();
  const relayKey = props.getProperty('RELAY_KEY') || '';
  if (!relayKey || key !== relayKey) return { error: 'forbidden' };
  let screens = [], held = {};
  try { screens = JSON.parse(props.getProperty('SAVED_SCREENS') || '[]'); } catch (e) {}
  try { held = JSON.parse(props.getProperty('HOLDINGS_CACHE') || '{}'); } catch (e) {}
  return { watchlist: watchList_().map(w => w.s), screens: screens, holdings: held.h || [], holdings_on: held.on || null };
}
