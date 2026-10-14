"""Second look at the expiry history (owner, 15 Oct 2026: "probably we are not analysing the right way").
Run on the private repo's state/expiry_history/records.json (hub/expiry_history.py):
    gh api -H "Accept: application/vnd.github.raw" repos/ramghatagedb1101-NSEFO/market-hub-private/contents/state/expiry_history/records.json > <dir>/recs.json
    python -m hub.expiry_patterns <dir>
Findings of 15 Oct 2026 in CHANGELOG ("Expiry history, second look").
Questions the first test did not ask, each against a shuffle baseline (other days' walls / max pain, scaled by each
day's one standard deviation, applied to this day's actual path), so chance cannot pass for a pattern."""
import json
import random
import sys

R = json.load(open(sys.argv[1] + "/recs.json"))
random.seed(7)
STEP = {"NIFTY": 50, "BANKNIFTY": 100, "SENSEX": 100}


def sd(r):
    return max(r["straddle"] / 0.8, r["open"] * 0.0005)


def shuffle_p(recs, stat, n=2000):
    """stat(rec, offsets) on own offsets vs offsets taken from a random other day; p = share of shuffles >= own."""
    own = sum(stat(r, r) for r in recs) / len(recs)
    hits, vals = 0, []
    for _ in range(n):
        perm = recs[:]
        random.shuffle(perm)
        v = sum(stat(r, q) for r, q in zip(recs, perm)) / len(recs)
        vals.append(v)
        hits += v >= own
    vals.sort()
    return own, sum(vals) / n, hits / n


def rel(r, q, key):
    """q's level `key` moved onto r: same distance from the open in standard deviations."""
    return r["open"] + (q[key] - q["open"]) / sd(q) * sd(r)


def pct(x):
    return f"{100 * x:.1f}%"


for sym in ("NIFTY", "BANKNIFTY", "SENSEX"):
    recs = sorted([r for r in R.values() if r["symbol"] == sym], key=lambda r: r["expiry"])
    print(f"\n================ {sym}: {len(recs)} expiries {recs[0]['expiry']} to {recs[-1]['expiry']}")

    # 1. Walls as barriers through the day (high/low), not just the close
    held_c = lambda r, q: r["high"] <= rel(r, q, "call_wall")
    held_p = lambda r, q: r["low"] >= rel(r, q, "put_wall")
    inside = lambda r, q: rel(r, q, "put_wall") <= r["close"] <= rel(r, q, "call_wall")
    for name, f in (("call wall never crossed (high below it)", held_c), ("put wall never crossed (low above it)", held_p),
                    ("close between the walls", inside)):
        own, base, p = shuffle_p(recs, f)
        print(f"1. {name:42} own {pct(own)}  vs shuffled {pct(base)}  (p {p:.3f})")

    # 2. Max pain: close nearer to it than chance?
    near_mp = lambda r, q: abs(r["close"] - rel(r, q, "max_pain")) <= STEP[sym]
    own, base, p = shuffle_p(recs, near_mp)
    print(f"2. close within 1 step of max pain               own {pct(own)}  vs shuffled {pct(base)}  (p {p:.3f})")

    # 3. Conditional pinning: by how far the open is from max pain (in sd), and OI concentration
    print("3. fraction of the open-to-max-pain gap closed by the close (1 = closed fully, 0 = none), by distance:")
    for lo, hi in ((0, 0.25), (0.25, 0.5), (0.5, 1.0), (1.0, 9)):
        b = [r for r in recs if lo <= abs(r["max_pain"] - r["open"]) / sd(r) < hi and r["max_pain"] != r["open"]]
        if len(b) < 5:
            print(f"     |open - MP| {lo}-{hi} sd: n {len(b)}")
            continue
        frac = sorted((r["close"] - r["open"]) / (r["max_pain"] - r["open"]) for r in b)
        toward = sum(f > 0 for f in frac)
        print(f"     |open - MP| {lo:>4}-{hi:<4} sd: n {len(b):3}  moved toward MP {toward}/{len(b)} ({pct(toward / len(b))})  median gap closed {frac[len(frac) // 2]:+.2f}")
    conc = sorted(recs, key=lambda r: (r["call_wall_oi"] / max(1, r["calls_oi"]) + r["put_wall_oi"] / max(1, r["puts_oi"])))
    third = len(conc) // 3
    for label, b in (("OI spread out (low third)", conc[:third]), ("OI piled on the walls (top third)", conc[-third:])):
        own, base, p = shuffle_p(b, inside, 1000)
        print(f"     {label:34} close between walls own {pct(own)} vs shuffled {pct(base)} (p {p:.3f}); n {len(b)}")

    # 4. From the previous close (includes the overnight move)
    tw = [r for r in recs if abs(r["max_pain"] - r["prev_close"]) >= STEP[sym]]
    toward = sum((r["close"] - r["prev_close"]) * (r["max_pain"] - r["prev_close"]) > 0 for r in tw)
    gap = [r for r in tw if (r["open"] - r["prev_close"]) * (r["max_pain"] - r["prev_close"]) > 0]
    print(f"4. from the previous close: moved toward max pain {toward}/{len(tw)} ({pct(toward / len(tw))}); the overnight gap went toward it {len(gap)}/{len(tw)} ({pct(len(gap) / len(tw))})")

    # 5. Eras
    eras = [("Oct 2023 - Nov 2024", "2023-01-01", "2024-11-20"), ("Nov 2024 - Aug 2025", "2024-11-20", "2025-09-01"),
            ("Sep 2025 - Jul 2026", "2025-09-01", "2026-08-03"), ("Aug 2026 on (closing auction)", "2026-08-03", "2099-01-01")]
    print("5. by era: close between walls (own vs shuffled) | toward max pain from the open")
    for name, a, b2 in eras:
        b = [r for r in recs if a <= r["expiry"] < b2]
        if len(b) < 8:
            print(f"     {name:30} n {len(b)}")
            continue
        own, base, p = shuffle_p(b, inside, 1000)
        tw = [r for r in b if abs(r["max_pain"] - r["open"]) >= STEP[sym]]
        t = sum((r["close"] - r["open"]) * (r["max_pain"] - r["open"]) > 0 for r in tw)
        print(f"     {name:30} n {len(b):3}  walls {pct(own)} vs {pct(base)} (p {p:.2f}) | toward MP {t}/{len(tw)}")

    # 6. The range: does the day-before straddle overprice the expiry-day move? (sellers' edge)
    mv = [abs(r["close"] - r["forward"]) for r in recs]
    st = [r["straddle"] for r in recs]
    in1 = sum(abs(r["close"] - r["forward"]) <= r["straddle"] / 0.8 for r in recs)
    win = sum(abs(r["close"] - r["forward"]) < r["straddle"] for r in recs)
    print(f"6. straddle (day before) avg {sum(st) / len(st):.0f} pts vs actual move from the forward to the close avg {sum(mv) / len(mv):.0f} pts "
          f"-> sellers kept {100 * (1 - sum(mv) / sum(st)):.0f}% of premium on average; straddle seller won {win}/{len(recs)} days; close within 1 sd {pct(in1 / len(recs))} (normal 68%)")
