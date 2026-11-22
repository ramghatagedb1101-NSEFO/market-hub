"""
Simulated orders on IBKR's live prices (owner, 22 Nov 2026, after IBKR's notice: "API trading for IBKR India accounts
will be disabled" while it reviews SEBI's framework for API trading by retail clients). Prices still come from IBKR
(trader/ibkr.py, unchanged); orders never go to IBKR: this class fills them itself and keeps the positions in
/opt/trader/sim_book.json, so a restart forgets nothing.

How it fills (the same rules as the back-tests' ReplayBroker, on live quotes):
  - an entry fills at the live ask (buy) or bid (sell), only from a quote at most 30 seconds old; a limit that is not
    reached waits, and an unfilled entry is dropped at the day's end
  - a stop protecting a long sells at the bid once the bid (or the last price) reaches it; one protecting a short buys
    at the ask; a trailing stop follows the best middle price since it started
  - an option still held at 15:30 on its expiry day is settled at its value against the index (the next morning, from
    the expiry day's close, if the program was down then)
  - charges: the full Indian table, as for IBKR's fills and the back-tests
Back to IBKR's own paper orders, if IBKR allows program trading again: create /opt/trader/ORDERS_AT_IBKR and restart.
"""
import json
from datetime import datetime
from pathlib import Path

from ib_async import Index

from hub.rule_test import charges

from .ibkr import IB_SYMBOL, IBKR
from .model import Contract, Fill, OrderRequest, Quote

FRESH = 30          # seconds: an older quote does not fill an order


def parse(key: str) -> Contract:
    """'NIFTY 2026-11-23 25550C' -> Contract."""
    idx, exp, sr = key.split()
    return Contract(idx, exp, float(sr[:-1]), sr[-1])


class SimIBKR(IBKR):
    simulated = True

    def __init__(self, path: str = "/opt/trader/sim_book.json", **kw):
        super().__init__(**kw)
        self.path = Path(path)
        self.pos: dict[Contract, dict] = {}         # contract -> {"qty": units (+ long / - short), "avg": price}
        self.stops: dict[Contract, dict] = {}       # one protective order per position (stop or trailing stop)
        self.waiting: list[tuple[str, OrderRequest]] = []
        self.done: list[Fill] = []
        self.n, self.day = 0, None
        self._load()

    # ---- the book on disk -----------------------------------------------------------------------------------------
    def _load(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.n, self.day = int(d.get("n") or 0), d.get("day")
        self.pos = {parse(k): v for k, v in (d.get("pos") or {}).items()}
        # a stop still waiting for its entry is dropped: the entry itself is not kept over a restart
        self.stops = {parse(k): v for k, v in (d.get("stops") or {}).items() if v.get("live")}

    def _save(self) -> None:
        d = {"n": self.n, "day": self.day, "pos": {c.key(): v for c, v in self.pos.items()},
             "stops": {c.key(): v for c, v in self.stops.items()}}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def _id(self) -> str:
        self.n += 1
        return f"S{self.n}"

    # ---- orders -----------------------------------------------------------------------------------------------------
    def submit(self, r: OrderRequest, q: Quote | None, now: datetime, stop: float | None = None,
               validity: str = "GTC") -> str:
        self._new_day(now)                           # (a day change first, so this order is not dropped as yesterday's)
        oid = self._id()
        self.waiting.append((oid, r))
        if stop is not None:                         # works once the entry has filled
            self.stops[r.contract] = {"id": self._id(), "parent": oid, "kind": "stop", "stop": round(stop, 2),
                                      "side": "SELL" if r.side == "BUY" else "BUY", "validity": validity,
                                      "qty": r.lots * r.contract.lot, "live": False}
        self._save()
        return oid

    def trail(self, c: Contract, by: float, now: datetime, by_type: str = "pct") -> str:
        old = self.stops.get(c)
        q = self.quotes().get(c)
        if not old or not old["live"] or not q or not q.mid:
            return ""
        st = {"id": self._id(), "parent": "", "kind": "trail", "by": by, "by_type": by_type, "best": q.mid,
              "side": old["side"], "validity": old["validity"], "qty": old["qty"], "live": True}
        st["stop"] = self._trail_stop(st)
        self.stops[c] = st
        self._save()
        return st["id"]

    @staticmethod
    def _trail_stop(st: dict) -> float:
        d = st["best"] * st["by"] / 100 if st["by_type"] == "pct" else st["by"]
        return round(st["best"] - d if st["side"] == "SELL" else st["best"] + d, 2)

    def ratchet(self, quotes) -> None:               # trailing stops always work here
        return None

    def cancel_children(self, c: Contract) -> None:
        if self.stops.pop(c, None) is not None:
            self._save()

    def working(self) -> set[Contract]:
        return {r.contract for _, r in self.waiting}

    def open_orders(self) -> list[dict]:
        out = [{"id": oid, "contract": r.contract.key(), "side": r.side, "qty": r.lots * r.contract.lot,
                "type": "Limit" if r.limit is not None else "At market", "price": r.limit, "tag": r.tag,
                "status": "Simulated"} for oid, r in self.waiting]
        out += [{"id": st["id"], "contract": c.key(), "side": st["side"], "qty": st["qty"],
                 "type": "Trailing stop" if st["kind"] == "trail" else "Stop-loss", "price": round(st["stop"], 2),
                 "tag": st["kind"], "status": "Simulated" if st["live"] else "Waiting for entry",
                 "trail_pct": st.get("by") if st["kind"] == "trail" and st.get("by_type") == "pct" else None}
                for c, st in self.stops.items()]
        return out

    # ---- fills ------------------------------------------------------------------------------------------------------
    def _fill(self, c: Contract, side: str, qty: int, px: float, now: datetime, oid: str, tag: str) -> None:
        px = round(max(px, 0.05), 2)
        self.done.append(Fill(c, side, qty, px, now, charges(px, qty, side.lower(), c.exchange), oid, tag))
        p = self.pos.get(c) or {"qty": 0, "avg": 0.0}
        d = qty if side == "BUY" else -qty
        new = p["qty"] + d
        if p["qty"] == 0 or (p["qty"] > 0) == (d > 0):         # opening or adding: average price
            p["avg"] = round((abs(p["qty"]) * p["avg"] + qty * px) / abs(new), 4) if new else 0.0
        elif new and (new > 0) != (p["qty"] > 0):              # turned through zero: the rest opens at this price
            p["avg"] = px
        p["qty"] = new
        if new:
            self.pos[c] = p
        else:
            self.pos.pop(c, None)
            self.stops.pop(c, None)

    def _fresh(self, q: Quote | None, now: datetime) -> bool:
        return bool(q and q.at and abs((now - q.at).total_seconds()) <= FRESH)

    def _try(self, now: datetime) -> None:
        quotes = self.quotes()
        keep = []
        for oid, r in self.waiting:
            q = quotes.get(r.contract)
            px = (q.ask if r.side == "BUY" else q.bid) if self._fresh(q, now) else None
            if px and r.limit is not None and ((r.side == "BUY" and px > r.limit) or (r.side == "SELL" and px < r.limit)):
                px = None
            if not px:
                keep.append((oid, r))
                continue
            self._fill(r.contract, r.side, r.lots * r.contract.lot, px, now, oid, r.tag)
            st = self.stops.get(r.contract)
            if st and st.get("parent") == oid:
                st["live"] = True
        self.waiting = keep
        for c, st in list(self.stops.items()):
            q = quotes.get(c)
            if not st["live"] or not self._fresh(q, now):
                continue
            if st["side"] == "SELL":                             # protects a long: stop below
                seen = q.bid or q.last
                if seen and seen <= st["stop"]:
                    self._fill(c, "SELL", min(st["qty"], abs(self.pos.get(c, {}).get("qty", 0))) or st["qty"],
                               q.bid or seen, now, st["id"], st["kind"])
                    self.stops.pop(c, None)
                    continue
            else:                                                # protects a short: stop above
                seen = q.ask or q.last
                if seen and seen >= st["stop"]:
                    self._fill(c, "BUY", min(st["qty"], abs(self.pos.get(c, {}).get("qty", 0))) or st["qty"],
                               q.ask or seen, now, st["id"], st["kind"])
                    self.stops.pop(c, None)
                    continue
            if st["kind"] == "trail" and q.mid and ((q.mid > st["best"]) if st["side"] == "SELL" else (q.mid < st["best"])):
                st["best"] = q.mid
                st["stop"] = self._trail_stop(st)

    def _index_close(self, index: str, day: str, now: datetime) -> float | None:
        """The index's close on `day`: the live price at 15:30 that day, else IBKR's daily bars afterwards."""
        if day == now.date().isoformat():
            t = self._index(index)
            return t.last if t.last == t.last and t.last and t.last > 0 else None
        try:
            und = Index(IB_SYMBOL[index], "NSE", "INR")
            self.ib.qualifyContracts(und)
            bars = self.ib.reqHistoricalData(und, "", "15 D", "1 day", "TRADES", True, timeout=30)
        except Exception:                                        # noqa: BLE001 -- tried again on the next step
            return None
        return next((b.close for b in bars or [] if str(b.date)[:10] == day), None)

    def _settle(self, now: datetime) -> None:
        today, hm = now.date().isoformat(), now.strftime("%H:%M")
        for c, p in list(self.pos.items()):
            if c.expiry > today or (c.expiry == today and hm < "15:30"):
                continue
            close = self._index_close(c.index, c.expiry, now)
            if close is None:
                continue
            side = "SELL" if p["qty"] > 0 else "BUY"
            self._fill(c, side, abs(p["qty"]), c.value_at(close), now, self._id(), "expiry")

    def _new_day(self, now: datetime) -> None:
        """Unfilled entries go at the day's end, and day-only stops (as at the exchange)."""
        today = now.date().isoformat()
        if self.day == today:
            return
        dropped = {oid for oid, _ in self.waiting}
        self.waiting = []
        for c in [c for c, st in self.stops.items() if st.get("parent") in dropped or st.get("validity") == "DAY"
                  or (not st["live"] and c not in self.pos)]:
            del self.stops[c]
        self.day = today

    def poll_fills(self) -> list[Fill]:
        now = datetime.now()
        before = (self.n, json.dumps({c.key(): v for c, v in self.pos.items()}, sort_keys=True),
                  json.dumps({c.key(): v for c, v in self.stops.items()}, sort_keys=True, default=str))
        self._new_day(now)
        self._try(now)
        self._settle(now)
        after = (self.n, json.dumps({c.key(): v for c, v in self.pos.items()}, sort_keys=True),
                 json.dumps({c.key(): v for c, v in self.stops.items()}, sort_keys=True, default=str))
        if after != before or self.done:
            self._save()
        out, self.done = self.done, []
        return out

    # ---- a start or restart -------------------------------------------------------------------------------------------
    def restore(self) -> int:
        self.children = {c: {"kind": st["kind"]} for c, st in self.stops.items() if st["live"]}
        return len(self.children)

    def held(self) -> dict[Contract, int]:
        return {c: int(p["qty"]) for c, p in self.pos.items() if p["qty"]}

    def avg_costs(self) -> dict[Contract, float]:
        return {c: float(p["avg"]) for c, p in self.pos.items()}


def ibkr_orders(home: Path) -> bool:
    """True when orders should go to IBKR's own paper account again (the file ORDERS_AT_IBKR on the machine)."""
    return (home / "ORDERS_AT_IBKR").exists()

