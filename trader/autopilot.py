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
from datetime import date
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


# Opening gap (17 Nov 2026, owner: "signal at pre open is also very very relevant"): Dec 2024 - Apr 2026, on days NIFTY
# opened 0.8% or more from the previous close the research ideas lost about 3 times as much a day as on other days, and the
# match pick's walk-forward total rose from +4,529 to +9,343 per lot by sitting those days out. Switching to the idea
# that did best on past gap days lost more than blind picking, so the rule is skip, not switch.
GAP_SKIP = 0.8


FILL_UNTIL = "14:30"        # no fresh strategy after this (time left to enter and exit the same day)
FILL_MIN_TRADES = 5          # a condition with fewer tested trades than this is not a record


def is_done(strategy, open_legs: int, hhmm: str) -> bool:
    """The strategy in charge is done for the day (17 Nov 2026, owner: "A. Fill idle time"): nothing open, and either its
    trades for the day are used or its entry window is over. No strategy at all (watching) counts as done."""
    if open_legs:
        return False
    if strategy is None:
        return True
    d = getattr(strategy, "d", None) or {}
    w = d.get("window") or {}
    return getattr(strategy, "trades", 0) >= (d.get("max_trades_day") or 1) or hhmm > (w.get("until") or "15:30")


def fill_choice(passed: list, regimes: dict, exclude: set) -> tuple[dict | None, str]:
    """Owner, 17 Nov 2026: "only with strategies that passed testing based on latest market condition at that time". Of the
    strategies that passed the research bot's full test, the one with the best tested profit per trade in the market
    condition read now (its own index), at least FILL_MIN_TRADES trades there and in profit; none, and it watches."""
    best, why = None, None
    for p in passed or []:
        s = p.get("strategy") or {}
        if not s or s.get("id") in exclude:
            continue
        reg = regimes.get(s.get("index") or "NIFTY")
        r = (p.get("by_regime") or {}).get(reg or "") or {}
        if r.get("trades", 0) < FILL_MIN_TRADES or r.get("profit", 0) <= 0:
            continue
        per = r["profit"] / r["trades"]
        if best is None or per > best[0]:
            best, why = (per, s), (f"fills the rest of the day: tested {r['trades']} trades in this market ({reg}), "
                                   f"{r['profit']} per lot, {r.get('won', 0)} won")
    if best is None:
        return None, "nothing that passed testing has a record in this market; watching"
    return best[1], why


def match_choice(b: dict, today: date, gap: float | None = None) -> tuple[dict | None, str]:
    """Autopilot by market match (16 Nov 2026, owner: "Matches today's market should be one of the option for auto mode.
    actually the default one"): the evening's pick (hub/match.py -> relay -> strategies.json "match_pick"). None, and a
    reason, when there is no pick or it is more than 4 days old (a stale evening run)."""
    p = b.get("match_pick") or {}
    item = p.get("strategy")
    if not item:
        return None, "market match: no pick from the evening run; watching only"
    try:
        age = (today - date.fromisoformat(str(p.get("asof"))[:10])).days
    except ValueError:
        age = 99
    if age > 4:
        return None, f"market match: the pick is from {p.get('asof')}, too old; watching only"
    if gap is not None and abs(gap) >= GAP_SKIP:
        return None, (f"market match: NIFTY opened {gap:+.2f}% from yesterday's close (big gap, {GAP_SKIP}% or more); "
                      "the pick sits today out")
    item = dict(item, id=item.get("id") or "m_" + str(p.get("key")), name=item.get("name") or p.get("name"))
    return item, (f"matches today's market (evening of {p.get('asof')}): made {p.get('total')} per lot in the 30 days after "
                  f"{p.get('won')} of 5 similar stretches")
