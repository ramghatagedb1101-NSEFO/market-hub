"""
The paper trading program as it runs on market-hub-trader (a systemd service, trader.service; restarts itself).

    /opt/trader/venv/bin/python -m trader.live          (from /opt/trader/app, a copy of this repo)

  settings   /opt/trader/settings.json (model.Settings fields). No file, or no "strategy": watch only, no orders.
  builder    /opt/trader/strategies.json, copied from the dashboard's strategy builder by the algo-sync job:
             {"active": id or null, "items": [...], "limits": {...}}. The active one trades (watch only when none);
             a change is picked up within seconds of the file arriving, for new trades only (open positions keep the
             exits they started with). "limits" may raise or lower max_lots_per_order and max_daily_loss.
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

from .engine import Engine, default_exits
from .ibkr import IBKR
from .journal import Journal
from .model import Settings
from .strategies import make

HOME = Path("/opt/trader")
SETTINGS, JOURNALS, STOP, STRATS = HOME / "settings.json", HOME / "journal", HOME / "STOP", HOME / "strategies.json"
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
    act = next((x for x in b.get("items") or [] if x.get("id") and x.get("id") == b.get("active")), None)
    if act:
        s.strategy, s.params = "rules", act
    return s


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
    return is_session(now.date()) and OPEN <= now.strftime("%H:%M") <= CLOSE


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
    stamp, kept = builder_stamp(), ""
    while True:
        now = datetime.now()
        if now.date() != day:                      # new day: fresh journal, fresh limits
            day, s = now.date(), settings()
            eng = start(br, s, day)
            stamp = builder_stamp()
        elif builder_stamp() != stamp:
            stamp = builder_stamp()
            switch(eng, now)
        try:
            if market_open(now):
                eng.step(now)
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
                br.restore()
            except Exception as e2:                # systemd restarts the program if this fails too
                eng.j.write(datetime.now(), "note", text=f"reconnect failed ({type(e2).__name__}); restarting")
                return 1


if __name__ == "__main__":
    sys.exit(main())
