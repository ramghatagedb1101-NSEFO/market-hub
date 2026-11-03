"""
Expiry meter's daily file (3 Nov 2026, owner: "I need a real prediction meter. Make it work"). The old meter showed an
"expected close" that was the live price under another name; this replaces it with what testing says can be predicted:

  1. Morning call: the close-estimate's pre-open figure from GIFT Nifty at 09:00 (hub/close_estimate.preopen; right
     67-68% on 146 past expiry days per index, 80-89% on the strongest 30% of mornings, diag_output/gift.json). Fixed
     for the day. The relay makes it at 09:00 from Kite's 08:45 GIFT bar with the settings written here.
  2. Settlement odds: chance the index settles above each strike, from the level now, the time left and the index's
     20-day daily volatility. Empirical, not a normal curve: per 15-minute checkpoint, the percentiles of
     z = log(close / level then) / vol20 over the last WINDOW expiries (hub/expiry_history.py's minute paths).
     Walk-forward on 399 expiries (Oct 2023 - Oct 2026) it was calibrated: said 70-80%, happened 67%; said 20-30%,
     happened 27% (see reliability_history). After the open the centre is the live level: 98 intraday signals tested
     (3 Nov 2026: momentum, gap, day average, range position, max pain, gamma strike, gamma regime, FII futures, PCR,
     first-half-hour) and none beat "close = now" out of sample.
  3. Record: the morning call on every expiry day since 27 Oct 2026 (close-estimate log), and the live odds checked on
     the recorded expiry days (state/expiry/).
  4. Learning: once LEARN_MIN expiry days of the relay's minute-by-minute option record exist, a walk-forward test of
     its option-flow signals against "close = now"; a signal is reported as proven only if it holds in both halves with
     t >= 2. Nothing switches on by itself.

python -m hub.expiry_meter   (daily.yml, after the daily job) writes docs/data/expiry_meter.json -> private site/.
Needs PRIVATE_REPO_TOKEN (reads state/expiry_history and state/expiry over the API).
"""
import bisect
import json
import math
from datetime import datetime

import numpy as np

from . import config
from .expiry_history import load

OUT = config.SITE_DIR / "data" / "expiry_meter.json"
MINS = list(range(0, 361, 15))                       # checkpoints, minutes after 09:15 (09:15 .. 15:15)
WINDOW, MIN_TRAIN, VOL_DAYS = 150, 80, 20
PCTS = list(range(1, 100))
STEP = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}
LEARN_MIN = 60
CHECK_TIMES = {"10:00": 45, "12:00": 165, "14:00": 285, "15:00": 345}


def _vol(prices: dict, before: str) -> float | None:
    ds = sorted(d for d in prices if d < before)[-(VOL_DAYS + 1):]
    if len(ds) < VOL_DAYS:
        return None
    r = [math.log(prices[ds[i]] / prices[ds[i - 1]]) for i in range(1, len(ds))]
    return float(np.std(r, ddof=1))


def _history(prices: dict) -> list:
    """Every past expiry with a minute path: level at each checkpoint, close, vol20 before the day."""
    recs = load("state/expiry_history/records.json") or {}
    paths, out = {}, []
    for r in sorted(recs.values(), key=lambda r: r["expiry"]):
        s, e = r["symbol"], r["expiry"]
        key = f"{s}_{e[:4]}"
        if key not in paths:
            paths[key] = load(f"state/expiry_history/intraday/{key}.json") or {}
        p = paths[key].get(e)
        vol = _vol(prices.get(s, {}), e)
        if not p or r.get("close") is None or len(p) < 340 or not vol:
            continue
        lv = {}
        for m in MINS:
            up = [x for x in p if x[0] <= m]
            lv[m] = up[-1][4] if up else p[0][1]
        out.append({"idx": s, "exp": e, "close": r["close"], "lv": lv, "vol": vol})
    return out


def _z(rows: list, m: int) -> np.ndarray:
    return np.array([math.log(x["close"] / x["lv"][m]) / x["vol"] for x in rows])


def fit(hist: list) -> dict:
    """Percentiles of z per checkpoint over the last WINDOW expiries (all three indices pooled)."""
    rows = hist[-WINDOW:]
    return {"mins": MINS, "pcts": PCTS, "n": len(rows), "from": rows[0]["exp"] if rows else None,
            "q": [[round(float(v), 5) for v in np.percentile(_z(rows, m), PCTS)] for m in MINS]}


def p_above(table: dict, minute: float, z: float) -> float:
    """P(close / level now > exp(z x vol20)) at `minute` after 09:15: the checkpoint tables interpolated in time, the
    percentiles linearly in z. Same arithmetic as relay Expiry.gs expOdds_ (keep both in step)."""
    mins, q = table["mins"], table["q"]
    m = max(mins[0], min(mins[-1], minute))
    i = min(bisect.bisect_right(mins, m) - 1, len(mins) - 2)
    w = (m - mins[i]) / (mins[i + 1] - mins[i])
    row = [a + w * (b - a) for a, b in zip(q[i], q[i + 1])]
    if z <= row[0]:
        below = 0.005
    elif z >= row[-1]:
        below = 0.995
    else:
        j = bisect.bisect_right(row, z) - 1
        below = (PCTS[j] + (z - row[j]) / ((row[j + 1] - row[j]) or 1e-12) * (PCTS[j + 1] - PCTS[j])) / 100
    return 1 - below


def reliability(hist: list) -> dict:
    """Walk-forward on every past expiry: tables built only from earlier expiries (last WINDOW), strikes at the level
    x exp(d x vol20 x sqrt(share left)). Said x% -> happened y%, in 10-point bins."""
    ds = [-3, -2, -1.5, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, 1.5, 2, 3]
    P, O = [], []
    for i in range(MIN_TRAIN, len(hist)):
        t = fit(hist[max(0, i - WINDOW):i])
        x = hist[i]
        for m in CHECK_TIMES.values():
            z_act = math.log(x["close"] / x["lv"][m]) / x["vol"]
            left = math.sqrt(max((375 - m) / 375, 0.02))
            for d in ds:
                P.append(p_above(t, m, d * left)); O.append(z_act > d * left)
    P, O = np.array(P), np.array(O, dtype=float)
    bins = []
    for lo in range(0, 100, 10):
        sel = (P * 100 >= lo) & (P * 100 < lo + 10)
        if sel.sum():
            bins.append({"said": f"{lo}-{lo + 10}%", "happened": round(float(O[sel].mean()) * 100, 1), "n": int(sel.sum())})
    return {"expiries": len(hist) - MIN_TRAIN, "brier": round(float(np.mean((P - O) ** 2)), 4), "bins": bins}


def _tapes() -> list:
    from .close_estimate import _gh
    r = _gh("GET", "state/expiry")
    names = sorted(x["name"] for x in r.json()) if r.status_code == 200 else []
    return [t for t in (load(f"state/expiry/{n}") for n in names) if t and t.get("close")]


def _live_odds(tapes: list, table: dict, prices: dict) -> dict:
    """The odds as the meter shows them, checked on each recorded expiry day at 10:00/12:00/14:00/15:00, for strikes
    within four steps of the level."""
    P, O, days = [], [], 0
    for t in tapes:
        vol = _vol(prices.get(t["id"], {}), t["date"])
        tape = t.get("tape") or []
        if not vol or not tape:
            continue
        days += 1
        for hm, m in CHECK_TIMES.items():
            up = [x for x in tape if x[0] <= hm]
            if not up:
                continue
            spot, step = up[-1][1], STEP.get(t["id"], 100)
            atm = round(spot / step) * step
            for k in range(-4, 5):
                K = atm + k * step
                P.append(p_above(table, m, math.log(K / spot) / vol)); O.append(t["close"] > K)
    P, O = np.array(P), np.array(O, dtype=float)
    bins = []
    for lo, hi in ((0, 20), (20, 40), (40, 60), (60, 80), (80, 101)):
        sel = (P * 100 >= lo) & (P * 100 < hi)
        if sel.sum():
            bins.append({"said": f"{lo}-{min(hi, 100)}%", "happened": round(float(O[sel].mean()) * 100, 1), "n": int(sel.sum())})
    return {"days": days, "checks": int(len(P)), "bins": bins,
            "brier": round(float(np.mean((P - O) ** 2)), 4) if len(P) else None}


def _expiry_days(tapes: list) -> set:
    recs = load("state/expiry_history/records.json") or {}
    return {(r["symbol"], r["expiry"]) for r in recs.values()} | {(t["id"], t["date"]) for t in tapes}


def _morning_record(days: set, prices: dict) -> dict:
    try:
        log = json.loads((config.REPO / "state" / "close_estimate_log.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log = []
    rows = []
    for e in log:
        if e["kind"] != "pre" or (e["index"], e["date"]) not in days or e.get("gift_pct") is None:
            continue
        close = prices.get(e["index"], {}).get(e["date"])
        call = "up" if e["pred"] > e["base"] else "down"
        rows.append({"date": e["date"], "index": e["index"], "call": call, "p": round(e["p_up"] * 100 if call == "up" else (1 - e["p_up"]) * 100),
                     "pred": round(e["pred"]), "base": round(e["base"], 2), "close": close,
                     "right": None if close is None else (close > e["base"]) == (call == "up")})
    done = [r for r in rows if r["right"] is not None]
    try:
        g = json.loads((config.REPO / "diag_output" / "gift.json").read_text(encoding="utf-8"))
        tested = {i: {"n": v["gift_0900_expiry_days"]["n"], "hit": v["gift_0900_expiry_days"]["hit"],
                      "hit_strong": v["gift_0900_expiry_days"]["hit_strongest_30pct"]} for i, v in g.items()}
    except (OSError, ValueError, KeyError):
        tested = {}
    return {"rows": sorted(rows, key=lambda r: (r["date"], r["index"]), reverse=True), "n": len(done),
            "right": sum(r["right"] for r in done), "tested": tested}


def _learn(tapes: list, prices: dict) -> dict:
    """Option-flow signals from the relay's minute record vs "close = now", walk-forward over recorded expiry days."""
    out = {"days": len(tapes), "needed": LEARN_MIN, "proven": [], "tested": []}
    if len(tapes) < LEARN_MIN:
        return out
    f = {}                                               # signal -> [(x, y)] in date order
    for t in sorted(tapes, key=lambda t: t["date"]):
        F = t.get("tape_fields") or []
        tape = t.get("tape") or []
        if not tape or "spot" not in F:
            continue
        col = {n: i for i, n in enumerate(F)}
        first = tape[0]
        for hm in CHECK_TIMES:
            up = [x for x in tape if x[0] <= hm]
            if len(up) < 2:
                continue
            r = up[-1]
            y = math.log(t["close"] / r[col["spot"]])
            g = lambda n: r[col[n]] if r[col[n]] is not None else None
            cand = {
                "puts_vs_calls_oi_change": (g("puts_oi_lakh") - first[col["puts_oi_lakh"]]) - (g("calls_oi_lakh") - first[col["calls_oi_lakh"]])
                if None not in (g("puts_oi_lakh"), g("calls_oi_lakh"), first[col["puts_oi_lakh"]], first[col["calls_oi_lakh"]]) else None,
                "sellers_cost_up_vs_down": (g("cost_step_up_cr") - g("cost_step_down_cr")) if None not in (g("cost_step_up_cr"), g("cost_step_down_cr")) else None,
                "forward_minus_spot": (g("forward") - g("spot")) / g("spot") if g("forward") else None,
                "toward_next_wall_mid": ((g("next_call_wall") + g("next_put_wall")) / 2 / g("spot") - 1) if None not in (g("next_call_wall"), g("next_put_wall")) else None,
            }
            for n, x in cand.items():
                if x is not None:
                    f.setdefault((n, hm), []).append((x, y))
    for (n, hm), xy in f.items():
        x, y = np.array([a for a, _ in xy]), np.array([b for _, b in xy])
        if len(y) < 40:
            continue
        p = np.array([(x[:i] @ y[:i]) / (x[:i] @ x[:i]) * x[i] if x[:i] @ x[:i] else 0.0 for i in range(20, len(y))])
        yy = y[20:]
        d = np.abs(yy) - np.abs(yy - p)
        tstat = float(d.mean() / (d.std(ddof=1) / math.sqrt(len(d)))) if d.std() else 0.0
        h = len(d) // 2
        row = {"signal": n, "at": hm, "n": int(len(d)), "t": round(tstat, 2),
               "hit": round(float(np.mean(np.sign(p) == np.sign(yy))) * 100, 1)}
        out["tested"].append(row)
        if tstat >= 2 and d[:h].mean() > 0 and d[h:].mean() > 0:
            out["proven"].append(row)
    return out


def next_session(fd: dict) -> dict:
    """Per index, the morning-call settings for its next session (the feed's "next" block after the close, else
    "today"): the relay turns GIFT Nifty's 09:00 move into the call with exactly close_estimate.preopen's arithmetic."""
    out = {}
    for idx, b in fd["indices"].items():
        t = b.get("next") if (b.get("today") or {}).get("actual") is not None and b.get("next") else b.get("today")
        if not t or not t.get("sig_d"):
            continue
        k = math.log(t["hi"] / t["lo"]) / 2
        if t.get("own_expiry") and t.get("straddle_pct") and t.get("expiry_q80"):
            k = t["expiry_q80"] * t["straddle_pct"] / 100
        g = t.get("gift") or {}
        out[idx] = {"target": t["target"], "asof": t["asof"], "base": t["base"], "own_expiry": bool(t.get("own_expiry")),
                    "beta": g.get("beta") or config.GIFT_BETA.get(idx), "k80": round(k * (g.get("range") or config.GIFT_RANGE.get(idx, 1)), 6)}
    return out


def main() -> dict:
    prices = json.loads((config.REPO / "state" / "prices.json").read_text(encoding="utf-8"))
    fd = json.loads(config.FEED_FILE.read_text(encoding="utf-8"))
    hist = _history(prices)
    table = fit(hist)
    tapes = _tapes()
    sessions = next_session(fd)
    vols = {i: _vol(prices.get(i, {}), "9999") for i in config.INDICES}
    out = {
        "generated_at": datetime.now(config.IST).isoformat(timespec="minutes"),
        "table": table,
        "vol20": {i: round(v, 6) for i, v in vols.items() if v},
        "session": sessions,
        "record": {"morning": _morning_record(_expiry_days(tapes), prices),
                   "odds_tested": reliability(hist),
                   "odds_live": _live_odds(tapes, table, prices),
                   "learning": _learn(tapes, prices)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    m, ot = out["record"]["morning"], out["record"]["odds_tested"]
    print(f"expiry meter: table from {table['n']} expiries since {table['from']}; morning calls on expiry days "
          f"{m['right']}/{m['n']}; tested odds on {ot['expiries']} expiries, Brier {ot['brier']}; "
          f"recorded expiry days {len(tapes)}; sessions {sessions}")
    return out


if __name__ == "__main__":
    main()
