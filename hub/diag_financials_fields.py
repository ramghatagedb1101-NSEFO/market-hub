"""
One-off diagnostic (14 Oct 2026, G4 check): working_capital_days/_change and dividend_paid have been a
gap for 2574/2574 companies in production since they were added -- every one of the guessed BharatStock
field names (trade_receivables/receivables/sundry_debtors, inventories/inventory/stock_in_trade,
trade_payables/payables/sundry_creditors, dividend_paid/dividends_paid/total_dividend_paid/
dividend_payout) apparently never matches. This prints the REAL top-level keys of one quarterly and one
annual financials row for a handful of large, dividend-paying companies, so the guesses in
hub/library.py can be corrected (or dropped) against confirmed field names instead of more guessing.

Nothing is published or written to disk.
"""
import json
import os

from .multibagger import fetch, fetch_annual, _consolidated

SAMPLE = ["RELIANCE", "TCS", "HDFCBANK"]


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    for sym in SAMPLE:
        print(f"\n=== {sym}: quarterly ===")
        try:
            q = _consolidated(fetch(sym, key))
            if q:
                print("keys:", sorted(q[0].keys()))
                print("row:", json.dumps(q[0], indent=1, default=str))
            else:
                print("no consolidated quarterly rows")
        except Exception as exc:
            print("ERROR:", exc)

        print(f"\n=== {sym}: annual ===")
        try:
            a = _consolidated(fetch_annual(sym, key))
            if a:
                print("keys:", sorted(a[0].keys()))
                print("row:", json.dumps(a[0], indent=1, default=str))
            else:
                print("no consolidated annual rows")
        except Exception as exc:
            print("ERROR:", exc)


if __name__ == "__main__":
    main()
