"""
Six-month figures read as one quarter (13 Nov 2026 audit). NSE's Jul-Sep 2026 filings for Coal India and Coforge carry
revenue only for 1 Apr - 30 Sep (the year to date), and BharatStock's latest quarterly row agrees with that figure, so
"revenue growth" compared six months with one quarter (+199.6%, +193.5%). This checks what BharatStock's rows say about
their own period, so the fix can use it. Prints KEY NAMES and DERIVED ratios only (BharatStock's figures must not be
re-served; this repo's logs are public). About one BharatStock request per company.
    gh workflow run diag.yml -f module=diag_ytd_rows
"""
import os

from .multibagger import fetch, _consolidated

SAMPLE = ["COALINDIA", "COFORGE", "STLTECH", "IOB", "NETWEB", "TCS"]


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    for sym in SAMPLE:
        try:
            q = _consolidated(fetch(sym, key))
        except Exception as e:                           # noqa: BLE001
            print(sym, "fetch failed", str(e)[:100])
            continue
        if not q:
            print(sym, "no rows")
            continue
        keys = sorted(q[0].keys())
        print(f"== {sym}: {len(q)} rows; period-like keys:", [k for k in keys if any(w in k for w in ("period", "date", "month", "type", "duration", "start", "end", "quarter", "year", "cumul", "ytd"))])
        for r in q[:6]:
            meta = {k: r.get(k) for k in keys if any(w in k for w in ("period", "date", "month", "type", "duration", "start", "quarter", "year", "cumul", "ytd"))}
            print("   ", meta)
        for i in range(min(5, len(q) - 1)):
            a, b = q[i].get("revenue"), q[i + 1].get("revenue")
            c = q[i + 4].get("revenue") if i + 4 < len(q) else None
            print(f"    {q[i].get('period_end_date')}: revenue / previous row = {a / b:.2f}" if a and b else "    -",
                  f" / year-ago row = {a / c:.2f}" if a and c else "")


if __name__ == "__main__":
    main()
