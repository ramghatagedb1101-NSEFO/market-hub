"""
The safety limits. Every order request passes check() before it reaches a broker; a refusal is journalled with its
reason and the order is dropped (never retried blindly).

Requests that only close an open position are always allowed (even after the kill switch), as long as they really
reduce that position. Everything else must pass every limit in Settings.

The kill switch: once tripped (daily loss reached, the STOP file on the machine, or a broker refusing to confirm the
account is paper) it stays tripped for the day; the engine then closes everything and opens nothing new.
"""
from datetime import datetime

from .book import Book
from .model import OrderRequest, Quote, Settings


def _hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


class Guard:
    def __init__(self, s: Settings):
        self.s = s
        self.killed = ""            # reason, empty while trading is allowed
        self.orders_today = 0
        self.day = None
        self.day_start = 0.0        # the book's profit when the day began: the loss limit counts from here

    def new_day(self, now: datetime, book: Book | None = None) -> None:
        """A new session: order count, the day's loss and the day's stop start again (one engine can span several
        sessions in a back-test over a whole expiry week; the live program starts a fresh engine each day)."""
        if self.day != now.date():
            self.day, self.orders_today, self.killed = now.date(), 0, ""
            self.day_start = book.pnl() if book is not None else 0.0

    def kill(self, reason: str) -> bool:
        """Trip the switch; True only the first time (so the engine closes positions once)."""
        if self.killed:
            return False
        self.killed = reason
        return True

    def watch(self, book: Book) -> str:
        """Called after every mark: trips the switch when the day's loss limit is reached."""
        lost = self.day_start - book.pnl()
        if not self.killed and lost >= self.s.max_daily_loss:
            self.kill(f"day's loss {lost:,.0f} reached the limit {self.s.max_daily_loss:,.0f}")
        return self.killed

    def check(self, r: OrderRequest, q: Quote | None, book: Book, now: datetime) -> str:
        """Empty string = allowed; otherwise the reason it is refused."""
        if r.lots < 1:
            return "no lots"
        held = book.qty.get(r.contract, 0)
        if r.closing:
            reduces = (held > 0 and r.side == "SELL") or (held < 0 and r.side == "BUY")
            if not reduces or r.lots * r.contract.lot > abs(held):
                return "marked as closing but does not reduce an open position"
            return ""
        if self.killed:
            return f"stopped for the day: {self.killed}"
        if held:
            return "already holding this contract (one entry per contract; its stop covers that entry only)"
        if not (self.s.entry_from <= _hhmm(now) <= self.s.entry_until):
            return f"outside {self.s.entry_from}-{self.s.entry_until}"
        if r.lots > self.s.max_lots_per_order:
            return f"{r.lots} lots is above the limit of {self.s.max_lots_per_order}"
        if self.orders_today >= self.s.max_orders_per_day:
            return f"{self.orders_today} orders today already (limit {self.s.max_orders_per_day})"
        if held == 0 and book.open_legs() >= self.s.max_open_legs:
            return f"{book.open_legs()} open legs already (limit {self.s.max_open_legs})"
        if q is None or not q.mid:
            return "no price"
        age = (now - q.at).total_seconds()
        if age > self.s.stale_seconds:
            return f"price is {age:.0f} seconds old"
        sp = q.spread_share()
        if sp is not None and sp > self.s.max_spread_share:
            return f"bid-ask gap {sp:.0%} of the price"
        return ""

    def sent(self) -> None:
        self.orders_today += 1
