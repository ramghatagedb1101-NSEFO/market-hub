"""
GIFT Nifty vs NIFTY's open (27 Oct 2026, outside review: "test the days GIFT and NIFTY's opens disagree"). Run on GitHub
with diag.yml (Kite token). For every session since GIFT's candles start (Nov 2023):
  g = log(GIFT at 09:00 / GIFT at 15:30 the day before)   the pre-open estimate's cue
  o = log(NIFTY open / previous close)                    the actual opening gap (Kite's daily open)
  y = log(close / previous close),  r = log(close / open)
Reports how often g and o agree, the pre-open hit rate on days they disagree, and whether what GIFT "said" beyond the
open (g - o) still predicts the rest of the day (r) -- if it does, the live estimate after 09:15 should keep part of GIFT
instead of starting from the live level alone. Fitted on the first half, tested on the second. Derived statistics only
go to diag_output/gift_open.json.
"""
import json
import os
from datetime import datetime, timedelta

import numpy as np

from . import config
from .diag_gift import _candles
from .sources import kite

OUT = "diag_output/gift_open.json"
IDX = {"NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"), "SENSEX": ("BSE", "SENSEX")}


def _hit(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return round(float(np.mean(np.sign(a) == np.sign(b))) * 100, 1) if len(a) else None


def main():
    k = kite.client()
    end = datetime.now(config.IST).date() - timedelta(days=1)
    start = end - timedelta(days=4 * 365)
    bars = {}
    for c in _candles(k, kite.instrument_token(k, "NSEIX", "GIFT NIFTY"), "15minute", start, end, 190):
        t = c["date"].astimezone(config.IST)
        bars.setdefault(t.date().isoformat(), {})[t.hour * 60 + t.minute + 15] = float(c["close"])   # by bar end

    def at(day, m):
        xs = [v for mm, v in sorted(bars.get(day, {}).items()) if mm <= m]
        return xs[-1] if xs else None

    out = {}
    for name, (ex, sym) in IDX.items():
        days = [(c["date"].date().isoformat(), float(c["open"]), float(c["close"]))
                for c in _candles(k, kite.instrument_token(k, ex, sym), "day", start, end, 1900)]
        five = {}
        for c in _candles(k, kite.instrument_token(k, ex, sym), "5minute", start, end, 95):
            t = c["date"].astimezone(config.IST)
            five.setdefault(t.date().isoformat(), {})[t.hour * 60 + t.minute + 5] = float(c["close"])
        G, O, Y, Rr = [], [], [], []
        L = {m: ([], []) for m in (570, 600, 660)}       # level at 09:30, 10:00, 11:00: (GIFT beyond it, rest of day)
        for i in range(1, len(days)):
            (pd, _, pc), (td, op, cl) = days[i - 1], days[i]
            a, b = at(pd, 15 * 60 + 30), at(td, 9 * 60)
            if not (a and b and op):
                continue
            G.append(np.log(b / a)); O.append(np.log(op / pc)); Y.append(np.log(cl / pc)); Rr.append(np.log(cl / op))
            for m, (xs, rs) in L.items():
                lv = [v for mm, v in sorted(five.get(td, {}).items()) if mm <= m]
                if lv:
                    xs.append(np.log(b / a) - np.log(lv[-1] / pc)); rs.append(np.log(cl / lv[-1]))
        G, O, Y, Rr = map(np.array, (G, O, Y, Rr))
        n, h = len(Y), len(Y) // 2
        dis = np.sign(G) != np.sign(O)                       # opposite directions
        far = np.abs(G - O) >= 0.003                         # or 0.3%+ apart
        res = {"days": n,
               "agree_direction_pct": round(float(np.mean(~dis)) * 100, 1),
               "corr_gift_open": round(float(np.corrcoef(G, O)[0, 1]), 3),
               "open_vs_gift_beta": round(float((G @ O) / (G @ G)), 3),   # how much of GIFT's move is in the open
               "all": {"preopen_hit": _hit(G, Y), "open_hit": _hit(O, Y)},
               "disagree_direction": {"n": int(dis.sum()), "preopen_hit": _hit(G[dis], Y[dis]), "open_hit": _hit(O[dis], Y[dis]),
                                      "abs_move_pct": round(float(np.mean(np.abs(Y[dis]))) * 100, 3) if dis.any() else None},
               "apart_0_3pct": {"n": int(far.sum()), "preopen_hit": _hit(G[far], Y[far]), "open_hit": _hit(O[far], Y[far])}}
        # does GIFT beyond the open (g - o) predict open -> close? fit first half, test second half
        X = G - O
        b1 = float((X[:h] @ Rr[:h]) / (X[:h] @ X[:h]))
        p = b1 * X[h:]
        res["beyond_open"] = {"beta_first_half": round(b1, 3),
                              "corr_all": round(float(np.corrcoef(X, Rr)[0, 1]), 3),
                              "test_hit": _hit(p, Rr[h:]),
                              "test_err_pct": round(float(np.mean(np.abs(Rr[h:] - p))) * 100, 4),
                              "test_zero_err_pct": round(float(np.mean(np.abs(Rr[h:]))) * 100, 4),
                              "big_gaps_hit": _hit(X[far], Rr[far])}
        # the same from the live level at 09:30 / 10:00 / 11:00: does GIFT's leftover still predict the rest of the day?
        for m, (xs, rs) in L.items():
            xs, rs = np.array(xs), np.array(rs)
            hh = len(xs) // 2
            if hh < 30:
                continue
            bm = float((xs[:hh] @ rs[:hh]) / (xs[:hh] @ xs[:hh]))
            pm = bm * xs[hh:]
            res[f"beyond_{m // 60:02d}{m % 60:02d}"] = {"n": int(len(xs)), "beta_first_half": round(bm, 3),
                "test_hit": _hit(pm, rs[hh:]), "test_err_pct": round(float(np.mean(np.abs(rs[hh:] - pm))) * 100, 4),
                "test_zero_err_pct": round(float(np.mean(np.abs(rs[hh:]))) * 100, 4)}
        # the pre-open estimate itself (GIFT beta fitted on the first half) on the second half, split by agreement
        bg = float((G[:h] @ Y[:h]) / (G[:h] @ G[:h]))
        e2, y2, d2 = bg * G[h:], Y[h:], dis[h:]
        res["preopen_test_half"] = {"err_pct_agree": round(float(np.mean(np.abs(y2[~d2] - e2[~d2]))) * 100, 4),
                                    "no_change_err_agree": round(float(np.mean(np.abs(y2[~d2]))) * 100, 4),
                                    "err_pct_disagree": round(float(np.mean(np.abs(y2[d2] - e2[d2]))) * 100, 4) if d2.any() else None,
                                    "no_change_err_disagree": round(float(np.mean(np.abs(y2[d2]))) * 100, 4) if d2.any() else None}
        out[name] = res
    os.makedirs("diag_output", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
