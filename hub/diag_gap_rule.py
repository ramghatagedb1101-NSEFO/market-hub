"""
Gap-follow rule review (13 Nov 2026, owner: "ok do it" + "reviewed like a professional grade institutional expert").
Research only: nothing here places an order. Run on GitHub with diag.yml (needs the day's Kite token):
    gh workflow run diag.yml -f module=diag_gap_rule

The earlier GIFT test (diag_gift_open.py) found the 09:00 GIFT Nifty move still says something about NIFTY/SENSEX after
the open, and nothing after 09:30. This turns that into fixed, tradeable rules and judges them like hub/rule_review.py:

  signal at 09:00   g = log(GIFT 09:00 / GIFT 15:30 the day before)
  entry E           09:20 or 09:30 (end of Kite's 5-minute bar; nothing earlier is a price you could be sure to get)
  rule "follow"     trade in the direction of g when |g| >= threshold
  rule "leftover"   trade in the direction of g - log(level at E / previous close) -- what GIFT said that the index has
                    not done yet -- when that is >= threshold
  exit X            09:45, 10:30 or 15:15
  instrument        index futures, 1 lot (NIFTY 65, BANKNIFTY 30, SENSEX 20); priced off the index (the futures premium
                    barely moves within a day)
  costs             Zerodha futures: brokerage min(Rs 20, 0.03%) a side, STT 0.02% on the sell side, exchange 0.00173%,
                    stamp 0.002% on the buy, SEBI Rs 10 a crore, 18% GST; slippage 0.01% a side (also shown at 0 and 2x)
  margin            about 12% of the contract value (SPAN + exposure; check Kite's calculator before any live use)

Judged by: walk-forward choice of settings, halves, years, t-statistic against the bar for the number of settings tried,
bootstrap 95% range, tail risk, neighbouring settings, slippage. Results go ONLY to the private repo
(state/rule_test/gap_review.json): this repo's Actions logs are public, so nothing but a one-line status is printed.
"""
import math
from datetime import datetime, timedelta

from . import config
from .diag_gift import _candles
from .expiry_history import save
from .rule_review import evidence, tail
from .sources import kite

IDX = {"NIFTY": ("NSE", "NIFTY 50"), "BANKNIFTY": ("NSE", "NIFTY BANK"), "SENSEX": ("BSE", "SENSEX")}
LOT = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}
ENTRIES = [9 * 60 + 20, 9 * 60 + 30]
EXITS = [9 * 60 + 45, 10 * 60 + 30, 15 * 60 + 15]
THRESH = [0.0, 0.002, 0.004]
RULES = ["follow", "leftover"]
TRIALS = len(ENTRIES) * len(EXITS) * len(THRESH) * len(RULES)
T_BAR = math.sqrt(2 * math.log(TRIALS))
SLIP = 0.0001
MARGIN = 0.12
MIN_PAST = 120


def cost(entry: float, exit_: float, qty: int, buy_first: bool, slip_mult: float) -> float:
    t_in, t_out = entry * qty, exit_ * qty
    buy, sell = (t_in, t_out) if buy_first else (t_out, t_in)
    brk = min(20, 0.0003 * t_in) + min(20, 0.0003 * t_out)
    txn = 0.0000173 * (t_in + t_out)
    sebi = 0.000001 * (t_in + t_out)
    return brk + txn + sebi + 0.0002 * sell + 0.00002 * buy + 0.18 * (brk + txn + sebi) + slip_mult * SLIP * (t_in + t_out)


def days_for(k, name, start, end, gift):
    ex, sym = IDX[name]
    tok = kite.instrument_token(k, ex, sym)
    daily = [(c["date"].date().isoformat(), float(c["close"])) for c in _candles(k, tok, "day", start, end, 1900)]
    five = {}
    for c in _candles(k, tok, "5minute", start, end, 95):
        t = c["date"].astimezone(config.IST)
        five.setdefault(t.date().isoformat(), {})[t.hour * 60 + t.minute + 5] = float(c["close"])
    out = []
    for i in range(1, len(daily)):
        (pd, pc), (td, _) = daily[i - 1], daily[i]
        a, b = gift(pd, 15 * 60 + 30), gift(td, 9 * 60)
        bars = five.get(td) or {}
        if not (a and b and bars):
            continue
        out.append({"day": td, "pc": pc, "g": math.log(b / a), "bars": bars})
    return out


def level(bars: dict, m: int):
    xs = [v for mm, v in sorted(bars.items()) if mm <= m]
    return xs[-1] if xs else None


def trade(d: dict, rule: str, e: int, x: int, th: float, qty: int, slip_mult: float = 1.0):
    pe, px = level(d["bars"], e), level(d["bars"], x)
    if not pe or not px:
        return None
    sig = d["g"] if rule == "follow" else d["g"] - math.log(pe / d["pc"])
    if abs(sig) < th or sig == 0:
        return None
    side = 1 if sig > 0 else -1
    pnl = side * (px - pe) * qty - cost(pe, px, qty, side > 0, slip_mult)
    return {"pnl": pnl, "risk": MARGIN * pe * qty, "cost": cost(pe, px, qty, side > 0, slip_mult), "exp": d["day"],
            "move_pct": round(100 * (px / pe - 1), 2)}


def summary(res: list) -> dict:
    p = [r["pnl"] for r in res]
    if not p:
        return {"n": 0}
    mg = sum(r["risk"] for r in res) / len(res)
    return {"n": len(p), "total_rs_per_lot": round(sum(p)), "avg_rs": round(sum(p) / len(p)), "avg_margin_rs": round(mg),
            "return_on_margin_per_trade_pct": round(100 * sum(p) / len(p) / mg, 3),
            "hit_pct": round(100 * sum(1 for x in p if x > 0) / len(p), 1)}


def review(days: list, qty: int) -> dict:
    keys = [(r, e, x, th) for r in RULES for e in ENTRIES for x in EXITS for th in THRESH if x > e]
    grid = {k: [trade(d, *k, qty) for d in days] for k in keys}
    half = len(days) // 2
    settings = []
    for k, res in grid.items():
        got = [r for r in res if r]
        first, second = [r for r in res[:half] if r], [r for r in res[half:] if r]
        ev = dict(evidence([r["pnl"] for r in got]), t_bar=round(T_BAR, 2))
        settings.append({"rule": k[0], "entry": f"{k[1] // 60:02d}:{k[1] % 60:02d}", "exit": f"{k[2] // 60:02d}:{k[2] % 60:02d}",
                         "threshold_pct": k[3] * 100, "all": summary(got), "evidence": ev,
                         "first_half": summary(first), "second_half": summary(second),
                         "slip0": summary([trade(d, *k, qty, 0.0) for d in days if trade(d, *k, qty, 0.0)]),
                         "slip2": summary([trade(d, *k, qty, 2.0) for d in days if trade(d, *k, qty, 2.0)]),
                         "by_year": {y: summary([r for r in got if r["exp"][:4] == y]) for y in sorted({r["exp"][:4] for r in got})},
                         "tail": tail(got)})
    for s in settings:
        ok = (s["evidence"].get("n", 0) >= 60 and (s["first_half"].get("avg_rs") or 0) > 0 and (s["second_half"].get("avg_rs") or 0) > 0
              and (s["slip2"].get("avg_rs") or 0) > 0)
        t = s["evidence"].get("t") or 0
        s["verdict"] = ("CANDIDATE FOR SMALL LIVE SIZE (after paper trading)" if ok and t >= T_BAR else
                        "PAPER: positive out of sample but below the bar for the settings tried" if ok and t >= 2 else
                        "REJECT")
    # walk-forward: each day uses the setting with the best average over earlier days only
    wf = []
    for i in range(MIN_PAST, len(days)):
        best, bv = None, 0.0
        for k, res in grid.items():
            past = [r["pnl"] for r in res[:i] if r]
            if len(past) >= 40 and sum(past) / len(past) > bv:
                best, bv = k, sum(past) / len(past)
        if best and grid[best][i]:
            wf.append(grid[best][i])
    settings.sort(key=lambda s: -(s["evidence"].get("t") or -99))
    return {"days": len(days), "from": days[0]["day"] if days else None, "to": days[-1]["day"] if days else None,
            "trials": len(keys), "t_bar": round(T_BAR, 2), "walk_forward": summary(wf),
            "walk_forward_evidence": dict(evidence([r["pnl"] for r in wf]), t_bar=round(T_BAR, 2)), "walk_forward_tail": tail(wf),
            "top": settings[:8], "all": settings}


def main():
    k = kite.client()
    end = datetime.now(config.IST).date() - timedelta(days=1)
    start = end - timedelta(days=4 * 365)
    bars = {}
    for c in _candles(k, kite.instrument_token(k, "NSEIX", "GIFT NIFTY"), "15minute", start, end, 190):
        t = c["date"].astimezone(config.IST)
        bars.setdefault(t.date().isoformat(), {})[t.hour * 60 + t.minute + 15] = float(c["close"])

    def gift(day, m):
        xs = [v for mm, v in sorted(bars.get(day, {}).items()) if mm <= m]
        return xs[-1] if xs else None

    if len(bars) < 200:      # 13 Nov 2026: a run before the Kite login got no candles and saved an empty review
        raise SystemExit("No GIFT Nifty history from Kite (no login yet today?): nothing saved; run again after the login")
    out = {"made": datetime.now(config.IST).isoformat(timespec="minutes"), "by_index": {}}
    for name in IDX:
        days = days_for(k, name, start, end, gift)
        if len(days) < 250:
            raise SystemExit(f"Only {len(days)} days for {name}: nothing saved")
        out["by_index"][name] = review(days, LOT[name])
    save("state/rule_test/gap_review.json", out, "gap rule review")
    print("saved state/rule_test/gap_review.json (private)")


if __name__ == "__main__":
    main()
