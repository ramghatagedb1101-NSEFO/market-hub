"""
One-off diagnostic (14 Oct 2026, Group F groundwork): before building a 3-year ROCE gate on the
multibagger screen, confirm BharatStock's annual financials actually carry operating_profit,
total_equity (or equity_attributable_to_owners) and both borrowings fields -- not just on the
latest annual row (already seen in hub/diag_financials_fields.py's dump), but on the last three,
since the gate needs three consecutive years, not one.

Five companies across cap sizes, to catch a field that only shows up for large caps.
Nothing is published or written to disk.
"""
import json
import os

from .multibagger import fetch_annual, _consolidated

SAMPLE = ["RELIANCE", "TCS", "HDFCBANK", "ITC", "INFY"]
FIELDS_NEEDED = ("operating_profit", "total_equity", "equity_attributable_to_owners",
                 "borrowings_current", "borrowings_non_current")


def _roce(row):
    op = row.get("operating_profit")
    eq = row.get("total_equity") or row.get("equity_attributable_to_owners")
    debt = row.get("borrowings_current"), row.get("borrowings_non_current")
    if op is None or eq is None or any(d is None for d in debt):
        return None
    ce = eq + sum(debt)
    return None if not ce else op / ce * 100


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    for sym in SAMPLE:
        print(f"\n=== {sym}: annual ===")
        try:
            a = _consolidated(fetch_annual(sym, key))
        except Exception as exc:
            print("ERROR:", exc)
            continue
        if not a:
            print("no consolidated annual rows")
            continue
        print(f"{len(a)} annual rows, newest first")
        for row in a[:3]:
            present = {f: (row.get(f) is not None) for f in FIELDS_NEEDED}
            print(row.get("period_end_date"), present, "roce:", _roce(row))
        print("first row, full:", json.dumps(a[0], indent=1, default=str))


if __name__ == "__main__":
    main()
