"""
One-off diagnostic (12 Oct 2026): can BSE supply results for companies that file none at NSE?
1) the scrip list with ISINs (to map NSE symbols), 2) the results table for a few of them, 3) the results
announcements with their attachments. Writes nothing.
"""
import csv
import io
import json
import sys

import requests

API = "https://api.bseindia.com/BseIndiaAPI/api"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.5",
     "Origin": "https://www.bseindia.com", "Referer": "https://www.bseindia.com/", "Sec-Fetch-Site": "same-site"}
SYMS = ["ABBOTINDIA", "ADDIND", "ALFREDHE", "ACEVECTOR", "TITAN"]


def main():
    s = requests.Session()
    s.headers.update(H)
    # NSE symbol -> ISIN
    eq = requests.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv", headers={"User-Agent": H["User-Agent"]}, timeout=60).text
    isin = {r["SYMBOL"]: r[" ISIN NUMBER"].strip() for r in csv.DictReader(io.StringIO(eq)) if r.get("SYMBOL")}
    print("NSE list:", len(isin), {k: isin.get(k) for k in SYMS})
    # BSE scrip list
    r = s.get(f"{API}/ListofScripData/w", params={"scripcode": "", "Group": "", "industry": "", "segment": "Equity", "status": "Active"}, timeout=90)
    print("ListofScripData", r.status_code, r.headers.get("content-type"), len(r.text))
    try:
        rows = r.json()
        rows = rows if isinstance(rows, list) else rows.get("Table") or rows.get("data") or []
        print("rows", len(rows), "keys", list(rows[0].keys()) if rows else None)
        by_isin = {str(x.get("ISIN_NUMBER") or x.get("ISIN") or "").strip(): x for x in rows}
        codes = {sym: (by_isin.get(isin.get(sym)) or {}).get("SCRIP_CD") for sym in SYMS}
        print("codes", codes)
    except Exception as exc:
        print("parse failed", exc, r.text[:300]); codes = {}
    for sym, code in codes.items():
        if not code:
            continue
        for name, url, params in (("TabResults_PAR", f"{API}/TabResults_PAR/w", {"scripcode": code, "tabtype": "RESULTS"}),
                                  ("announcements Result", f"{API}/AnnSubCategoryGetData/w",
                                   {"pageno": 1, "strCat": "Result", "subcategory": "-1", "strPrevDate": "20260601", "strToDate": "20261012",
                                    "strSearch": "P", "strscrip": code, "strType": "C"})):
            try:
                x = s.get(url, params=params, timeout=60)
                print(f"\n{sym} {code} {name} {x.status_code}: {x.text[:2500]}")
            except Exception as exc:
                print(sym, name, "ERROR", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
