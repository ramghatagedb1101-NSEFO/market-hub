"""
Results outliers (13 Nov 2026 audit): after the year-to-date fix, a few companies still show impossible exchange-filing
growth (Metro Brands +11,115%, Ingersoll-Rand +5,904%, Dhanlaxmi Bank +4,572%, Oswal Pumps +1,871%) and NSE's figure
overrides BharatStock's. This prints what the reader takes from every filing of each (period, start, consolidated or
standalone, revenue and profit in crore, plus the unit/decimals attributes of the revenue fact), from NSE's public
filings only (nothing from BharatStock).
    gh workflow run diag.yml -f module=diag_results_outliers
"""
import re

import requests

from . import nse_results as nr
from . import shareholding as shp

SYMS = ["METROBRAND", "INGERRAND", "DHANBANK", "OSWALPUMPS", "TI"]


def main():
    s = shp.session()
    cr = lambda v: None if v is None else round(v / 1e7, 2)
    for sym in SYMS:
        try:
            rows = nr.filings(s, sym)
        except Exception as e:                       # noqa: BLE001
            print(sym, "filings failed:", str(e)[:120])
            continue
        print("==", sym, len(rows), "filings")
        for r in sorted(rows, key=lambda r: (r["quarter"], r["nature"]))[-12:]:
            try:
                f = nr.facts(r["xbrl"])
                t = requests.get(r["xbrl"], headers=nr.UA, timeout=60).text
                m = re.search(r'<in-capmkt:(RevenueFromOperations|Income)\b([^>]*)>', t)
                attrs = re.sub(r'contextRef="[^"]*"', "", m.group(2)).strip() if m else "-"
            except Exception as e:                   # noqa: BLE001
                print("  ", r["quarter"], r["nature"], "read failed", str(e)[:80])
                continue
            print("  ", r["quarter"], r["nature"], "revised" if r["revised"] else "original", r["broadcast"][:11],
                  "| start", f.get("start"), "ytd", f.get("ytd"), "| rev", cr(f.get("revenue")), "cr, profit",
                  cr(f.get("profit")), "cr, eps", f.get("eps"), "|", attrs[:80])


if __name__ == "__main__":
    main()
