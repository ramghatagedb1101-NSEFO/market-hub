"""
Evidence for the phone's close estimate (26 Oct 2026). Manual run: python -m hub.us_cue_test [prices.json]

1. Overnight US cue. x = sum of S&P 500 log returns over the US sessions dated on or after the last Indian close
   and before the target day (they all finish after 15:30 IST and before 09:15 IST); y = the index's next close log
   return. Reports direction hit rate against two baselines ("always up" and the ten forecast tools' 41-48%), and a
   walk-forward check where beta comes only from the 250 days before each day. config.US_BETA holds the 2-year betas.
2. Intraday range. From Yahoo's 5-minute bars (60 days), the 80th percentile of |log(close / level at time t)| in
   units of the 20-day daily volatility, by time of day, fitted as a*sqrt(share of session left) + c. The phone uses
   that curve (docs/index.html closeEstimate) for its range after 09:15.
Free Yahoo data only; nothing is stored.
"""
import bisect
import json
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

from . import config

H = {"User-Agent": "Mozilla/5.0"}
IST = timezone(timedelta(hours=5, minutes=30))
YAHOO = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "SENSEX": "^BSESN"}


def _yahoo(sym, rng, interval):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval={interval}",
                     headers=H, timeout=30).json()["chart"]["result"][0]
    return r["timestamp"], r["indicators"]["quote"][0]["close"], r["meta"].get("gmtoffset", 0)


def us_cue(prices):
    ts, cl, off = _yahoo("^GSPC", "5y", "1d")
    us = {datetime.fromtimestamp(t + off, timezone.utc).date().isoformat(): v for t, v in zip(ts, cl) if v}
    ud = sorted(us)
    ur = {ud[i]: np.log(us[ud[i]] / us[ud[i - 1]]) for i in range(1, len(ud))}
    out = {}
    for idx in YAHOO:
        rows = sorted(prices[idx].items())
        X, Y = [], []
        for i in range(1, len(rows)):
            sess = [ur[d] for d in ud[bisect.bisect_left(ud, rows[i - 1][0]):bisect.bisect_left(ud, rows[i][0])] if d in ur]
            if sess:
                X.append(sum(sess)); Y.append(np.log(rows[i][1] / rows[i - 1][1]))
        X, Y = np.array(X), np.array(Y)
        x2, y2 = X[-490:], Y[-490:]
        wf = np.array([(X[i - 250:i] @ Y[i - 250:i]) / (X[i - 250:i] @ X[i - 250:i]) * X[i] for i in range(250, len(X))])
        out[idx] = {"n": len(X), "beta_2y": round(float((x2 @ y2) / (x2 @ x2)), 3),
                    "hit_5y": round(float(np.mean(np.sign(X) == np.sign(Y))) * 100, 1),
                    "up_share_5y": round(float(np.mean(Y > 0)) * 100, 1),
                    "walk_forward_hit": round(float(np.mean(np.sign(wf) == np.sign(Y[250:]))) * 100, 1),
                    "walk_forward_err_pct": round(float(np.mean(np.abs(Y[250:] - wf))) * 100, 3),
                    "no_change_err_pct": round(float(np.mean(np.abs(Y[250:]))) * 100, 3)}
    return out


def intraday_range(prices):
    buckets = list(range(570, 930, 15))                 # bar end, minutes after midnight IST
    acc = {b: [] for b in buckets}
    for idx, sym in YAHOO.items():
        ts, cl, _ = _yahoo(sym, "60d", "5m")
        rows = sorted(prices[idx].items())
        dates, closes = [d for d, _ in rows], np.array([c for _, c in rows])
        days = {}
        for t, v in zip(ts, cl):
            if v is not None:
                d = datetime.fromtimestamp(t, IST)
                days.setdefault(d.date().isoformat(), {})[d.hour * 60 + d.minute + 5] = v
        for day, bars in days.items():
            if day not in prices[idx]:
                continue
            i = dates.index(day)
            sig = np.diff(np.log(closes[i - config.VOL_WINDOW - 1:i])).std(ddof=1)
            for b in buckets:
                if b in bars:
                    acc[b].append(abs(np.log(prices[idx][day] / bars[b])) / sig)
    rem = np.array([(930 - b) / 375 for b in buckets])
    q = np.array([np.percentile(acc[b], 80) for b in buckets])
    (a, c), *_ = np.linalg.lstsq(np.vstack([np.sqrt(rem), np.ones_like(rem)]).T, q, rcond=None)
    cover = [round(float(np.mean(np.array(acc[b]) <= a * np.sqrt((930 - b) / 375) + c)) * 100) for b in buckets]
    return {"a": round(float(a), 3), "c": round(float(c), 3), "coverage_by_15min": cover, "days": len(acc[buckets[0]])}


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else config.PRICES_FILE
    prices = json.load(open(path, encoding="utf-8"))
    print(json.dumps({"us_cue": us_cue(prices), "intraday_range": intraday_range(prices)}, indent=2))
