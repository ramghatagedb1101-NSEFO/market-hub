"""
Results plausibility check (13 Nov 2026, owner's audit: "not sure what else is missed"). About 31 of 352 companies above
Rs 20,000 crore showed figures that cannot be right (Coal India revenue +199.6% a year, Sterlite Tech profit +12,825%),
yet the library's NSE cross-check said "ok". For a few of them this prints what NSE's own filings say: every results
filing in the list (quarter, consolidated/standalone, original/revised) and, from each XBRL, every reporting context with
its period and revenue -- so we can see whether the quarter or the year-to-date column was read. NSE's figures only
(public filings); nothing from BharatStock is printed.
    gh workflow run diag.yml -f module=diag_results_check
"""
import re

import requests

from . import nse_results as nr
from . import shareholding as shp

SYMS = ["COALINDIA", "COFORGE", "STLTECH", "IOB", "NETWEB", "HATSUN"]


def contexts(url: str) -> list:
    t = requests.get(url, headers=nr.UA, timeout=60).text
    out = []
    for m in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', t, re.S):
        cid, body = m.group(1), m.group(2)
        st = re.search(r"<xbrli:startDate>([^<]+)<", body)
        en = re.search(r"<xbrli:endDate>([^<]+)<", body) or re.search(r"<xbrli:instant>([^<]+)<", body)
        rev = nr._fact(t, nr.REVENUE, cid)
        prof = nr._fact(t, nr.PROFIT, cid)
        if rev is not None or prof is not None:
            out.append((cid, st.group(1) if st else None, en.group(1) if en else None, rev, prof))
    first = re.search(r'<in-capmkt:DateOfEndOfReportingPeriod\b[^>]*contextRef="([^"]+)"', t)
    return out, first.group(1) if first else None


def main():
    s = shp.session() if hasattr(shp, "session") else requests.Session()
    for sym in SYMS:
        try:
            rows = nr.filings(s, sym)
        except Exception as e:                       # noqa: BLE001
            print(sym, "filings failed:", str(e)[:120])
            continue
        rows.sort(key=lambda r: (r["quarter"], r["nature"], r["broadcast"]))
        print(f"== {sym}: {len(rows)} filings; latest 6:")
        for r in rows[-6:]:
            print("  ", r["quarter"], r["nature"], "revised" if r["revised"] else "original", r["broadcast"])
        latest = max(r["quarter"] for r in rows) if rows else None
        for q in sorted({r["quarter"] for r in rows}, reverse=True)[:5]:
            for nature in ("consolidated", "standalone"):
                pick = nr._pick(rows, q, nature)
                if not pick:
                    continue
                try:
                    ctx, first = contexts(pick["xbrl"])
                    f = nr.facts(pick["xbrl"])
                except Exception as e:               # noqa: BLE001
                    print("   ", q, nature, "read failed", str(e)[:80])
                    continue
                print(f"   {q} {nature}: facts() read ctx={first} revenue={f.get('revenue')} profit={f.get('profit')}")
                for c in ctx:
                    print(f"      ctx {c[0]} {c[1]} -> {c[2]}  revenue={c[3]}  profit={c[4]}")
        print("   latest:", latest)


if __name__ == "__main__":
    main()
