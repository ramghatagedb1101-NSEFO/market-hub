"""One-off (14 Oct 2026, Kite/BharatStock audit): does BharatStock report the day's used or remaining allowance, so
every caller (library, manual multibagger and back-test runs, the relay) can share one true count? Three requests:
one normal data call (all response headers printed) and two likely usage endpoints."""
import os

import requests


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    for url, params in (("https://bharatstockapi.com/v1/stocks/RELIANCE/financials", {"period_type": "quarterly"}),
                        ("https://bharatstockapi.com/v1/usage", None),
                        ("https://bharatstockapi.com/v1/account", None)):
        r = requests.get(url, params=params, headers={"X-API-Key": key}, timeout=30)
        print("\n==", r.status_code, url)
        for k, v in r.headers.items():
            if any(s in k.lower() for s in ("limit", "quota", "remain", "usage", "reset", "retry", "credit", "plan")):
                print(f"   {k}: {v}")
        print("   header names:", ", ".join(sorted(r.headers.keys())))
        if "financials" not in url:
            print("   body:", r.text[:400])


if __name__ == "__main__":
    main()
