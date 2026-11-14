"""
Positions and money, worked out only from fills (nothing is typed in). Profit and loss = cash moved by fills and
charges + what the open positions are worth at the latest prices.
"""
from .model import Contract, Fill, Quote

STT_EXERCISE = 0.0015       # buyer's STT on an option that settles in the money (hub/rule_test.py RATES)


class Book:
    def __init__(self):
        self.qty: dict[Contract, int] = {}        # units; + bought, - sold
        self.cash = 0.0                           # premium in and out, minus every charge
        self.charges = 0.0
        self.marks: dict[Contract, float] = {}    # last price used to value each open position
        self.fills: list[Fill] = []

    def apply(self, f: Fill) -> None:
        sign = 1 if f.side == "BUY" else -1
        self.qty[f.contract] = self.qty.get(f.contract, 0) + sign * f.qty
        if self.qty[f.contract] == 0:
            del self.qty[f.contract]
        self.cash += -sign * f.price * f.qty - f.charges
        self.charges += f.charges
        self.marks.setdefault(f.contract, f.price)
        self.fills.append(f)

    def mark(self, quotes: dict[Contract, Quote]) -> None:
        for c in self.qty:
            q = quotes.get(c)
            if q and q.mid:
                self.marks[c] = q.mid

    def open_value(self) -> float:
        return sum(q * self.marks.get(c, 0.0) for c, q in self.qty.items())

    def pnl(self) -> float:
        return self.cash + self.open_value()

    def open_legs(self) -> int:
        return len(self.qty)

    def settle(self, index: str, expiry: str, index_close: float) -> float:
        """Every open option of that index and expiry settles at its value against the close. Returns the cash moved."""
        moved = 0.0
        for c in [c for c in self.qty if c.index == index and c.expiry == expiry]:
            q, v = self.qty.pop(c), c.value_at(index_close)
            stt = v * q * STT_EXERCISE if q > 0 and v > 0 else 0.0
            self.cash += q * v - stt
            self.charges += stt
            self.marks[c] = v
            moved += q * v - stt
        return moved

    def closing_requests(self, reason: str):
        """Requests that would close everything (used by the kill switch)."""
        from .model import OrderRequest
        return [OrderRequest(c, "SELL" if q > 0 else "BUY", abs(q) // c.lot, None, reason, closing=True, tag="close-all")
                for c, q in sorted(self.qty.items())]
