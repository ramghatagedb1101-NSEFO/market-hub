"""
Daily equity prices for every NSE stock from NSE's own full bhavcopy (free, no key, one file per
trading day covering the whole market, with delivery %):
    nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv

Replaces BharatStock's per-company prices endpoint in the stock library (10 Oct 2026). That endpoint
was being read from 2010 for every company every batch -- about 4 of the ~7 BharatStock calls each
company cost -- when nothing uses more than the last 253 trading days. One file a day covers all
~2,500 companies for zero BharatStock calls.

Each day's file is reduced to the columns used (close, volume, delivery %, previous close) and kept
in CACHE_DIR, which the library workflow carries between runs with actions/cache, so a run downloads
only the days it has not seen. A day NSE has no file for (holiday, weekend) is remembered with a
marker once it is safely in the past, so it is not asked for again. Weekends are asked for too: NSE
holds the odd special session on one (Sunday 1 Feb 2026, Budget day), and missing it shifts every
return that spans it.

The file's prices are NOT adjusted for splits or bonuses -- its PREV_CLOSE on an ex-date is the
unadjusted figure (checked 10 Oct 2026: Rolex Rings' 10-to-1 split on 17 Oct 2025 shows as a 90%
fall). load() takes the split/bonus factors from NSE's corporate-actions list
(corporate_actions.price_factors) and scales every close before each ex-date, which is how
BharatStock's series is adjusted too.
"""
import csv
import io
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from . import config

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0 Safari/537.36", "Accept": "*/*"}
CACHE_DIR = config.REPO / ".cache" / "bhav"
SERIES_PREF = ("EQ", "BE", "BZ", "SM", "ST")     # one row per symbol: the first series found in this order
LOOKBACK_DAYS = 400                               # calendar days: > 253 trading days plus holidays


def _num(s):
    s = (s or "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _path(d: date) -> Path:
    return CACHE_DIR / f"{d.isoformat()}.csv"


def _none_marker(d: date) -> Path:
    return CACHE_DIR / f"{d.isoformat()}.none"


def _slim(text: str) -> tuple[date | None, str]:
    """(the trading date printed in the file, symbol,close,volume,deliv_pct,prev_close rows) -- one
    row per symbol, preferred series first."""
    best, file_date = {}, None
    rank = {s: i for i, s in enumerate(SERIES_PREF)}
    reader = csv.reader(io.StringIO(text))
    head = [h.strip().upper() for h in next(reader)]
    ix = {k: head.index(k) for k in ("SYMBOL", "SERIES", "DATE1", "PREV_CLOSE", "CLOSE_PRICE", "TTL_TRD_QNTY",
                                     "DELIV_PER")}
    for row in reader:
        if len(row) < len(head):
            continue
        if file_date is None:
            try:
                file_date = datetime.strptime(row[ix["DATE1"]].strip(), "%d-%b-%Y").date()
            except ValueError:
                pass
        ser = row[ix["SERIES"]].strip()
        if ser not in rank:
            continue
        sym = row[ix["SYMBOL"]].strip()
        if sym in best and rank[best[sym][0]] <= rank[ser]:
            continue
        best[sym] = (ser, row[ix["CLOSE_PRICE"]].strip(), row[ix["TTL_TRD_QNTY"]].strip(),
                     row[ix["DELIV_PER"]].strip(), row[ix["PREV_CLOSE"]].strip())
    out = io.StringIO()
    w = csv.writer(out)
    for sym, (_, close, vol, deliv, prev) in sorted(best.items()):
        w.writerow([sym, close, vol, deliv, prev])
    return file_date, out.getvalue()


def _download(d: date, today: date) -> bool:
    """True if the day's file is now cached. A 404 more than 3 days back is a holiday (marked, never
    asked again); a recent 404 just means NSE has not published it yet.

    On some holidays NSE serves the previous trading day's file under the holiday's name (seen for
    2 Oct 2026: identical to 1 Oct). The file's own DATE1 column decides which day it is, so a
    holiday is never counted as a second copy of the day before."""
    for attempt in range(3):
        try:
            r = requests.get(URL.format(d=d.strftime("%d%m%Y")), headers=HEADERS, timeout=30)
        except requests.RequestException:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 404:
            if (today - d).days > 3:
                _none_marker(d).write_text("", encoding="utf-8")
            return False
        if r.ok and r.text.lstrip("﻿").upper().startswith("SYMBOL"):
            file_date, slim = _slim(r.text.lstrip("﻿"))
            if file_date is None:
                return False
            if not _path(file_date).exists():
                _path(file_date).write_text(slim, encoding="utf-8")
            if file_date != d:
                _none_marker(d).write_text("", encoding="utf-8")
                return False
            return True
        time.sleep(3 * (attempt + 1))
    return False


def refresh(today: date | None = None, lookback_days: int = LOOKBACK_DAYS, pause: float = 0.2) -> dict:
    """Downloads every weekday in the lookback window that is neither cached nor a known holiday.
    Returns counts for the run log."""
    today = today or date.today()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    got = missing = cached = 0
    d = today - timedelta(days=lookback_days)
    while d <= today:
        if _path(d).exists() or _none_marker(d).exists():
            cached += 1
        else:
            if _download(d, today):
                got += 1
            else:
                missing += 1
            time.sleep(pause)
        d += timedelta(days=1)
    # Days older than the window are never read again.
    cutoff = (today - timedelta(days=lookback_days + 7)).isoformat()
    for f in CACHE_DIR.iterdir():
        if f.stem < cutoff:
            f.unlink()
    return {"downloaded": got, "not_available": missing, "already_cached": cached}


def load(factors: dict | None = None, today: date | None = None, lookback_days: int = LOOKBACK_DAYS) -> dict:
    """{symbol: (series [(date, adjusted close)], volume [adjusted], delivery %)} from the cached days,
    oldest first -- the same shapes BharatStock's prices endpoint used to give, so price_values() and
    index_relative_values() take them unchanged. Delivery % is listed only for days that report it
    (it is blank for some series), as the BharatStock version did.

    factors: {symbol: [(ex_date, factor)]} from corporate_actions.price_factors() -- every close
    before an ex-date is multiplied by its factor (0.1 for a 10-to-1 split), volume divided by it."""
    today = today or date.today()
    factors = factors or {}
    start = (today - timedelta(days=lookback_days)).isoformat()
    raw = {}   # sym -> list of (date, close, volume, deliv)
    for f in sorted(CACHE_DIR.glob("*.csv")):
        if f.stem < start:
            continue
        d = date.fromisoformat(f.stem)
        for row in csv.reader(io.StringIO(f.read_text(encoding="utf-8"))):
            if len(row) < 5:
                continue
            close = _num(row[1])
            if not close:
                continue
            raw.setdefault(row[0], []).append((d, close, _num(row[2]), _num(row[3])))
    out = {}
    for sym, rows in raw.items():
        events = factors.get(sym) or []
        series, volume, delivery = [], [], []
        for d, close, vol, deliv in rows:
            k = 1.0
            for ex, fac in events:
                if d < ex:
                    k *= fac
            series.append((d, close * k))
            volume.append(vol / k if vol is not None else 0.0)
            if deliv is not None:
                delivery.append(deliv)
        out[sym] = (series, volume, delivery)
    return out
