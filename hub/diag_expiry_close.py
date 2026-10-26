"""
Expiry-day close: what the option chain adds to the close estimate (26 Oct 2026, owner: "make it better at expiry
specifically"). Run on GitHub with diag.yml (Kite token + PRIVATE_REPO_TOKEN). Uses the private expiry history
(state/expiry_history/records.json: the evening-before max pain, walls and ATM straddle, and the day's OHLC for 402
expiries since Oct 2023) with Kite 5-minute index candles and GIFT Nifty 15-minute candles. Derived statistics only go to
diag_output/expiry_close.json.

  A  before the open: GIFT's move alone vs GIFT plus the pull to max pain / wall midpoint (fitted on the first half of
     the expiries, tested on the second half)
  B  during the day (10:30 ... 15:00): from the live level L, does the close move towards max pain or the wall midpoint?
     Hit rate when they are at least 0.2% away, and the error of L + g x (MP - L) against L alone (out of sample)
  C  range: the ATM straddle (the options market's expected move to the expiry close) against the 20-day volatility
  D  intraday range on expiry days, in daily-vol units by time, against the everyday curve (0.656 sqrt(left) + 0.245)
"""
import json
import os
from datetime import date, datetime, timedelta

import numpy as np
import requests

from . import config
from .sources import kite

OUT = "diag_output/expiry_close.json"
IDX = {"NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"), "SENSEX": ("BSE", "SENSEX")}
TIMES = [630, 720, 780, 840, 870, 900]                  # 10:30, 12:00, 13:00, 14:00, 14:30, 15:00 (bar end)


def _records():
    r = requests.get("https://api.github.com/repos/ramghatagedb1101-NSEFO/market-hub-private/contents/state/expiry_history/records.json",
                     headers={"Authorization": "Bearer " + os.environ["PRIVATE_REPO_TOKEN"], "Accept": "application/vnd.github.raw"}, timeout=60)
    r.raise_for_status()
    return r.json()


def _candles(k, token, interval, start, end, chunk):
    rows, s = [], start
    while s <= end:
        e = min(end, s + timedelta(days=chunk))
        try:
            rows += kite._retry(lambda: k.historical_data(token, s, e + timedelta(days=1), interval))
        except Exception as exc:                        # noqa: BLE001
            print("candles", interval, s, "failed:", str(exc)[:100])
        s = e + timedelta(days=1)
    return rows


def _bars(rows, minutes):
    out = {}
    for c in rows:
        t = c["date"].astimezone(config.IST)
        out.setdefault(t.date().isoformat(), {})[t.hour * 60 + t.minute + minutes] = float(c["close"])   # keyed by bar END
    return out


def _at(day_bars, m):
    xs = [v for mm, v in sorted(day_bars.items()) if mm <= m]
    return xs[-1] if xs else None


def _fit_test(X, y):
    """First half fits (least squares, no intercept), second half tests: MAE of the fit vs of zero, and hit rate."""
    X, y = np.asarray(X, float), np.asarray(y, float)
    if X.ndim == 1:
        X = X[:, None]
    n = len(y)
    if n < 30:
        return {"n": n}
    h = n // 2
    b = np.linalg.lstsq(X[:h], y[:h], rcond=None)[0]
    p = X[h:] @ b
    return {"n": n, "coef": [round(float(v), 3) for v in b], "test_n": n - h,
            "err_pct": round(float(np.mean(np.abs(y[h:] - p))) * 100, 4),
            "zero_err_pct": round(float(np.mean(np.abs(y[h:]))) * 100, 4),
            "hit": round(float(np.mean(np.sign(p) == np.sign(y[h:]))) * 100, 1)}


def main():
    recs = _records()
    k = kite.client()
    start, end = date(2023, 9, 1), datetime.now(config.IST).date() - timedelta(days=1)
    gift = _bars(_candles(k, kite.instrument_token(k, "NSEIX", "GIFT NIFTY"), "15minute", start, end, 190), 15)
    out = {}
    for name, (ex, sym) in IDX.items():
        tok = kite.instrument_token(k, ex, sym)
        five = _bars(_candles(k, tok, "5minute", start, end, 95), 5)
        daily = sorted((c["date"].date().isoformat(), float(c["close"])) for c in _candles(k, tok, "day", start - timedelta(days=60), end, 1900))
        ddays = [d for d, _ in daily]
        rows = sorted((r for r in recs.values() if r["symbol"] == name and r.get("close") and r.get("prev_close")), key=lambda r: r["expiry"])
        A_g, A_gm, A_gw, A_y = [], [], [], []
        B = {t: {"mp": [], "wm": [], "y": []} for t in TIMES}
        C = []
        D = {t: [] for t in TIMES}
        for r in rows:
            day, prev, pc, close = r["expiry"], r["prev_day"], r["prev_close"], r["close"]
            if day not in ddays:
                continue
            i = ddays.index(day)
            sig = float(np.std(np.diff(np.log([c for _, c in daily[max(0, i - 21):i]])), ddof=1))
            mp, wm = r.get("max_pain"), r.get("wall_mid")
            y_full = np.log(close / pc)
            if r.get("straddle") and r.get("forward"):
                C.append((abs(y_full), r["straddle"] / r["forward"], sig))
            ga, gb = _at(gift.get(prev, {}), 15 * 60 + 30), _at(gift.get(day, {}), 9 * 60)
            if ga and gb and mp and wm:
                A_g.append(np.log(gb / ga)); A_gm.append(np.log(mp / pc)); A_gw.append(np.log(wm / pc)); A_y.append(y_full)
            fb = five.get(day, {})
            for t in TIMES:
                L = _at(fb, t)
                if not L:
                    continue
                y = np.log(close / L)
                D[t].append(abs(y) / sig if sig else np.nan)
                if mp and wm:
                    B[t]["mp"].append(np.log(mp / L)); B[t]["wm"].append(np.log(wm / L)); B[t]["y"].append(y)
        res = {"expiries": len(rows)}
        if A_y:
            g = np.array(A_g)
            res["A_preopen"] = {"gift": _fit_test(g, A_y), "gift+maxpain": _fit_test(np.c_[g, A_gm], A_y),
                                "gift+wallmid": _fit_test(np.c_[g, A_gw], A_y)}
        res["B_intraday"] = {}
        for t in TIMES:
            mpv, wmv, yv = np.array(B[t]["mp"]), np.array(B[t]["wm"]), np.array(B[t]["y"])
            if len(yv) < 30:
                continue
            far = np.abs(mpv) >= 0.002
            farw = np.abs(wmv) >= 0.002
            res["B_intraday"][f"{t // 60:02d}:{t % 60:02d}"] = {
                "n": int(len(yv)),
                "toward_maxpain_hit": round(float(np.mean(np.sign(yv[far]) == np.sign(mpv[far]))) * 100, 1) if far.any() else None,
                "toward_maxpain_n": int(far.sum()),
                "toward_wallmid_hit": round(float(np.mean(np.sign(yv[farw]) == np.sign(wmv[farw]))) * 100, 1) if farw.any() else None,
                "maxpain_pull": _fit_test(mpv, yv), "wallmid_pull": _fit_test(wmv, yv)}
        if C:
            a, s_str, s_d = (np.array(v) for v in zip(*C))
            res["C_range"] = {"n": int(len(a)),
                              "mean_abs_move_over_straddle": round(float(np.mean(a / s_str)), 3),
                              "q80_abs_move_over_straddle": round(float(np.percentile(a / s_str, 80)), 3),
                              "q80_abs_move_over_dailyvol": round(float(np.percentile(a / s_d, 80)), 3),
                              # which scale predicts the size of the move better: correlation of |move| with each
                              "corr_absmove_straddle": round(float(np.corrcoef(a, s_str)[0, 1]), 3),
                              "corr_absmove_dailyvol": round(float(np.corrcoef(a, s_d)[0, 1]), 3),
                              # dispersion of |move| / scale: smaller = the scale fits the day better
                              "cv_over_straddle": round(float(np.std(a / s_str) / np.mean(a / s_str)), 3),
                              "cv_over_dailyvol": round(float(np.std(a / s_d) / np.mean(a / s_d)), 3)}
        res["D_range_by_time"] = {f"{t // 60:02d}:{t % 60:02d}": {
            "q80_dailyvol_units": round(float(np.nanpercentile(D[t], 80)), 3) if D[t] else None,
            "everyday_curve": round(0.656 * np.sqrt(max(930 - t, 0) / 375) + 0.245, 3), "n": len(D[t])} for t in TIMES}
        out[name] = res
    os.makedirs("diag_output", exist_ok=True)
    json.dump(out, open(OUT, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
