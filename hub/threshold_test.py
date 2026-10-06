"""
Test of the IV-rank threshold (the screen only sells when IV rank is at or above 30).
Manual run only (workflow_dispatch). Publishes summary statistics to docs/data/threshold_test.json.

For each Nifty 50 name and each day with enough history:
  - IV rank = where today's ATM IV sits in its own trailing 252-day range (0 = low, 100 = high).
  - Realised move = absolute price move over the next 21 sessions.
  - Implied move = ATM IV x sqrt(21/252): the one-standard-deviation move the premium prices in.
  - Breach = realised move larger than the implied move (a short strike at one sd would be hit).
The breach rate and the average premium (implied minus realised) are computed for each IV-rank band
and for each candidate threshold. The split is in time: the first 60% of days choose nothing, they
only describe; the last 40% is the test. A threshold is reported as useful only if it lowers the
breach rate on both halves, and the test half is untouched by the choice.
"""
import json
import math
import os
import statistics as st
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from . import config
from .sources import kite

OUT_FILE = config.SITE_DIR / "data" / "threshold_test.json"
IV_DIR = config.REPO / "iv_history"
NAMES_FILE = config.REPO / "rg" / "data" / "nifty50.json"
H = 21
WARM = 252
THRESHOLDS = (20, 30, 40, 50, 60)


def nifty_names() -> list[str]:
    raw = json.loads(NAMES_FILE.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("symbols") or raw.get("constituents") or list(raw.keys())
    out = []
    for x in raw:
        out.append(x if isinstance(x, str) else (x.get("symbol") or x.get("Symbol")))
    return [s for s in out if s]


def iv_series(sym: str) -> dict[str, float]:
    p = IV_DIR / f"{sym}.json"
    if not p.exists():
        return {}
    h = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(h, list):
        return {r["date"]: float(r["iv"]) for r in h if r.get("iv")}
    return {d: float(v) for d, v in zip(h["dates"], h["daily_atm_iv"]) if v}


def closes(k, sym: str, start: date, end: date) -> dict[str, float]:
    inst = kite.instrument_token(k, "NSE", sym)
    rows, a = [], start
    while a <= end:
        b = min(end, a + timedelta(days=1900))
        rows += k.historical_data(inst, a, b, "day")
        a = b + timedelta(days=1)
    return {str(r["date"])[:10]: float(r["close"]) for r in rows}


def band(r: float) -> str:
    if r < 30: return "0-30"
    if r < 50: return "30-50"
    if r < 70: return "50-70"
    return "70-100"


def main() -> dict:
    k = kite.client()
    end = date.today()
    start = end - timedelta(days=365 * 3 + 60)
    obs = []   # (date_index_order, ivrank, breach, premium)
    names_used = []
    for sym in nifty_names():
        iv = iv_series(sym)
        if len(iv) < WARM + H + 5:
            continue
        try:
            px = closes(k, sym, start, end)
        except Exception:
            continue
        days = sorted(d for d in iv if d in px)
        if len(days) < WARM + H + 5:
            continue
        names_used.append(sym)
        cl = [px[d] for d in days]
        ivs = [iv[d] for d in days]
        for i in range(WARM, len(days) - H):
            win = ivs[i - WARM:i]
            lo, hi = min(win), max(win)
            if hi <= lo:
                continue
            rank = 100 * (ivs[i] - lo) / (hi - lo)
            implied = (ivs[i] / 100) * math.sqrt(H / 252)
            realised = abs(cl[i + H] / cl[i] - 1)
            obs.append((i / len(days), rank, realised > implied, implied - realised))
    if not obs:
        out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"), "error": "no usable observations"}
    else:
        obs.sort(key=lambda o: o[0])
        cut = int(len(obs) * 0.6)
        sel, tst = obs[:cut], obs[cut:]

        def summary(rows):
            if not rows:
                return {"n": 0}
            return {"n": len(rows),
                    "breach_pct": round(sum(1 for o in rows if o[2]) / len(rows) * 100, 1),
                    "avg_premium_pct": round(st.mean(o[3] for o in rows) * 100, 2)}

        bands = {b: {"selection": summary([o for o in sel if band(o[1]) == b]),
                     "test": summary([o for o in tst if band(o[1]) == b])} for b in ["0-30", "30-50", "50-70", "70-100"]}
        thr = {}
        for t in THRESHOLDS:
            s_hi = [o for o in sel if o[1] >= t]; t_hi = [o for o in tst if o[1] >= t]
            s_lo = [o for o in sel if o[1] < t]; t_lo = [o for o in tst if o[1] < t]
            a, b = summary(s_hi), summary(t_hi)
            c, d = summary(s_lo), summary(t_lo)
            better = (a.get("n", 0) and c.get("n", 0) and b.get("n", 0) and d.get("n", 0)
                      and a["breach_pct"] < c["breach_pct"] and b["breach_pct"] < d["breach_pct"])
            thr[str(t)] = {"at_or_above": {"selection": a, "test": b},
                           "below": {"selection": c, "test": d},
                           "lowers_breach_on_both_halves": bool(better)}
        out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"),
               "names": len(names_used), "observations": len(obs),
               "split": "first 60% selection, last 40% test",
               "by_iv_rank_band": bands, "by_threshold": thr,
               "caveat": "Breach uses ATM IV versus realised close-to-close moves, not the spread's own prices. "
                         "Overlapping windows and one market cycle make these estimates less certain than they look."}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
