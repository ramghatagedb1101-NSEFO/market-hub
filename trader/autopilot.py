"""
Autopilot (14 Nov 2026, owner: "the engine should be able to take a call and decide which is the best strategy";
choices: "Record + my tags", re-check "09:30, 11:00, 13:00", when nothing qualifies "Use my fallback strategy").

At each check time the market condition is read for each index in use (trader/regime.py). Candidates are the saved
strategies the owner has tagged for that condition ("Suited to"). Each candidate's record in that condition is its
back-test trades plus its paper trades entered in that condition. A candidate qualifies with at least MIN_TRADES
trades there and a profit after charges; the one with the best average profit per trade is picked. If none
qualifies: the owner's fallback strategy, or watch only when there is none. The safety limits stay in force
whichever strategy runs; a switch applies to new trades only.
"""
from .regime import REGIMES

CHECKS = ("09:30", "11:00", "13:00")
MIN_TRADES = 10


def record(sid: str, regime: str, backtests: dict, paper: dict) -> dict:
    out = {"trades": 0, "wins": 0, "pnl": 0.0}
    for src in ((backtests.get(sid) or {}).get("by_regime") or {}, (paper.get(sid) or {})):
        r = src.get(regime) or {}
        out["trades"] += int(r.get("trades") or 0)
        out["wins"] += int(r.get("wins") or 0)
        out["pnl"] += float(r.get("pnl") or 0)
    return out


def choose(items: list, regimes: dict, backtests: dict, paper: dict, fallback: str | None):
    """(strategy dict or None, why in words, scores). regimes: index -> condition (None before 09:30's reading)."""
    scores = []
    for it in items:
        reg = regimes.get(it.get("index") or "NIFTY")
        if not reg or reg not in (it.get("conditions") or []):
            continue
        rec = record(it["id"], reg, backtests, paper)
        ok = rec["trades"] >= MIN_TRADES and rec["pnl"] > 0
        scores.append({"id": it["id"], "name": it.get("name"), "regime": reg, **rec,
                       "avg": round(rec["pnl"] / rec["trades"], 2) if rec["trades"] else None, "qualifies": ok})
    good = [s for s in scores if s["qualifies"]]
    if good:
        best = max(good, key=lambda s: s["avg"])
        it = next(x for x in items if x["id"] == best["id"])
        why = (f"best record on {REGIMES[best['regime']].lower()} days among the strategies tagged for it: "
               f"{best['trades']} trades, {round(100 * best['wins'] / best['trades'])}% won, "
               f"₹{best['avg']:,.0f} a trade after charges")
        return it, why, scores
    fb = next((x for x in items if x["id"] == fallback), None) if fallback else None
    conds = ", ".join(sorted({REGIMES[r].lower() for r in regimes.values() if r})) or "not read yet"
    if fb:
        return fb, f"no tagged strategy has {MIN_TRADES}+ trades in profit for today's condition ({conds}): fallback", scores
    return None, f"no tagged strategy has {MIN_TRADES}+ trades in profit for today's condition ({conds}) and no fallback: watching only", scores
