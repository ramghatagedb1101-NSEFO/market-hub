"""
One step of the program, the same live (every 2 seconds) and in replay (every minute of history):
  1. take any fills the broker reports and book them
  2. value the open positions at the latest prices; manage their exits (trailing switch, target, exit-by time)
  3. kill switch: STOP file, day's loss limit
  4. stopped: close whatever is open (once per position, while no close is already working)
     otherwise: ask the strategy what it wants
  5. every request passes the safety limits; refusals are journalled with the reason, the rest go to the broker

Protection (owner, 14 Nov 2026: "every order to buy options should go with an attached child stop loss ... once ... a
decent amount of profit this stop loss order should cancel and a new trailing stop loss should be activated"; the
strategy builder the same day added targets, points as well as %, an exit-by time, day-only or good-till-cancelled
orders, and stops on sold options):
  - an order that opens a position is sent with a child stop-loss when it is a BUY (always; the Settings values unless
    its strategy gives its own exits) or when its strategy gives exits (a SELL then gets a buy-stop above the entry).
    The stop sits with the broker (on IBKR's servers), so it works even if this program or the machine stops.
  - each step, once the price has moved trail_after in the position's favour, the broker puts on a trailing stop and
    only then cancels the fixed stop (one-cancels-other, so never two exits)
  - target and exit-by time: the program closes the position (cancelling its stop first)
  - never on a bought wing that caps a sold leg (OrderRequest.hedge): a stop there would take away the cap
  - any other exit of that position (the strategy's, or the kill switch's) cancels its stop first

A feed gives prices: quotes(), subscribe(contracts), strikes(index, expiry), expiries(index), is_day_before(expiry),
and for the builder's signals index_bars(index), prev_close(index).
A broker takes orders: submit(request, quote, now, stop, validity) -> order id, trail(contract, by, now, by_type),
cancel_children(contract), poll_fills() -> fills, working() -> contracts with an order still open.
"""
from datetime import datetime, timedelta
from pathlib import Path

from .book import Book
from .journal import Journal
from .model import Contract, OrderRequest, Quote, Settings
from .risk import Guard


class View:
    """What a strategy may look at (read-only by convention)."""

    def __init__(self, now: datetime, quotes: dict[Contract, Quote], book: Book, feed, settings: Settings):
        self.now, self.quotes, self.book, self.feed, self.settings = now, quotes, book, feed, settings


def default_exits(s: Settings) -> dict:
    """The owner's standing rule for any option buy without exits of its own."""
    return {"sl_type": "pct", "sl": s.stop_loss * 100, "target_type": "pct", "target": 0,
            "trail_after_type": "pct", "trail_after": s.trail_after_gain * 100, "trail_type": "pct",
            "trail": s.trail_by * 100, "exit_by": None, "validity": "GTC"}


def _move(entry: float, kind: str, size: float) -> float:
    """Distance in price for a % or points setting."""
    return entry * size / 100 if kind == "pct" else size


class Engine:
    MARK_EVERY = 60                    # seconds between profit lines in the journal

    def __init__(self, feed, broker, strategy, settings: Settings, journal: Journal, stop_file: str | None = None):
        self.feed, self.broker, self.strategy, self.s, self.j = feed, broker, strategy, settings, journal
        self.book, self.guard = Book(), Guard(settings)
        self.stop_file = Path(stop_file) if stop_file else None
        self.last_mark = None
        self.protect: dict[Contract, dict] = {}     # protected positions: entry, direction, exits, "stop" / "trail"
        self.exits_of: dict[str, dict] = {}         # order id -> exits for the position it will open

    def step(self, now: datetime) -> None:
        self.guard.new_day(now, self.book)
        for f in self.broker.poll_fills():
            self.book.apply(f)
            # 14 Nov 2026: a fill is recorded at its own time (a back-test's 15:00 exit showed as 15:01, the minute it was
            # read); a time that is not in the last hour (e.g. another time zone) falls back to now
            when = f.at if isinstance(f.at, datetime) and timedelta(0) <= now - f.at <= timedelta(hours=1) else now
            self.j.write(when, "fill", contract=f.contract.key(), side=f.side, qty=f.qty, price=f.price,
                         charges=round(f.charges, 2), tag=f.tag, order=f.order_id)
            self._protection_after(f, now)
        quotes = self.feed.quotes()
        self.book.mark(quotes)
        managed = self._manage(quotes, now)
        if hasattr(self.broker, "ratchet"):
            self.broker.ratchet(quotes)

        if self.stop_file and self.stop_file.exists() and self.guard.kill("STOP file on the machine"):
            self.j.write(now, "kill", reason=self.guard.killed)
        was = self.guard.killed
        if self.guard.watch(self.book) and not was:
            self.j.write(now, "kill", reason=self.guard.killed)

        busy = self.broker.working()
        if self.guard.killed:
            reqs = [r for r in self.book.closing_requests(f"closing: {self.guard.killed}") if r.contract not in busy]
        else:
            reqs = [r for r in managed if r.contract not in busy]
            want = set(self.strategy.wants(View(now, quotes, self.book, self.feed, self.s))) if self.strategy else set()
            self.feed.subscribe(want | set(self.protect) | set(self.book.qty))   # held positions keep their prices
            if self.strategy:
                reqs += self.strategy.step(View(now, quotes, self.book, self.feed, self.s))

        for r in reqs:
            q = quotes.get(r.contract)
            why = self.guard.check(r, q, self.book, now)
            if why:
                self.j.write(now, "refused", contract=r.contract.key(), side=r.side, lots=r.lots, reason=why,
                             wanted=r.reason)
                continue
            stop, validity, ex = None, "GTC", None
            if r.closing:
                if r.contract in self.protect:
                    self.broker.cancel_children(r.contract)
                    self.j.write(now, "stop-cancelled", contract=r.contract.key(), why="position being closed")
                    self.protect.pop(r.contract)
            elif not r.hedge and (r.exits or r.side == "BUY"):
                ex = r.exits or default_exits(self.s)
                ref = r.limit or (q.ask if r.side == "BUY" and q and q.ask else q.bid if q and q.bid else q.mid)
                if ex.get("sl"):
                    d = _move(ref, ex.get("sl_type", "pct"), float(ex["sl"]))
                    stop = round(max(ref - d, 0.05), 2) if r.side == "BUY" else round(ref + d, 2)
                validity = ex.get("validity") or "GTC"
            oid = self.broker.submit(r, q, now, stop=stop, validity=validity)
            if ex and oid:
                self.exits_of[oid] = ex
            self.guard.sent()
            self.j.write(now, "order", contract=r.contract.key(), side=r.side, lots=r.lots, limit=r.limit,
                         reason=r.reason, closing=r.closing, order=oid, stop=stop, tag=r.tag,
                         validity=validity if stop else None, regime=r.regime)

        if self.last_mark is None or (now - self.last_mark).total_seconds() >= self.MARK_EVERY:
            self.last_mark = now
            self.j.write(now, "mark", pnl=round(self.book.pnl(), 2), open_legs=self.book.open_legs(),
                         charges=round(self.book.charges, 2), killed=self.guard.killed or None,
                         positions={c.key(): [q, round(self.book.marks.get(c, 0.0), 2),
                                              (self.protect.get(c) or {}).get("state")]
                                    for c, q in self.book.qty.items()},
                         orders=self.broker.open_orders() if hasattr(self.broker, "open_orders") else None)

    def _protection_after(self, f, now: datetime) -> None:
        c, held = f.contract, self.book.qty.get(f.contract, 0)
        ex = self.exits_of.pop(f.order_id, None)
        if ex and held and c not in self.protect and (held > 0) == (f.side == "BUY"):
            self.protect[c] = {"entry": f.price, "dir": 1 if held > 0 else -1, "ex": ex, "state": "stop"}
        elif held == 0 and c in self.protect:
            self.protect.pop(c)
            if f.tag in ("stop", "trail"):
                self.j.write(now, f"{f.tag}-hit", contract=c.key(), price=f.price)

    def _manage(self, quotes: dict, now: datetime) -> list[OrderRequest]:
        """Trailing switch, target and exit-by time for every protected position; returns the closes wanted."""
        out = []
        hhmm = now.strftime("%H:%M")
        for c, p in self.protect.items():
            q, ex, e, d = quotes.get(c), p["ex"], p["entry"], p["dir"]
            held = self.book.qty.get(c, 0)
            if not held:
                continue
            close = lambda why, tag: out.append(OrderRequest(c, "SELL" if held > 0 else "BUY", abs(held) // c.lot,
                                                             None, why, closing=True, tag=tag))
            if ex.get("exit_by") and hhmm >= ex["exit_by"]:
                close(f"exit time {ex['exit_by']}", "time-exit")
                continue
            if not q or not q.mid:
                continue
            gain = d * (q.mid - e)
            if ex.get("target") and gain >= _move(e, ex.get("target_type", "pct"), float(ex["target"])):
                close(f"target reached ({q.mid:g} from {e:g})", "target")
                continue
            if p["state"] == "stop" and ex.get("trail") and gain >= _move(e, ex.get("trail_after_type", "pct"),
                                                                           float(ex.get("trail_after") or 0)):
                oid = self.broker.trail(c, float(ex["trail"]), now, ex.get("trail_type", "pct"))
                if oid:
                    p["state"] = "trail"
                    self.j.write(now, "trail-on", contract=c.key(), entry=e, price=q.mid, by=ex["trail"],
                                 by_type=ex.get("trail_type", "pct"), order=oid)
        return out

    def settle(self, now: datetime, index: str, expiry: str, index_close: float) -> None:
        for c in [c for c in self.protect if c.index == index and c.expiry == expiry]:
            self.broker.cancel_children(c)
            self.protect.pop(c)
        moved = self.book.settle(index, expiry, index_close)
        self.j.write(now, "settle", index=index, expiry=expiry, index_close=index_close, cash=round(moved, 2),
                     pnl=round(self.book.pnl(), 2))
