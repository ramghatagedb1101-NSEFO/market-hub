"""
GIFT Nifty as a pre-open cue for NIFTY's close (26 Oct 2026, owner: "look for a free GIFT Nifty feed"). Run on GitHub
with diag.yml (needs today's Kite token). Kite lists it as NSEIX:GIFT NIFTY (an index-type instrument).

For each NIFTY session t: x = log(GIFT at 09:00 IST on t / GIFT at 15:30 IST on t-1) -- the move since the last Indian
close, so the futures premium cancels; y = log(NIFTY close t / close t-1). Compared with the S&P 500 cue (Yahoo, US
sessions since the last Indian close) on the same days, and both together. Writes derived statistics only to
diag_output/gift.json (no candles).

Two kinds of out-of-sample check, kept side by side for comparison: `both_second_half` fits once on the first half
and tests on the second (the original, 26 Oct 2026); `rolling_walkforward_gift_alone`/`_gift_spx` (27 Oct 2026, an
outside review's suggestion) retrain on a trailing 250-day window and predict one day ahead, sliding forward --
the same method hub/us_cue_test.py already uses for the S&P cue, and a sturdier check than a single split: it asks
whether the relationship holds up continuously, not just once, two-thirds of the way through the sample.
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


def _rolling_wf(X, Y, S=None, window=250):
    """Retrain on the trailing `window` days only, predict the next day, slide forward one day at a time --
    the same rolling walk-forward hub/us_cue_test.py already uses for the S&P cue (27 Oct 2026: the single
    first-half/second-half split in both_second_half is weaker evidence than this; added alongside it, not
    instead, so both stay comparable). With `S` given, fits GIFT+SPX jointly each window; without, GIFT alone."""
    if len(Y) < window + 20:
        return None
    preds = []
    for i in range(window, len(Y)):
        if S is None:
            xi, yi = X[i - window:i], Y[i - window:i]
            b = float((xi @ yi) / (xi @ xi)) if xi @ xi else 0.0
            preds.append(b * X[i])
        else:
            A = np.vstack([X[i - window:i], S[i - window:i]]).T
            coef = np.linalg.lstsq(A, Y[i - window:i], rcond=None)[0]
            preds.append(float(np.array([X[i], S[i]]) @ coef))
    preds, y2 = np.array(preds), Y[window:]
    return {"n": int(len(preds)), "window": window,
            "hit": round(float(np.mean(np.sign(preds) == np.sign(y2))) * 100, 1),
            "gift_alone_hit": round(float(np.mean(np.sign(X[window:]) == np.sign(y2))) * 100, 1),
            "err_pct": round(float(np.mean(np.abs(y2 - preds))) * 100, 3),
            "no_change_err_pct": round(float(np.mean(np.abs(y2))) * 100, 3)}


def _one(n, at, ud, ur):
    closes = [(c["date"].date().isoformat(), float(c["close"])) for c in n]
    X, S, Y, E = [], [], [], []
    for i in range(1, len(closes)):
        (pd, pc), (td, tc) = closes[i - 1], closes[i]
        a, b = at(pd, 15 * 60 + 15), at(td, 8 * 60 + 55)    # bars starting 15:15 (ends 15:30) and 08:45 (ends 09:00; 15-minute bars start on the quarter-hour)
        if not (a and b):
            continue
        sess = [ur[d] for d in ud[bisect.bisect_left(ud, pd):bisect.bisect_left(ud, td)] if d in ur]
        X.append(np.log(b / a)); S.append(sum(sess)); Y.append(np.log(tc / pc))
        # NIFTY weekly expiry by rule: Thursday until Aug 2025, Tuesday from Sep 2025 (holiday moves ignored)
        wd = date.fromisoformat(td).weekday()
        E.append(wd == (3 if td < "2025-09-01" else 1))
    X, S, Y, E = np.array(X), np.array(S), np.array(Y), np.array(E)
    out = {"days": int(len(Y)), "first_day": closes[0][0] if closes else None,
           "gift_0900": _stats(X, Y), "spx": _stats(S, Y)}
    out["gift_0900_expiry_days"] = _stats(X[E], Y[E])
    out["gift_0900_other_days"] = _stats(X[~E], Y[~E])
    out["abs_move_expiry_vs_other_pct"] = [round(float(np.mean(np.abs(Y[E]))) * 100, 3), round(float(np.mean(np.abs(Y[~E]))) * 100, 3)]
    for m in (6 * 60 + 45, 7 * 60 + 45, 8 * 60 + 15):   # earlier in the morning: bars ending 07:00, 08:00, 08:30
        xs, ys = [], []
        for i in range(1, len(closes)):
            (pd, pc), (td, tc) = closes[i - 1], closes[i]
            a, b = at(pd, 15 * 60 + 15), at(td, m)
            if a and b:
                xs.append(np.log(b / a)); ys.append(np.log(tc / pc))
        out[f"gift_{(m + 15) // 60:02d}{(m + 15) % 60:02d}"] = _stats(xs, ys)
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
    rwf = _rolling_wf(X, Y, S, window=250)
    if rwf:
        out["rolling_walkforward_gift_alone"] = _rolling_wf(X, Y, window=250)
        out["rolling_walkforward_gift_spx"] = rwf
    return out


def main():
    k = kite.client()
    gift = kite.instrument_token(k, "NSEIX", "GIFT NIFTY")
    targets = {"NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"), "SENSEX": ("BSE", "SENSEX")}
    end = datetime.now(IST).date() - timedelta(days=1)
    start = end - timedelta(days=4 * 365)
    g = _candles(k, gift, "15minute", start, end, 190)
    print("GIFT 15-minute candles:", len(g), "first", g[0]["date"] if g else None)
    bars = {}
    for c in g:
        t = c["date"].astimezone(IST)
        bars.setdefault(t.date().isoformat(), []).append((t.hour * 60 + t.minute, float(c["close"])))

    def at(day, m):                                     # last 15-minute close starting at or before m minutes
        xs = [v for mm, v in bars.get(day, []) if mm <= m]
        return xs[-1] if xs else None

    ud, ur = _spx()
    result = {}
    for name, (ex, sym) in targets.items():
        n = _candles(k, kite.instrument_token(k, ex, sym), "day", start, end, 1900)
        result[name] = _one(n, at, ud, ur)
    out = result
    os.makedirs("diag_output", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
