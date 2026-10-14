/**
 * Mutual funds holding a company (11 Oct 2026), for the dashboard's stock report. Fetched live from
 * BharatStock's mf-holdings endpoint when the report opens and never stored: the batch keeps only the
 * scheme count, because BharatStock's terms do not allow keeping its raw data (hub/multibagger.py).
 * One request per report (more only for a company held by over a page of schemes).
 *
 * BharatStock's field names for this endpoint were never logged, so each value is read from the likely
 * names, and the field list of the first row is returned too: the panel shows it when a column comes
 * back empty, so a wrong guess is visible instead of silently blank.
 */
function adminFunds(token, symbol) {
  if (!sessionValid_(token)) return { error: 'session_expired' };
  const sym = String(symbol || '').toUpperCase();
  if (!/^[A-Z0-9&_-]{1,20}$/.test(sym)) return { error: 'Not a valid NSE symbol.' };
  const key = PropertiesService.getScriptProperties().getProperty('BHARATSTOCK_API_KEY') || '';
  if (!key) return { error: 'BHARATSTOCK_API_KEY is not set in the script properties.' };
  const rows = [];
  for (let page = 1; page <= 5; page++) {
    const r = UrlFetchApp.fetch(BHARAT + encodeURIComponent(sym) + '/mf-holdings' + (page > 1 ? '?page=' + page : ''),
      { muteHttpExceptions: true, headers: { 'X-API-Key': key } });
    bsCount_(1);
    const code = r.getResponseCode();
    if (code === 404) break;
    if (code === 429) return { error: 'BharatStock daily limit reached; try again after it resets (05:30 IST).' };
    if (code !== 200) return { error: 'BharatStock answered ' + code + '.' };
    const body = JSON.parse(r.getContentText());
    const got = bsRows_(body);
    got.forEach(x => rows.push(x));
    if (!got.length || !bsHasNext_(body, page)) break;
  }
  const pick = (x, names) => { for (const n of names) if (x[n] != null && x[n] !== '') return x[n]; return null; };
  const items = rows.map(x => ({
    scheme: pick(x, ['scheme_name', 'scheme', 'fund_name', 'name', 'scheme_code']),
    amc: pick(x, ['amc_name', 'amc', 'fund_house', 'asset_management_company']),
    shares: pick(x, ['quantity', 'shares', 'shares_held', 'holding_quantity', 'no_of_shares', 'quantity_held']),
    change: pick(x, ['quantity_change', 'change_in_quantity', 'shares_change', 'qty_change']),
    pct_company: pick(x, ['holding_percentage', 'holding_percent', 'percent_holding', 'pct_holding', 'percentage_of_shares', 'percent_of_shares']),
    pct_scheme: pick(x, ['percent_of_aum', 'pct_of_aum', 'aum_percentage', 'weight', 'percentage_of_aum', 'portfolio_weight']),
    value: pick(x, ['market_value', 'value', 'holding_value', 'market_value_cr']),
    date: pick(x, ['as_of_date', 'portfolio_date', 'holding_date', 'month', 'date', 'period', 'report_date'])
  })).filter(i => i.scheme != null);
  items.sort((a, b) => (Number(b.shares) || 0) - (Number(a.shares) || 0));
  return { symbol: sym, items: items, fields: rows.length ? Object.keys(rows[0]).sort() : [] };
}
