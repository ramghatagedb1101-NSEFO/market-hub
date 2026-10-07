"""One-off: inspect the full response headers on a BharatStock 429, looking for a rate-limit/quota
reset time (X-RateLimit-Reset, Retry-After, or similar) so we know when to safely resume, instead of
guessing. A single call -- it is already failing anyway, so this costs nothing extra."""
import os
import requests


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    r = requests.get("https://bharatstockapi.com/v1/stocks/RELIANCE/financials",
                      params={"period_type": "quarterly"}, headers={"X-API-Key": key}, timeout=30)
    print("status:", r.status_code)
    for k, v in r.headers.items():
        print(f"{k}: {v}")
    print("body:", r.text[:500])


if __name__ == "__main__":
    main()
