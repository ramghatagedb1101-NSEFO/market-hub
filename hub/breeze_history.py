"""
ICICI one-minute option prices around the evening-before entry (13 Nov 2026, owner: "go ahead with the ICICI download").

The expiry rule tests (hub/rule_test.py, hub/rule_review.py) enter at about 15:25 on the day before each expiry, priced
at that day's closing prices from the exchange files -- and the review itself warns that closes of far strikes can be
stale. This downloads what really traded: for every expiry already recorded by hub/expiry_history.py, and every strike in
its stored day-before chain (within +-5% of spot), the call's and the put's one-minute candles from 15:00 to 15:30 on the
day before expiry, from ICICI Breeze (hub/breeze.py; run through .github/workflows/breeze.yml, module=breeze_history).

Stored in the private repo only (ICICI data, never re-served): state/breeze/day_before/<INDEX>_<YYYY-MM>.json, one entry
per expiry: {"prev_day", "fields": [min, open, high, low, close, volume, oi], "call": {strike: [[...], ...]}, "put": {...},
"empty": legs with no trades}. min = minutes after 15:00 (0-30); a missing minute is a minute with no trade.

Newest expiries first. Each run stops at BUDGET requests (default 4,000) or MAX_MINUTES (default 300), always between
expiries, and the next run carries on. The public log shows counts and dates only, never prices.
"""
import os
import sys
import time
from collections import defaultdict

from .breeze import Breeze
from .expiry_history import load, save

ICICI = {"NIFTY": ("NIFTY", "NFO"), "BANKNIFTY": ("CNXBAN", "NFO"), "SENSEX": ("BSESEN", "BFO")}
FIELDS = ["min", "open", "high", "low", "close", "volume", "oi"]
DIR = "state/breeze/day_before"
INDEX = f"{DIR}/_done.json"
START, END = "15:00", "15:30"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def candles(rows: list) -> list:
    """ICICI rows -> [[min, o, h, l, c, v, oi], ...] inside the window, sorted by minute."""
    out = []
    for r in rows:
        t = str(r.get("datetime", ""))[11:16]                  # "2026-11-13 15:25:00"
        if not (START <= t <= END):
            continue
        m = (int(t[:2]) - 15) * 60 + int(t[3:5])
        o, h, l, c = (_num(r.get(k)) for k in ("open", "high", "low", "close"))
        v, oi = _num(r.get("volume")), _num(r.get("open_interest"))
        out.append([m, o, h, l, c, int(v or 0), int(oi or 0)])
    return sorted(out)


def _strike(k: float):
    return int(k) if float(k).is_integer() else k


def todo(recs: dict, done: dict) -> list:
    """(record, day-before chain) for recorded expiries not yet downloaded, newest first."""
    chains, out = {}, []
    for key, r in sorted(recs.items(), key=lambda kv: kv[1]["expiry"], reverse=True):
        if key in done or r.get("symbol") not in ICICI or not r.get("prev_day"):
            continue
        f = f"state/expiry_history/chains/{r['symbol']}_{r['expiry'][:4]}.json"
        if f not in chains:
            chains[f] = load(f) or {}
        ch = (chains[f].get(key) or {}).get("day_before")
        if ch:
            out.append((key, r, ch))
    return out


def fetch_expiry(b: Breeze, r: dict, chain: list) -> dict:
    code, exch = ICICI[r["symbol"]]
    day, exp = r["prev_day"], r["expiry"]
    entry = {"prev_day": day, "fields": FIELDS, "call": {}, "put": {}, "empty": 0, "errors": 0}
    for k, ce, pe, ce_oi, pe_oi in chain:
        for right, px, oi in (("call", ce, ce_oi), ("put", pe, pe_oi)):
            if not (px or oi):
                continue                                         # never listed or never traded that day: nothing to ask
            try:
                rows = b.history(code, exch, "1minute", f"{day}T{START}:00.000Z", f"{day}T{END}:00.000Z",
                                 product="options", expiry=f"{exp}T07:00:00.000Z", right=right, strike=_strike(k))
            except RuntimeError as e:
                if "no data" in str(e).lower():
                    rows = []
                else:
                    entry["errors"] += 1
                    if entry["errors"] >= 5:
                        raise RuntimeError(f"ICICI kept failing on {r['symbol']} {exp}: {str(e)[:120]}")
                    continue
            got = candles(rows)
            if got:
                entry[right][str(_strike(k))] = got
            else:
                entry["empty"] += 1
    return entry


def main() -> int:
    budget = int(os.getenv("BUDGET") or 4000)
    stop_at = time.time() + 60 * int(os.getenv("MAX_MINUTES") or 300)
    recs = load("state/expiry_history/records.json") or {}
    done = load(INDEX) or {}
    queue = todo(recs, done)
    print(f"{len(recs)} expiries recorded, {len(done)} already downloaded, {len(queue)} to go; budget {budget} requests")
    if not queue:
        return 0
    b = Breeze()
    files = defaultdict(dict)
    failed, pending = None, 0
    for key, r, ch in queue:
        legs = sum(1 for row in ch for px, oi in ((row[1], row[3]), (row[2], row[4])) if px or oi)
        if b.calls + legs > budget or time.time() > stop_at:
            print(f"budget or time reached before {key}; the next run carries on from there")
            break
        try:
            e = fetch_expiry(b, r, ch)
        except RuntimeError as exc:
            failed = str(exc)
            break
        files[f"{DIR}/{r['symbol']}_{r['expiry'][:7]}.json"][key] = e
        got = len(e["call"]) + len(e["put"])
        done[key] = {"legs": legs, "with_trades": got, "empty": e["empty"], "errors": e["errors"]}
        print(f"{key}: {got} of {legs} legs traded {START}-{END} on {r['prev_day']}, {e['errors']} errors; {b.calls} requests")
        pending += 1
        if pending >= 10:                                       # save as we go, so a stopped run keeps its work
            _save(files, done)
            files.clear()
            pending = 0
    _save(files, done)
    print(f"run done: {b.calls} requests, {len(done)} expiries downloaded in all, {len(todo(recs, done))} to go")
    if failed:
        print(f"::error title=ICICI download::{failed[:200]} (work up to here is saved; run again after an ICICI sign-in)")
        return 1
    return 0


def _save(files: dict, done: dict) -> None:
    for path, entries in sorted(files.items()):
        old = load(path) or {}
        old.update(entries)
        save(path, old, f"ICICI day-before minutes: {path.rsplit('/', 1)[-1]} ({len(old)} expiries)")
    if files:
        save(INDEX, done, f"ICICI day-before minutes: {len(done)} expiries")


if __name__ == "__main__":
    sys.exit(main())
