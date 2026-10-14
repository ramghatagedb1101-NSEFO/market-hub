"""
Expiry-day intraday test (14 Oct 2026), on the minute paths from hub/expiry_intraday.py and the evening-before chain
features from hub/expiry_history.py (399 expiries, Oct 2023 - Oct 2026). Index paths only: no intraday option prices
exist for past expiries.

Questions, each answered walk-forward (a prediction for an expiry uses only earlier expiries of the same index, after
MIN_TRAIN of them) and per index:
  1. pull     -- from the spot at each meter checkpoint, does the official close move toward the evening-before max pain
                 or wall midpoint, or continue the morning move, more than "close = spot now"? (the forward on expiry
                 day is spot plus a few points of carry, so spot-now is the market's own estimate)
  2. average  -- before the 3 Aug 2026 closing auction, the close was the 15:00-15:30 average; from 15:00 on, part of
                 that average is already known. How much does using it beat spot-now?
  3. range    -- the remaining move from each checkpoint, scaled by the evening-before ATM straddle and the square root
                 of the time left: the multiplier that holds 68% (about 1 sd) out of sample.
  4. theta    -- the live expiry-theta rule (short strikes >= 3x the 60-session daily sigma from the 10:00 spot): how
                 often the close ends beyond, and how often the path touches, those strikes; same at 12:30 and 14:45.
A result "holds" only if it improves in BOTH halves of the out-of-sample period and its paired t-statistic is >= 2;
the report says how many cells were tested, since some will pass by chance.

    python -m hub.expiry_intraday_test --local /path/to/market-hub-private     # read files from a local clone
    python -m hub.expiry_intraday_test                                          # read from the private repo (API)
Writes state/expiry_history/intraday_test.json (local clone or private repo).
"""
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

AUCTION_FROM = "2026-08-03"
MIN_TRAIN = 30
SESSION_MIN = 375
CHECKPOINTS = {"10:00": 45, "12:00": 165, "12:30": 195, "14:00": 285, "14:45": 330, "15:00": 345, "15:15": 360}
THETA_TIMES = ("10:00", "12:30", "14:45")
THETA_MULTS = (2.0, 2.5, 3.0, 3.5, 4.0)


# ------------------------------------------------------------------ data
def _reader(local: str | None):
    if local:
        root = Path(local)
        return lambda p: json.loads((root / p).read_text(encoding="utf-8")) if (root / p).exists() else None
    from .expiry_history import load
    return load


def assemble(read) -> dict:
    """{index: [day dict sorted by expiry]} for every expiry with a minute path."""
    records = read("state/expiry_history/records.json") or {}
    prices = read("state/prices.json") or {}
    paths = {}
    out = defaultdict(list)
    for r in sorted(records.values(), key=lambda r: r["expiry"]):
        s, e = r["symbol"], r["expiry"]
        key = f"{s}_{e[:4]}"
        if key not in paths:
            paths[key] = read(f"state/expiry_history/intraday/{key}.json") or {}
        path = paths[key].get(e)
        if not path or r.get("close") is None:
            continue
        closes = sorted(prices.get(s, {}).items())
        prior = [v for d, v in closes if d < e][-61:]
        rets = [prior[i] / prior[i - 1] - 1 for i in range(1, len(prior))]
        sigma = None
        if len(rets) >= 20:
            m = sum(rets) / len(rets)
            sigma = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
        out[s].append({
            "expiry": e, "era": "auction" if e >= AUCTION_FROM else "average", "path": path,
            "open": path[0][1], "close": float(r["close"]), "prev_close": r.get("prev_close"),
            "max_pain": r.get("max_pain"), "wall_mid": r.get("wall_mid"),
            "call_wall": r.get("call_wall"), "put_wall": r.get("put_wall"),
            "straddle": r.get("straddle"), "sigma": sigma,
        })
    return out


def spot_at(path: list, minute: int) -> float:
    last = path[0][4]
    for row in path:
        if row[0] > minute:
            break
        last = row[4]
    return last


def extremes_after(path: list, minute: int) -> tuple[float, float]:
    rest = [row for row in path if row[0] > minute] or path[-1:]
    return max(row[2] for row in rest), min(row[3] for row in rest)


# ------------------------------------------------------------------ statistics
def paired(base: list, model: list) -> dict:
    """base/model: absolute errors in bp, same days. Positive gain = model better."""
    d = [b - m for b, m in zip(base, model)]
    n = len(d)
    if n < 10:
        return {"n": n}
    mean = sum(d) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in d) / (n - 1)) or 1e-9
    h = n // 2
    first, second = sum(d[:h]) / h, sum(d[h:]) / (n - h)
    t = mean / (sd / math.sqrt(n))
    return {"n": n, "mae_base_bp": round(sum(base) / n, 1), "mae_model_bp": round(sum(model) / n, 1),
            "gain_bp": round(mean, 2), "t": round(t, 2), "share_better": round(sum(1 for x in d if x > 0) / n, 3),
            "gain_first_half_bp": round(first, 2), "gain_second_half_bp": round(second, 2),
            "holds": bool(t >= 2 and first > 0 and second > 0)}


def walk_forward_slope(xs: list, ys: list) -> list:
    """Prediction of y_i from x_i with beta fit through the origin on points before i (None until MIN_TRAIN)."""
    out, sxy, sxx = [], 0.0, 0.0
    for i, (x, y) in enumerate(zip(xs, ys)):
        if i >= MIN_TRAIN and sxx > 0:
            beta = max(-1.0, min(1.0, sxy / sxx))
            out.append(beta * x)
        else:
            out.append(None)
        sxy += x * y
        sxx += x * x
    return out


def quantile(vals: list, q: float) -> float:
    s = sorted(vals)
    i = q * (len(s) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


# ------------------------------------------------------------------ tests
def test_pull(days: list) -> dict:
    out = {}
    for label, m in CHECKPOINTS.items():
        spots = [spot_at(d["path"], m) for d in days]
        y = [(d["close"] - s) / s for d, s in zip(days, spots)]
        cell = {}
        features = {
            "max_pain": [((d["max_pain"] - s) / s) if d["max_pain"] else 0.0 for d, s in zip(days, spots)],
            "wall_mid": [((d["wall_mid"] - s) / s) if d["wall_mid"] else 0.0 for d, s in zip(days, spots)],
            "morning_move": [(s - d["open"]) / d["open"] for d, s in zip(days, spots)],
        }
        for name, xs in features.items():
            preds = walk_forward_slope(xs, y)
            base, model = [], []
            for p, yy in zip(preds, y):
                if p is None:
                    continue
                base.append(abs(yy) * 1e4)
                model.append(abs(yy - p) * 1e4)
            cell[name] = paired(base, model)
        out[label] = cell
    return out


def test_average(days: list) -> dict:
    """Pre-auction era only: close was the 15:00-15:30 average. Partial average + spot for the rest vs spot alone."""
    out = {}
    pre = [d for d in days if d["era"] == "average"]
    for label, m in (("15:05", 350), ("15:10", 355), ("15:15", 360), ("15:20", 365), ("15:25", 370)):
        base, model = [], []
        for d in pre:
            known = [row[4] for row in d["path"] if 345 <= row[0] <= m]
            if not known:
                continue
            s = known[-1]
            rest = 30 - len(known)
            pred = (sum(known) + s * max(rest, 0)) / (len(known) + max(rest, 0))
            base.append(abs(d["close"] - s) / s * 1e4)
            model.append(abs(d["close"] - pred) / s * 1e4)
        out[label] = paired(base, model)
    return out


def test_range(days: list) -> dict:
    """z = |close - spot_t| / (spot_t * straddle_frac * sqrt(time left)). Walk-forward 68% multiplier and its coverage."""
    out = {}
    for label, m in CHECKPOINTS.items():
        z, scale = [], []
        for d in days:
            if not d["straddle"] or not d["prev_close"]:
                continue
            s = spot_at(d["path"], m)
            frac = d["straddle"] / d["prev_close"] * math.sqrt(max(SESSION_MIN - m, 1) / SESSION_MIN)
            z.append(abs(d["close"] - s) / s / frac)
            scale.append(frac)
        hits, widths, ks = 0, [], []
        for i in range(MIN_TRAIN, len(z)):
            k = quantile(z[:i], 0.68)
            ks.append(k)
            hits += z[i] <= k
            widths.append(k * scale[i] * 1e4)
        n = len(z) - MIN_TRAIN
        if n < 10:
            out[label] = {"n": n}
            continue
        out[label] = {"n": n, "k_latest": round(ks[-1], 2), "coverage_oos": round(hits / n, 3),
                      "half_width_bp_mean": round(sum(widths) / n, 1),
                      "remaining_move_bp_median": round(quantile([zz * sc * 1e4 for zz, sc in zip(z, scale)], 0.5), 1)}
    return out


def test_theta(days: list) -> dict:
    out = {}
    for label in THETA_TIMES:
        m = CHECKPOINTS[label]
        rows = [d for d in days if d["sigma"]]
        cell = {"n": len(rows)}
        for k in THETA_MULTS:
            close_out = touch = 0
            for d in rows:
                s = spot_at(d["path"], m)
                band = s * d["sigma"] * k
                hi, lo = extremes_after(d["path"], m)
                close_out += abs(d["close"] - s) > band
                touch += hi > s + band or lo < s - band
            cell[f"{k}x"] = {"close_beyond": round(close_out / max(len(rows), 1), 3),
                             "touched": round(touch / max(len(rows), 1), 3)}
        out[label] = cell
    return out


def main(argv=None) -> dict:
    argv = sys.argv[1:] if argv is None else argv
    local = argv[argv.index("--local") + 1] if "--local" in argv else None
    read = _reader(local)
    data = assemble(read)
    report = {"generated": date.today().isoformat(), "min_train": MIN_TRAIN, "auction_from": AUCTION_FROM, "indices": {}}
    cells = holds = 0
    for idx, days in sorted(data.items()):
        pull = test_pull(days)
        avg = test_average(days)
        for c in list(pull.values()):
            for v in c.values():
                cells += 1
                holds += bool(v.get("holds"))
        for v in avg.values():
            cells += 1
            holds += bool(v.get("holds"))
        report["indices"][idx] = {"expiries": len(days),
                                  "eras": {e: sum(1 for d in days if d["era"] == e) for e in ("average", "auction")},
                                  "pull": pull, "late_average": avg, "range": test_range(days), "theta": test_theta(days)}
    report["multiple_testing"] = {"cells_tested": cells, "cells_holding": holds,
                                  "expected_by_chance_at_t2": round(cells * 0.023, 1)}
    body = json.dumps(report, indent=1)
    if local:
        (Path(local) / "state/expiry_history/intraday_test.json").write_text(body, encoding="utf-8")
    else:
        from .expiry_history import save
        save("state/expiry_history/intraday_test.json", report, "expiry intraday test")
    return report


if __name__ == "__main__":
    print(json.dumps(main(), indent=1))
