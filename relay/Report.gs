/**
 * Stock report (9 Oct 2026): the live parts of the admin dashboard's per-company report. Everything
 * stored (the ~50 library measures, multi-bagger gates, corporate actions, sector, name) is already in
 * the page from adminLibrary/adminMultibagger; this adds what is not stored:
 *   - quarterly revenue / profit / EPS from BharatStock (consolidated, up to 40 quarters = 10 years)
 *   - annual revenue / profit / EPS / operating cash flow from BharatStock (up to 10 years)
 *   - recent headlines from Google News
 * Prices for the chart come from adminChart (Research.gs) since 11 Oct 2026.
 * BharatStock figures are fetched on click and never stored or cached here: its licence forbids
 * re-serving raw financial data from storage. Needs BHARATSTOCK_API_KEY in the script properties
 * (entered by the owner). Each part fails on its own and says why; one slow source never blanks the rest.
 */
const BHARAT = 'https://bharatstockapi.com/v1/stocks/';

function adminStock(token, symbol, companyName) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const props = PropertiesService.getScriptProperties();
  const bsKey = props.getProperty('BHARATSTOCK_API_KEY') || '';
  const name = String(companyName || '').replace(/\s+(limited|ltd\.?)$/i, '').trim();
  const newsQuery = '"' + (name || sym) + '" share OR stock OR results';

  const reqs = [];
  const idx = {};
  function add(key, req) { idx[key] = reqs.length; reqs.push(Object.assign({ muteHttpExceptions: true }, req)); }
  if (bsKey) {
    add('fin', { url: BHARAT + encodeURIComponent(sym) + '/financials?period_type=quarterly', headers: { 'X-API-Key': bsKey } });
    add('fina', { url: BHARAT + encodeURIComponent(sym) + '/financials?period_type=annual', headers: { 'X-API-Key': bsKey } });
  }
  add('news', { url: 'https://news.google.com/rss/search?q=' + encodeURIComponent(newsQuery) + '&hl=en-IN&gl=IN&ceid=IN:en' });
  const res = UrlFetchApp.fetchAll(reqs);
  const out = { symbol: sym, errors: {}, news_query: newsQuery };
  const bsMissing = 'BHARATSTOCK_API_KEY is not set in the script properties (Project Settings).';

  // Quarterly financials
  if (!bsKey) {
    out.errors.financials = bsMissing;
  } else {
    try {
      const r = res[idx.fin];
      const code = r.getResponseCode();
      if (code === 404) out.errors.financials = 'BharatStock has no financials for ' + sym + '.';
      else if (code === 429) out.errors.financials = 'BharatStock daily limit reached; try again later.';
      else if (code !== 200) out.errors.financials = 'BharatStock returned ' + code + '.';
      else {
        let body = JSON.parse(r.getContentText());
        let rows = bsRows_(body);
        let page = 2;
        // Follow pagination until 40 quarters (10 years) or the end (at most 10 pages).
        while (page <= 10 && bsHasNext_(body, page - 1) && consolidated_(rows).length < 40) {
          const more = UrlFetchApp.fetch(BHARAT + encodeURIComponent(sym) + '/financials?period_type=quarterly&page=' + page,
                                         { muteHttpExceptions: true, headers: { 'X-API-Key': bsKey } });
          if (more.getResponseCode() !== 200) break;
          body = JSON.parse(more.getContentText());
          rows = rows.concat(bsRows_(body));
          page++;
        }
        out.quarters = consolidated_(rows).slice(0, 40).reverse().map(function (x) {
          return { period: String(x.period_end_date || '').slice(0, 10),
                   revenue: pick_(x, ['revenue', 'total_revenue', 'revenue_from_operations', 'total_income']),
                   net_profit: pick_(x, ['net_profit', 'profit_after_tax', 'pat']),
                   operating_profit: pick_(x, ['operating_profit', 'ebitda', 'operating_income']),
                   eps: pick_(x, ['eps', 'basic_eps', 'diluted_eps']) };
        });
        if (!out.quarters.length) out.errors.financials = 'No quarterly results on BharatStock.';
      }
    } catch (e) { out.errors.financials = 'Could not read financials: ' + e.message; }
  }

  // Annual results, up to 10 years
  if (bsKey) {
    try {
      const r = res[idx.fina];
      if (r.getResponseCode() === 200) {
        out.annual = consolidated_(bsRows_(JSON.parse(r.getContentText()))).slice(0, 10).reverse().map(function (x) {
          return { period: String(x.period_end_date || '').slice(0, 10),
                   revenue: pick_(x, ['revenue', 'total_revenue', 'revenue_from_operations', 'total_income']),
                   net_profit: pick_(x, ['net_profit', 'profit_after_tax', 'pat']),
                   eps: pick_(x, ['eps', 'basic_eps', 'diluted_eps']),
                   cfo: pick_(x, ['cash_flow_operating']) };
        });
      } else if (r.getResponseCode() === 429) out.errors.annual = 'BharatStock daily limit reached; try again later.';
    } catch (e) { out.errors.annual = 'Could not read annual results: ' + e.message; }
  }

  // Headlines
  try {
    const r = res[idx.news];
    if (r.getResponseCode() !== 200) {
      out.errors.news = 'Google News returned ' + r.getResponseCode() + '.';
    } else {
      const items = XmlService.parse(r.getContentText()).getRootElement().getChild('channel').getChildren('item');
      out.news = items.slice(0, 10).map(function (it) {
        const src = it.getChild('source');
        return { title: it.getChildText('title'), link: it.getChildText('link'),
                 date: it.getChildText('pubDate'), source: src ? src.getText() : '' };
      });
    }
  } catch (e) { out.errors.news = 'Could not read headlines: ' + e.message; }
  return out;
}

function bsRows_(body) {
  return Array.isArray(body) ? body : (body.data || []);
}

function bsHasNext_(body, page) {
  if (Array.isArray(body)) return false;
  const p = body.pagination || {};
  return p.has_next != null ? !!p.has_next : page < (p.total_pages || 1);
}

// Same rule as hub/multibagger.py _consolidated(): consolidated (or unlabelled) rows, newest first -- or
// standalone rows for a company that files no consolidated results.
function consolidated_(rows) {
  const dated = rows.filter(function (x) { return x.period_end_date; });
  let pick = dated.filter(function (x) { return (x.consolidation_type || 'consolidated') === 'consolidated'; });
  if (!pick.length) pick = dated.filter(function (x) { return String(x.consolidation_type || '').toLowerCase() === 'standalone'; });
  return pick.sort(function (a, b) { return a.period_end_date < b.period_end_date ? 1 : (a.period_end_date > b.period_end_date ? -1 : 0); });
}

function pick_(row, keys) {
  for (let i = 0; i < keys.length; i++) {
    if (row[keys[i]] != null && row[keys[i]] !== '') return Number(row[keys[i]]);
  }
  return null;
}

/**
 * Symbol -> NSE industry for the ~750 NIFTY Total Market companies (9 Oct 2026), for sector analytics
 * and peer comparison. The weekly batch also stores this map in library.json; serving it here means the
 * sector views work before every company has been re-scored. Cached for six hours.
 */
function adminIndustries(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const cache = CacheService.getScriptCache();
  const hit = cache.get('industries_v1');
  if (hit) return JSON.parse(hit);
  const r = UrlFetchApp.fetch('https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv',
                              { muteHttpExceptions: true, headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (r.getResponseCode() !== 200) return { error: 'NSE returned ' + r.getResponseCode() + ' for the industry list.' };
  const rows = Utilities.parseCsv(r.getContentText());
  const head = rows[0].map(function (h) { return String(h).trim(); });
  const iSym = head.indexOf('Symbol'), iInd = head.indexOf('Industry');
  if (iSym < 0 || iInd < 0) return { error: 'Unexpected industry list format.' };
  const map = {};
  rows.slice(1).forEach(function (row) {
    const s = String(row[iSym] || '').trim(), ind = String(row[iInd] || '').trim();
    if (s && ind) map[s] = ind;
  });
  const out = { industries: map };
  try { cache.put('industries_v1', JSON.stringify(out), 21600); } catch (e) { /* too large to cache: fine */ }
  return out;
}

/**
 * Saved screener screens (9 Oct 2026), kept in the script properties so they follow the owner across
 * devices. A list of {name, conditions:[{field, op, value}], sort}. Script property values are capped
 * at 9 KB, which is a few dozen screens.
 */
function adminScreens(token) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const raw = PropertiesService.getScriptProperties().getProperty('SAVED_SCREENS');
  try { return { screens: raw ? JSON.parse(raw) : [] }; } catch (e) { return { screens: [] }; }
}

function adminSaveScreens(token, screens) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  if (!Array.isArray(screens)) return { error: 'Expected a list of screens.' };
  const clean = screens.slice(0, 60).map(function (s) {
    return { name: String(s.name || 'Untitled').slice(0, 60),
             sort: s.sort ? String(s.sort).slice(0, 40) : null,
             conditions: (Array.isArray(s.conditions) ? s.conditions : []).slice(0, 15).map(function (c) {
               return { field: String(c.field || '').slice(0, 40), op: String(c.op || '').slice(0, 4),
                        value: typeof c.value === 'number' ? c.value : String(c.value == null ? '' : c.value).slice(0, 60) };
             }) };
  });
  const json = JSON.stringify(clean);
  if (json.length > 9000) return { error: 'Too many saved screens to store (limit about 9 KB). Delete a few first.' };
  PropertiesService.getScriptProperties().setProperty('SAVED_SCREENS', json);
  return { ok: true, screens: clean };
}
