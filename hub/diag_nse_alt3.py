"""
One-off diagnostic (12 Oct 2026), third pass: does a quarter's results XBRL carry the comparison periods
(same quarter last year) as their own contexts, and what do revenue / profit read as in each? Writes nothing.
"""
import re
import sys

import requests

from . import nse_results as nr
from . import shareholding as shp

SYMS = ["ABB", "BURNPUR", "AASTHA", "DCMFINSERV", "TITAN"]


def main():
    s = shp.session()
    for sym in SYMS:
        rows = nr.filings(s, sym)
        if not rows:
            print(sym, "no financial filings"); continue
        latest = max(r["quarter"] for r in rows)
        cur = sorted([r for r in rows if r["quarter"] == latest], key=lambda r: r["nature"])[0]
        t = requests.get(cur["xbrl"], headers=nr.UA, timeout=60).text
        ctxs = re.findall(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', t, re.S)
        print(f"\n{sym} {latest} {cur['nature']}: {len(ctxs)} contexts")
        for cid, body in ctxs[:12]:
            sd = re.search(r"<xbrli:startDate>([^<]+)", body); ed = re.search(r"<xbrli:endDate>([^<]+)", body)
            inst = re.search(r"<xbrli:instant>([^<]+)", body)
            dims = re.findall(r'dimension="([^"]+)">([^<]+)<', body)
            vals = {n: nr._fact(t, (n,), cid) for n in ("RevenueFromOperations", "Income", "ProfitLossForPeriod", "ProfitBeforeTax")}
            print(f"   {cid:28} {sd.group(1) if sd else ''}..{ed.group(1) if ed else (inst.group(1) if inst else '')} dims={dims[:2]} {vals}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
