"""
The expiry rule tests at what really traded (13 Nov 2026). Research only: nothing here places an order.

hub/rule_test.py enters each expiry's iron condor at about 15:25 the day before, priced at the exchange's closing
prices -- and hub/rule_review.py notes that closes of far strikes can be stale. hub/breeze_history.py has downloaded
ICICI's one-minute candles for 15:00-15:30 on those days. This runs rule_test's grid and walk-forward twice on the same
expiries -- once at the closing prices, once at the real 15:25 price -- and reports the gap:

  real price of a leg  close of its last one-minute candle from 15:15 to 15:25; no trade in those ten minutes means
                       there was no price to deal at, and the leg counts as untraded (rule_test then skips the trade
                       rather than guess, as it does for an untraded close)
  price check          for every leg with both prices: how far the close was from the 15:25 price, and how many legs
                       priced at a close had no trade near 15:25 at all

Output to the private repo only (state/rule_test/real_fill.json); the public log shows counts.
    gh workflow run diag.yml -f module=rule_real_fill      (or locally: python -m hub.rule_real_fill --print)
"""
import json
import sys
from collections import defaultdict

from . import rule_test as rt
from .breeze_history import DIR, INDEX, load_gz
from .expiry_history import load, save

FROM_MIN, AT_MIN = 360, 370                     # 15:15 and 15:25, as minutes after 09:15
OUT = "state/rule_test/real_fill.json"


def real_price(candles: list):
    """Last trade 15:15-15:25 on the day before expiry (day 0); fields [day, min, o, h, l, c, v, oi]."""
    xs = [c for c in candles or [] if c[0] == 0 and FROM_MIN <= c[1] <= AT_MIN and c[5]]
    return xs[-1][5] if xs else None


def icici() -> dict:
    """{record key: entry} for every expiry downloaded so far."""
    out = {}
    for key in sorted(load(INDEX) or {}):
        sym, exp = key.split("_", 1)
        e = load_gz(f"{DIR}/{sym}/{exp}.json.gz")
        if e:
            out[key] = e
    return out


def real_chain(chain: list, entry: dict) -> list:
    """The stored day-before chain with each price replaced by the real 15:25 price (0 = no trade near 15:25)."""
    out = []
    for k, ce, pe, ce_oi, pe_oi in chain:
        s = str(int(k) if float(k).is_integer() else k)
        out.append([k, real_price(entry["call"].get(s)) or 0.0, real_price(entry["put"].get(s)) or 0.0, ce_oi, pe_oi])
    return out


def price_check(pairs: list) -> dict:
    """pairs: (close, real or None) per leg that had a close."""
    both = [(c, r) for c, r in pairs if c > 0 and r]
    gaps = sorted(abs(r / c - 1) for c, r in both)
    q = lambda p: round(100 * gaps[min(len(gaps) - 1, int(p * len(gaps)))], 1) if gaps else None
    return {"legs_with_close": sum(1 for c, _ in pairs if c > 0),
            "no_trade_near_1525": sum(1 for c, r in pairs if c > 0 and not r),
            "median_gap_pct": q(0.5), "p90_gap_pct": q(0.9),
            "gap_over_10pct": sum(1 for g in gaps if g > 0.10)}


def main() -> int:
    data = icici()
    base = rt.rows()
    sub = [x for x in base if f"{x['rec']['symbol']}_{x['rec']['expiry']}" in data]
    print(f"{len(data)} expiries with ICICI minutes; {len(sub)} of {len(base)} test expiries covered")
    if not sub:
        return 0
    real = [dict(x, chain=real_chain(x["chain"], data[f"{x['rec']['symbol']}_{x['rec']['expiry']}"])) for x in sub]
    checks = defaultdict(list)
    for x, y in zip(sub, real):
        for a, b in zip(x["chain"], y["chain"]):
            checks[x["rec"]["symbol"]] += [(a[1], b[1] or None), (a[2], b[2] or None)]
    orig = rt.rows
    try:
        rt.rows = lambda: sub
        at_close = rt.run()
        rt.rows = lambda: real
        at_real = rt.run()
    finally:
        rt.rows = orig
    out = {"expiries": len(sub), "rule": f"real price = last trade {15}:{FROM_MIN:02d}-{15}:{AT_MIN:02d}", "by_index": {}}
    for idx in at_close["by_index"]:
        c, r = at_close["by_index"][idx], at_real["by_index"].get(idx, {})
        out["by_index"][idx] = {"expiries": c["expiries"], "price_check": price_check(checks[idx]),
                                "walk_forward_at_close": c["walk_forward"], "walk_forward_at_real": r.get("walk_forward"),
                                "best_second_half_at_close": c["best_second_half"][:3],
                                "best_second_half_at_real": (r.get("best_second_half") or [])[:3]}
        pc = out["by_index"][idx]["price_check"]
        print(f"{idx}: {c['expiries']} expiries; {pc['legs_with_close']} legs with a close, "
              f"{pc['no_trade_near_1525']} with no trade 15:15-15:25, {pc['gap_over_10pct']} more than 10% off")
    if "--print" in sys.argv:                                   # local use only: GitHub logs are public
        print(json.dumps(out, indent=1))
    else:
        save(OUT, out, f"rule test at real 15:25 prices ({len(sub)} expiries)")
        print(f"saved {OUT} (private)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
