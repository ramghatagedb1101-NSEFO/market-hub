"""
Trading-rule test (13 Nov 2026, owner: "ok do it" -- turn a signal into fixed rules and test them before any paper or
live trading). Research only: nothing here places an order.

Rule family tested: the expiry iron condor, entered the evening before an index's expiry and held to settlement.
  - Entry, about 15:25 on the day before expiry, at that day's closing option prices (NSE/BSE end-of-day files, already
    stored by hub/expiry_history.py in state/expiry_history/chains/). The day-before ATM straddle S is the options
    market's own expected move for the expiry day.
  - Sell the call nearest forward + m*S and the put nearest forward - m*S; buy the call and put a further w*S out
    (the wings cap the loss; w = 0 means no wings, a naked strangle, reported for comparison only).
  - Hold to expiry; every leg settles at intrinsic value against the index's close on the day.
  - Costs: Zerodha's published charges (the same table as the relay's paper account, relay/Paper.gs PAPER_RATES:
    brokerage Rs 20 an order, STT 0.15% on sold premium and on in-the-money long legs at settlement, exchange fees,
    stamp duty, SEBI fee, 18% GST) plus slippage: each leg filled worse than the close by max(0.10, 2% of price).
  - Optional filter "rich": trade only when the straddle is large next to recent realised movement (S / (index * 20-day
    daily vol) above its median over earlier expiries) -- selling only when options look expensive.

How it is judged (walk-forward, so the result cannot flatter itself): for each expiry the settings (m, w, filter) are
chosen from earlier expiries only (best total return on the money at risk, at least MIN_PAST of them), then applied to
that expiry. Also reported: every setting's result in the first and second half separately, worst single loss, worst
run of losses, and the share of expiries that lost.

    python -m hub.rule_test     (needs PRIVATE_REPO_TOKEN; reads the private repo, writes extras-style output to
                                 state/rule_test/summary.json in the private repo and prints it)
"""
import json
import math
import sys
from collections import defaultdict

from .expiry_history import load, save

LOT = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}          # current lot sizes (relay/Paper.gs PAPER_LOT)
EXCH = {"NIFTY": "NSE", "BANKNIFTY": "NSE", "SENSEX": "BSE"}
RATES = {"brokerage": 20, "stt_sell": 0.0015, "stt_exercise": 0.0015, "txn": {"NSE": 0.0003553, "BSE": 0.000325},
         "stamp_buy": 0.00003, "sebi": 0.000001, "gst": 0.18}   # zerodha.com/charges, checked Sat 17 Oct 2026
M_GRID = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0]
W_GRID = [0.0, 0.5, 1.0, 2.0]
FILTERS = ["all", "rich"]
MIN_PAST = 40
VOL_DAYS = 20
OUT = "state/rule_test/summary.json"


SLIP_MULT = 1.0                                               # 0 = fill at the close, 2 = twice the usual slippage


def slip(p: float) -> float:
    return SLIP_MULT * max(0.10, 0.02 * p)


def charges(price: float, qty: int, side: str, exch: str) -> float:
    turn = price * qty
    brk, txn, sebi = RATES["brokerage"], turn * RATES["txn"][exch], turn * RATES["sebi"]
    stt = turn * RATES["stt_sell"] if side == "sell" else 0.0
    stamp = turn * RATES["stamp_buy"] if side == "buy" else 0.0
    return brk + txn + sebi + stt + stamp + (brk + txn + sebi) * RATES["gst"]


def _nearest(chain: list, target: float, col: int):
    """Row whose strike is nearest the target and whose option (col 1 call, 2 put) traded (price > 0)."""
    ok = [r for r in chain if r[col] and r[col] > 0]
    return min(ok, key=lambda r: abs(r[0] - target)) if ok else None


def trade(rec: dict, chain: list, m: float, w: float):
    """One iron condor (or strangle when w == 0). Returns rupees per lot after costs and the money at risk, or None."""
    idx, f, s, close = rec["symbol"], rec["forward"], rec["straddle"], rec["close"]
    qty, exch = LOT[idx], EXCH[idx]
    sc, sp = _nearest(chain, f + m * s, 1), _nearest(chain, f - m * s, 2)
    if not sc or not sp or sc[0] <= sp[0]:
        return None
    legs = [("sell", "C", sc[0], sc[1]), ("sell", "P", sp[0], sp[2])]
    if w > 0:
        lc, lp = _nearest(chain, sc[0] + w * s, 1), _nearest(chain, sp[0] - w * s, 2)
        if not lc or not lp or lc[0] <= sc[0] or lp[0] >= sp[0]:
            return None                                           # chain too short for the wing: skip, never guess
        legs += [("buy", "C", lc[0], lc[1]), ("buy", "P", lp[0], lp[2])]
    pnl, cost, credit = 0.0, 0.0, 0.0
    for side, kind, k, px in legs:
        fill = px - slip(px) if side == "sell" else px + slip(px)
        value = max(close - k, 0) if kind == "C" else max(k - close, 0)
        sign = 1 if side == "sell" else -1
        credit += sign * fill
        pnl += sign * (fill - value) * qty
        cost += charges(fill, qty, side, exch)
        if side == "buy" and value > 0:
            cost += value * qty * RATES["stt_exercise"]           # long leg settles in the money
    if w > 0:
        width = max(legs[2][2] - legs[0][2], legs[1][2] - legs[3][2])
        risk = max(width - credit, 0.01) * qty
    else:
        risk = s * 3 * qty                                        # naked: no cap; 3 straddles as a stand-in for margin
    shorts = 2 * rec["prev_close"] * qty                      # notional of the two sold legs
    return {"pnl": pnl - cost, "risk": risk, "cost": cost, "credit": credit * qty, "short_notional": shorts}


def _vol(px: dict, before: str):
    ds = sorted(d for d in px if d < before)[-(VOL_DAYS + 1):]
    if len(ds) < VOL_DAYS:
        return None
    r = [math.log(px[ds[i]] / px[ds[i - 1]]) for i in range(1, len(ds))]
    mu = sum(r) / len(r)
    return math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1))


def rows() -> list:
    recs = load("state/expiry_history/records.json") or {}
    closes = defaultdict(dict)                                    # index closes from the records' own prev-day/close
    for r in recs.values():
        if r.get("close") is not None:
            closes[r["symbol"]][r["expiry"]] = r["close"]
        if r.get("prev_close") is not None:
            closes[r["symbol"]][r["prev_day"]] = r["prev_close"]
    chains, out = {}, []
    for r in sorted(recs.values(), key=lambda r: r["expiry"]):
        if r.get("close") is None or not r.get("straddle") or not r.get("forward"):
            continue
        key = f"{r['symbol']}_{r['expiry'][:4]}"
        if key not in chains:
            chains[key] = load(f"state/expiry_history/chains/{key}.json") or {}
        ch = (chains[key].get(f"{r['symbol']}_{r['expiry']}") or {}).get("day_before")
        if not ch:
            continue
        v = _vol(closes[r["symbol"]], r["prev_day"])
        rich = r["straddle"] / (r["prev_close"] * v) if v else None
        out.append({"rec": r, "chain": ch, "rich": rich})
    return out


def _stats(res: list) -> dict:
    if not res:
        return {"n": 0}
    p = [x["pnl"] for x in res]
    run = worst = 0
    for x in p:
        run = run + 1 if x < 0 else 0
        worst = max(worst, run)
    risk = sum(x["risk"] for x in res)
    return {"n": len(p), "total_rs_per_lot": round(sum(p)), "avg_rs": round(sum(p) / len(p)),
            "return_on_risk_pct": round(100 * sum(p) / risk, 2) if risk else None,
            "lost_pct": round(100 * sum(1 for x in p if x < 0) / len(p), 1), "worst_rs": round(min(p)),
            "best_rs": round(max(p)), "worst_losing_run": worst, "costs_rs": round(sum(x["cost"] for x in res))}


def run() -> dict:
    data = rows()
    out = {"expiries": len(data), "from": data[0]["rec"]["expiry"] if data else None,
           "to": data[-1]["rec"]["expiry"] if data else None, "by_index": {}}
    for idx in ("NIFTY", "BANKNIFTY", "SENSEX"):
        d = [x for x in data if x["rec"]["symbol"] == idx]
        if not d:
            continue
        grid = {}
        for m in M_GRID:
            for w in W_GRID:
                grid[(m, w)] = [trade(x["rec"], x["chain"], m, w) for x in d]
        half = len(d) // 2
        rich_ok = []                                              # options look expensive, judged on earlier expiries only
        for i in range(len(d)):
            pr = sorted(y["rich"] for y in d[:i] if y["rich"] is not None)
            rich_ok.append(d[i]["rich"] is not None and len(pr) >= 20 and d[i]["rich"] > pr[len(pr) // 2])
        settings = []
        for (m, w), res in grid.items():
            for flt in FILTERS:
                def keep(i):
                    if res[i] is None:
                        return False
                    return flt == "all" or rich_ok[i]
                first = [res[i] for i in range(half) if keep(i)]
                second = [res[i] for i in range(half, len(d)) if keep(i)]
                settings.append({"m": m, "w": w, "filter": flt, "first_half": _stats(first), "second_half": _stats(second)})
        # walk-forward: pick the setting with the best return on risk over earlier expiries, wings only (w > 0)
        wf, picks = [], defaultdict(int)
        for i in range(MIN_PAST, len(d)):
            best, best_r = None, -1e18
            for (m, w), res in grid.items():
                if w == 0:
                    continue
                for flt in FILTERS:
                    past = [res[j] for j in range(i) if res[j] is not None and (flt == "all" or rich_ok[j])]
                    if len(past) < 20:
                        continue
                    rr = sum(x["pnl"] for x in past) / sum(x["risk"] for x in past)
                    if rr > best_r:
                        best, best_r = (m, w, flt), rr
            if not best or best_r <= 0:
                continue                                          # nothing has made money so far: stay out
            m, w, flt = best
            x = grid[(m, w)][i]
            if x is None:
                continue
            if flt == "rich" and not rich_ok[i]:
                continue
            picks[f"m{m}_w{w}_{flt}"] += 1
            wf.append(dict(x, exp=d[i]["rec"]["expiry"]))
        settings.sort(key=lambda s: -(s["second_half"].get("return_on_risk_pct") or -1e9))
        out["by_index"][idx] = {"expiries": len(d), "from": d[0]["rec"]["expiry"], "to": d[-1]["rec"]["expiry"],
                                "walk_forward": _stats(wf), "walk_forward_picks": dict(picks),
                                "walk_forward_by_year": {y: _stats([x for x in wf if x["exp"][:4] == y])
                                                         for y in sorted({x["exp"][:4] for x in wf})},
                                "best_second_half": settings[:5], "all_settings": settings}
    return out


if __name__ == "__main__":
    res = run()
    brief = {k: v for k, v in res.items() if k != "by_index"}
    brief["by_index"] = {i: {k: v for k, v in b.items() if k != "all_settings"} for i, b in res["by_index"].items()}
    print(json.dumps(brief, indent=1))
    if "--save" in sys.argv:
        save(OUT, res, "rule test " + (res.get("to") or ""))
