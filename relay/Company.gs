/**
 * Phone company search and company page (11 Oct 2026). The phone used to open a company only from the
 * Shortlist, the digest or the watchlist, with a handful of figures. Now:
 *   app_names    every company (symbol, name, industry) for the search box, plus the measure catalogue
 *                (labels, groups, formats) read from the dashboard's own definitions in AdminPage.html,
 *                so the two never disagree. The phone keeps it for a day.
 *   app_profile  one company's full library entry: every measure with its pass / fail, holdings history,
 *                corporate actions, NSE check and data flags (from library_compact.json, as the dashboard).
 *   app_results  40 quarters and 10 years of results plus news (adminStock, Report.gs): 2 BharatStock
 *                requests, only when the phone's Results section is opened.
 *   app_funds    mutual funds holding it (adminFunds, Funds.gs): 1 BharatStock request, only when opened.
 */
const CATALOGUE_KEY = 'catalogue_v1';

function compactLib_() {
  const readToken = PropertiesService.getScriptProperties().getProperty('ADMIN_READ_TOKEN') || '';
  if (!readToken) throw new Error('ADMIN_READ_TOKEN is not set in the script properties.');
  const res = privateRaw_(readToken, 'library_compact.json');
  if (res.getResponseCode() !== 200) throw new Error('The stock library could not be read (' + res.getResponseCode() + ').');
  return JSON.parse(res.getContentText());
}

// The dashboard's measure catalogue (const M and const GROUPS in AdminPage.html): literals only.
function catalogue_() {
  const cache = CacheService.getScriptCache();
  const hit = cache.get(CATALOGUE_KEY);
  if (hit) return JSON.parse(hit);
  const html = HtmlService.createHtmlOutputFromFile('AdminPage').getContent();
  const m = html.match(/const M = (\{[\s\S]*?\n\});/), g = html.match(/const GROUPS = (\[[\s\S]*?\]);/);
  const out = { M: m ? new Function('return ' + m[1])() : {}, GROUPS: g ? new Function('return ' + g[1])() : [] };
  try { cache.put(CATALOGUE_KEY, JSON.stringify(out), 21600); } catch (e) { /* too big to cache: rebuilt next time */ }
  return out;
}

function appNames_(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  try {
    const lib = compactLib_();
    const names = lib.names || {}, inds = lib.industries || {};
    const list = (lib.stocks || []).map(s => [s.symbol, names[s.symbol] || '', inds[s.symbol] || s.sector || '']);
    return { generated: lib.generated, names: list, catalogue: catalogue_() };
  } catch (e) { return { error: String(e.message || e) }; }
}

function appProfile_(token, symbol) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  try {
    const lib = compactLib_();
    const s = (lib.stocks || []).find(x => x.symbol === sym);
    if (!s) return { error: sym + ' is not in the stock library.' };
    const pids = lib.pids || [], values = {}, rules = {};
    if (s.v) pids.forEach((p, i) => {
      if (s.s[i] === 'x' || s.v[i] == null) return;
      values[p] = [s.v[i], s.s[i]];                 // [value, Y met / N not met / . not testable]
      rules[p] = (lib.rules || {})[p] || '';
    });
    return {
      symbol: sym, name: (lib.names || {})[sym] || '', industry: (lib.industries || {})[sym] || s.sector || '',
      generated: lib.generated, latest_period: s.latest_period, quarters: s.quarters, scored_on: s.scored_on,
      met: s.met, testable: s.testable, data_quality_pct: s.data_quality_pct,
      values: values, rules: rules, actions: s.actions || [], hh: (s.hh || []).slice(-8),
      check: s.check || null, flags: s.flags || [], scored: !!s.v
    };
  } catch (e) { return { error: String(e.message || e) }; }
}
