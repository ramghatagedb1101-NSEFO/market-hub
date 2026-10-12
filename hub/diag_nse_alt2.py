"""
One-off diagnostic (12 Oct 2026), second pass: the filing types NSE uses for the companies the results
check missed, and which revenue / profit facts the "unreadable" filings actually carry. Writes nothing.
"""
import collections
import re
import sys

import requests

from . import nse_results as nr
from . import shareholding as shp

ALL = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={sym}"
       "&period_ended=all&page=1&size=40")
SYMS = ["AASTHA", "3BBLACKBIO", "ADVAIT", "AARNAV", "ABB", "BURNPUR", "BOHRAIND", "DCMFINSERV",
        "ABBOTINDIA", "ADDIND", "ALFREDHE", "ACEVECTOR"]


def main():
    s = shp.session()
    types = collections.Counter()
    for sym in SYMS:
        r = s.get(ALL.format(sym=sym), headers={**shp.HEADERS, "Accept": "application/json"}, timeout=45)
        rows = (r.json() or {}).get("data") or []
        print(f"\n{sym}: {len(rows)} filings")
        for row in rows[:8]:
            types[row.get("type")] += 1
            print(f"   {row.get('qe_Date')}  type={row.get('type')!r}  sub={row.get('type_Sub')!r}  cons={row.get('consolidated')!r}  xbrl={'yes' if str(row.get('xbrl','')).endswith('.xml') else row.get('xbrl')!r}")
        if sym in ("BURNPUR", "BOHRAIND", "DCMFINSERV", "AASTHA", "3BBLACKBIO"):
            fin = [x for x in rows if str(x.get("xbrl", "")).endswith(".xml") and "financ" in str(x.get("type", "")).lower()]
            if fin:
                try:
                    text = requests.get(fin[0]["xbrl"], headers=nr.UA, timeout=60).text
                    tags = sorted(set(re.findall(r"<in-capmkt:([A-Za-z]+)", text)))
                    keep = [t for t in tags if re.search(r"Revenue|Income|Profit|Loss|Sales|Turnover|Earnings", t)]
                    print(f"   facts in {fin[0]['qe_Date']} XBRL ({len(tags)} tags): {keep[:60]}")
                except Exception as exc:
                    print("   XBRL read failed:", exc)
    print("\nfiling types seen:", dict(types))
    # Abbott India and others with no filings: try the symbol search and the quarterly announcements
    for sym in ("ABBOTINDIA", "ADDIND"):
        for url in (f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={sym}&period_ended=all",
                    f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}&subject=Financial%20Result%20Updates"):
            try:
                r = s.get(url, headers={**shp.HEADERS, "Accept": "application/json"}, timeout=45)
                print(f"\n{sym} {url.split('/api/')[1][:60]} {r.status_code} {r.text[:600]}")
            except Exception as exc:
                print(sym, "ERROR", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
