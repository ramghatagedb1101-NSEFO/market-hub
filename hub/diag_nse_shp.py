"""
One-off diagnostic: can GitHub Actions reach NSE's shareholding-pattern JSON API?

It works from a home/office IP (tested directly), but several other www.nseindia.com endpoints have
previously 403/404'd specifically from GitHub Actions runners (datacenter IPs), per hub/README notes
on bulk deals and delivery data migrating to Kite for that reason. This checks the same risk here
before any production code is built on it.

Prints status codes and a short sample only -- nothing is published or written to disk.
"""
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}
HOMEPAGE = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
API = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={sym}"
SAMPLES = ["RELIANCE", "TCS", "20MICRONS"]


def main() -> None:
    s = requests.Session()
    try:
        r1 = s.get(HOMEPAGE, headers=HEADERS, timeout=20)
        print("homepage status:", r1.status_code, "cookies:", list(s.cookies.keys()))
    except Exception as exc:
        print("homepage error:", repr(exc)[:200])
        r1 = None
    for sym in SAMPLES:
        try:
            r = s.get(API.format(sym=sym), headers=HEADERS, timeout=20)
            print(sym, "-> status", r.status_code, "len", len(r.text))
            print(" sample:", r.text[:300])
        except Exception as exc:
            print(sym, "error:", repr(exc)[:200])


if __name__ == "__main__":
    main()
