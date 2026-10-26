"""
GIFT Nifty as a pre-open cue for NIFTY's close (26 Oct 2026, owner: "look for a free GIFT Nifty feed"). Run on GitHub
with diag.yml (needs today's Kite token). Kite lists it as NSEIX:GIFT NIFTY (an index-type instrument).

For each NIFTY session t: x = log(GIFT at 09:10 IST on t / GIFT at 15:30 IST on t-1) -- the move since the last Indian
close, so the futures premium cancels; y = log(NIFTY close t / close t-1). Compared with the S&P 500 cue (Yahoo, US
sessions since the last Indian close) on the same days, and both together. Writes derived statistics only to
diag_output/gift.json (no candles).
"""
import bisect
import json
import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import requests

from .sources import kite

IST = timezone(timedelta(hours=5, minutes=30))
OUT = "diag_output/gift.json"


def _candles(k, token, interval, start, end, chunk):
    rows, s = [], start
    while s <= end:
        e = min(end, s + timedelta(days=chunk))
        try:
            rows += kite._retry(lambda: k.historical_data(token, s, e, interval))
        except Exception as exc:                       # noqa: BLE001 -- older ranges may not exist
            print("candles", interval, s, e, "failed:", str(exc)[:120])
        s = e + timedelta(days=1)
    return rows


def _spx():
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=10y&interval=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    us = {datetime.fromtimestamp(t + off, timezone.utc).date().isoformat(): v
          for t, v in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if v}
    d = sorted(us)
    return d, {d[i]: float(np.log(us[d[i]] / us[d[i - 1]])) for i in range(1, len(d))}


def _stats(x, y):
    x, y = np.array(x), np.array(y)
    if len(x) < 20:
        return {"n": int(len(x))}
    b = float((x @ y) / (x @ x))
    a = np.abs(x)
    big = a >= np.quantile(a, 0.7)
    return {"n": int(len(x)), "corr": round(float(np.corrcoef(x, y)[0, 1]), 3), "beta": round(b, 3),
            "hit": round(float(np.mean(np.sign(x) == np.sign(y))) * 100, 1),
            "hit_strongest_30pct": round(float(np.mean(np.sign(x[big]) == np.sign(y[big]))) * 100, 1),
            "err_pct": round(float(np.mean(np.abs(y - b * x))) * 100, 3),
            "no_change_err_pct": round(float(np.mean(np.abs(y))) * 100, 3)}


def main():
    k = kite.client()
    gift = kite.instrument_token(k, "NSEIX", "GIFT NIFTY")
    nifty = kite.instrument_token(k, "NSE", "NIFTY 50")
    end = datetime.now(IST).date() - timedelta(days=1)
    start = end - timedelta(days=4 * 365)
    g = _candles(k, gift, "15minute", start, end, 190)
    n = _candles(k, nifty, "day", start, end, 1900)
    print("GIFT 15-minute candles:", len(g), "first", g[0]["date"] if g else None, "| NIFTY days:", len(n))
    bars = {}
    for c in g:
        t = c["date"].astimezone(IST)
        bars.setdefault(t.date().isoformat(), []).append((t.hour * 60 + t.minute, float(c["close"])))

    def at(day, m):                                     # last 15-minute close starting at or before m minutes
        xs = [v for mm, v in bars.get(day, []) if mm <= m]
        return xs[-1] if xs else None

    closes = [(c["date"].date().isoformat(), float(c["close"])) for c in n]
    ud, ur = _spx()
    X, S, Y = [], [], []
    for i in range(1, len(closes)):
        (pd, pc), (td, tc) = closes[i - 1], closes[i]
        a, b = at(pd, 15 * 60 + 15), at(td, 8 * 60 + 55)    # bars starting 15:15 (ends 15:30) and 08:55 (ends 09:10)
        if not (a and b):
            continue
        sess = [ur[d] for d in ud[bisect.bisect_left(ud, pd):bisect.bisect_left(ud, td)] if d in ur]
        X.append(np.log(b / a)); S.append(sum(sess)); Y.append(np.log(tc / pc))
    X, S, Y = np.array(X), np.array(S), np.array(Y)
    out = {"days": int(len(Y)), "first_day": closes[0][0] if closes else None,
           "gift_0910": _stats(X, Y), "spx": _stats(S, Y)}
    if len(Y) >= 60:                                    # both together, walk-forward on the second half
        h = len(Y) // 2
        A = np.vstack([X[:h], S[:h]]).T
        coef = np.linalg.lstsq(A, Y[:h], rcond=None)[0]
        p = np.vstack([X[h:], S[h:]]).T @ coef
        out["both_second_half"] = {"coef_gift_spx": [round(float(c), 3) for c in coef],
                                   "hit": round(float(np.mean(np.sign(p) == np.sign(Y[h:]))) * 100, 1),
                                   "gift_alone_hit": round(float(np.mean(np.sign(X[h:]) == np.sign(Y[h:]))) * 100, 1),
                                   "err_pct": round(float(np.mean(np.abs(Y[h:] - p))) * 100, 3),
                                   "no_change_err_pct": round(float(np.mean(np.abs(Y[h:]))) * 100, 3)}
    os.makedirs("diag_output", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
