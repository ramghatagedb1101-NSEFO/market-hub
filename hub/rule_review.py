"""
Professional-grade review of the candidate trading rules (13 Nov 2026, owner: "i want the rules to be reviewed like how
a professional grade institutional expert would do"). Research only: nothing here places an order.

Takes the rule family in hub/rule_test.py (expiry iron condor entered the evening before, held to settlement) and judges
each candidate the way a risk desk would before allocating capital:
  1. Evidence    mean result per trade, its t-statistic and a bootstrap 95% range; the bar is raised for the number of
                 settings tried (48 per index), because the best of many random settings looks good by luck alone
                 (expected best t of 48 coin-flip strategies is about sqrt(2 ln 48) = 2.78).
  2. Out of sample  first half vs second half, every year, and the walk-forward choice (settings picked from the past only).
  3. Tail risk   worst trade, worst 5% of trades (CVaR), largest fall from a peak, worst losing run, the five worst
                 expiries with dates, and event days (RBI, Budget, election result) on their own.
  4. Costs       results at no slippage, normal (max(0.10, 2% of price) per leg) and double.
  5. Robustness  the neighbouring settings (one step either way): a real edge is a plateau, not a spike.
  6. Capital     return on the margin a broker actually blocks: the condor's maximum loss plus SEBI's extra 2% margin on
                 short options on expiry day (circular of 1 Oct 2024, in force 20 Nov 2024; check against Kite's margin
                 calculator before any live use).
  7. Regime      before and after 20 Nov 2024 (SEBI: one weekly expiry per exchange, larger lots, extra expiry-day margin).
  8. Data        trades skipped for missing or untraded prices; known limits (closing prices of far strikes can be stale;
                 settlement is the index close here, the exchange uses its own settlement price).
Verdict per candidate: REJECT, PAPER (meets the bar out of sample but not proven), or CANDIDATE FOR SMALL LIVE SIZE.

    python -m hub.rule_review [--save]     (PRIVATE_REPO_TOKEN; --save writes state/rule_test/review.json, private)
"""
import json
import math
import random
import sys

from . import rule_test as rt

REGIME = "2024-11-20"
EXTRA_ELM = 0.02
TRIALS = len(rt.M_GRID) * len(rt.W_GRID) * len(rt.FILTERS)
T_BAR = math.sqrt(2 * math.log(TRIALS))
CANDIDATES = {                                     # chosen from rule_test's grid: positive in both halves, or comparison
    "NIFTY": [(1.0, 2.0, "all"), (1.25, 2.0, "all"), (1.5, 2.0, "all"), (0.75, 2.0, "all"), (1.25, 0.0, "all")],
    "BANKNIFTY": [(0.5, 0.5, "all"), (0.5, 1.0, "all"), (0.75, 0.5, "all")],
    "SENSEX": [(0.75, 1.0, "rich"), (0.75, 2.0, "rich"), (1.0, 2.0, "all")],
}
NEIGH_M = rt.M_GRID
NEIGH_W = rt.W_GRID


def evidence(p: list) -> dict:
    n = len(p)
    if n < 5:
        return {"n": n}
    mu = sum(p) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in p) / (n - 1))
    t = mu / (sd / math.sqrt(n)) if sd else 0.0
    rnd = random.Random(7)
    boots = sorted(sum(rnd.choice(p) for _ in range(n)) / n for _ in range(4000))
    return {"n": n, "avg_rs": round(mu), "t": round(t, 2), "t_bar": round(T_BAR, 2),
            "range95_avg_rs": [round(boots[100]), round(boots[3899])],
            "chance_avg_above_0_pct": round(100 * sum(1 for b in boots if b > 0) / len(boots), 1)}


def tail(res: list) -> dict:
    p = [x["pnl"] for x in res]
    if not p:
        return {}
    cum = peak = dd = 0.0
    for x in p:
        cum += x
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    k = max(1, len(p) // 20)
    worst5 = sorted(p)[:k]
    run = longest = 0
    for x in p:
        run = run + 1 if x < 0 else 0
        longest = max(longest, run)
    worst = sorted(res, key=lambda x: x["pnl"])[:5]
    return {"worst_rs": round(min(p)), "cvar5_rs": round(sum(worst5) / len(worst5)), "max_drawdown_rs": round(dd),
            "worst_losing_run": longest, "lost_pct": round(100 * sum(1 for x in p if x < 0) / len(p), 1),
            "worst_five": [{"expiry": x["exp"], "rs": round(x["pnl"]), "move_pct": x["move_pct"]} for x in worst],
            "avg_win_rs": round(sum(x for x in p if x > 0) / max(1, sum(1 for x in p if x > 0))),
            "avg_loss_rs": round(sum(x for x in p if x < 0) / max(1, sum(1 for x in p if x < 0)))}


def margin(x: dict) -> float:
    """Approximate blocked margin: the defined maximum loss, plus the extra 2% on sold legs on expiry day after 20 Nov 2024."""
    extra = EXTRA_ELM * x["short_notional"] if x["exp"] >= REGIME else 0.0
    return x["risk"] + extra


def series(d: list, m: float, w: float, flt: str, rich_ok: list) -> list:
    out = []
    for i, y in enumerate(d):
        if flt == "rich" and not rich_ok[i]:
            continue
        x = rt.trade(y["rec"], y["chain"], m, w)
        if x is None:
            continue
        r = y["rec"]
        out.append(dict(x, exp=r["expiry"], event=r.get("event"),
                        move_pct=round(100 * (r["close"] / r["prev_close"] - 1), 2)))
    return out


def summary(res: list) -> dict:
    p = [x["pnl"] for x in res]
    if not p:
        return {"n": 0}
    mg = sum(margin(x) for x in res) / len(res)
    return {"n": len(p), "total_rs_per_lot": round(sum(p)), "avg_rs": round(sum(p) / len(p)),
            "avg_margin_rs": round(mg), "return_on_margin_per_trade_pct": round(100 * sum(p) / len(p) / mg, 2),
            "costs_share_of_gross_pct": round(100 * sum(x["cost"] for x in res) / max(1.0, sum(x["pnl"] + x["cost"] for x in res if x["pnl"] + x["cost"] > 0)), 1)}


def verdict(ev: dict, halves: list, slip2: dict, neigh_ok: float, post: dict) -> str:
    if ev.get("n", 0) < 30:
        return "REJECT: too few trades to judge"
    if ev["avg_rs"] <= 0 or any((h.get("avg_rs") or 0) <= 0 for h in halves):
        return "REJECT: does not make money in both halves"
    if (slip2.get("avg_rs") or 0) <= 0:
        return "REJECT: the profit disappears at double slippage"
    if (post.get("avg_rs") or 0) <= 0:
        return "REJECT: loses since SEBI's Nov 2024 changes"
    if ev["t"] < 2 or neigh_ok < 0.5:
        return "REJECT: not distinguishable from luck" if ev["t"] < 2 else "REJECT: isolated spike, neighbours fail"
    if ev["t"] < ev["t_bar"]:
        return "PAPER: positive out of sample but below the bar for 48 settings tried"
    return "CANDIDATE FOR SMALL LIVE SIZE (after paper trading)"


def review() -> dict:
    data = rt.rows()
    out = {"trials_per_index": TRIALS, "t_bar": round(T_BAR, 2), "regime_from": REGIME, "by_index": {}}
    for idx, cands in CANDIDATES.items():
        d = [x for x in data if x["rec"]["symbol"] == idx]
        rich_ok = []
        for i in range(len(d)):
            pr = sorted(y["rich"] for y in d[:i] if y["rich"] is not None)
            rich_ok.append(d[i]["rich"] is not None and len(pr) >= 20 and d[i]["rich"] > pr[len(pr) // 2])
        half_day = d[len(d) // 2]["rec"]["expiry"]
        block = {"expiries": len(d), "split_at": half_day, "candidates": []}
        for m, w, flt in cands:
            rt.SLIP_MULT = 1.0
            res = series(d, m, w, flt, rich_ok)
            p = [x["pnl"] for x in res]
            first = [x for x in res if x["exp"] < half_day]
            second = [x for x in res if x["exp"] >= half_day]
            pre = [x for x in res if x["exp"] < REGIME]
            post = [x for x in res if x["exp"] >= REGIME]
            ev = evidence(p)
            slips = {}
            for mult in (0.0, 1.0, 2.0):
                rt.SLIP_MULT = mult
                slips[f"x{mult:g}"] = summary(series(d, m, w, flt, rich_ok))
            rt.SLIP_MULT = 1.0
            neigh = []
            mi, wi = NEIGH_M.index(m), NEIGH_W.index(w)
            for dm in (-1, 0, 1):
                for dw in (-1, 0, 1):
                    if (dm, dw) == (0, 0) or not (0 <= mi + dm < len(NEIGH_M)) or not (0 <= wi + dw < len(NEIGH_W)):
                        continue
                    nm, nw = NEIGH_M[mi + dm], NEIGH_W[wi + dw]
                    if (nw == 0) != (w == 0):
                        continue                                  # do not mix capped and uncapped risk
                    s = summary(series(d, nm, nw, flt, rich_ok))
                    neigh.append({"m": nm, "w": nw, "avg_rs": s.get("avg_rs"), "n": s.get("n")})
            neigh_ok = sum(1 for x in neigh if (x["avg_rs"] or 0) > 0) / len(neigh) if neigh else 0.0
            events = [x for x in res if x["event"]]
            years = sorted({x["exp"][:4] for x in res})
            s_first, s_second, s_post = summary(first), summary(second), summary(post)
            c = {"rule": f"sell {m} x straddle out, wings {w} x straddle further" if w else f"sell {m} x straddle out, NO wings (unlimited loss)",
                 "m": m, "w": w, "filter": flt, "all": summary(res), "evidence": ev,
                 "first_half": s_first, "second_half": s_second,
                 "before_nov_2024": summary(pre), "since_nov_2024": s_post,
                 "by_year": {y: summary([x for x in res if x["exp"][:4] == y]) for y in years},
                 "slippage": slips, "neighbours": neigh, "neighbours_positive_pct": round(100 * neigh_ok),
                 "tail": tail(res),
                 "event_days": [{"expiry": x["exp"], "event": x["event"], "rs": round(x["pnl"])} for x in events],
                 "skipped_expiries": len(d) - len(res) - (sum(1 for i in range(len(d)) if not rich_ok[i]) if flt == "rich" else 0)}
            c["verdict"] = verdict(ev, [s_first, s_second], slips["x2"], neigh_ok, s_post)
            if w == 0:
                c["verdict"] = "REJECT: unlimited loss; shown only to price what the wings cost"
            block["candidates"].append(c)
        out["by_index"][idx] = block
    return out


if __name__ == "__main__":
    res = review()
    print(json.dumps(res, indent=1))
    if "--save" in sys.argv:
        from .expiry_history import save
        save("state/rule_test/review.json", res, "rule review")
