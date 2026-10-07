"""
Parameter registry for the stock library. Every stock is measured on these parameters, and the
deep-research gate counts how many a stock meets. This list is fixed before testing; a parameter is
added only with a written reason, and nothing is removed after a back-test looked poor.

Status meanings:
  available          source confirmed working (field names checked)
  pending_field_check source is expected to exist, but its field names are not yet confirmed
  collecting         a collector is running and history is building from its start date
  to_build           source identified, collector not yet written
  gap                no free source found; the parameter stays out of the score until one is found

Each parameter: (id, family, definition, source, status)
"""

PARAMETERS = [
    # Financials and cycle (BharatStock quarterly financials)
    ("rev_yoy", "financials", "Revenue growth, latest quarter vs same quarter last year", "BharatStock financials", "pending_field_check"),
    ("rev_run", "financials", "Consecutive quarters of revenue growth vs a year earlier", "BharatStock financials", "pending_field_check"),
    ("profit_yoy", "financials", "Net profit growth, latest quarter vs same quarter last year", "BharatStock financials", "available"),
    ("profit_run", "financials", "Consecutive quarters of profit above a year earlier, and positive", "BharatStock financials", "available"),
    ("profit_consistency_8q", "financials", "Quarters of profit growth in the last eight", "BharatStock financials", "available"),
    ("profit_turnaround", "financials", "Profit turned positive within the last four quarters after a loss or decline", "BharatStock financials", "available"),
    ("profit_acceleration", "financials", "Change in profit growth rate vs the previous quarter", "BharatStock financials", "pending_field_check"),
    ("eps_yoy", "financials", "EPS growth, latest quarter vs same quarter last year", "BharatStock financials", "available"),
    ("net_margin", "financials", "Net profit as a share of revenue, latest quarter", "BharatStock financials", "available"),
    ("net_margin_change", "financials", "Change in net margin vs a year earlier", "BharatStock financials", "available"),
    ("operating_margin", "financials", "Operating profit as a share of revenue", "BharatStock financials", "pending_field_check"),
    ("rev_cagr_3y", "financials", "Three-year revenue growth rate per year", "BharatStock financials", "pending_field_check"),
    ("profit_cagr_3y", "financials", "Three-year profit growth rate per year", "BharatStock financials", "pending_field_check"),
    ("other_income_share", "financials", "Other income as a share of profit (quality of earnings)", "BharatStock financials", "pending_field_check"),
    ("interest_cost", "financials", "Finance cost, latest quarter", "BharatStock financials", "pending_field_check"),
    ("interest_cover", "financials", "Operating profit divided by finance cost", "BharatStock financials", "pending_field_check"),

    # Balance sheet and capital
    ("total_debt", "balance_sheet", "Total borrowings, latest year", "BharatStock balance sheet", "pending_field_check"),
    ("debt_change_1y", "balance_sheet", "Change in total borrowings over one year", "BharatStock balance sheet", "pending_field_check"),
    ("debt_to_equity", "balance_sheet", "Total borrowings divided by net worth", "BharatStock balance sheet", "pending_field_check"),
    ("net_worth_growth", "balance_sheet", "Growth in net worth over one year", "BharatStock balance sheet", "pending_field_check"),
    ("capital_employed", "balance_sheet", "Net worth plus borrowings", "BharatStock balance sheet", "pending_field_check"),
    ("roce", "balance_sheet", "Return on capital employed, latest year", "BharatStock balance sheet", "pending_field_check"),
    ("roe", "balance_sheet", "Return on equity, latest year", "BharatStock balance sheet", "pending_field_check"),
    ("incremental_roce", "balance_sheet", "Change in operating profit divided by change in capital employed", "BharatStock balance sheet", "pending_field_check"),
    ("debt_reduction_flag", "balance_sheet", "Borrowings fell while profit rose", "BharatStock balance sheet", "pending_field_check"),
    ("borrow_to_expand_flag", "balance_sheet", "Borrowings and capital employed rose while profit rose faster than debt", "BharatStock balance sheet", "pending_field_check"),
    ("red_flag_debt", "balance_sheet", "Borrowings rose while profit fell or cash flow turned negative", "BharatStock balance sheet", "pending_field_check"),
    ("cash_and_equivalents", "balance_sheet", "Cash and bank balances, latest year", "BharatStock balance sheet", "pending_field_check"),
    ("working_capital_days", "balance_sheet", "Receivable days plus inventory days less payable days", "BharatStock balance sheet", "pending_field_check"),

    # Cash flow
    ("cfo", "cash_flow", "Operating cash flow, latest year", "BharatStock cash flow", "pending_field_check"),
    ("cfo_to_pat", "cash_flow", "Operating cash flow divided by net profit", "BharatStock cash flow", "pending_field_check"),
    ("fcf", "cash_flow", "Operating cash flow less capital spending", "BharatStock cash flow", "pending_field_check"),
    ("capex", "cash_flow", "Capital spending, latest year", "BharatStock cash flow", "pending_field_check"),
    ("capex_to_sales", "cash_flow", "Capital spending as a share of revenue", "BharatStock cash flow", "pending_field_check"),
    ("capex_change", "cash_flow", "Change in capital spending over one year", "BharatStock cash flow", "pending_field_check"),
    ("dividend_paid", "cash_flow", "Dividends paid, latest year", "BharatStock cash flow", "pending_field_check"),
    ("buyback_flag", "cash_flow", "Share buyback announced or completed in the last year", "NSE corporate announcements", "to_build"),

    # Ownership (quarterly shareholding patterns, NSE and BSE)
    ("promoter_holding", "ownership", "Promoter and promoter group holding, latest quarter", "NSE shareholding pattern", "to_build"),
    ("promoter_change_qoq", "ownership", "Change in promoter holding over one quarter", "NSE shareholding pattern", "to_build"),
    ("promoter_change_yoy", "ownership", "Change in promoter holding over one year", "NSE shareholding pattern", "to_build"),
    ("pledge_pct", "ownership", "Share of promoter holding pledged", "NSE shareholding pattern", "to_build"),
    ("fii_holding", "ownership", "Foreign institutional holding, latest quarter", "NSE shareholding pattern", "to_build"),
    ("dii_holding", "ownership", "Domestic institutional holding, latest quarter", "NSE shareholding pattern", "to_build"),
    ("mf_schemes_holding", "ownership", "Number of mutual fund schemes holding the stock", "BharatStock mf-holdings", "pending_field_check"),
    ("mf_schemes_added", "ownership", "Number of schemes that added the stock in the last month", "BharatStock mf-holdings", "pending_field_check"),
    ("mf_new_entrants", "ownership", "Fund houses that were not holders last quarter and are now", "BharatStock mf-holdings", "pending_field_check"),
    ("registry_holders", "ownership", "Registry investors holding the stock, confirmed matches only", "NSE shareholding pattern + registry", "to_build"),
    ("registry_new_entrants", "ownership", "Registry investors that entered the stock this quarter", "NSE shareholding pattern + registry", "to_build"),
    ("holder_count_change", "ownership", "Change in the number of holders above 1% over one quarter", "NSE shareholding pattern", "to_build"),
    ("top10_holding_change", "ownership", "Change in the top ten holders' combined holding", "NSE shareholding pattern", "to_build"),
    ("public_float", "ownership", "Share of shares held by the public, latest quarter", "NSE shareholding pattern", "to_build"),

    # Bulk and block deals (NSE, daily from 2026-10-06)
    ("bulk_buys_20d", "smart_money", "Bulk-deal buys in the last 20 sessions", "NSE bulk deals", "collecting"),
    ("bulk_sells_20d", "smart_money", "Bulk-deal sells in the last 20 sessions", "NSE bulk deals", "collecting"),
    ("registry_buys_20d", "smart_money", "Bulk-deal buys by confirmed registry investors in the last 20 sessions", "NSE bulk deals + registry", "collecting"),
    ("net_bulk_value", "smart_money", "Value of bulk buys less bulk sells in the last 20 sessions", "NSE bulk deals", "collecting"),
    ("distinct_bulk_buyers", "smart_money", "Number of different buyers in the last 20 sessions", "NSE bulk deals", "collecting"),
    ("promoter_bulk_sells", "smart_money", "Bulk sells by promoter group in the last 90 sessions", "NSE bulk deals + shareholding", "collecting"),

    # Promoter behaviour
    ("insider_buys_6m", "promoter_behaviour", "Promoter insider purchases in the last six months", "BharatStock insider-trades", "pending_field_check"),
    ("insider_sells_6m", "promoter_behaviour", "Promoter insider sales in the last six months", "BharatStock insider-trades", "pending_field_check"),
    ("promoter_net_shares_6m", "promoter_behaviour", "Net shares bought less sold by promoters in six months", "BharatStock insider-trades", "pending_field_check"),
    ("capex_announcement", "promoter_behaviour", "Expansion or capex announcement in the last year", "NSE corporate announcements", "to_build"),
    ("related_party_flag", "promoter_behaviour", "Material related-party transactions disclosed", "NSE filings", "gap"),

    # Price and volume (BharatStock prices; fields confirmed in the back-test)
    ("ret_1m", "price", "Share price return over one month", "BharatStock prices", "available"),
    ("ret_3m", "price", "Share price return over three months", "BharatStock prices", "available"),
    ("ret_12m", "price", "Share price return over twelve months", "BharatStock prices", "available"),
    ("from_52w_low", "price", "Price above the 52-week low, in percent", "BharatStock prices", "available"),
    ("from_52w_high", "price", "Price below the 52-week high, in percent", "BharatStock prices", "available"),
    ("volume_ratio_20d", "price", "Volume over the last 20 sessions vs the prior 60", "BharatStock prices", "available"),
    ("delivery_pct_20d", "price", "Average delivery percentage over 20 sessions", "BharatStock prices", "available"),
    ("delivery_change", "price", "Change in delivery percentage vs the prior 60 sessions", "BharatStock prices", "available"),
    ("rel_strength_vs_index", "price", "Return relative to the Nifty 500 over six months", "NSE index data", "to_build"),
    ("volatility_60d", "price", "Annualised volatility over 60 sessions", "BharatStock prices", "available"),
    ("above_200dma", "price", "Close above the 200-day moving average", "BharatStock prices", "available"),
    ("avg_turnover_20d", "price", "Average daily turnover over 20 sessions", "BharatStock prices", "available"),

    # Valuation
    ("pe", "valuation", "Price to trailing twelve-month earnings", "BharatStock prices + financials", "pending_field_check"),
    ("pe_vs_own_history", "valuation", "Current P/E vs the company's own five-year median", "BharatStock prices + financials", "pending_field_check"),
    ("pb", "valuation", "Price to book value", "BharatStock prices + balance sheet", "pending_field_check"),
    ("ps", "valuation", "Price to trailing revenue", "BharatStock prices + financials", "pending_field_check"),
    ("peg", "valuation", "P/E divided by profit growth rate", "BharatStock prices + financials", "pending_field_check"),
    ("ev_ebitda", "valuation", "Enterprise value to EBITDA", "BharatStock balance sheet + financials", "pending_field_check"),
    ("dividend_yield", "valuation", "Dividend per share over price", "BharatStock prices + cash flow", "pending_field_check"),
    ("market_value_bucket", "valuation", "Estimated market value: micro, small, mid or large", "BharatStock prices + shares outstanding", "gap"),

    # Sector and context
    ("sector_ret_3m", "context", "Median three-month return of companies in the same sector", "BharatStock prices + NSE master", "to_build"),
    ("sector_news_count", "context", "News items about the sector in the last 30 days", "Public RSS feeds", "to_build"),
    ("regulatory_events", "context", "Government or regulator notifications touching the sector in the last 90 days", "Government and regulator RSS feeds", "to_build"),
    ("global_peer_ret_3m", "context", "Three-month return of listed global peers", "Free price sources, to be chosen", "gap"),
    ("sector_pe_vs_history", "context", "Sector median P/E vs its own five-year median", "BharatStock prices + financials", "to_build"),
    ("listing_age_years", "context", "Years since listing on NSE", "NSE equity list", "available"),
    ("index_membership", "context", "Current index membership (Nifty 50, Next 50, Midcap, Smallcap, Microcap)", "NSE index files", "to_build"),
]


def summary() -> dict:
    counts = {}
    for _, _, _, _, status in PARAMETERS:
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(PARAMETERS), "by_status": counts}


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), indent=2))
