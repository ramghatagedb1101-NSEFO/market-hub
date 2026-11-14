"""
One step of the program, the same live (every 2 seconds) and in replay (every minute of history):
  1. take any fills the broker reports and book them
  2. value the open positions at the latest prices
  3. kill switch: STOP file, day's loss limit
  4. stopped: close whatever is open (once per position, while no close is already working)
     otherwise: ask the strategy what it wants
  5. every request passes the safety limits; refusals are journalled with the reason, the rest go to the broker

Protection (owner, 14 Nov 2026: "every order to buy options should go with an attached child stop loss ... once ... a
decent amount of profit this stop loss order should cancel and a new trailing stop loss should be activated"):
  - every BUY that opens a position is sent with a child stop-loss at stop_loss below the expected entry price; it
    sits with the broker (on IBKR's servers), so it works even if this program or the machine stops
  - each step, once the price is trail_after_gain above the actual entry, the broker puts on a trailing stop trail_by
    below the highest price since and only then cancels the fixed stop (one-cancels-other, so never two sells)
  - not on a bought wing that caps a sold leg (OrderRequest.hedge): a stop there would take away the cap
  - any other exit of that position (the strategy's, or the kill switch's) cancels its stop first, so it cannot sell
    twice

A feed gives prices: quotes(), subscribe(contracts), strikes(index, expiry), expiries(index), is_day_before(expiry).
A broker takes orders: submit(request, quote, now) -> order id, poll_fills() -> fills, working() -> contracts with an
order still open.
"""
from datetime import datetime
from pathlib import Path

from .book import Book
from .journal import Journal
from .model import Contract, OrderRequest, Quote, Settings
from .risk import Guard


class View:
    """What a strategy may look at (read-only by convention)."""

    def __init__(self, now: datetime, quotes: dict[Contract, Quote], book: Book, feed, settings: Settings):
        self.now, self.quotes, self.book, self.feed, self.settings = now, quotes, book, feed, settings


class Engine:
    MARK_EVERY = 60                    # seconds between profit lines in the journal

    def __init__(self, feed, broker, strategy, settings: Settings, journal: Journal, stop_file: str | None = None):
        self.feed, self.broker, self.strategy, self.s, self.j = feed, broker, strategy, settings, journal
        self.book, self.guard = Book(), Guard(settings)
        self.stop_file = Path(stop_file) if stop_file else None
        self.last_mark = None
        self.protect: dict[Contract, dict] = {}     # long positions with a stop: entry price, "stop" or "trail"

    def step(self, now: datetime) -> None:
        self.guard.new_day(now)
        for f in self.broker.poll_fills():
            self.book.apply(f)
            self.j.write(now, "fill", contract=f.contract.key(), side=f.side, qty=f.qty, price=f.price,
                         charges=round(f.charges, 2), tag=f.tag, order=f.order_id)
            self._protection_after(f, now)
        quotes = self.feed.quotes()
        self.book.mark(quotes)
        self._trail(quotes, now)
        if hasattr(self.broker, "ratchet"):
            self.broker.ratchet(quotes)

        if self.stop_file and self.stop_file.exists() and self.guard.kill("STOP file on the machine"):
            self.j.write(now, "kill", reason=self.guard.killed)
        was = self.guard.killed
        if self.guard.watch(self.book) and not was:
            self.j.write(now, "kill", reason=self.guard.killed)

        if self.guard.killed:
            busy = self.broker.working()
            reqs = [r for r in self.book.closing_requests(f"closing: {self.guard.killed}") if r.contract not in busy]
        else:
            if self.strategy:
                self.feed.subscribe(self.strategy.wants(View(now, quotes, self.book, self.feed, self.s)))
            reqs = self.strategy.step(View(now, quotes, self.book, self.feed, self.s)) if self.strategy else []

        for r in reqs:
            q = quotes.get(r.contract)
            why = self.guard.check(r, q, self.book, now)
            if why:
                self.j.write(now, "refused", contract=r.contract.key(), side=r.side, lots=r.lots, reason=why,
                             wanted=r.reason)
                continue
            stop = None
            if r.closing:
                if r.contract in self.protect:
                    self.broker.cancel_children(r.contract)
                    self.j.write(now, "stop-cancelled", contract=r.contract.key(), why="position being closed")
                    self.protect.pop(r.contract)
            elif r.side == "BUY" and not r.hedge:
                ref = r.limit or (q.ask if q and q.ask else q.mid)
                stop = round(ref * (1 - self.s.stop_loss), 2)
            oid = self.broker.submit(r, q, now, stop=stop)
            self.guard.sent()
            self.j.write(now, "order", contract=r.contract.key(), side=r.side, lots=r.lots, limit=r.limit,
                         reason=r.reason, closing=r.closing, order=oid, stop=stop)

        if self.last_mark is None or (now - self.last_mark).total_seconds() >= self.MARK_EVERY:
            self.last_mark = now
            self.j.write(now, "mark", pnl=round(self.book.pnl(), 2), open_legs=self.book.open_legs(),
                         charges=round(self.book.charges, 2), killed=self.guard.killed or None,
                         positions={c.key(): [q, round(self.book.marks.get(c, 0.0), 2),
                                              (self.protect.get(c) or {}).get("state")]
                                    for c, q in self.book.qty.items()},
                         orders=self.broker.open_orders() if hasattr(self.broker, "open_orders") else None)

    def _protection_after(self, f, now: datetime) -> None:
        c = f.contract
        if f.side == "BUY" and self.book.qty.get(c, 0) > 0 and c not in self.protect:
            self.protect[c] = {"entry": f.price, "state": "stop"}
        elif f.side == "SELL" and self.book.qty.get(c, 0) <= 0 and c in self.protect:
            self.protect.pop(c)
            if f.tag in ("stop", "trail"):
                self.j.write(now, f"{f.tag}-hit", contract=c.key(), price=f.price)

    def _trail(self, quotes: dict, now: datetime) -> None:
        for c, p in self.protect.items():
            q = quotes.get(c)
            if p["state"] != "stop" or not q or not q.mid or q.mid < p["entry"] * (1 + self.s.trail_after_gain):
                continue
            oid = self.broker.trail(c, self.s.trail_by, now)
            if oid:
                p["state"] = "trail"
                self.j.write(now, "trail-on", contract=c.key(), entry=p["entry"], price=q.mid, by=self.s.trail_by,
                             order=oid)

    def settle(self, now: datetime, index: str, expiry: str, index_close: float) -> None:
        for c in [c for c in self.protect if c.index == index and c.expiry == expiry]:
            self.broker.cancel_children(c)
            self.protect.pop(c)
        moved = self.book.settle(index, expiry, index_close)
        self.j.write(now, "settle", index=index, expiry=expiry, index_close=index_close, cash=round(moved, 2),
                     pnl=round(self.book.pnl(), 2))
