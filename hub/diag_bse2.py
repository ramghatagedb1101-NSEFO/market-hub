"""One-off diagnostic (12 Oct 2026): BSE through a Chrome-like TLS connection (curl_cffi) from GitHub's runners."""
import sys

from curl_cffi import requests as cr

H = {"Accept": "application/json, text/plain, */*", "Origin": "https://www.bseindia.com", "Referer": "https://www.bseindia.com/"}


def main():
    for url in ("https://api.bseindia.com/BseIndiaAPI/api/TabResults_PAR/w?scripcode=500488&tabtype=RESULTS",
                "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?scripcode=&Group=&industry=&segment=Equity&status=Active"):
        for imp in ("chrome", "chrome124", "safari17_0", "edge101"):
            try:
                r = cr.get(url, headers=H, impersonate=imp, timeout=60)
                print(imp, r.status_code, len(r.text), r.text[:160].replace("\n", " "))
                if r.status_code == 200:
                    break
            except Exception as exc:
                print(imp, "ERROR", str(exc)[:150])
    return 0


if __name__ == "__main__":
    sys.exit(main())
