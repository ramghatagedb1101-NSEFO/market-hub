"""
Parameter registry for the stock library. Every stock is measured on these parameters, and the
deep-research gate counts how many a stock meets. This list is fixed before testing; a parameter is
added only with a written reason, and nothing is removed after a back-test looked poor.

Status meanings:
  available          source confirmed working (field names checked)
  pending_field_check source is expected to exist, but its field names are not yet confirmed
  collecting         a collector is running and history is building from its start date
  to_build           source identified, collector not yet written
  annual_only        the field exists but is filled once a year, so it cannot be tested quarterly
  gap                no free source found; the parameter stays out of the score until one is found

Each parameter: (id, family, definition, source, status)
"""

PARAMETERS = [
    # Ids and statuses updated from the confirmed BharatStock field names.
    ('rev_yoy', 'financials', 'Revenue growth, latest quarter vs same quarter last year', 'BharatStock financials', 'available'),
    ('rev_run', 'financials', 'Consecutive quarters of revenue growth vs a year earlier', 'BharatStock financials', 'available'),
    ('profit_yoy', 'financials', 'Net profit growth, latest quarter vs same quarter last year', 'BharatStock financials', 'available'),
    ('profit_run', 'financials', 'Consecutive quarters of profit above a year earlier, and positive', 'BharatStock financials', 'available'),
    ('profit_consistency_8q', 'financials', 'Quarters of profit growth in the last eight', 'BharatStock financials', 'available'),
    ('profit_turnaround', 'financials', 'Profit turned positive within the last four quarters after a loss or decline', 'BharatStock financials', 'available'),
    ('profit_acceleration', 'financials', 'Change in profit growth rate vs the previous quarter', 'BharatStock financials', 'available'),
    ('eps_yoy', 'financials', 'EPS growth, latest quarter vs same quarter last year', 'BharatStock financials', 'available'),
    ('net_margin', 'financials', 'Net profit as a share of revenue, latest quarter', 'BharatStock financials', 'available'),
    ('net_margin_change', 'financials', 'Change in net margin vs a year earlier', 'BharatStock financials', 'available'),
    ('operating_margin', 'financials', 'Operating profit as a share of revenue', 'BharatStock financials', 'available'),
    ('rev_cagr_3y', 'financials', 'Three-year revenue growth rate per year', 'BharatStock financials', 'available'),
    ('profit_cagr_3y', 'financials', 'Three-year profit growth rate per year', 'BharatStock financials', 'available'),
    ('other_income_share', 'financials', 'Other income as a share of profit (quality of earnings)', 'BharatStock financials', 'available'),
    ('interest_cost', 'financials', 'Finance cost, latest quarter', 'BharatStock financials', 'available'),
    ('interest_cover', 'financials', 'Operating profit divided by finance cost', 'BharatStock financials', 'available'),
    ('total_debt', 'balance_sheet', 'Total borrowings, latest year', 'BharatStock balance sheet', 'available'),
    ('debt_change_1y', 'balance_sheet', 'Change in total borrowings over one year', 'BharatStock balance sheet', 'available'),
    ('debt_to_equity', 'balance_sheet', 'Total borrowings divided by net worth', 'BharatStock balance sheet', 'available'),
    ('net_worth_growth', 'balance_sheet', 'Growth in net worth over one year', 'BharatStock balance sheet', 'available'),
    ('capital_employed', 'balance_sheet', 'Net worth plus borrowings', 'BharatStock balance sheet', 'available'),
    ('roce', 'balance_sheet', 'Return on capital employed, latest year', 'BharatStock balance sheet', 'available'),
    ('roe', 'balance_sheet', 'Return on equity, latest year', 'BharatStock balance sheet', 'available'),
    ('incremental_roce', 'balance_sheet', 'Change in operating profit divided by change in capital employed', 'BharatStock balance sheet', 'available'),
    ('debt_reduction_flag', 'balance_sheet', 'Borrowings fell while profit rose', 'BharatStock balance sheet', 'available'),
    ('borrow_to_expand_flag', 'balance_sheet', 'Borrowings and capital employed rose while profit rose faster than debt', 'BharatStock balance sheet', 'available'),
    ('red_flag_debt', 'balance_sheet', 'Borrowings rose while profit fell or cash flow turned negative', 'BharatStock balance sheet', 'available'),
    ('cash_and_equivalents', 'balance_sheet', 'Cash and bank balances, latest year', 'BharatStock balance sheet', 'available'),
    ('working_capital_days', 'balance_sheet', 'Receivable days plus inventory days less payable days', 'BharatStock balance sheet', 'available'),
    ('cfo', 'cash_flow', 'Operating cash flow, latest year', 'BharatStock cash flow (annual)', 'available'),
    ('cfo_to_pat', 'cash_flow', 'Operating cash flow divided by net profit', 'BharatStock cash flow (annual)', 'available'),
    ('fcf', 'cash_flow', 'Operating cash flow less capital spending', 'BharatStock cash flow (annual)', 'available'),
    ('capex', 'cash_flow', 'Capital spending, latest year', 'BharatStock cash flow (annual)', 'available'),
    ('capex_to_sales', 'cash_flow', 'Capital spending as a share of revenue', 'BharatStock cash flow (annual)', 'available'),
    ('capex_change', 'cash_flow', 'Change in capital spending over one year', 'BharatStock cash flow (annual)', 'available'),
    ('dividend_paid', 'cash_flow', 'Dividends paid, latest year', 'BharatStock cash flow', 'gap'),
    ('buyback_flag', 'cash_flow', 'Share buyback announced or completed in the last year', 'NSE corporate-actions', 'available'),
    ('promoter_holding', 'ownership', 'Promoter and promoter group holding, latest quarter', 'NSE corporate-share-holdings-master', 'available'),
    ('promoter_change_qoq', 'ownership', 'Change in promoter holding over one quarter', 'NSE corporate-share-holdings-master', 'available'),
    ('promoter_change_yoy', 'ownership', 'Change in promoter holding over one year', 'NSE corporate-share-holdings-master', 'available'),
    ('pledge_pct', 'ownership', 'Share of promoter holding pledged', 'NSE shareholding pattern XBRL', 'available'),
    ('fii_holding', 'ownership', 'Foreign institutional holding, latest quarter', 'NSE shareholding pattern XBRL', 'available'),
    ('dii_holding', 'ownership', 'Domestic institutional holding, latest quarter', 'NSE shareholding pattern XBRL', 'available'),
    ('mf_schemes_holding', 'ownership', 'Number of mutual fund schemes holding the stock', 'BharatStock mf-holdings', 'available'),
    ('mf_schemes_added', 'ownership', 'Number of schemes that added the stock in the last month', 'BharatStock mf-holdings', 'available'),
    ('mf_new_entrants', 'ownership', 'Fund houses that were not holders last quarter and are now', 'BharatStock mf-holdings', 'available'),
    ('registry_holders', 'ownership', 'Registry investors holding the stock, confirmed matches only', 'NSE shareholding pattern XBRL + registry', 'available'),
    ('registry_new_entrants', 'ownership', 'Registry investors that entered the stock this quarter', 'NSE shareholding pattern XBRL + registry', 'available'),
    ('holder_count_change', 'ownership', 'Change in the number of publicly disclosed holders (above the 2-lakh nominal-value threshold) over one quarter', 'NSE shareholding pattern XBRL', 'available'),
    ('top10_holding_change', 'ownership', "Change in the combined holding of the ten largest publicly disclosed holders", 'NSE shareholding pattern XBRL', 'available'),
    ('public_float', 'ownership', 'Share of shares held by the public, latest quarter', 'NSE corporate-share-holdings-master', 'available'),
    ('bulk_buys_20d', 'smart_money', 'Bulk-deal buys in the last 20 sessions', 'NSE bulk deals', 'collecting'),
    ('bulk_sells_20d', 'smart_money', 'Bulk-deal sells in the last 20 sessions', 'NSE bulk deals', 'collecting'),
    ('registry_buys_20d', 'smart_money', 'Bulk-deal buys by confirmed registry investors in the last 20 sessions', 'NSE bulk deals + registry', 'collecting'),
    ('net_bulk_value', 'smart_money', 'Value of bulk buys less bulk sells in the last 20 sessions', 'NSE bulk deals', 'collecting'),
    ('distinct_bulk_buyers', 'smart_money', 'Number of different buyers in the last 20 sessions', 'NSE bulk deals', 'collecting'),
    ('promoter_bulk_sells', 'smart_money', 'Bulk sells by promoter group in the last 90 sessions', 'NSE bulk deals + shareholding', 'collecting'),
    ('insider_buys_6m', 'promoter_behaviour', 'Promoter insider purchases in the last six months', 'BharatStock insider-trades', 'available'),
    ('insider_sells_6m', 'promoter_behaviour', 'Promoter insider sales in the last six months', 'BharatStock insider-trades', 'available'),
    ('promoter_net_shares_6m', 'promoter_behaviour', 'Net shares bought less sold by promoters in six months', 'BharatStock insider-trades', 'available'),
    ('capex_announcement', 'promoter_behaviour', 'Expansion or capex announcement in the last year', 'NSE corporate announcements', 'to_build'),
    ('related_party_flag', 'promoter_behaviour', 'Material related-party transactions disclosed', 'NSE filings', 'gap'),
    ('ret_1m', 'price', 'Share price return over one month', 'BharatStock prices', 'available'),
    ('ret_3m', 'price', 'Share price return over three months', 'BharatStock prices', 'available'),
    ('ret_12m', 'price', 'Share price return over twelve months', 'BharatStock prices', 'available'),
    ('from_52w_low', 'price', 'Price above the 52-week low, in percent', 'BharatStock prices', 'available'),
    ('from_52w_high', 'price', 'Price below the 52-week high, in percent', 'BharatStock prices', 'available'),
    ('volume_ratio_20d', 'price', 'Volume over the last 20 sessions vs the prior 60', 'BharatStock prices', 'available'),
    ('delivery_pct_20d', 'price', 'Average delivery percentage over 20 sessions', 'BharatStock prices', 'available'),
    ('delivery_change', 'price', 'Change in delivery percentage vs the prior 60 sessions', 'BharatStock prices', 'available'),
    ('rel_strength_vs_index', 'price', 'Return relative to the Nifty 500 over six months', 'NSE index data', 'to_build'),
    ('volatility_60d', 'price', 'Annualised volatility over 60 sessions', 'BharatStock prices', 'available'),
    ('above_200dma', 'price', 'Close above the 200-day moving average', 'BharatStock prices', 'available'),
    ('avg_turnover_20d', 'price', 'Average daily turnover over 20 sessions', 'BharatStock prices', 'available'),
    ('pe', 'valuation', 'Price to trailing twelve-month earnings', 'BharatStock prices + financials', 'available'),
    ('pe_vs_own_history', 'valuation', "Current P/E vs the company's own five-year median", 'BharatStock prices + financials', 'available'),
    ('pb', 'valuation', 'Price to book value', 'BharatStock prices + balance sheet', 'available'),
    ('ps', 'valuation', 'Price to trailing revenue', 'BharatStock prices + financials', 'available'),
    ('peg', 'valuation', 'P/E divided by profit growth rate', 'BharatStock prices + financials', 'available'),
    ('ev_ebitda', 'valuation', 'Enterprise value to EBITDA', 'BharatStock balance sheet + financials', 'available'),
    ('dividend_yield', 'valuation', 'Dividend per share over price', 'NSE corporate-actions + BharatStock prices', 'available'),
    ('market_value_bucket', 'valuation', 'Estimated market value: micro, small, mid or large', 'BharatStock prices + shares outstanding', 'available'),
    ('sector_ret_3m', 'context', 'Median three-month return of companies in the same sector', 'BharatStock prices + NSE master', 'to_build'),
    ('sector_news_count', 'context', 'News items about the sector in the last 30 days', 'Public RSS feeds', 'to_build'),
    ('regulatory_events', 'context', 'Government or regulator notifications touching the sector in the last 90 days', 'Government and regulator RSS feeds', 'to_build'),
    ('global_peer_ret_3m', 'context', 'Three-month return of listed global peers', 'Free price sources, to be chosen', 'gap'),
    ('sector_pe_vs_history', 'context', 'Sector median P/E vs its own five-year median', 'BharatStock prices + financials', 'to_build'),
    ('listing_age_years', 'context', 'Years since listing on NSE', 'NSE equity list', 'available'),
    ('index_membership', 'context', 'Current index membership (Nifty 50, Next 50, Midcap, Smallcap, Microcap)', 'NSE index files', 'to_build'),
    ('net_profit_level', 'financials', 'Net profit, latest quarter, in rupees (scale and survivability)', 'BharatStock financials', 'available'),
    ('revenue_level', 'financials', 'Revenue, latest quarter, in rupees (scale)', 'BharatStock financials', 'available'),
    ('ebitda_margin', 'financials', 'Earnings before interest, tax, depreciation and amortisation as a share of revenue', 'BharatStock financials', 'available'),
    ('revenue_acceleration', 'financials', 'Change in revenue growth rate vs the previous quarter', 'BharatStock financials', 'available'),
    ('margin_trend_3y', 'financials', 'Change in net margin over three years', 'BharatStock financials', 'available'),
    ('eps_cagr_3y', 'financials', 'Three-year earnings per share growth rate per year', 'BharatStock financials', 'available'),
    ('tax_rate', 'financials', 'Tax as a share of profit before tax', 'BharatStock financials', 'available'),
    ('depreciation_to_sales', 'financials', 'Depreciation as a share of revenue (asset intensity)', 'BharatStock financials', 'available'),
    ('employee_cost_share', 'financials', 'Employee cost as a share of revenue', 'BharatStock financials', 'available'),
    ('equity_multiplier', 'balance_sheet', 'Total assets divided by net worth (leverage including non-debt liabilities)', 'BharatStock balance sheet', 'available'),
    ('total_assets_growth', 'balance_sheet', 'Growth in total assets over one year', 'BharatStock balance sheet', 'available'),
    ('asset_turnover', 'balance_sheet', 'Revenue divided by total assets (how hard the assets work)', 'BharatStock balance sheet', 'available'),
    ('book_value_per_share_growth', 'balance_sheet', 'Growth in book value per share over one year', 'BharatStock balance sheet', 'available'),
    ('cfo_growth', 'cash_flow', 'Growth in operating cash flow over one year', 'BharatStock cash flow (annual)', 'available'),
    ('cfo_margin', 'cash_flow', 'Operating cash flow as a share of revenue', 'BharatStock cash flow (annual)', 'available'),
    ('working_capital_change', 'cash_flow', 'Change in working capital days over one year', 'BharatStock balance sheet', 'annual_only'),
    ('fii_change_qoq', 'ownership', 'Change in foreign institutional holding over one quarter', 'NSE shareholding pattern XBRL', 'available'),
    ('dii_change_qoq', 'ownership', 'Change in domestic institutional holding over one quarter', 'NSE shareholding pattern XBRL', 'available'),
    ('mf_holding_pct_change', 'ownership', 'Change in mutual fund holding as a share of shares, over one quarter', 'BharatStock mf-holdings', 'available'),
    ('promoter_holding_change_3q', 'ownership', 'Change in promoter holding over three quarters', 'NSE corporate-share-holdings-master', 'available'),
    ('pledge_change', 'ownership', 'Change in promoter pledge share over one year', 'NSE shareholding pattern XBRL', 'available'),
    ('bulk_sell_value_ratio', 'smart_money', 'Bulk sell value as a share of bulk buy value, 20 sessions', 'NSE bulk deals', 'collecting'),
    ('block_deal_count_90d', 'smart_money', 'Block deals in the last 90 sessions', 'NSE block deals', 'collecting'),
    ('dividend_policy_change', 'promoter_behaviour', 'Dividend per share raised vs the previous year', 'BharatStock cash flow', 'gap'),
    ('ret_6m', 'price', 'Share price return over six months', 'BharatStock prices', 'available'),
    ('drawdown_from_12m_peak', 'price', 'Fall from the twelve-month high, in percent', 'BharatStock prices', 'available'),
    ('beta_vs_index', 'price', 'Beta of the stock against the Nifty 500 over one year', 'BharatStock prices + NSE index data', 'to_build'),
    ('volume_surge_count_60d', 'price', 'Sessions in the last 60 with volume above twice the 20-day average', 'BharatStock prices', 'available'),
    ('rel_strength_rank_sector', 'price', "Rank of the stock's six-month return within its sector", 'BharatStock prices + NSE master', 'to_build'),
    ('ev_sales', 'valuation', 'Enterprise value to revenue', 'BharatStock balance sheet + financials', 'available'),
    ('earnings_yield', 'valuation', 'Trailing earnings divided by price', 'BharatStock prices + financials', 'available'),
    ('pe_percentile_5y', 'valuation', 'Where the current P/E sits within its five-year range (0 to 100)', 'BharatStock prices + financials', 'available'),
    ('peer_group_growth_median', 'context', 'Median profit growth of companies in the same sector', 'BharatStock financials + NSE master', 'to_build'),
    ('commodity_input_trend', 'context', 'Price trend of the main input commodity for the sector', 'Free commodity price source, to be chosen', 'gap'),
    ('supply_chain_exposure', 'context', 'Share of revenue exposed to a single supplier or market (judgment)', 'Annual reports and filings', 'gap'),
]


def summary() -> dict:
    counts = {}
    for _, _, _, _, status in PARAMETERS:
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(PARAMETERS), "by_status": counts}


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
