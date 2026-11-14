"""
ICICI one-minute option history for the expiry back-tests (13 Nov 2026, owner: "go ahead with the ICICI download";
"the data ... will be a gold mine for the algo trading").

For every expiry already recorded by hub/expiry_history.py (Oct 2023 onwards), and every strike in its stored day-before
chain (within +-5% of spot), the call's and the put's one-minute candles for the WHOLE day before expiry and the WHOLE
expiry day, from ICICI Breeze (hub/breeze.py; run through .github/workflows/breeze.yml, module=breeze_history).
One request per contract covers both days (ICICI returns up to 1,000 candles a request; two sessions are ~750), so the
full two days cost the same number of requests as a half-hour window would.

Stored in the private repo only (ICICI data, never re-served), one gzip-compressed JSON file per expiry:
state/breeze/expiry_days/<INDEX>/<expiry>.json.gz =
  {"prev_day", "expiry", "fields": [day, min, open, high, low, close, volume, oi], "call": {strike: [[...], ...]},
   "put": {...}, "empty": contracts with no trade on either day}
day 0 = the day before expiry, 1 = expiry day; min = minutes after 09:15 (0-375). A missing minute had no trade.
Progress: state/breeze/expiry_days/_done.json.

Newest expiries first. Each run stops at BUDGET requests (default 4,000) or MAX_MINUTES (default 300), always between
expiries, and the next run carries on. The public log shows counts and dates only, never prices.
"""
import base64
import gzip
import json
import os
import sys
import time

import requests

from .breeze import Breeze
from .expiry_history import _gh, load, save

ICICI = {"NIFTY": ("NIFTY", "NFO"), "BANKNIFTY": ("CNXBAN", "NFO"), "SENSEX": ("BSESEN", "BFO")}
FIELDS = ["day", "min", "open", "high", "low", "close", "volume", "oi"]
DIR = "state/breeze/expiry_days"
INDEX = f"{DIR}/_done.json"
OPEN, CLOSE = "09:15", "15:30"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def candles(rows: list, prev_day: str, expiry: str) -> list:
    """ICICI rows -> [[day, min, o, h, l, c, v, oi], ...] for the two sessions, in time order."""
    out = []
    for r in rows:
        dt = str(r.get("datetime", ""))                          # "2026-11-13 15:25:00"
        d, t = dt[:10], dt[11:16]
        if d not in (prev_day, expiry) or not (OPEN <= t <= CLOSE):
            continue
        m = (int(t[:2]) * 60 + int(t[3:5])) - (9 * 60 + 15)
        o, h, l, c = (_num(r.get(k)) for k in ("open", "high", "low", "close"))
        v, oi = _num(r.get("volume")), _num(r.get("open_interest"))
        out.append([int(d == expiry), m, o, h, l, c, int(v or 0), int(oi or 0)])
    return sorted(out)


def _strike(k: float):
    return int(k) if float(k).is_integer() else k


def legs(chain: list) -> list:
    """(strike, right) for every contract that had a close or open interest the day before."""
    return [(k, right) for k, ce, pe, ce_oi, pe_oi in chain
            for right, px, oi in (("call", ce, ce_oi), ("put", pe, pe_oi)) if px or oi]


def todo(recs: dict, done: dict) -> list:
    """(key, record, day-before chain) for recorded expiries not yet downloaded, newest first."""
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
    entry = {"prev_day": day, "expiry": exp, "fields": FIELDS, "call": {}, "put": {}, "empty": 0, "errors": 0}
    for k, right in legs(chain):
        try:
            rows = b.history(code, exch, "1minute", f"{day}T{OPEN}:00.000Z", f"{exp}T{CLOSE}:00.000Z",
                             product="options", expiry=f"{exp}T07:00:00.000Z", right=right, strike=_strike(k))
        except RuntimeError as e:
            if "no data" in str(e).lower():
                rows = []
            else:
                entry["errors"] += 1
                if entry["errors"] >= 5:
                    raise RuntimeError(f"ICICI kept failing on {r['symbol']} {exp}: {str(e)[:120]}")
                continue
        got = candles(rows, day, exp)
        if got:
            entry[right][str(_strike(k))] = got
        else:
            entry["empty"] += 1
    return entry


def save_gz(path: str, body: dict, message: str) -> int:
    """One expiry's file, gzip-compressed (written once; a re-run replaces it). Returns the compressed size."""
    data = gzip.compress(json.dumps(body, separators=(",", ":")).encode("utf-8"), 9)
    url, h = _gh(path)
    got = requests.get(url, headers=h, timeout=30)
    put = {"message": message, "content": base64.b64encode(data).decode("ascii")}
    if got.status_code == 200:
        put["sha"] = got.json()["sha"]
    requests.put(url, headers=h, json=put, timeout=120).raise_for_status()
    return len(data)


def load_gz(path: str):
    url, h = _gh(path)
    r = requests.get(url, headers=dict(h, Accept="application/vnd.github.raw"), timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return json.loads(gzip.decompress(r.content))


def main() -> int:
    budget = int(os.getenv("BUDGET") or 4000)
    stop_at = time.time() + 60 * int(os.getenv("MAX_MINUTES") or 300)
    # Index minutes first (small: about 1,200 requests once, then ~10 a run), sharing this run's budget (14 Nov 2026).
    from .breeze_index import run as index_run
    b, failed = index_run(None, budget, stop_at)
    if failed:
        print(f"::error title=ICICI index download::{failed[:200]} (work up to here is saved)")
        return 1
    recs = load("state/expiry_history/records.json") or {}
    done = load(INDEX) or {}
    queue = todo(recs, done)
    print(f"{len(recs)} expiries recorded, {len(done)} already downloaded, {len(queue)} to go; budget {budget} requests")
    if not queue:
        return 0
    b = b or Breeze()
    for key, r, ch in queue:
        n = len(legs(ch))
        if b.calls + n > budget or time.time() > stop_at:
            print(f"budget or time reached before {key}; the next run carries on from there")
            break
        try:
            e = fetch_expiry(b, r, ch)
        except RuntimeError as exc:
            failed = str(exc)
            break
        size = save_gz(f"{DIR}/{r['symbol']}/{r['expiry']}.json.gz", e, f"ICICI minutes: {key}")
        got = len(e["call"]) + len(e["put"])
        candles_n = sum(len(v) for side in ("call", "put") for v in e[side].values())
        done[key] = {"contracts": n, "with_trades": got, "empty": e["empty"], "errors": e["errors"], "candles": candles_n}
        save(INDEX, done, f"ICICI minutes: {len(done)} expiries")
        print(f"{key}: {got} of {n} contracts traded ({candles_n} candles, {size // 1024} KB), {e['errors']} errors; "
              f"{b.calls} requests")
    print(f"run done: {b.calls} requests, {len(done)} expiries downloaded in all, {len(todo(recs, done))} to go")
    if failed:
        print(f"::error title=ICICI download::{failed[:200]} (work up to here is saved; run again after an ICICI sign-in)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
