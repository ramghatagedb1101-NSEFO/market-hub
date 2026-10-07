"""
One-off diagnostic: runs the exact same per-company pipeline as hub/library.main() -- fetch,
fetch_annual, cash_flow_values, fetch_prices, valuation_values, NSE shareholding -- but against a
fixed sample of 10 symbols instead of the full 2570-company universe. Finishes in well under a
minute of real work, so a fix can be checked without a 70-minute GitHub Actions run every time.

Prints full detail per company: whether each step succeeded, the exception text on failure, and the
computed values -- not just the published met/not_met counts. Nothing is published.
"""
import json
import os
import time

from .library import financial_values, cash_flow_values, price_values, valuation_values, evaluate
from .multibagger import fetch, fetch_annual, _consolidated
from .backtest_multibagger import prices as fetch_prices
from . import shareholding as shp

SAMPLE = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
          "20MICRONS", "ZAGGLE", "RBZJEWEL", "CENTUM", "ACC"]


def run_one(sym: str, key: str, nse_session) -> dict:
    out = {"symbol": sym}
    try:
        rows = fetch(sym, key)
        out["financials_quarters"] = len(rows)
    except Exception as exc:
        out["financials_error"] = str(exc)[:200]
        return out
    values = financial_values(rows)
    try:
        annual_rows = fetch_annual(sym, key)
        out["annual_quarters"] = len(annual_rows)
        values.update(cash_flow_values(annual_rows))
    except Exception as exc:
        out["annual_error"] = str(exc)[:200]
    try:
        px = fetch_prices(sym, key)
        out["price_points"] = len(px)
    except Exception as exc:
        out["price_error"] = str(exc)[:200]
        px = []
    values.update(price_values(px, [], []))
    last = px[-1][1] if px else None
    values.update(valuation_values(_consolidated(rows), last))
    try:
        nse_records = shp.fetch(nse_session, sym)
        out["nse_shp_quarters"] = len(nse_records)
        values.update(shp.values(nse_records))
    except Exception as exc:
        out["nse_shp_error"] = str(exc)[:200]
    result = evaluate({k: v for k, v in values.items() if not k.startswith("_")})
    out["result"] = {k: v for k, v in result.items() if k != "cells"}
    out["values"] = {k: round(v, 3) if isinstance(v, float) else v for k, v in values.items()}
    return out


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    nse_session = shp.session()
    started = time.time()
    for sym in SAMPLE:
        r = run_one(sym, key, nse_session)
        print(f"\n=== {sym} ===")
        print(json.dumps(r, indent=1, default=str))
    print(f"\ntotal seconds: {time.time() - started:.1f}")


if __name__ == "__main__":
    main()
