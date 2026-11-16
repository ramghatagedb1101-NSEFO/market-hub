"""16 Nov 2026: does NSE's bulk-deal history service cap a day at 70 rows? 13 Nov had 136 in the daily file.
Prints counts and the response's own keys only."""
import sys

from curl_cffi import requests as creq

URL = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"


def main() -> int:
    s = creq.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/", timeout=30)
    s.get("https://www.nseindia.com/report-detail/display-bulk-and-block-deals", timeout=30)
    ref = {"Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"}
    for extra in ({}, {"page": 2}, {"csv": "true"}):
        r = s.get(URL, params={"optionType": "bulk_deals", "from": "13-11-2026", "to": "13-11-2026", **extra}, timeout=60, headers=ref)
        ct = r.headers.get("content-type", "")
        if "json" in ct:
            b = r.json()
            rows = b.get("data", []) if isinstance(b, dict) else b
            print(extra, "rows", len(rows), "top keys", sorted(b.keys()) if isinstance(b, dict) else "list",
                  {k: v for k, v in b.items() if k != "data"} if isinstance(b, dict) else "")
        else:
            lines = r.text.splitlines()
            print(extra, ct, "lines", len(lines), "head", lines[0][:150] if lines else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
