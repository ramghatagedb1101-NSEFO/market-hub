"""
The paper trading program as it runs on market-hub-trader (a systemd service, trader.service; restarts itself).

    /opt/trader/venv/bin/python -m trader.live          (from /opt/trader/app, a copy of this repo)

  settings   /opt/trader/settings.json (model.Settings fields). No file, or no "strategy": watch only, no orders.
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

from .engine import Engine
from .ibkr import IBKR
from .journal import Journal
from .model import Settings
from .strategies import make

HOME = Path("/opt/trader")
SETTINGS, JOURNALS, STOP = HOME / "settings.json", HOME / "journal", HOME / "STOP"
EVERY = 2.0
OPEN, CLOSE = "09:15", "15:30"


def settings() -> Settings:
    try:
        data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in known})


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
    for c, ch in br.children.items():
        eng.protect[c] = {"entry": avg.get(c, 0.0), "state": "stop" if ch["kind"] in ("stop", "ratchet") else "trail"}
    j.write(datetime.now(), "start", strategy=s.strategy or "watch only", settings=asdict(s),
            positions_found=len(held), stops_found=kept)
    return eng


def main() -> int:
    s = settings()
    br = IBKR()
    br.connect()
    day = date.today()
    eng = start(br, s, day)
    while True:
        now = datetime.now()
        if now.date() != day:                      # new day: fresh journal, fresh limits
            day, s = now.date(), settings()
            eng = start(br, s, day)
        try:
            if market_open(now):
                eng.step(now)
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
