"""
The paper trading program as it runs on market-hub-trader (a systemd service, trader.service; restarts itself).

    /opt/trader/venv/bin/python -m trader.live          (from /opt/trader/app, a copy of this repo)

  settings   /opt/trader/settings.json (model.Settings fields). No file, or no "strategy": watch only, no orders.
  builder    /opt/trader/strategies.json, copied from the dashboard's strategy builder by the algo-sync job:
             {"active": id or null, "items": [...], "limits": {...}}. The active one trades (watch only when none);
             a change is picked up within seconds of the file arriving, for new trades only (open positions keep the
             exits they started with). "limits" may raise or lower max_lots_per_order and max_daily_loss.
             "mode": "autopilot" instead: at 09:30, 11:00 and 13:00 the program reads the market condition and picks
             the strategy itself (trader/autopilot.py), or the "fallback", or watches; every pick is journalled.
  journal    /opt/trader/journal/YYYY-MM-DD.jsonl, one line per decision, order, fill, refusal and profit mark
  stop       create /opt/trader/STOP to close everything and stop new entries for the day

Steps every 2 seconds while the exchange is open (09:15-15:30 IST on a trading day); quiet otherwise. On a start or
restart it first reads what IBKR already holds and the stops IBKR is still keeping, so nothing is forgotten (profit
for the day restarts from those positions' current value; the journal says so).
"""
import json
import sys
import time
from dataclasses import asdict, fields
from datetime import date, datetime
from pathlib import Path

from hub.holidays import is_session

from .autopilot import CHECKS, FILL_UNTIL, choose, fill_choice, first_choice, is_done, us_close
from .engine import Engine, default_exits
from .indicators import completed
from .regime import classify
from .strategies.rules import pick_expiry
from . import summary as summary_mod
from .ibkr import IBKR
from .journal import Journal
from .model import Settings
from .strategies import make

HOME = Path("/opt/trader")
SETTINGS, JOURNALS, STOP, STRATS = HOME / "settings.json", HOME / "journal", HOME / "STOP", HOME / "strategies.json"
KILL = HOME / "KILL"          # the dashboard's emergency stop (kicker each minute, algo-sync on every change)
PROTECT = HOME / "protect.json"            # each open position's exits, so a restart keeps them
EVERY = 2.0
OPEN, CLOSE = "09:15", "15:30"


def settings() -> Settings:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    known = {f.name for f in fields(Settings)}
    s = Settings(**{k: v for k, v in data.items() if k in known})
    try:
        b = json.loads(STRATS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return s
    lim = b.get("limits") or {}
    if lim.get("max_lots_per_order"):
        s.max_lots_per_order = int(min(max(float(lim["max_lots_per_order"]), 1), 50))
    if lim.get("max_daily_loss"):
        s.max_daily_loss = float(min(max(float(lim["max_daily_loss"]), 500), 1e7))
    if b.get("mode") == "autopilot":
        return s                                   # autopilot picks the strategy itself at its check times
    act = next((x for x in b.get("items") or [] if x.get("id") and x.get("id") == b.get("active")), None)
    if act:
        s.strategy, s.params = "rules", act
    return s


def builder() -> dict:
    try:
        return json.loads(STRATS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def use(eng: Engine, item: dict | None) -> None:
    """Run this builder strategy (or none) from now on; the day's count carries over if it is the same one."""
    old = eng.strategy
    eng.strategy = make(Settings(strategy="rules", params=item)) if item else None
    if old is not None and eng.strategy is not None and getattr(old, "id", None) == getattr(eng.strategy, "id", None):
        eng.strategy.day, eng.strategy.trades = old.day, old.trades
        eng.strategy.last_entry, eng.strategy.mine = old.last_entry, old.mine


def open_gap(bars: list, now: datetime, prev_close: float | None) -> float | None:
    """NIFTY's opening gap today, % from yesterday's close (None when either is missing)."""
    day = [x for x in bars or [] if x[0].date() == now.date()]
    if not day or not prev_close:
        return None
    return (day[0][1] / prev_close - 1) * 100


FINISHED: set = set()          # strategies done for the day (cleared each new day)
FLOWS = HOME / "flows.json"   # the market diary's figures (algo-sync): US closes for the autopilot log


def flows_now() -> dict:
    try:
        return json.loads(FLOWS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fill_idle(br: IBKR, eng: Engine, now: datetime, b: dict) -> None:
    """Fill idle time (owner, 17 Nov 2026): when the strategy in charge is done for the day, the strategy that passed
    testing with the best record in the market condition read now takes over (autopilot only; never after FILL_UNTIL,
    never when stopped)."""
    if eng.guard.killed or now.strftime("%H:%M") > FILL_UNTIL:
        return
    if not b.get("passed") and (b.get("method") or "match") != "match":
        return
    if not is_done(eng.strategy, eng.book.open_legs(), now.strftime("%H:%M"), pending=len(eng.broker.working()), now=now):
        return
    cur = getattr(eng.strategy, "id", None)
    if cur:
        FINISHED.add(cur)
    if getattr(eng, "_fill_tried", None) == (cur, now.strftime("%H")):
        return                                     # nothing qualified for this one this hour; look again next hour
    eng._fill_tried = (cur, now.strftime("%H"))
    regimes, words, gap = {}, {}, None
    for idx in sorted({(p.get("strategy") or {}).get("index") or "NIFTY" for p in b["passed"]} | {"NIFTY"}):
        bars = completed(br.index_bars(idx), now)
        exp = pick_expiry(br.expiries(idx), now.date(), "nearest")
        regimes[idx], words[idx] = classify(bars, now, exp)
        if idx == "NIFTY":
            gap = open_gap(bars, now, br.prev_close("NIFTY"))
    excl = FINISHED | ({cur} if cur else set())
    if (b.get("method") or "match") == "match":
        item, why = first_choice(b, regimes, gap, now.date(), excl)
    else:
        item, why = fill_choice(b["passed"], regimes, excl)
    if not item:
        return
    use(eng, item)
    eng.j.write(now, "autopilot", regime=regimes.get("NIFTY") or next(iter(regimes.values()), None),
                regime_why=words.get("NIFTY"), regimes=regimes, strategy=item.get("name"), strategy_id=item.get("id"),
                why=why, scores={}, gap=round(gap, 2) if gap is not None else None, us_close=us_close(flows_now(), now.date()))


def autopilot_check(br: IBKR, eng: Engine, now: datetime, b: dict) -> None:
    items = b.get("items") or []
    regimes, words, gap = {}, {}, None
    for idx in sorted({it.get("index") or "NIFTY" for it in items} | {(p.get("strategy") or {}).get("index") or "NIFTY" for p in b.get("passed") or []} | {"NIFTY"}):
        bars = completed(br.index_bars(idx), now)
        if idx == "NIFTY":
            gap = open_gap(bars, now, br.prev_close("NIFTY"))
        exp = pick_expiry(br.expiries(idx), now.date(), "nearest")
        regimes[idx], words[idx] = classify(bars, now, exp)
    try:
        paper = summary_mod.build(summary_mod.read(str(JOURNALS)))["by_strategy_regime"]
    except Exception:
        paper = {}
    if (b.get("method") or "match") == "match":
        item, why = first_choice(b, regimes, gap, now.date(), FINISHED)
        scores = {}
    else:
        item, why, scores = choose(items, regimes, b.get("backtests") or {}, paper, b.get("fallback"))
    if item and item.get("id") in FINISHED:          # done for the day already: the strategy filling the time stays
        eng.j.write(now, "note", text=f"autopilot: {item.get('name')} is done for the day; keeping the current strategy")
        return
    use(eng, item)
    main = "NIFTY" if "NIFTY" in regimes else next(iter(regimes))
    eng.j.write(now, "autopilot", regime=regimes.get(main), regime_why=words.get(main), regimes=regimes,
                strategy=item.get("name") if item else None, strategy_id=item.get("id") if item else None,
                why=why, scores=scores, gap=round(gap, 2) if gap is not None else None, us_close=us_close(flows_now(), now.date()))


def builder_stamp():
    try:
        return STRATS.stat().st_mtime
    except OSError:
        return None


def switch(eng: Engine, now: datetime) -> None:
    """The dashboard changed the active strategy or the limits: new trades follow it; open positions keep their exits."""
    s = settings()
    old = eng.strategy
    eng.s, eng.guard.s = s, s
    if builder().get("mode") == "autopilot":
        eng.j.write(now, "switch", strategy="autopilot", max_lots=s.max_lots_per_order, max_daily_loss=s.max_daily_loss)
        return                                     # the next autopilot check (at once) picks the strategy
    eng.strategy = make(s)
    if old is not None and eng.strategy is not None and getattr(old, "id", None) == getattr(eng.strategy, "id", None):
        eng.strategy.day, eng.strategy.trades = old.day, old.trades           # the day's count survives an edit
        eng.strategy.last_entry, eng.strategy.mine = old.last_entry, old.mine
    eng.j.write(now, "switch", strategy=getattr(eng.strategy, "name", None) or s.strategy or "watch only",
                strategy_id=getattr(eng.strategy, "id", None), max_lots=s.max_lots_per_order,
                max_daily_loss=s.max_daily_loss)


def keep_protect(eng: Engine, last: str) -> str:
    """Writes the open positions' exits when they change; returns what was written."""
    text = json.dumps({c.key(): p for c, p in eng.protect.items()}, sort_keys=True, default=str)
    if text != last:
        tmp = PROTECT.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(PROTECT)
    return text


def market_open(now: datetime) -> bool:
    from .session import session_close            # 15:45 from 7 Dec 2026 (SEBI, 15 Oct 2026 circular)
    return is_session(now.date()) and OPEN <= now.strftime("%H:%M") <= session_close(now.date())


def start(br: IBKR, s: Settings, day: date) -> Engine:
    j = Journal(str(JOURNALS / f"{day.isoformat()}.jsonl"))
    eng = Engine(br, br, make(s), s, j, stop_file=str(STOP))
    held = br.held()
    for c, q in held.items():
        eng.book.qty[c] = q
    kept = br.restore()
    avg = {br._ours(p.contract): p.avgCost / float(p.contract.multiplier or 1) for p in br.ib.positions()
           if br._ours(p.contract)}
    try:
        saved = json.loads(PROTECT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    for c, ch in br.children.items():
        p = saved.get(c.key()) or {}
        eng.protect[c] = {"entry": p.get("entry") or avg.get(c, 0.0), "dir": 1 if held.get(c, 0) > 0 else -1,
                          "ex": p.get("ex") or default_exits(s),
                          "state": "stop" if ch["kind"] in ("stop", "ratchet") else "trail"}
    j.write(datetime.now(), "start", strategy=getattr(eng.strategy, "name", None) or s.strategy or "watch only",
            settings={k: v for k, v in asdict(s).items() if k != "params"},
            positions_found=len(held), stops_found=kept)
    return eng


def main() -> int:
    s = settings()
    br = IBKR()
    br.connect()
    day = date.today()
    eng = start(br, s, day)
    stamp, kept, done = builder_stamp(), "", set()
    while True:
        now = datetime.now()
        if now.date() != day:                      # new day: fresh journal, fresh limits, autopilot checks again
            day, s, done = now.date(), settings(), set()
            FINISHED.clear()
            eng = start(br, s, day)
            stamp = builder_stamp()
        elif builder_stamp() != stamp:
            stamp = builder_stamp()
            switch(eng, now)
            done = set()                           # autopilot: a change on the dashboard means a fresh look now
        eng.dash_kill(now, KILL.exists())
        b = builder()
        if b.get("mode") == "autopilot" and market_open(now):
            due = [c for c in CHECKS if now.strftime("%H:%M") >= c and c not in done]
            if due:
                done |= set(due)
                try:
                    autopilot_check(br, eng, now, b)
                except Exception as e:             # a failed check keeps whatever was running; journalled
                    eng.j.write(now, "note", text=f"autopilot check failed ({type(e).__name__}); keeping the current choice")
            elif now.strftime("%H:%M") > CHECKS[0]:
                try:
                    fill_idle(br, eng, now, b)
                except Exception as e:             # noqa: BLE001 -- the strategy in charge stays
                    eng.j.write(now, "note", text=f"fill check failed ({type(e).__name__})")
        try:
            # 16 Nov 2026: a gateway restart (06:30 daily, or a repair) dropped the link silently outside market hours;
            # reconnect as soon as it is gone, not at the first step after 09:15
            if not br.ib.isConnected():
                raise ConnectionError("not connected")
            if market_open(now):
                eng.step(now)
                for ev in getattr(br, "feed_events", [])[:]:
                    eng.j.write(now, "feed", **ev)
                    br.feed_events.remove(ev)
                kept = keep_protect(eng, kept)
                br.ib.sleep(EVERY)
            else:
                br.ib.sleep(30)
        except (ConnectionError, OSError) as e:
            eng.j.write(datetime.now(), "note", text=f"connection lost ({type(e).__name__}); reconnecting")
            time.sleep(20)
            try:
                br.ib.disconnect()
                br.connect()
                br.reset_feed()                    # 20 Nov 2026: the old connection's price feeds are dead
                br.restore()
            except Exception as e2:                # systemd restarts the program if this fails too
                eng.j.write(datetime.now(), "note", text=f"reconnect failed ({type(e2).__name__}); restarting")
                return 1


if __name__ == "__main__":
    sys.exit(main())
