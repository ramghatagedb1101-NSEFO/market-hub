"""16 Nov 2026: can NSE's history service give the bulk deals of days the daily collector missed (6 and 9 Nov)?
Prints counts and column names only."""
import sys

from curl_cffi import requests as creq


def main() -> int:
    s = creq.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/", timeout=30)
    s.get("https://www.nseindia.com/report-detail/display-bulk-and-block-deals", timeout=30)
    for frm, to in (("06-11-2026", "09-11-2026"), ("06-10-2026", "13-11-2026")):
        r = s.get("https://www.nseindia.com/api/historical/bulk-deals", params={"from": frm, "to": to}, timeout=60,
                  headers={"Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"})
        print(frm, to, "HTTP", r.status_code, r.headers.get("content-type"))
        try:
            body = r.json()
        except Exception:
            print("  not JSON:", r.text[:200].replace("\n", " "))
            continue
        rows = body.get("data", body) if isinstance(body, dict) else body
        print("  rows", len(rows), "keys", sorted(rows[0].keys()) if rows else None)
        days = {}
        for x in rows:
            d = x.get("BD_DT_DATE") or x.get("date")
            days[d] = days.get(d, 0) + 1
        print("  per day", dict(sorted(days.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
