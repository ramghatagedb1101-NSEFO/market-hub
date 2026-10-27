"""
Exchange trading holidays (27 Oct 2026). Until now "the next session" meant the next weekday, so on a weekday holiday the
close estimate targeted a day the market was shut and its records were never scored. NSE publishes the year's trading
holidays (free JSON, needs a homepage visit for cookies; blocked from the owner's laptop, fine on GitHub). The daily run
refreshes state/holidays.json; everything else reads load(). BSE keeps the same equity holidays, so SENSEX uses them too.
A failed refresh keeps the stored list; with no list at all, weekends only (the old behaviour).
"""
import json
from datetime import date, datetime

import requests

from . import config

FILE = config.REPO / "state" / "holidays.json"
HOME = "https://www.nseindia.com/resources/exchange-communication-holidays"
API = "https://www.nseindia.com/api/holiday-master?type=trading"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
           "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Referer": HOME}
_cache: set | None = None


def fetch() -> list[str]:
    """ISO dates of this year's equity (CM segment) trading holidays, from NSE."""
    s = requests.Session()
    s.get(HOME, headers=HEADERS, timeout=20)
    body = s.get(API, headers=HEADERS, timeout=20).json()
    rows = body.get("CM") or body.get("FO") or []
    days = sorted({datetime.strptime(r["tradingDate"], "%d-%b-%Y").date().isoformat() for r in rows if r.get("tradingDate")})
    if not days:
        raise RuntimeError("NSE holiday list came back empty")
    return days


def refresh() -> dict:
    """Merge NSE's current list into the stored one (past years are kept, so history stays right)."""
    try:
        old = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = {"days": []}
    days = sorted(set(old.get("days", [])) | set(fetch()))
    out = {"fetched": datetime.now(config.IST).isoformat(timespec="minutes"), "days": days}
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(out, indent=0), encoding="utf-8")
    global _cache
    _cache = set(days)
    return out


def load() -> set:
    global _cache
    if _cache is None:
        try:
            _cache = set(json.loads(FILE.read_text(encoding="utf-8")).get("days", []))
        except (OSError, ValueError):
            _cache = set()
    return _cache


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in load()


if __name__ == "__main__":
    print(json.dumps(fetch(), indent=0))
