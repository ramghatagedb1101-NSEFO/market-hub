"""
Probe (16 Oct 2026): why did the first insights run find market insider trades for only 4 of 450 followed
companies? Asks NSE's per-company insider list for 30 large companies, with and without a date range, and
writes only counts and field values of the trade-type column (no company data) to diag_output/insider_check.json.
"""
import json
import time
from collections import Counter
from datetime import datetime, timedelta

from . import config
from .insights import NSE, Nse, _day

SYMS = ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "ITC", "LT", "SBIN", "BHARTIARTL", "AXISBANK",
        "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ADANIENT", "WIPRO", "HCLTECH",
        "TATAMOTORS", "ONGC", "NTPC", "POWERGRID", "M&M", "ULTRACEMCO", "ASIANPAINT", "NESTLEIND", "JSWSTEEL",
        "TATASTEEL", "DRREDDY"]

today = datetime.now(config.IST).date()
d = lambda x: x.strftime("%d-%m-%Y")
cut = (today - timedelta(days=180)).isoformat()
n = Nse()
out = {}
for label, extra in (("no_dates", ""), ("dates_180d", f"&from_date={d(today - timedelta(days=180))}&to_date={d(today)}")):
    none = empty = 0
    raw = recent = market_recent = 0
    modes, oldest = Counter(), []
    for sym in SYMS:
        body = n.json(NSE + f"corporates-pit?index=equities&symbol={sym.replace('&', '%26')}{extra}")
        time.sleep(0.4)
        if body is None:
            none += 1
            continue
        rows = body.get("data") or []
        if not rows:
            empty += 1
        raw += len(rows)
        days = []
        for r in rows:
            dd = _day(r.get("acqfromDt") or r.get("date"))
            if dd:
                days.append(dd.isoformat())
            if dd and dd.isoformat() >= cut:
                recent += 1
                modes[str(r.get("acqMode") or "")] += 1
                if "market" in str(r.get("acqMode") or "").lower():
                    market_recent += 1
        if days:
            oldest.append(min(days))
    out[label] = {"asked": len(SYMS), "no_answer": none, "empty": empty, "rows": raw, "rows_180d": recent,
                  "market_rows_180d": market_recent, "modes_180d": dict(modes.most_common(12)),
                  "oldest_row_seen": min(oldest) if oldest else None, "median_oldest": sorted(oldest)[len(oldest) // 2] if oldest else None}
out["calls"] = n.calls
print(json.dumps(out, indent=1))
config.REPO.joinpath("diag_output").mkdir(exist_ok=True)
config.REPO.joinpath("diag_output", "insider_check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
