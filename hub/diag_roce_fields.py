"""
One-off diagnostic (14 Oct 2026, Group F groundwork): before building a 3-year ROCE gate on the
multibagger screen, confirm BharatStock's annual financials actually carry operating_profit,
total_equity (or equity_attributable_to_owners) and both borrowings fields -- not just on the
latest annual row (already seen in hub/diag_financials_fields.py's dump), but on the last three,
since the gate needs three consecutive years, not one.

Five companies across cap sizes, to catch a field that only shows up for large caps.

Prints full rows (for a human reading the Actions log) and also writes a derived-only summary --
field presence booleans and computed ROCE percentages, never raw financial figures -- to
diag_output/roce_fields.json, since this cloud environment cannot always read back an Actions run
log directly (egress policy); the workflow commits that file so any session can read it from git.
"""
import json
import os
from pathlib import Path

from .multibagger import fetch_annual, _consolidated

OUT_FILE = Path(__file__).resolve().parent.parent / "diag_output" / "roce_fields.json"

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
    summary = {}
    for sym in SAMPLE:
        print(f"\n=== {sym}: annual ===")
        try:
            a = _consolidated(fetch_annual(sym, key))
        except Exception as exc:
            print("ERROR:", exc)
            summary[sym] = {"error": str(exc)[:200]}
            continue
        if not a:
            print("no consolidated annual rows")
            summary[sym] = {"rows": 0}
            continue
        print(f"{len(a)} annual rows, newest first")
        years = []
        for row in a[:3]:
            present = {f: (row.get(f) is not None) for f in FIELDS_NEEDED}
            roce = _roce(row)
            print(row.get("period_end_date"), present, "roce:", roce)
            years.append({"period_end_date": row.get("period_end_date"), "present": present, "roce": roce})
        summary[sym] = {"rows": len(a), "years": years}
        print("first row, full:", json.dumps(a[0], indent=1, default=str))
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote derived-only summary to {OUT_FILE}")


if __name__ == "__main__":
    main()
