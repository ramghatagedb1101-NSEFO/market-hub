"""
Intraday index path on every recorded expiry day (14 Oct 2026).

The history test (hub/expiry_history.py) holds the evening-before option chain and only the expiry day's
open/high/low/close. The live meter reads at 10:00/12:00/14:00/15:00, so testing anything about the day's own state
-- where the index is at 14:00 against the walls, how far it has already run, whether it pins late -- needs the path.
Kite's historical minute candles for the index (owner's paid plan) supply it.

Reads state/expiry_history/records.json from the private repository and fetches only expiry days not stored yet:
state/expiry_history/intraday/<INDEX>_<YEAR>.json = {"YYYY-MM-DD": [[minute, open, high, low, close], ...]}, where
minute = minutes after 09:15 IST (0 = the 09:15 candle, 374 = 15:29). coverage.json says which days have a path.
Index prices only: Kite keeps no history for expired option contracts.

Run by hand: workflow expiry-intraday.yml (needs the day's Kite login, like threshold-test.yml).
"""
import json
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from . import config
from .expiry_history import load, save
from .sources import kite

BASE = "state/expiry_history/intraday"
WINDOW_DAYS = 55            # Kite caps one minute-candle request at 60 days
OPEN_MIN = 9 * 60 + 15
LAST_MIN = 374              # the 15:29 candle; Kite's minute candles stop there
FULL_DAY = 360              # fewer minutes than this marks a short or gappy day in coverage.json


def windows(days: list) -> list:
    """Sorted dates grouped so each group spans at most WINDOW_DAYS calendar days (one Kite request each)."""
    out, cur = [], []
    for d in days:
        if cur and (d - cur[0]).days > WINDOW_DAYS:
            out.append(cur)
            cur = []
        cur.append(d)
    if cur:
        out.append(cur)
    return out


def _ist(ts: datetime) -> datetime:
    return ts.astimezone(config.IST) if ts.tzinfo else ts


def rows_by_day(candles: list, want: set) -> dict:
    """Kite candles -> {day: [[minute, o, h, l, c], ...]} for the wanted days, sorted by minute, session only."""
    got = defaultdict(list)
    for r in candles or []:
        t = _ist(r["date"])
        day = t.date().isoformat()
        m = t.hour * 60 + t.minute - OPEN_MIN
        if day in want and 0 <= m <= LAST_MIN:
            got[day].append([m, round(float(r["open"]), 2), round(float(r["high"]), 2),
                             round(float(r["low"]), 2), round(float(r["close"]), 2)])
    return {d: sorted(v) for d, v in got.items()}


def fetch_index(k, symbol: str, days: list) -> tuple[dict, int]:
    exch, name = config.INDEX_SOURCES[symbol]["kite"]
    token = kite.instrument_token(k, exch, name)
    got, calls = {}, 0
    for w in windows(sorted(days)):
        frm, to = datetime.combine(w[0], time(9, 0)), datetime.combine(w[-1], time(15, 35))
        candles = kite._retry(lambda: k.historical_data(token, frm, to, "minute"))
        calls += 1
        got.update(rows_by_day(candles, {d.isoformat() for d in w}))
    return got, calls


def main() -> dict:
    records = load("state/expiry_history/records.json") or {}
    if not records:
        raise RuntimeError("no state/expiry_history/records.json in the private repository")
    expiries = defaultdict(set)
    for r in records.values():
        expiries[r["symbol"]].add(r["expiry"])
    coverage = load(f"{BASE}/coverage.json") or {}
    retry_missing = os.getenv("RETRY_MISSING") == "1"
    k = kite.client()

    report = {}
    for sym in sorted(expiries):
        exps = expiries[sym]
        files = {}
        for year in sorted({e[:4] for e in exps}):
            path = f"{BASE}/{sym}_{year}.json"
            files[path] = load(path) or {}
        have = {d for f in files.values() for d in f}
        known_empty = set() if retry_missing else set((coverage.get(sym) or {}).get("no_data", []))
        need = sorted(date.fromisoformat(e) for e in exps if e not in have and e not in known_empty)
        got, calls = fetch_index(k, sym, need) if need else ({}, 0)
        for day, rows in got.items():
            files[f"{BASE}/{sym}_{day[:4]}.json"][day] = rows
        for path in sorted({f"{BASE}/{sym}_{d[:4]}.json" for d in got}):
            save(path, files[path], f"expiry intraday: {path.rsplit('/', 1)[-1]} ({len(files[path])} days)")
        with_path = {d for f in files.values() for d in f}
        report[sym] = {
            "expiries": len(exps),
            "with_path": len(with_path),
            "fetched_now": len(got),
            "kite_calls": calls,
            "first_with_path": min(with_path) if with_path else None,
            "no_data": sorted(e for e in exps if e not in with_path),
            "short_days": sorted(d for f in files.values() for d, rows in f.items() if len(rows) < FULL_DAY),
        }
    out = {"updated": datetime.now(config.IST).isoformat(timespec="minutes"), **report}
    save(f"{BASE}/coverage.json", out, "expiry intraday coverage")
    return out


if __name__ == "__main__":
    result = main()
    print(json.dumps(result, indent=1))
    if os.getenv("GITHUB_ACTIONS"):
        brief = {s: {k: (v if not isinstance(v, list) else len(v)) for k, v in r.items()}
                 for s, r in result.items() if isinstance(r, dict)}
        print(f"::notice title=expiry intraday::{json.dumps(brief)}")
