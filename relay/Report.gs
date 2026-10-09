/**
 * Stock report (9 Oct 2026): the live parts of the admin dashboard's per-company report. Everything
 * stored (the ~50 library measures, multi-bagger gates, corporate actions, sector, name) is already in
 * the page from adminLibrary/adminMultibagger; this adds what is not stored:
 *   - quarterly revenue / profit / EPS from BharatStock (consolidated, last 12 quarters)
 *   - three years of daily closes from BharatStock, and NIFTY 50 from the private state/prices.json
 *   - recent headlines from Google News
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
  const readToken = props.getProperty('ADMIN_READ_TOKEN') || '';
  const from = Utilities.formatDate(new Date(Date.now() - 3 * 366 * 86400000), 'Asia/Kolkata', 'yyyy-MM-dd');
  const name = String(companyName || '').replace(/\s+(limited|ltd\.?)$/i, '').trim();
  const newsQuery = '"' + (name || sym) + '" share OR stock OR results';

  const reqs = [];
  const idx = {};
  function add(key, req) { idx[key] = reqs.length; reqs.push(Object.assign({ muteHttpExceptions: true }, req)); }
  if (bsKey) {
    add('fin', { url: BHARAT + encodeURIComponent(sym) + '/financials?period_type=quarterly', headers: { 'X-API-Key': bsKey } });
    add('px', { url: BHARAT + encodeURIComponent(sym) + '/prices?from=' + from + '&page_size=1000', headers: { 'X-API-Key': bsKey } });
  }
  add('news', { url: 'https://news.google.com/rss/search?q=' + encodeURIComponent(newsQuery) + '&hl=en-IN&gl=IN&ceid=IN:en' });
  if (readToken) {
    add('nifty', { url: 'https://api.github.com/repos/' + ADMIN_REPO + '/contents/state/prices.json',
                   headers: { Authorization: 'Bearer ' + readToken, Accept: 'application/vnd.github.raw' } });
  }
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
        // Follow pagination until 12 consolidated quarters or the end (at most 4 pages).
        while (page <= 4 && bsHasNext_(body, page - 1) && consolidated_(rows).length < 12) {
          const more = UrlFetchApp.fetch(BHARAT + encodeURIComponent(sym) + '/financials?period_type=quarterly&page=' + page,
                                         { muteHttpExceptions: true, headers: { 'X-API-Key': bsKey } });
          if (more.getResponseCode() !== 200) break;
          body = JSON.parse(more.getContentText());
          rows = rows.concat(bsRows_(body));
          page++;
        }
        out.quarters = consolidated_(rows).slice(0, 12).reverse().map(function (x) {
          return { period: String(x.period_end_date || '').slice(0, 10),
                   revenue: pick_(x, ['revenue', 'total_revenue', 'revenue_from_operations', 'total_income']),
                   net_profit: pick_(x, ['net_profit', 'profit_after_tax', 'pat']),
                   operating_profit: pick_(x, ['operating_profit', 'ebitda', 'operating_income']),
                   eps: pick_(x, ['eps', 'basic_eps', 'diluted_eps']) };
        });
        if (!out.quarters.length) out.errors.financials = 'No consolidated quarters on BharatStock.';
      }
    } catch (e) { out.errors.financials = 'Could not read financials: ' + e.message; }
  }

  // Price history
  if (!bsKey) {
    out.errors.prices = bsMissing;
  } else {
    try {
      const r = res[idx.px];
      const code = r.getResponseCode();
      if (code === 429) out.errors.prices = 'BharatStock daily limit reached; try again later.';
      else if (code !== 200) out.errors.prices = 'BharatStock returned ' + code + ' for prices.';
      else {
        out.prices = bsRows_(JSON.parse(r.getContentText())).map(function (x) {
          const c = x.adjusted_close != null ? x.adjusted_close : x.close;
          return [String(x.trade_date || '').slice(0, 10), c == null ? null : Number(c)];
        }).filter(function (p) { return p[0] && p[1] != null; })
          .sort(function (a, b) { return a[0] < b[0] ? -1 : (a[0] > b[0] ? 1 : 0); });
        if (!out.prices.length) out.errors.prices = 'No price history on BharatStock.';
      }
    } catch (e) { out.errors.prices = 'Could not read prices: ' + e.message; }
  }

  // NIFTY 50 for the relative-performance line
  if (idx.nifty != null) {
    try {
      const r = res[idx.nifty];
      if (r.getResponseCode() === 200) {
        const n = JSON.parse(r.getContentText()).NIFTY || {};
        out.nifty = Object.keys(n).filter(function (d) { return d >= from; }).sort().map(function (d) { return [d, n[d]]; });
      }
    } catch (e) { /* the chart simply shows no benchmark line */ }
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

// Same rule as hub/multibagger.py _consolidated(): consolidated (or unlabelled) rows, newest first.
function consolidated_(rows) {
  return rows.filter(function (x) { return (x.consolidation_type || 'consolidated') === 'consolidated' && x.period_end_date; })
    .sort(function (a, b) { return a.period_end_date < b.period_end_date ? 1 : (a.period_end_date > b.period_end_date ? -1 : 0); });
}

function pick_(row, keys) {
  for (let i = 0; i < keys.length; i++) {
    if (row[keys[i]] != null && row[keys[i]] !== '') return Number(row[keys[i]]);
  }
  return null;
}
