"""
The research bot (owner, 14 Nov 2026: "an agentic AI bot who can use the available data sources ... test models on
historic data and come up with algorithms that can be applied as strategies for forward live trades via my paper
account"; "the bot can recommend and I should be able to turn on and off strategies").

It proposes strategy ideas, tests each one with the same back-tester as the dashboard (trader/backtest.py: ICICI / IBKR
minute prices, full charges, the program's own engine), keeps only what survives, and recommends the survivors. It
never switches anything on: the owner adds a recommendation to the strategies and switches it on or off.

Where ideas come from
  - FAMILIES: ideas with a stated reason someone pays us (option buyers overpay for insurance, time decay is fastest at
    expiry, opening gaps partly reverse, trend days continue, ...), each over a small grid of settings;
  - Gemini (through the relay, ?mode=bot_ask, so its key stays there): a few new ideas each run, given what has passed
    and failed so far; each must state its reason too.

The tests, in order (cheapest first; a failure stops there and is recorded in the ledger, never retried):
  1. development period DEV_FROM..DEV_TO (after SEBI's Nov 2024 F&O rules; rules use days to expiry, not weekdays):
     enough trades (MIN_TRADES); profit after all charges; profit factor >= MIN_PF; still in profit without its best 5
     days; in profit in both halves; worst day inside the day's loss limit; and a t-statistic of the daily profit above
     a bar that RISES with the number of ideas ever tested (bar(N) = 1.5 + 0.5 log10 N), so testing many ideas cannot
     manufacture a winner by luck;
  2. neighbours: the same idea with each setting moved one step must mostly (2 in 3) still make money -- a real edge is
     a plateau, not a lucky peak;
  3. the vault VAULT_FROM..latest, never seen before: tested ONCE per idea, ever (ledger), and the neighbours of an idea
     that failed it are barred from it; it must make money there too.
Survivors get a "normal range" from their daily profits (a bad 20-session stretch at the 5% level, the longest losing
run), which the dashboard shows and the coming switch-off rule (step 4) will use.

State (private repo): state/bot/ledger.json (every idea tested, its stage and figures), state/bot/report.json (counts,
recommendations, near misses) for the dashboard (relay adminBotReport).

Runs on market-hub-trader (infra/trader/research.timer: 18:40 IST on weekdays, 10:00 at weekends), never in market
hours, until its time budget (RESEARCH_MINUTES) runs out; the next run carries on from the ledger.
    python -m trader.research [--minutes 120] [--max 50] [--no-ai] [--dry]
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import random
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

from hub.expiry_history import load, save

from .replay import COST_VERSION
from .strategies.rules import clean

IST = timezone(timedelta(hours=5, minutes=30))
DEV_FROM, DEV_TO, VAULT_FROM = "2024-12-01", "2026-04-30", "2026-05-01"
PRE_FROM, PRE_TO = "2024-01-01", "2024-11-19"
# Rule changes the bot must respect (owner, 14 Nov 2026). The development period starts after the first. The last
# (SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/23843/2026 of 15 Oct 2026, paras 4.2.4 and 4.9.1, in force Mon 7 Dec
# 2026; read from SEBI's own PDF 14 Nov 2026): index options trade to 15:45 on normal days, to 15:30 on their
# expiry day, and expiring contracts settle at a price built from the cash market's last 30 minutes (15:00-15:30)
# instead of the closing price. No history exists after it yet, so an idea whose trades are alive in that last half
# hour of an expiry day, or held to settlement, is "on probation" until POST_RULE_MIN sessions after it show it still
# makes money; every recommendation is re-checked on the sessions after it as they arrive.
RULE_CHANGES = [("2024-11-20", "SEBI F&O rules: one weekly expiry per exchange, bigger lots, extra expiry-day margin"),
                ("2026-08-03", "Closing auction in the cash market; expiry settled on the auction's closing prices (SEBI "
                               "circular 16 Jan 2026, in force 3 Aug 2026 per SEBI's annual report)"),
                ("2026-12-07", "Index options trade to 15:45 (15:30 on expiry day); expiry settles on the 15:00-15:30 "
                               "average price, not the close")]
SETTLE_RULE_FROM = "2026-12-07"
POST_RULE_MIN = 20
LEDGER, REPORT = "state/bot/ledger.json", "state/bot/report.json"
MIN_TRADES, MIN_PF, DAY_LIMIT = 30, 1.2, 10000.0
VAULT_MIN_TRADES = 8


def bar(n_tested: int) -> float:
    """The t-statistic an idea must reach, higher the more ideas have been tried (10 -> 2.0, 100 -> 2.5, 1000 -> 3.0)."""
    return 1.5 + 0.5 * math.log10(max(n_tested, 10))


def market_hours(now: datetime) -> bool:
    from .session import busy_until
    return now.weekday() < 5 and "09:05" <= now.strftime("%H:%M") <= busy_until(now.date())


# ---- ideas -------------------------------------------------------------------------------------------------------
def base(name: str, index: str = "NIFTY") -> dict:
    return {"name": name, "index": index, "lots": 1, "expiry": "nearest", "side": "BUY", "right": "C",
            "strike": {"mode": "atm", "steps": 0}, "window": {"from": "09:30", "until": "14:30"},
            "groups_match": "any", "style": "intraday", "max_trades_day": 1, "max_loss_day": 0, "reentry_gap": 15,
            "exits": {"sl_type": "pct", "sl": 50, "target_type": "pct", "target": 50, "trail_after_type": "pct",
                      "trail_after": 0, "trail_type": "pct", "trail": 0, "exit_by": "15:15"}}


def val(src, op, v):
    return {"type": "compare", "left": {"src": src}, "op": op, "right": {"src": "value", "value": v}, "tf": 5}


def plus(t: str, minutes: int) -> str:
    h, m = map(int, t.split(":"))
    m = h * 60 + m + minutes
    return f"{m // 60:02d}:{m % 60:02d}"


def f_vol_condor(p):
    d = base(f"IV-rich iron condor (IV pct >= {p['ivp']}, {p['dte']}d)")
    d["structure"] = {"kind": "iron_condor", "side": "SELL", "width": p["width"], "wing": p["wing"]}
    sig = [val("iv_pct", ">=", p["ivp"]), {"type": "dte", "op": "<=", "days": p["dte"]},
           {"type": "event", "when": "not_today", "kinds": ["rbi", "budget", "election"]}]
    if p["vix_cap"]:
        sig.append(val("vix_pct", "<", p["vix_cap"]))
    d["groups"] = [{"match": "all", "signals": sig}]
    d["window"] = {"from": p["entry"], "until": plus(p["entry"], 10)}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


def f_expiry_strangle(p):
    d = base(f"Expiry-day short strangle ({p['width']} out, {p['entry']})")
    d["structure"] = {"kind": "strangle", "side": "SELL", "width": p["width"]}
    d["groups"] = [{"match": "all", "signals": [{"type": "dte", "op": "<=", "days": 0},
                                                {"type": "event", "when": "not_today", "kinds": ["rbi", "budget", "election"]}]}]
    d["window"] = {"from": p["entry"], "until": plus(p["entry"], 10)}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


def f_gap_fade(p):
    up = p["dir"] == "down"                    # a gap down that recovers -> buy calls; a gap up that fades -> buy puts
    d = base(f"Gap {'down' if up else 'up'} {p['gap']}% fades ({'spread' if p['spread'] else 'option'})")
    gap = {"type": "change", "from": "prev_close", "op": "below" if up else "above", "pct": -p["gap"] if up else p["gap"]}
    back = {"type": "compare", "left": {"src": "close"}, "op": ">" if up else "<", "right": {"src": "day_open"}, "tf": 5}
    d["groups"] = [{"match": "all", "signals": [gap, back]}]
    d["window"] = {"from": "09:30", "until": "11:30"}
    if p["spread"]:
        d["structure"] = {"kind": "spread", "side": "BUY", "right": "C" if up else "P", "width": 0, "wing": p["spread"]}
    else:
        d["right"] = "C" if up else "P"
    d["exits"].update(sl=p["sl"], target=p["target"], exit_by=p["exit_by"])
    return d


def f_trend_orb(p):
    up = p["dir"] == "up"
    d = base(f"Trend day: {p['minutes']}-min range break {'up' if up else 'down'}, ADX > {p['adx']}")
    d["groups"] = [{"match": "all", "signals": [{"type": "orb", "minutes": p["minutes"], "dir": p["dir"]},
                                                {"type": "compare", "left": {"src": "adx", "n": 14}, "op": ">",
                                                 "right": {"src": "value", "value": p["adx"]}, "tf": 5}]}]
    d["window"] = {"from": plus("09:15", p["minutes"]), "until": "13:30"}
    d["structure"] = {"kind": "spread", "side": "BUY", "right": "C" if up else "P", "width": 0, "wing": p["wing"]}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


def f_cheap_straddle(p):
    d = base(f"Cheap-volatility long straddle (IV pct <= {p['ivp']})")
    d["structure"] = {"kind": "straddle", "side": "BUY"}
    d["groups"] = [{"match": "all", "signals": [val("iv_pct", "<=", p["ivp"]), {"type": "dte", "op": ">=", "days": p["dte"]}]}]
    d["window"] = {"from": p["entry"], "until": plus(p["entry"], 10)}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


def f_fii_bear(p):
    d = base(f"FIIs heavily short: put spread (FII futures <= {p['fii']}%)")
    d["structure"] = {"kind": "spread", "side": "BUY", "right": "P", "width": 0, "wing": p["wing"]}
    d["groups"] = [{"match": "all", "signals": [val("fii_fut", "<=", p["fii"]),
                                                {"type": "change", "from": "prev_close", "op": "below", "pct": -p["drop"]}]}]
    d["window"] = {"from": "09:45", "until": "12:00"}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


def f_pcr_put_sell(p):
    d = base(f"High put-call ratio: bull put spread (PCR >= {p['pcr']})")
    d["structure"] = {"kind": "spread", "side": "SELL", "right": "P", "width": p["width"], "wing": p["wing"]}
    d["groups"] = [{"match": "all", "signals": [val("pcr", ">=", p["pcr"]), {"type": "dte", "op": "<=", "days": 3}]}]
    d["window"] = {"from": "10:00", "until": "10:10"}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


def f_flows_follow(p):
    up = p["dir"] == "up"
    d = base(f"Follow FII cash and the US close ({'up' if up else 'down'}, FII {'>=' if up else '<='} {p['fii']} cr)")
    d["groups"] = [{"match": "all", "signals": [val("fii_cash", ">=" if up else "<=", p["fii"] if up else -p["fii"]),
                                                val("sp500_chg", ">" if up else "<", 0),
                                                {"type": "change", "from": "open", "op": "above" if up else "below",
                                                 "pct": p["confirm"] if up else -p["confirm"]}]}]
    d["window"] = {"from": "09:45", "until": "11:30"}
    d["structure"] = {"kind": "spread", "side": "BUY", "right": "C" if up else "P", "width": 0, "wing": p["wing"]}
    d["exits"].update(sl=p["sl"], target=p["target"])
    return d


FAMILIES = {
    "vol_condor": ("Option buyers overpay for insurance: implied volatility is usually above the movement that follows. "
                   "Selling a hedged iron condor when volatility is rich collects that premium near expiry.",
                   f_vol_condor, {"ivp": [40, 60, 75], "dte": [1, 2, 3], "width": [2, 3, 4], "wing": [2, 4],
                                  "entry": ["09:45", "11:00", "13:00"], "target": [40, 60], "sl": [100, 150],
                                  "vix_cap": [0, 90]}),
    "expiry_strangle": ("Time decay is fastest on expiry day: out-of-the-money options lose most of what is left by the "
                        "close, so sellers are paid for the hours of risk.",
                        f_expiry_strangle, {"width": [2, 3, 4, 6], "entry": ["10:00", "11:30", "13:00"],
                                            "target": [50, 70], "sl": [50, 100]}),
    "gap_fade": ("Large opening gaps often partly reverse once the overnight orders are absorbed.",
                 f_gap_fade, {"dir": ["down", "up"], "gap": [0.5, 0.8, 1.2], "spread": [0, 2, 4],
                              "target": [50, 100], "sl": [30, 50], "exit_by": ["13:30", "15:15"]}),
    "trend_orb": ("On trend days a break of the opening range tends to continue; a debit spread pays for direction with "
                  "less time decay than a single option.",
                  f_trend_orb, {"dir": ["up", "down"], "minutes": [15, 30], "adx": [20, 25, 30], "wing": [2, 4],
                                "target": [50, 100], "sl": [40, 60]}),
    "cheap_straddle": ("When implied volatility is unusually low, a big move is under-priced, so owning both sides can "
                       "pay.", f_cheap_straddle, {"ivp": [10, 20, 30], "dte": [2, 4], "entry": ["09:30", "11:00"],
                                                   "target": [20, 40], "sl": [25, 40]}),
    "fii_bear": ("Foreign institutions are the best-informed large traders; heavy net shorts in index futures often "
                 "come before weakness.", f_fii_bear, {"fii": [-20, -35, -50], "drop": [0.2, 0.5], "wing": [2, 4],
                                                        "target": [50, 100], "sl": [40, 60]}),
    "pcr_put_sell": ("A very high put-call ratio means heavy put writing: sellers defend those strikes, which act as "
                     "support near expiry.", f_pcr_put_sell, {"pcr": [1.1, 1.3, 1.5], "width": [1, 2, 3],
                                                              "wing": [2, 3], "target": [50, 70], "sl": [100, 150]}),
    "flows_follow": ("Large foreign buying or selling in the cash market, with Wall Street agreeing overnight, tends to "
                     "carry into the next morning.", f_flows_follow, {"dir": ["up", "down"], "fii": [1000, 2500, 4000],
                                                                      "confirm": [0.1, 0.3], "wing": [2, 4],
                                                                      "target": [50, 100], "sl": [40, 60]}),
}
# Families that need data the market diary started keeping on 14 Nov 2026 (hub/market_daily.py flows; being filled in
# back to 2023): tested only once that data covers NEEDS_COVER of the development period's sessions.
NEEDS = {"flows_follow": ("fii_cash", "sp500_chg"), "vol_condor": ("iv_pct", "vix_pct"),
         "cheap_straddle": ("iv_pct",), "fii_bear": ("fii_fut",), "pcr_put_sell": ("pcr",)}
NEEDS_COVER = 0.8
INDICES = ("NIFTY", "BANKNIFTY")


def build(fam: str, p: dict) -> dict:
    """One idea from its family and settings, on NIFTY or BANK NIFTY (BANK NIFTY: monthly expiries only)."""
    d = FAMILIES[fam][1](p)
    d["index"] = p.get("index", "NIFTY")
    if d["index"] == "BANKNIFTY":
        d["name"] += " · BANK NIFTY"
    return d


def key_of(defn: dict) -> str:
    """Identity of an idea: its cleaned settings, without the name or ids."""
    d = clean(dict(defn, id="x"))
    for k in ("id", "name"):
        d.pop(k, None)
    return hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:12]


def grid_points(grid: dict) -> list[dict]:
    keys = sorted(grid)
    return [dict(zip(keys, vs)) for vs in itertools.product(*(grid[k] for k in keys))]


def neighbours(fam: str, p: dict, k: int = 4) -> list[dict]:
    """The same idea with one setting moved one step along its grid (up to k of them, chosen at random)."""
    grid = dict(FAMILIES[fam][2])
    out = []
    for name, vals in grid.items():
        i = vals.index(p[name])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                out.append(dict(p, **{name: vals[j]}))
    random.shuffle(out)
    return out[:k]


def ai_neighbours(defn: dict, k: int = 4) -> list[dict]:
    """For an idea with no grid (from Gemini): stop and target 25% either way, the entry window 30 minutes later."""
    out = []
    for f, key in ((0.75, "sl"), (1.25, "sl"), (0.75, "target"), (1.25, "target")):
        x = json.loads(json.dumps(defn))
        if x["exits"].get(key):
            x["exits"][key] = round(x["exits"][key] * f, 1)
            out.append(x)
    x = json.loads(json.dumps(defn))
    w = x.get("window") or {}
    if w.get("from") and w.get("until") and plus(w["until"], 30) <= "15:00":
        x["window"] = {"from": plus(w["from"], 30), "until": plus(w["until"], 30)}
        out.append(x)
    return out[:k]


# ---- testing -----------------------------------------------------------------------------------------------------
def run_bt(defn: dict, frm: str, until: str | None) -> dict:
    from .backtest import backtest
    d = dict(defn, id="s_bot" + key_of(defn)[:8], **{"from": frm})
    if until:
        d["until"] = until
    else:
        d.pop("until", None)
    res = backtest(d, {"max_lots_per_order": 5, "max_daily_loss": DAY_LIMIT}, progress=lambda m: None)
    days = [(x["date"], x["pnl"]) for x in res["summary"].get("days") or []]
    t = res["summary"]["totals"]
    return {"days": days, "trades": t["trades"], "wins": t["wins"], "profit": round(t["booked"], 2),
            "sessions": res["coverage"]["sessions"], "note": res.get("note")}


def stats(r: dict) -> dict:
    pnl = [p for _, p in r["days"]]
    gains, losses = sum(p for p in pnl if p > 0), -sum(p for p in pnl if p < 0)
    n = len(pnl)
    sd = statistics.pstdev(pnl) if n > 1 else 0.0
    t = (statistics.mean(pnl) / sd * math.sqrt(n)) if sd > 0 else 0.0
    best5 = sum(sorted(pnl, reverse=True)[:5])
    half = n // 2
    return {"trades": r["trades"], "wins": r["wins"], "profit": round(sum(pnl), 2),
            "pf": round(gains / losses, 2) if losses else (99.0 if gains else 0.0), "t": round(t, 2),
            "without_best5": round(sum(pnl) - best5, 2), "first_half": round(sum(pnl[:half]), 2),
            "second_half": round(sum(pnl[half:]), 2), "worst_day": round(min(pnl), 2) if pnl else 0.0, "days": n}


def dev_verdict(s: dict, n_tested: int) -> str:
    """Empty when the development tests pass; else the first reason it failed, in words."""
    if s["trades"] < MIN_TRADES:
        return f"only {s['trades']} trades (need {MIN_TRADES})"
    if s["profit"] <= 0:
        return f"lost money after charges (₹{s['profit']:,.0f})"
    if s["pf"] < MIN_PF:
        return f"profit factor {s['pf']} (need {MIN_PF})"
    if s["without_best5"] <= 0:
        return "the profit came from its 5 best days"
    if s["first_half"] <= 0 or s["second_half"] <= 0:
        return "lost money in one half of the period"
    if s["worst_day"] < -DAY_LIMIT:
        return f"a day lost ₹{-s['worst_day']:,.0f} (limit ₹{DAY_LIMIT:,.0f})"
    if s["t"] < bar(n_tested):
        return f"not clearly better than luck (t {s['t']}, need {bar(n_tested):.2f} after {n_tested} ideas)"
    return ""


def normal_range(days: list[float], draws: int = 2000) -> dict:
    """From the daily profits: a bad 20-session stretch (5% level, by resampling), the typical 20 sessions, the longest
    run of losing days -- what 'normal' looks like, for judging the paper results later."""
    if len(days) < 10:
        return {}
    rnd = random.Random(7)
    sums = sorted(sum(rnd.choice(days) for _ in range(20)) for _ in range(draws))
    run = worst = 0
    for p in days:
        run = run + 1 if p < 0 else 0
        worst = max(worst, run)
    return {"bad_20": round(sums[int(0.05 * draws)], 0), "typical_20": round(sums[draws // 2], 0),
            "longest_losing_run": worst}


# ---- Gemini ideas ------------------------------------------------------------------------------------------------
AI_SYSTEM = """You propose intraday NIFTY / BANKNIFTY index-option strategies for a back-tester. Answer with JSON only:
{"ideas": [{"why": "who pays us and why, one or two plain sentences", "strategy": S}, ...]} with at most 3 ideas.
Each idea must rest on a real reason someone pays (insurance premium / volatility risk premium, time decay, event
volatility crush, order-flow reversal after gaps, trend continuation, positioning of large players) -- no pure
indicator fishing. Ideas must differ from the ones already tested (listed by name).
S = {"name", "index":"NIFTY"|"BANKNIFTY", "lots":1, "expiry":"nearest", "side":"BUY"|"SELL", "right":"C"|"P",
 "strike":{"mode":"atm","steps":k}, "structure": {"kind":"straddle"|"strangle"|"iron_condor"|"spread","side":"SELL"|"BUY",
 "width":n,"wing":n,"right":"C"|"P"} (omit for a single option), "window":{"from":"HH:MM","until":"HH:MM"},
 "groups":[{"match":"all","signals":[SIG...]}], "groups_match":"any", "style":"intraday", "max_trades_day":1,
 "exits":{"sl_type":"pct","sl":x,"target_type":"pct","target":x,"trail":0,"exit_by":"HH:MM"}}
 (with a structure, sl / target are % of the premium of the whole position).
SIG = {"type":"compare","left":{"src":A},"op":">"|"<"|">="|"<=","right":{"src":"value","value":x},"tf":5} where A is one
 of: price, day_open, prev_close, chg_prev, chg_open, rsi (with "n"), adx (with "n"), ema (with "n"), atr (with "n"),
 dte, vix, vix_pct, iv, iv_pct, pcr, pcr_all, oi_chg, fii_fut, fii_call, fii_put, client_fut, pro_fut, fii_cash,
 sp500_chg, nasdaq_chg, usdinr_chg (official figures only, the previous session's; shares in %, negative = net short;
 cash flows in rupees crore). No news or sentiment inputs.
 | {"type":"dte","op":"<="|">=","days":n} | {"type":"orb","minutes":15|30,"dir":"up"|"down"}
 | {"type":"change","from":"prev_close"|"open","op":"above"|"below","pct":x}
 | {"type":"event","when":"today"|"not_today","kinds":["rbi","budget","election"]}
 | {"type":"supertrend","period":10,"mult":3,"tf":5,"dir":"buy"|"sell"|"up"|"down"}
Data: Dec 2024 - Apr 2026 for testing; NIFTY strikes are 50 apart, BANKNIFTY 100 (BANKNIFTY has monthly expiries only).
Rules: from 7 Dec 2026 index options trade to 15:45 on normal days and to 15:30 on their expiry day, and expiring
contracts settle on the average price of 15:00-15:30 (no longer the close). Ideas that depend on the closing minutes of
an expiry day or on settlement at the close will behave differently after that date: prefer ideas that do not, and
say so in "why" when one does."""


def relay_ask(system: str, prompt: str) -> dict | None:
    import requests
    url, key = os.getenv("RELAY_URL"), os.getenv("RELAY_KEY")
    if not url or not key:
        return None
    try:
        r = requests.post(url, params={"mode": "bot_ask", "key": key}, data=json.dumps({"system": system, "prompt": prompt}),
                          timeout=330)
        out = r.json()
        return json.loads(out["text"]) if out.get("text") else None
    except Exception:                                            # noqa: BLE001 -- no ideas this run
        return None


def ai_ideas(ledger: dict) -> list[tuple[str, dict, str]]:
    rows = sorted(ledger.values(), key=lambda r: -((r.get("dev") or {}).get("profit") or -1e9))
    lines = [f"- {r['name']}: {r['stage']}" + (f" ({r['dev']['trades']} trades, ₹{r['dev']['profit']:,.0f}, t {r['dev']['t']})"
                                                   if r.get("dev") else f" ({r.get('why_failed', '')})") for r in rows[:40]]
    prompt = "Ideas tested so far (best first):\n" + ("\n".join(lines) or "none yet") + "\n\nPropose up to 3 new ideas."
    got = relay_ask(AI_SYSTEM, prompt) or {}
    out = []
    for x in (got.get("ideas") or [])[:3]:
        s, why = x.get("strategy"), str(x.get("why") or "").strip()
        if not isinstance(s, dict) or len(why) < 20:
            continue
        s = dict(s, name=str(s.get("name") or "AI idea")[:70], lots=1, max_trades_day=min(int(s.get("max_trades_day") or 1), 3))
        try:
            c = clean(dict(s, id="x"))
        except Exception:                                        # noqa: BLE001
            continue
        if not c["groups"]:
            continue
        out.append(("ai", s, why[:400]))
    return out


# ---- the loop ----------------------------------------------------------------------------------------------------
def needs_of(defn: dict) -> tuple:
    """The market figures an idea reads (compare signals on either side)."""
    from .market import MARKET
    sig = [x for g in (defn.get("groups") or []) + (defn.get("put_groups") or []) for x in g.get("signals") or []]
    return tuple(sorted({o.get("src") for x in sig if x.get("type") == "compare" for o in (x.get("left") or {}, x.get("right") or {})}
                        & set(MARKET)))


def coverage(fam: str, mkt, sessions: list, need: tuple | None = None) -> float:
    """Share of the development period's sessions whose figures (as a strategy would read them that morning, on NIFTY)
    include everything the family needs; 1.0 when it needs none. Below NEEDS_COVER the family waits, so half-filled
    history can never reject an idea for good."""
    need = need if need is not None else NEEDS.get(fam)
    if not need:
        return 1.0
    if not sessions:
        return 0.0
    return sum(1 for d in sessions if all(mkt.prev("NIFTY", d).get(k) is not None for k in need)) / len(sessions)


def candidates(ledger: dict, rnd: random.Random, n: int, ready: set) -> list[tuple[str, dict, dict | None, str]]:
    """Untested grid points (each on NIFTY and BANK NIFTY), round-robin across the families that have their data."""
    per = {}
    for fam, (why, fn, grid) in FAMILIES.items():
        if fam not in ready:
            continue
        pts = [dict(q, index=ix) for q in grid_points(grid) for ix in INDICES]
        rnd.shuffle(pts)
        per[fam] = [(fam, build(fam, p), p, why) for p in pts]
    out, fams = [], list(per)
    while len(out) < n and any(per.values()):
        for fam in fams:
            while per[fam]:
                fam_, d, p, why = per[fam].pop()
                kd = key_of(d)
                if kd not in ledger or ledger[kd].get("cost") != COST_VERSION:
                    out.append((fam_, d, p, why))
                    break
            if len(out) >= n:
                break
    return out


def evaluate(fam: str, defn: dict, p: dict | None, why: str, ledger: dict, deadline: float, log=print) -> dict:
    k = key_of(defn)
    rec = {"key": k, "family": fam, "name": defn["name"], "why": why, "params": p, "cost": COST_VERSION,
           "tested": datetime.now(IST).isoformat(timespec="minutes")}
    if k in ledger:                      # tested before under an older cost setting: kept for the record
        old = ledger[k]
        rec["earlier"] = (old.get("earlier") or []) + [{x: old.get(x) for x in ("stage", "why_failed", "dev", "tested", "cost")}]
    # every test ever run counts towards the luck bar, earlier cost settings included
    n_tested = len(ledger) + sum(len(r.get("earlier") or []) for r in ledger.values()) + 1
    dev = run_bt(defn, DEV_FROM, DEV_TO)
    s = stats(dev)
    rec["dev"] = s
    if dev.get("note"):
        rec["note"] = dev["note"]
    fail = dev_verdict(s, n_tested)
    if fail:
        rec.update(stage="failed development", why_failed=fail)
        return rec
    # neighbours (a plateau, not a peak)
    nbs = [build(fam, q) for q in neighbours(fam, p)] if p and fam in FAMILIES else ai_neighbours(defn)
    good, tried = 0, 0
    for nd in nbs:
        if time.time() > deadline:
            rec.update(stage="paused", why_failed="time ran out during the neighbour tests")
            return rec
        r = stats(run_bt(nd, DEV_FROM, DEV_TO))
        tried += 1
        good += r["profit"] > 0 and r["trades"] >= MIN_TRADES // 2
    rec["neighbours"] = {"tried": tried, "profitable": good}
    if tried and good * 3 < tried * 2:
        rec.update(stage="failed neighbours", why_failed=f"only {good} of {tried} nearby settings made money")
        return rec
    # before SEBI's Nov 2024 rules (shown on the card; the market worked differently, so not a pass / fail)
    try:
        rec["pre_rule"] = stats(run_bt(defn, PRE_FROM, PRE_TO))
    except Exception:                                            # noqa: BLE001
        pass
    # the vault: once, ever
    barred = {x for r in ledger.values() for x in r.get("bars", [])}
    if k in barred:
        rec.update(stage="barred from the vault", why_failed="a near-identical idea already failed the unseen months")
        return rec
    v = run_bt(defn, VAULT_FROM, None)
    vs = stats(v)
    rec["vault"] = vs
    if vs["trades"] < VAULT_MIN_TRADES or vs["profit"] <= 0 or vs["pf"] < 1.1:
        rec.update(stage="failed the unseen months",
                   why_failed=f"unseen months: {vs['trades']} trades, ₹{vs['profit']:,.0f}, profit factor {vs['pf']}")
        rec["bars"] = [key_of(nd) for nd in nbs]
        return rec
    rec["stage"] = "recommended"
    rec["settle_sensitive"] = settle_sensitive(defn)
    rec["probation"] = rec["settle_sensitive"]                  # until POST_RULE_MIN sessions after 7 Dec 2026
    rec["normal"] = normal_range([x for _, x in dev["days"]] + [x for _, x in v["days"]])
    rec["strategy"] = {k2: v2 for k2, v2 in defn.items() if k2 not in ("id", "from", "until")}
    return rec


def recheck(ledger: dict, deadline: float, log=print) -> None:
    """Each run, every recommended idea is run again on the months since VAULT_FROM, which grow with every recorded
    session (IBKR each evening, ICICI back-fills): its figures there are updated, and it is marked fading when they
    turn to a loss. This is a health check, not a second chance: a fading idea stays marked until it recovers."""
    for r in ledger.values():
        if r.get("stage") != "recommended" or time.time() > deadline:
            continue
        try:
            v = stats(run_bt(r["strategy"], VAULT_FROM, None))
        except Exception:                                        # noqa: BLE001
            continue
        r["vault_now"], r["fading"] = v, v["profit"] <= 0
        r["checked"] = datetime.now(IST).isoformat(timespec="minutes")
        try:
            post = stats(run_bt(r["strategy"], SETTLE_RULE_FROM, None))
        except Exception:                                        # noqa: BLE001 -- no sessions after it yet
            post = None
        if post and post["days"]:
            r["after_rules"] = post
            if post["days"] >= POST_RULE_MIN and post["profit"] <= 0:
                r["fading"] = True
        r["probation"] = bool(r.get("settle_sensitive")) and not (post and post["days"] >= POST_RULE_MIN and post["profit"] > 0)
        log(f"  recheck: {r['name']} -- {v['trades']} trades, ₹{v['profit']:,.0f}{' (fading)' if r['fading'] else ''}")


def _weekdays(a: str, b: str) -> list[str]:
    d, end, out = date.fromisoformat(a), date.fromisoformat(b), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def settle_sensitive(defn: dict) -> bool:
    """Trades still open in the last half hour of an expiry day, or held to settlement: what the 7 Dec 2026 rules change."""
    st = clean(dict(defn, id="x"))
    if st["style"] == "carry":
        return True
    sig = [x for g in st["groups"] + st["put_groups"] for x in g["signals"]]
    on_expiry = any(x.get("type") == "dte" and x.get("op", "<=") == "<=" and int(x.get("days", 9)) <= 0 for x in sig) or \
        not any(x.get("type") == "dte" for x in sig)
    return on_expiry and (st["exits"].get("exit_by") or "15:30") > "15:00"


def report(ledger: dict, waiting: dict | None = None) -> dict:
    rows = list(ledger.values())
    stages = {}
    for r in rows:
        stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    rec = sorted((r for r in rows if r["stage"] == "recommended"), key=lambda r: -r["vault"]["profit"])
    near = sorted((r for r in rows if r["stage"] in ("failed the unseen months", "failed neighbours")),
                  key=lambda r: -r["dev"]["profit"])[:5]
    fams = {}
    for r in rows:
        f = fams.setdefault(r["family"], {"tested": 0, "passed_dev": 0, "recommended": 0})
        f["tested"] += 1
        f["passed_dev"] += r["stage"] not in ("failed development",)
        f["recommended"] += r["stage"] == "recommended"
    tries = len(rows) + sum(len(r.get("earlier") or []) for r in rows)
    return {"asof": datetime.now(IST).isoformat(timespec="minutes"), "tested": len(rows), "tries": tries, "stages": stages,
            "bar": round(bar(tries), 2), "cost": {"slip_pct": 0.5, "slip_min": 0.10, "version": COST_VERSION}, "periods": {"dev": [DEV_FROM, DEV_TO], "vault_from": VAULT_FROM},
            "families": fams, "recommended": rec, "near_misses": near, "waiting": waiting or {},
            "rule_changes": [{"from": d, "what": w} for d, w in RULE_CHANGES], "post_rule_min": POST_RULE_MIN}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=float(os.getenv("RESEARCH_MINUTES") or 120))
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--no-ai", action="store_true")
    ap.add_argument("--dry", action="store_true", help="do not save to the private repo")
    a = ap.parse_args()
    t0 = time.time()
    deadline = t0 + a.minutes * 60
    ledger = load(LEDGER) or {}
    rnd = random.Random(int(t0))
    from .market import Market
    table = load("state/market/daily.json") or {}
    mkt = Market(table, load("state/market/flows.json") or {})
    sessions = [d for d in sorted(set(k for k in table) | set(_weekdays(DEV_FROM, DEV_TO)))
                if DEV_FROM <= d <= DEV_TO and not (table.get(d) or {}).get("holiday") and date.fromisoformat(d).weekday() < 5]
    cover = {f: coverage(f, mkt, sessions) for f in FAMILIES}
    ready = {f for f, c in cover.items() if c >= NEEDS_COVER}
    waiting = {f: round(100 * c) for f, c in cover.items() if f not in ready}
    if waiting:
        print("waiting for data (% of the development period covered): " + ", ".join(f"{f} {c}%" for f, c in waiting.items()))
    recheck(ledger, deadline)
    queue = candidates(ledger, rnd, a.max, ready)
    if not a.no_ai:
        for f, d, w in ai_ideas(ledger):
            c = coverage("ai", mkt, sessions, needs_of(d))
            if c >= NEEDS_COVER:
                queue.insert(0, (f, d, None, w))
            else:
                print(f"  later: Gemini idea '{d.get('name')}' needs figures covering only {100 * c:.0f}% of the period yet")
    print(f"research: {len(ledger)} ideas in the ledger; {len(queue)} to try; {a.minutes:.0f} minutes", flush=True)
    done = 0
    for fam, d, p, why in queue:
        if time.time() > deadline or market_hours(datetime.now(IST)):
            break
        if key_of(d) in ledger and ledger[key_of(d)].get("cost") == COST_VERSION:
            continue
        t1 = time.time()
        try:
            rec = evaluate(fam, d, p, why, ledger, deadline)
        except Exception as exc:                                 # noqa: BLE001 -- one broken idea never stops the run
            rec = {"key": key_of(d), "family": fam, "name": d.get("name"), "why": why, "stage": "error",
                   "why_failed": str(exc)[:200], "tested": datetime.now(IST).isoformat(timespec="minutes")}
        if rec["stage"] == "paused":
            break
        ledger[rec["key"]] = rec
        done += 1
        dv = rec.get("dev") or {}
        print(f"  {rec['stage']}: {rec['name']} -- {dv.get('trades', '-')} trades, ₹{dv.get('profit', 0):,.0f}, "
              f"t {dv.get('t', '-')}; {rec.get('why_failed', '')} ({time.time() - t1:.0f} s)", flush=True)
        if not a.dry and done % 5 == 0:
            save(LEDGER, ledger, f"Research bot: {len(ledger)} ideas tested")
    rep = report(ledger, waiting)
    if not a.dry:
        save(LEDGER, ledger, f"Research bot: {len(ledger)} ideas tested")
        save(REPORT, rep, f"Research bot: {rep['stages'].get('recommended', 0)} recommended of {rep['tested']}")
    print(f"research: {done} ideas this run, {rep['tested']} in all; {rep['stages']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
