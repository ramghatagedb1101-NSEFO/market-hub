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
    r = requests.get(URL.format(d=d.strftime("%d%m%Y")), headers=HEADERS, timeout=20)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    for row in csv.DictReader(io.StringIO(r.text)):
        if row["Index Name"].strip() == index_name:
            return float(row["Closing Index Value"])
    return None


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
