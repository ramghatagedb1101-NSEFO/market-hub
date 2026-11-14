"""
Tests for the trading program on made-up minute prices (no network, no broker). Run from the repo root:
    python -m trader.selftest
"""
import sys

from .journal import Journal
from .model import Contract, OrderRequest, Settings
from .replay import run

R = []
EXP, PREV = "2026-11-03", "2026-11-02"


def ok(name, cond, detail=""):
    R.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))


def candles(path: list[tuple[int, int, float]]) -> list:
    """[(day, minute, price)] -> one-minute candles with that price as open, high, low and close."""
    return [[d, m, p, p, p, p, 100, 1000] for d, m, p in path]


def walk(day: int, start: int, prices: list[float]) -> list:
    return candles([(day, start + i, p) for i, p in enumerate(prices)])


class Script:
    """Sends the given requests at the given (day, minute)."""

    def __init__(self, plan: dict, contracts: set):
        self.plan, self.c, self.sent = plan, contracts, set()

    def wants(self, view):
        return self.c

    def step(self, view):
        key = (0 if view.now.strftime("%Y-%m-%d") == PREV else 1, view.now.hour * 60 + view.now.minute - 555)
        if key in self.plan and key not in self.sent:
            self.sent.add(key)
            return self.plan[key]
        return []


def entry(call: dict, put: dict | None = None) -> dict:
    return {"prev_day": PREV, "expiry": EXP, "call": call, "put": put or {}}


def go(e, plan, contracts, s=None, close=None):
    s = s or Settings(strategy="script", stale_seconds=300)
    j = Journal()
    eng = run("NIFTY", e, close, Script(plan, contracts), s, j)
    return eng, j


C = Contract("NIFTY", EXP, 25000.0, "C")
P = Contract("NIFTY", EXP, 25000.0, "P")
buy = lambda c=C, lots=1, **k: OrderRequest(c, "BUY", lots, None, "test", **k)


def test_stop_hit():
    # buy at minute 30 near 100; price slides to 70 -> the 25% stop (about 76.5 on a 102 fill) fires
    e = entry({"25000": walk(0, 30, [100, 98, 95, 90, 85, 80, 75, 70, 65])})
    eng, j = go(e, {(0, 30): [buy()]}, {C})
    fills = [r for r in j.lines if r["kind"] == "fill"]
    ok("stop: buy then stop sell", [f["side"] for f in fills] == ["BUY", "SELL"], fills)
    ok("stop: tagged as the stop", fills[-1]["tag"] == "stop")
    ok("stop: sold near the stop, not at the low", 70 <= fills[-1]["price"] <= 80, fills[-1]["price"])
    ok("stop: order carried its stop price", any(r["kind"] == "order" and r["stop"] for r in j.lines))
    ok("stop: flat afterwards", eng.book.open_legs() == 0)
    loss = -eng.book.pnl()
    ok("stop: loss about a quarter of the premium plus costs", 0.22 * 102 * 65 < loss < 0.35 * 102 * 65, round(loss))


def test_trail():
    # up 30% -> trailing stop replaces the fixed stop; peak 150; fall to 130 -> trail (10% under 150 = 135) fires
    e = entry({"25000": walk(0, 30, [100, 105, 112, 120, 128, 135, 142, 150, 146, 140, 133, 125])})
    eng, j = go(e, {(0, 30): [buy()]}, {C})
    kinds = [r["kind"] for r in j.lines]
    ok("trail: switched on", "trail-on" in kinds)
    on = next(r for r in j.lines if r["kind"] == "trail-on")
    ok("trail: switched on only after the 20% gain", on["price"] >= 1.2 * 102, on["price"])
    fills = [r for r in j.lines if r["kind"] == "fill"]
    ok("trail: exit tagged trail", fills[-1]["tag"] == "trail", fills[-1])
    ok("trail: exit near 10% under the peak", 128 <= fills[-1]["price"] <= 136, fills[-1]["price"])
    ok("trail: profit kept", eng.book.pnl() > 20 * 65, round(eng.book.pnl()))
    ok("trail: one sell only", sum(1 for f in fills if f["side"] == "SELL") == 1)


def test_no_trail_without_gain():
    e = entry({"25000": walk(0, 30, [100, 104, 108, 110, 109, 108])})
    eng, j = go(e, {(0, 30): [buy()]}, {C})
    ok("no trail below the 20% gain", "trail-on" not in [r["kind"] for r in j.lines])
    ok("stop still protecting at the day's end", eng.book.open_legs() == 1)


def test_hedge_has_no_stop():
    e = entry({"25000": walk(0, 30, [100, 90, 80, 70, 60, 50])})
    eng, j = go(e, {(0, 30): [buy(hedge=True)]}, {C})
    order = next(r for r in j.lines if r["kind"] == "order")
    ok("hedge: no stop attached", order["stop"] is None)
    ok("hedge: still held after a fall", eng.book.open_legs() == 1)


def test_kill_switch_no_double_sell():
    # 3 lots would breach the per-order limit; use a small loss limit so one lot trips it before the stop
    s = Settings(strategy="script", stale_seconds=300, max_daily_loss=500, stop_loss=0.5)
    e = entry({"25000": walk(0, 30, [100, 95, 90, 85, 80, 78, 76, 74])})
    eng, j = go(e, {(0, 30): [buy()]}, {C}, s=s)
    kinds = [r["kind"] for r in j.lines]
    ok("kill: tripped by the loss limit", "kill" in kinds)
    ok("kill: stop cancelled before closing", "stop-cancelled" in kinds)
    sells = [r for r in j.lines if r["kind"] == "fill" and r["side"] == "SELL"]
    ok("kill: exactly one sell", len(sells) == 1, sells)
    ok("kill: never short", all(q >= 0 for q in eng.book.qty.values()) and eng.book.open_legs() == 0)


def test_refusals():
    e = entry({"25000": walk(0, 0, [100] * 376)}, {"25000": walk(0, 0, [90] * 376)})
    plan = {(0, 1): [buy()],                                    # 09:16: before 09:20
            (0, 30): [buy(lots=3)],                             # above the per-order limit
            (0, 31): [buy()],                                   # allowed
            (0, 32): [buy()],                                   # already holding
            (0, 33): [OrderRequest(P, "SELL", 1, None, "x", closing=True)]}   # closing nothing
    eng, j = go(e, plan, {C, P})
    why = [r["reason"] for r in j.lines if r["kind"] == "refused"]
    ok("refused: before the entry window", any("outside" in w for w in why), why)
    ok("refused: too many lots", any("above the limit" in w for w in why), why)
    ok("refused: already holding", any("already holding" in w for w in why), why)
    ok("refused: fake closing order", any("does not reduce" in w for w in why), why)
    ok("one order went through", j.count("order") == 1, j.count("order"))


def test_stale_price():
    e = entry({"25000": walk(0, 30, [100])})                    # last trade 09:45, order at 10:15
    eng, j = go(e, {(0, 60): [buy()]}, {C}, s=Settings(strategy="script", stale_seconds=10))
    why = [r["reason"] for r in j.lines if r["kind"] == "refused"]
    ok("refused: old price", any("seconds old" in w for w in why), why)


def test_settlement():
    e = entry({"25000": walk(0, 30, [100, 101, 102])})
    eng, j = go(e, {(0, 30): [buy(hedge=True)]}, {C}, close=25150.0)
    ok("settled at the index close", eng.book.open_legs() == 0 and any(r["kind"] == "settle" for r in j.lines))
    ok("settlement value counted", eng.book.cash > 0, round(eng.book.cash))


def test_condor():
    from .strategies.expiry_condor import ExpiryCondor
    strikes = range(24000, 26050, 50)
    call = {str(k): walk(0, 360, [max(25000 - k, 0) + 60 * 2.718 ** (-abs(k - 25000) / 300)] * 16) for k in strikes}
    put = {str(k): walk(0, 360, [max(k - 25000, 0) + 60 * 2.718 ** (-abs(k - 25000) / 300)] * 16) for k in strikes}
    s = Settings(strategy="expiry_condor", stale_seconds=300)
    j = Journal()
    eng = run("NIFTY", entry(call, put), 25020.0, ExpiryCondor({"m": 1.0, "w": 1.0}), s, j)
    orders = [r for r in j.lines if r["kind"] == "order"]
    ok("condor: four orders at 15:25", len(orders) == 4 and all(r["t"].endswith("15:25:00") for r in orders),
       [(r["t"], r["contract"]) for r in orders])
    ok("condor: wings carry no stop", all(r["stop"] is None for r in orders))
    ok("condor: two sold, two bought", sorted(r["side"] for r in orders) == ["BUY", "BUY", "SELL", "SELL"])
    ok("condor: settled flat", eng.book.open_legs() == 0)


def test_summary():
    from datetime import datetime as dt
    from .summary import build
    # trailing-stop trade: one long round trip, closed by the trailing stop, profit equals the engine's
    e = entry({"25000": walk(0, 30, [100, 105, 112, 120, 128, 135, 142, 150, 146, 140, 133, 125])})
    eng, j = go(e, {(0, 30): [buy()]}, {C})
    s = build(j.lines, now=dt(2026, 11, 2, 16, 0))
    t = s["trades"]
    ok("summary: one trade, closed by the trailing stop", len(t) == 1 and t[0]["why"] == "Trailing stop", t)
    ok("summary: trade profit matches the engine", abs(t[0]["pnl"] - eng.book.pnl()) < 0.01, (t[0]["pnl"], eng.book.pnl()))
    ok("summary: day and month rows", s["days"][0]["date"] == PREV and s["months"][0]["month"] == "2026-11"
       and s["today"]["booked"] == t[0]["pnl"])
    ok("summary: nothing left open", s["open"] == [])
    # stop still working at the day's end: shows as open with its stop
    e = entry({"25000": walk(0, 30, [100, 104, 108, 110, 109, 108])})
    eng, j = go(e, {(0, 30): [buy()]}, {C})
    s = build(j.lines, now=dt(2026, 11, 2, 16, 0))
    o = s["open"]
    ok("summary: open position with its stop-loss", len(o) == 1 and o[0]["protection"].startswith("Stop-loss at"), o)
    ok("summary: open profit valued at the last price", o[0]["mark"] == 108 and o[0]["pnl"] is not None, o)
    pend = s["pending"]
    ok("summary: pending shows the working stop-loss", len(pend) == 1 and pend[0]["type"] == "Stop-loss"
       and pend[0]["side"] == "SELL" and pend[0]["qty"] == 65, pend)
    # a limit buy below the market never fills: pending until the day's end
    e = entry({"25000": walk(0, 30, [100] * 20)})
    eng, j = go(e, {(0, 30): [OrderRequest(C, "BUY", 1, 90.0, "test")]}, {C})
    mid = [r for r in j.lines if r["kind"] == "mark" and r["t"].startswith(PREV + "T10:")]
    ok("summary: unfilled limit order shown as pending during the day",
       any(o["type"] == "Limit" and o["price"] == 90.0 for o in mid[-1]["orders"]), mid[-1]["orders"] if mid else None)
    # condor settled at expiry: four trades, booked total equals the engine's
    from .strategies.expiry_condor import ExpiryCondor
    strikes = range(24000, 26050, 50)
    call = {str(k): walk(0, 360, [max(25000 - k, 0) + 60 * 2.718 ** (-abs(k - 25000) / 300)] * 16) for k in strikes}
    put = {str(k): walk(0, 360, [max(k - 25000, 0) + 60 * 2.718 ** (-abs(k - 25000) / 300)] * 16) for k in strikes}
    st = Settings(strategy="expiry_condor", stale_seconds=300)
    j = Journal()
    eng = run("NIFTY", entry(call, put), 25020.0, ExpiryCondor({}), st, j)
    s = build(j.lines, now=dt(2026, 11, 3, 16, 0))
    ok("summary: condor gives four trades at expiry", len(s["trades"]) == 4 and all(x["why"] == "Expiry" for x in s["trades"]),
       [(x["contract"], x["why"]) for x in s["trades"]])
    ok("summary: condor total matches the engine", abs(s["totals"]["booked"] - eng.book.pnl()) < 0.05,
       (s["totals"]["booked"], eng.book.pnl()))


def test_indicators():
    from datetime import datetime as dt, timedelta as td
    from .indicators import check, completed, ema, resample, rsi, sma
    ok("ind: sma", sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5])
    e = ema([1, 2, 3, 4, 5], 3)
    ok("ind: ema seeded with the average", e[2] == 2 and abs(e[3] - 3) < 1e-9 and abs(e[4] - 4) < 1e-9, e)
    r = rsi([float(i) for i in range(30)], 14)
    ok("ind: rsi of a straight rise is 100", r[-1] == 100.0, r[-1])
    r = rsi([100 + (i % 2) for i in range(40)], 14)
    ok("ind: rsi of a flat zigzag is near 50", 40 < r[-1] < 60, r[-1])
    t0 = dt(2026, 11, 2, 9, 15)
    bars = [(t0 + td(minutes=i), 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(10)]
    rs = resample(bars, 5)
    ok("ind: 5-minute bars", len(rs) == 2 and rs[0][1] == 100 and rs[0][2] == 105 and rs[0][4] == 104.5, rs)
    ok("ind: unfinished minute left out", len(completed(bars, t0 + td(minutes=9, seconds=30))) == 9)
    day = [(t0 + td(minutes=i), 100, 101, 99, 100) for i in range(15)] + [(t0 + td(minutes=15), 100, 103, 100, 102.5)]
    ok("ind: opening range breakout up", check({"type": "orb", "minutes": 15, "dir": "up"}, day, t0 + td(minutes=16), None, None)[0])
    ok("ind: no breakdown at the same time", not check({"type": "orb", "minutes": 15, "dir": "down"}, day, t0 + td(minutes=16), None, None)[0])
    ok("ind: change from yesterday", check({"type": "change", "from": "prev_close", "op": "above", "pct": 2}, day, t0, 100.0, None)[0])
    ok("ind: days to expiry", check({"type": "dte", "op": "<=", "days": 1}, [], t0, None, "2026-11-03")[0])


def _rules_case(strategy, call=None, put=None, index_path=None):
    from .journal import Journal
    from .strategies.rules import Rules
    warm = {"2026-10-30": [[m, 25000, 25001, 24999, 25000, 0] for m in range(376)]}
    path = index_path or [25000] * 15 + [25000 + 3 * i for i in range(1, 361)]
    warm[PREV] = [[m, p, p + 1, p - 1, p, 0] for m, p in enumerate(path)]
    warm[EXP] = [[m, path[-1], path[-1] + 1, path[-1] - 1, path[-1], 0] for m in range(376)]
    e = entry(call or {}, put or {})
    s = Settings(strategy="rules", stale_seconds=300, max_lots_per_order=5)
    j = Journal()
    eng = run("NIFTY", e, None, Rules(strategy), s, j, index_days=warm)
    return eng, j


def test_rules():
    base = {"id": "t1", "name": "ORB call", "index": "NIFTY", "side": "BUY", "right": "C",
            "strike": {"mode": "atm", "steps": 0}, "expiry": "nearest", "lots": 1,
            "window": {"from": "09:30", "until": "14:30"}, "match": "all",
            "signals": [{"type": "orb", "minutes": 15, "dir": "up"}],
            "exits": {"sl": 25, "target": 30, "trail": 0}, "style": "intraday", "max_trades_day": 1}
    strikes = range(24800, 25300, 50)
    rising = {str(k): walk(0, 0, [max(100 + (i - 15) * 2, 100) if k == 25000 else 50 for i in range(376)]) for k in strikes}
    eng, j = _rules_case(base, call=rising)
    orders = [r for r in j.lines if r["kind"] == "order"]
    ok("rules: one entry, at 09:30 or later", len(orders) >= 1 and orders[0]["t"][11:16] >= "09:30", orders[:1])
    ok("rules: bought the at-the-money call", orders and orders[0]["contract"].endswith(" 25000C") and orders[0]["side"] == "BUY")
    ok("rules: stop attached, day-only", orders and orders[0]["stop"] and orders[0]["validity"] == "DAY", orders[:1])
    fills = [r for r in j.lines if r["kind"] == "fill"]
    ok("rules: closed at the target", len(fills) == 2 and fills[1]["tag"] == "target" and fills[1]["side"] == "SELL", fills)
    ok("rules: target near +30%", fills and 1.25 * fills[0]["price"] <= fills[-1]["price"] <= 1.45 * fills[0]["price"],
       [f["price"] for f in fills])
    ok("rules: only one trade that day", len(orders) == 2)        # entry + target close
    # no signal, no trade
    flat = dict(base, signals=[{"type": "orb", "minutes": 15, "dir": "down"}])
    eng, j = _rules_case(flat, call=rising)
    ok("rules: no trade without its signal", j.count("order") == 0)
    # a sold put with its own stop: the put rises, the buy-stop above fires
    short = dict(base, id="t2", side="SELL", right="P", exits={"sl": 20, "target": 0, "trail": 0}, style="carry")
    up_put = {str(k): walk(0, 0, [100 + max(i - 15, 0) for i in range(376)] if k == 25000 else [50] * 376) for k in strikes}
    eng, j = _rules_case(short, put=up_put)
    fills = [r for r in j.lines if r["kind"] == "fill"]
    o = next(r for r in j.lines if r["kind"] == "order")
    ok("rules: sold put gets a buy-stop above, good till cancelled", o["stop"] > 100 and o["validity"] == "GTC", o)
    ok("rules: buy-stop closes the short", len(fills) == 2 and fills[1]["side"] == "BUY" and fills[1]["tag"] == "stop", fills)
    ok("rules: short closed near +20%", fills and 1.15 * fills[0]["price"] <= fills[-1]["price"] <= 1.35 * fills[0]["price"],
       [f["price"] for f in fills])
    ok("rules: flat after the stop", eng.book.open_legs() == 0)
    # exit-by time: no target, no stop hit; closed at 15:15
    timed = dict(base, id="t3", exits={"sl": 90, "target": 0, "trail": 0, "exit_by": "11:00"})
    eng, j = _rules_case(timed, call=rising)
    fills = [r for r in j.lines if r["kind"] == "fill"]
    ok("rules: closed at the exit-by time", len(fills) == 2 and fills[1]["tag"] == "time-exit"
       and fills[1]["t"][11:16] <= "11:02", [(f["t"], f["tag"]) for f in fills])
    # trailing in points: switch after +20 points, trail 10 points
    trail = dict(base, id="t4", exits={"sl": 25, "target": 0, "trail_after_type": "points", "trail_after": 20,
                                       "trail_type": "points", "trail": 10})
    peak = {str(k): walk(0, 0, [100] * 16 + [100 + 3 * i for i in range(1, 20)] + [157 - 2 * i for i in range(1, 30)] + [99] * 312
                         if k == 25000 else [50] * 376) for k in strikes}
    eng, j = _rules_case(trail, call=peak)
    fills = [r for r in j.lines if r["kind"] == "fill"]
    on = [r for r in j.lines if r["kind"] == "trail-on"]
    ok("rules: points trailing switched on", on and on[0]["by_type"] == "points", on[:1])
    ok("rules: trailing exit about 10 points under the peak", fills and fills[-1]["tag"] == "trail"
       and 140 <= fills[-1]["price"] <= 150, [(f["price"], f["tag"]) for f in fills])


def main() -> int:
    for t in [test_indicators, test_rules, test_summary, test_stop_hit, test_trail, test_no_trail_without_gain, test_hedge_has_no_stop,
              test_kill_switch_no_double_sell, test_refusals, test_stale_price, test_settlement, test_condor]:
        t()
    bad = [n for n, good in R if not good]
    print(f"{len(R) - len(bad)} of {len(R)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
