"""Walk-forward test of index-specific expiry rules (14 Oct 2026, owner: "go ahead" on rules per index). Forecast at the
open from the evening-before chain; each expiry predicted only from earlier ones. Run like hub/expiry_patterns.py:
    python -m hub.expiry_rules_test <dir holding recs.json>
Result of 14 Oct 2026 in CHANGELOG ("Index rules tested walk-forward")."""
import json
import math
import sys

R = json.load(open(sys.argv[1] + "/recs.json"))
STEP = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}
BUCKETS = [0.0, 0.25, 0.5, 1.0, 99.0]
PRIOR_SD = 0.5          # pull weight per distance band starts at 0, spread 0.5 (one expiry only nudges it)


def sd(r):
    return max(r["straddle"] / 0.8, r["open"] * 0.0005)


def band(r):
    d = abs(r["max_pain"] - r["open"]) / sd(r)
    return next(i for i in range(4) if BUCKETS[i] <= d < BUCKETS[i + 1])


def fit_pull(past):
    """per band: k = sum(x y / sd^2) / (sum(x^2 / sd^2) + 1 / PRIOR_SD^2), x = MP - O, y = C - O (in sd units)."""
    num, den = [0.0] * 4, [1 / PRIOR_SD ** 2] * 4
    for q in past:
        x, y = (q["max_pain"] - q["open"]) / sd(q), (q["close"] - q["open"]) / sd(q)
        b = band(q)
        num[b] += x * y
        den[b] += x * x
    return [n / d for n, d in zip(num, den)]


def bp(v, c):
    return abs(v - c) / c * 1e4


for sym in ("NIFTY", "BANKNIFTY", "SENSEX"):
    recs = sorted([r for r in R.values() if r["symbol"] == sym], key=lambda r: r["expiry"])
    e_open, e_pull, e_clip, near_o, near_p, wins = [], [], [], 0, 0, 0
    cov1, cov_c, cov_w, wid1, wid_c, wid_w = 0, 0, 0, 0.0, 0.0, 0.0
    for t, r in enumerate(recs):
        past = recs[:t]
        k = fit_pull(past)
        pred = r["open"] + k[band(r)] * (r["max_pain"] - r["open"])
        clip = min(max(pred, r["put_wall"]), r["call_wall"])
        e_open.append(bp(r["open"], r["close"]))
        e_pull.append(bp(pred, r["close"]))
        e_clip.append(bp(clip, r["close"]))
        wins += abs(pred - r["close"]) < abs(r["open"] - r["close"])
        near_o += abs(r["open"] - r["close"]) <= STEP[sym]
        near_p += abs(pred - r["close"]) <= STEP[sym]
        # range: +-1 sd as now, +-c sd with c = 68th percentile of past |close - pred| / sd, and that range cut at the walls
        z = sorted(abs(q["close"] - (q["open"] + fit_pull(recs[:i])[band(q)] * (q["max_pain"] - q["open"]))) / sd(q)
                   for i, q in enumerate(past[-60:], start=max(0, t - 60))) if t >= 20 else []
        c = z[int(0.68 * len(z))] if z else 1.0
        lo1, hi1 = pred - sd(r), pred + sd(r)
        loc, hic = pred - c * sd(r), pred + c * sd(r)
        low, hiw = max(loc, r["put_wall"]), min(hic, r["call_wall"])
        cov1 += lo1 <= r["close"] <= hi1
        cov_c += loc <= r["close"] <= hic
        cov_w += low <= r["close"] <= hiw
        wid1 += (hi1 - lo1) / r["open"] * 1e4
        wid_c += (hic - loc) / r["open"] * 1e4
        wid_w += max(0, hiw - low) / r["open"] * 1e4
    n = len(recs)
    d = [a - b for a, b in zip(e_pull, e_open)]
    md = sum(d) / n
    sdd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1))
    tt = md / (sdd / math.sqrt(n)) if sdd else 0
    k_all = fit_pull(recs)
    print(f"\n{sym} ({n} expiries)")
    print(f"  point forecast, mean error bp: open {sum(e_open) / n:.1f} | pull by distance {sum(e_pull) / n:.1f} | pull + walls clip {sum(e_clip) / n:.1f}"
          f"   (difference {md:+.1f} bp, t {tt:+.2f}); closer than the open {wins}/{n}; close within one strike: open {near_o}, rule {near_p}")
    print(f"  pull weight per distance band (all expiries), |open - MP| <0.25 / 0.25-0.5 / 0.5-1 / >1 sd: " + " / ".join(f"{x:+.2f}" for x in k_all))
    print(f"  range coverage (target ~68%) and width: +-1 sd {100 * cov1 / n:.0f}% ({wid1 / n:.0f} bp) | calibrated {100 * cov_c / n:.0f}% ({wid_c / n:.0f} bp)"
          f" | calibrated and cut at the walls {100 * cov_w / n:.0f}% ({wid_w / n:.0f} bp)")
