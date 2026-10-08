"""
NSE official index bhavcopy (free, no key). Fallback for NIFTY when Kite is not configured.
One CSV per trading day: nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv
Holidays return 404 and are skipped.
"""
import csv
import io
import time
from datetime import date, timedelta

import requests

URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "*/*"}


def fetch_day(d: date, index_name: str):
    """store.refresh_prices() deliberately raises rather than write a partial day, so a transient
    network blip here would otherwise skip the entire rest of the daily pipeline (seen 2026-10-08 on
    the Kite-token relay call, same class of bug). Retries a genuine fetch failure a few times before
    letting it propagate; a 404 (holiday, no bhavcopy published) is not retried, it means no data."""
    last_exc = None
    for attempt in range(4):
        try:
            r = requests.get(URL.format(d=d.strftime("%d%m%Y")), headers=HEADERS, timeout=20)
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if r.status_code == 404:
                return None
            if r.ok:
                for row in csv.DictReader(io.StringIO(r.text)):
                    if row["Index Name"].strip() == index_name:
                        return float(row["Closing Index Value"])
                return None
            last_exc = requests.HTTPError(f"{r.status_code} for {d.isoformat()}")
        if attempt < 3:
            time.sleep(3 * (attempt + 1))
    raise last_exc


def fetch_range(start: date, end: date, index_name: str, pause: float = 0.25) -> dict:
    out = {}
    d = start
    while d <= end:
        if d.weekday() < 5:
            close = fetch_day(d, index_name)
            if close is not None:
                out[d.isoformat()] = close
            time.sleep(pause)
        d += timedelta(days=1)
    return out
