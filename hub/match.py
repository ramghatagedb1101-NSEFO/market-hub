"""
Market match (16 Nov 2026, owner: "i want such recommendations to decide. i cant keep asking you every day").

Every evening: how NIFTY behaved over the last 10 sessions (its move, its average daily swing, its distance from the
50-day average), the past stretches that looked most like it, and the research-bot strategies that made the most in the
30 days (21 sessions) after those stretches. Shown on the dashboard's Strategies page (with "Use this") and the phone's
F&O tab. A starting point for the owner's decision, not a tested recommendation: 16 Nov's walk-forward test found that
choosing this way alone did not beat picking blindly.

    python -m hub.match RESULTS_DIR      (RESULTS_DIR: a copy of the private repo's state/bot/results, the bot's ideas
                                          with day-by-day results)
Writes docs/data/match.json (site/match.json in the private repo through hub.site_data push). Reads state/prices.json.
"""
import glob
import gzip
import json
import math
import os
import statistics as st
import sys
from datetime import datetime

from . import config

LOOK, AFTER, STRETCHES, APART, TOP, PICK_WON = 10, 21, 5, 15, 5, 3
OUT = config.SITE_DIR / "data" / "match.json"


def describe(c: list, j: int) -> list:
    """The LOOK sessions ending at index j: NIFTY's move %, average daily swing %, distance from its 50-day average %."""
    r = [math.log(c[j - k] / c[j - k - 1]) for k in range(LOOK)]
    ma50 = sum(c[j - 49:j + 1]) / 50
    return [round((c[j] / c[j - LOOK] - 1) * 100, 2), round(st.pstdev(r) * 100, 2), round((c[j] / ma50 - 1) * 100, 2)]


def by_regime(trades: list) -> dict:
    """A strategy's tested record in each market condition (the condition at entry, as the trading program reads it)."""
    out = {}
    for t in trades:
        r = out.setdefault(t.get("regime") or "unknown", {"trades": 0, "profit": 0.0, "won": 0})
        r["trades"] += 1
        r["profit"] += t.get("pnl") or 0.0
        r["won"] += (t.get("pnl") or 0) > 0
    return {k: dict(v, profit=round(v["profit"])) for k, v in out.items()}


def passed(ideas: dict) -> list:
    """Every idea that passed the research bot's full test (development months, nearby settings, unseen months), with its
    settings and record by condition: the trading program fills idle time with these (owner, 17 Nov 2026: "Fill idle
    time. only with strategies that passed testing based on latest market condition at that time")."""
    return [{"key": k, "name": v["name"], "by_regime": v["by_regime"],
             "strategy": dict(v["strategy"], id="p_" + k, name=v["name"])}
            for k, v in ideas.items() if v.get("stage") == "recommended" and v.get("strategy")]


def load_ideas(results_dir: str) -> dict:
    ideas = {}
    for f in glob.glob(os.path.join(results_dir, "*.json.gz")):
        try:
            x = json.loads(gzip.decompress(open(f, "rb").read()))
        except (OSError, ValueError):
            continue
        days, trades = [], []
        for part in ("dev", "vault"):
            days += ((x.get(part) or {}).get("summary") or {}).get("days") or []
            trades += ((x.get(part) or {}).get("summary") or {}).get("trades") or []
        if days:
            ideas[x["key"]] = {"name": x.get("name"), "stage": x.get("stage"), "family": x.get("family"), "strategy": x.get("strategy"),
                               "by_regime": by_regime(trades),
                               "pnl": {d["date"]: d["pnl"] for d in days}, "first": min(d["date"] for d in days),
                               "last": max(d["date"] for d in days)}
    return ideas


def build(closes: dict, ideas: dict) -> dict:
    nd = sorted(closes)
    nc = [closes[d] for d in nd]
    now = describe(nc, len(nd) - 1)
    first = min(v["first"] for v in ideas.values())
    last = max(v["last"] for v in ideas.values())
    cand = [j for j, d in enumerate(nd) if j >= 60 and d >= first and j + AFTER < len(nd) and nd[j + AFTER] <= last]
    feats = {j: describe(nc, j) for j in cand}
    scale = [st.pstdev([f[i] for f in feats.values()]) or 1 for i in range(3)]
    dist = {j: math.sqrt(sum(((feats[j][i] - now[i]) / scale[i]) ** 2 for i in range(3))) for j in cand}
    chosen = []
    for j in sorted(cand, key=dist.get):           # the closest stretches, each a separate episode
        if all(abs(j - c) >= APART for c in chosen):
            chosen.append(j)
        if len(chosen) == STRETCHES:
            break
    rows = []
    for k, v in ideas.items():
        per = [sum(v["pnl"].get(nd[j + n], 0.0) for n in range(1, AFTER + 1)) for j in chosen]
        rows.append({"key": k, "name": v["name"], "stage": v["stage"], "total": round(sum(per)),
                     "won": sum(p > 0 for p in per), "traded": sum(p != 0 for p in per), "each": [round(p) for p in per]})
    rows.sort(key=lambda r: (-r["total"], -r["won"]))
    # autopilot's pick (owner, 16 Nov 2026: "Matches today's market should be one of the option for auto mode. actually
    # the default one"): the highest total among ideas that made money after at least 3 of the stretches, so the pick
    # does not rest on one or two lucky ones; it must have its settings stored
    pick = next((r for r in rows if r["won"] >= PICK_WON and r["total"] > 0 and (ideas[r["key"]].get("strategy"))), None)
    if pick:
        pick = dict(pick, strategy=dict(ideas[pick["key"]]["strategy"], id="m_" + pick["key"], name=pick["name"]))
    return {"generated": datetime.now(config.IST).isoformat(timespec="minutes"), "asof": nd[-1],
            "now": {"move": now[0], "swing": now[1], "vs_ma50": now[2]},
            "stretches": [{"end": nd[j], "move": feats[j][0], "swing": feats[j][1], "vs_ma50": feats[j][2]} for j in chosen],
            "top": rows[:TOP], "pick": pick, "passed": passed(ideas), "pick_rule": f"highest total among those that made money after {PICK_WON}+ of the {STRETCHES}",
            "ideas": len(ideas), "after_sessions": AFTER, "look_sessions": LOOK}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    closes = json.loads((config.REPO / "state" / "prices.json").read_text(encoding="utf-8")).get("NIFTY") or {}
    ideas = load_ideas(argv[0]) if argv else {}
    if len(closes) < 80 or not ideas:
        print(f"market match: not built ({len(closes)} closes, {len(ideas)} ideas)")
        return 0
    out = build(closes, ideas)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"market match {out['asof']}: NIFTY {out['now']}; stretches {[s['end'] for s in out['stretches']]}; "
          f"top {out['top'][0]['name'] if out['top'] else None}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
