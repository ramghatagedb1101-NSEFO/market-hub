"""
Data-health checks (11 Oct 2026): figures that cannot be right, or that two sources disagree on, are
flagged on the company's library entry ("flags") so the Shortlist does not rank on them and the
dashboard shows them. Complements the NSE cross-check (hub/nse_results.py), which compares growth.
"""
from datetime import date


def flags(values: dict, check: dict | None, val_basis: dict | None, fin_period, today: date) -> list[dict]:
    """[{"level": "severe" | "info", "text": ...}]. Severe = the figure is probably wrong."""
    out = []

    def add(level, text):
        out.append({"level": level, "text": text})

    v = values.get
    # Odd but often genuine (10 Oct, Bajaj Holdings: profit 687% of revenue from associates' profits), so notes:
    if v("net_margin") is not None and v("net_margin") > 100:
        add("info", f"Profit is {v('net_margin'):.0f}% of revenue: associates' profits or a one-off gain, not operations")
    if v("net_margin") is not None and v("net_margin") < -100:
        add("info", f"Losses are {-v('net_margin'):.0f}% of revenue: revenue is tiny or the quarter is exceptional")
    if v("roe") is not None and abs(v("roe")) > 200:
        add("info", f"ROE of {v('roe'):.0f}% is distorted by very small or negative equity")
    if v("debt_to_equity") is not None and v("debt_to_equity") > 50:
        add("info", f"Debt/equity of {v('debt_to_equity'):.0f}: equity is very small or negative")
    # Probably wrong figures:
    if v("pe") is not None and 0 < v("pe") < 1:
        add("severe", f"P/E of {v('pe'):.2f}x: the price or earnings figure is suspect")
    nse = (check or {}).get("nse") or {}
    bs_shares = (val_basis or {}).get("shares")
    if nse.get("shares") and bs_shares and abs(bs_shares / nse["shares"] - 1) > 0.10:
        add("severe", f"Share count differs: {bs_shares / 1e7:,.2f} cr (BharatStock) vs {nse['shares'] / 1e7:,.2f} cr "
                      f"(NSE filing) - market value and P/E may be off (recent split or bonus?)")
    st = (check or {}).get("status")
    if st == "period_differs" and (check.get("period") or "") > (check.get("bs_period") or ""):
        add("info", f"Results for the quarter to {check['period']} are filed at NSE but not yet loaded from BharatStock")
    try:
        age = (today - date.fromisoformat(str(fin_period)[:10])).days
        if age > 200:
            add("info", f"Latest results on file are for the quarter to {str(fin_period)[:10]}")
    except (TypeError, ValueError):
        pass
    return out
