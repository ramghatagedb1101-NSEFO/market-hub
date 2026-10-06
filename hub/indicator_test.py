"""
Indicator test for the NIFTY and BANK NIFTY direction forecasts. Manual run only (workflow_dispatch).

Data: Kite daily candles for NSE:NIFTY 50 and NSE:NIFTY BANK (close and volume), from the token the
daily workflow fetches. Candidate indicators are scored on the sign of the next 5-session move.

Method, to limit false discoveries:
  - Split history in time: the first 60% is for SELECTION, the last 40% is for TESTING.
  - An indicator is reported as useful only if it beats the baseline on BOTH halves, with the test
    half decided on untouched data. Otherwise it is reported as not shown to work.
  - The baseline is "always predict the historical up-share of the period" (the market drifts up
    more often than down, so a coin toss is the wrong bar).

Publishes summary statistics only to docs/data/indicator_test.json.
"""
import json
import math
import os
from datetime import date, datetime, timedelta

import numpy as np

from . import config
from .sources import kite

OUT_FILE = config.SITE_DIR / "data" / "indicator_test.json"
HORIZON = 5
INDEXES = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}


def candles(k, name: str, start: date, end: date):
    inst = kite.instrument_token(k, "NSE", name)
    rows, a = [], start
    while a <= end:                      # Kite allows at most 2000 days per daily request
        b = min(end, a + timedelta(days=1900))
        rows += k.historical_data(inst, a, b, "day")
        a = b + timedelta(days=1)
    seen = set(); uniq = []
    for r in sorted(rows, key=lambda r: r["date"]):
        key = str(r["date"])[:10]
        if key not in seen:
            seen.add(key); uniq.append(r)
    rows = uniq
    close = np.array([float(r["close"]) for r in rows])
    vol = np.array([float(r.get("volume") or 0) for r in rows])
    return [r["date"] for r in rows], close, vol


def ema(x, n):
    a = 2 / (n + 1)
    out = np.empty_like(x)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def rsi(x, n=14):
    d = np.diff(x, prepend=x[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    au = ema(up, 2 * n - 1)
    ad = ema(dn, 2 * n - 1)
    rs = np.divide(au, ad, out=np.ones_like(au), where=ad != 0)
    return 100 - 100 / (1 + rs)


def sma(x, n):
    out = np.full_like(x, np.nan)
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def signals(close, vol):
    """Each candidate returns +1 (expect up), -1 (expect down) or 0 (no view) per day."""
    s = {}
    m20, m50 = sma(close, 20), sma(close, 50)
    s["trend_sma20"] = np.sign(close - m20)
    s["trend_sma50"] = np.sign(close - m50)
    s["sma20_over_50"] = np.sign(m20 - m50)
    r = rsi(close)
    s["rsi14_reversion"] = np.where(r < 30, 1, np.where(r > 70, -1, 0))
    s["rsi14_momentum"] = np.where(r > 55, 1, np.where(r < 45, -1, 0))
    macd = ema(close, 12) - ema(close, 26)
    hist = macd - ema(macd, 9)
    s["macd_histogram"] = np.sign(hist)
    sd = np.array([np.std(close[max(0, i - 19):i + 1]) if i >= 19 else np.nan for i in range(len(close))])
    lo, hi = m20 - 2 * sd, m20 + 2 * sd
    s["bollinger_reversion"] = np.where(close < lo, 1, np.where(close > hi, -1, 0))
    ret1 = np.diff(close, prepend=close[0]) / np.roll(close, 1)
    ret1[0] = 0
    vavg = sma(vol, 20)
    surge = vol > 1.5 * avg_safe(vavg)
    s["volume_surge_follow"] = np.where(surge, np.sign(ret1), 0)
    s["volume_surge_fade"] = np.where(surge, -np.sign(ret1), 0)
    s["roc5_momentum"] = np.sign(close / np.roll(close, 5) - 1)
    s["roc5_reversal"] = -np.sign(close / np.roll(close, 5) - 1)
    return s


def avg_safe(x):
    return np.where(np.isnan(x), np.inf, x)


def evaluate(sig, fwd):
    """Hit rate on days where the indicator has a view and the future move is known."""
    m = (sig != 0) & ~np.isnan(fwd)
    if m.sum() == 0:
        return None
    hits = (np.sign(sig[m]) == np.sign(fwd[m])) & (fwd[m] != 0)
    n = int(m.sum())
    p = hits.mean()
    se = math.sqrt(0.25 / n)
    return {"n": n, "hit_pct": round(p * 100, 1), "z_vs_coin": round((p - 0.5) / se, 2)}


def run_index(k, name, start, end):
    dates, close, vol = candles(k, name, start, end)
    n = len(close)
    fwd = np.full(n, np.nan)
    fwd[: n - HORIZON] = np.sign(close[HORIZON:] - close[: n - HORIZON])
    cut = int(n * 0.6)
    sigs = signals(close, vol)
    base_up = float(np.mean(fwd[~np.isnan(fwd)] > 0))
    result = {"days": n, "from": str(dates[0])[:10], "to": str(dates[-1])[:10], "baseline_up_share_pct": round(base_up * 100, 1),
              "candidates": {}}
    for nm, sg in sigs.items():
        train = evaluate(sg[:cut], fwd[:cut])
        test = evaluate(sg[cut:], fwd[cut:])
        useful = bool(train and test and train["hit_pct"] > 55 and test["hit_pct"] > 55
                      and test["z_vs_coin"] > 1.64)
        result["candidates"][nm] = {"selection": train, "test": test, "shown_to_work": useful}
    return result


def main() -> dict:
    k = kite.client()
    end = date.today()
    start = end - timedelta(days=365 * 10)
    out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"), "horizon_sessions": HORIZON,
           "split": "first 60% selection, last 40% test", "indexes": {}}
    for label, name in INDEXES.items():
        try:
            out["indexes"][label] = run_index(k, name, start, end)
        except Exception as exc:
            out["indexes"][label] = {"error": str(exc)[:160]}
    shown = {lbl: [c for c, v in r.get("candidates", {}).items() if v.get("shown_to_work")]
             for lbl, r in out["indexes"].items() if "candidates" in r}
    out["shown_to_work"] = shown
    out["caveat"] = ("Many candidates are tested, so some will look good by chance. Only those that pass "
                     "the selection AND test halves, with a z above 1.64 on untouched data, are listed as "
                     "shown to work. Nothing here proves a trading edge.")
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
