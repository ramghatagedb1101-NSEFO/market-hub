"""Plain records shared by every part of the program."""
from dataclasses import dataclass, field
from datetime import datetime

LOT = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20}        # as hub/rule_test.py and relay/Paper.gs
EXCH = {"NIFTY": "NSE", "BANKNIFTY": "NSE", "SENSEX": "BSE"}


@dataclass(frozen=True, order=True)
class Contract:
    index: str            # NIFTY, BANKNIFTY, SENSEX
    expiry: str           # YYYY-MM-DD
    strike: float
    right: str            # "C" or "P"

    @property
    def lot(self) -> int:
        return LOT[self.index]

    @property
    def exchange(self) -> str:
        return EXCH[self.index]

    def key(self) -> str:
        k = int(self.strike) if float(self.strike).is_integer() else self.strike
        return f"{self.index} {self.expiry} {k}{self.right}"

    def value_at(self, index_close: float) -> float:
        """What one unit is worth at settlement against the index close."""
        return max(index_close - self.strike, 0.0) if self.right == "C" else max(self.strike - index_close, 0.0)


@dataclass
class Quote:
    bid: float | None
    ask: float | None
    last: float | None
    at: datetime          # when this price was last updated

    @property
    def mid(self) -> float | None:
        if self.bid and self.ask and self.ask >= self.bid > 0:
            return (self.bid + self.ask) / 2
        return self.last or None

    def spread_share(self) -> float | None:
        """Bid-ask gap as a share of the middle price (None when either side is missing)."""
        if self.bid and self.ask and self.ask >= self.bid > 0:
            return (self.ask - self.bid) / ((self.ask + self.bid) / 2)
        return None


@dataclass
class OrderRequest:
    contract: Contract
    side: str             # "BUY" or "SELL"
    lots: int
    limit: float | None   # None: the broker prices it at the far side of the quote
    reason: str           # why the strategy wants it, in words (goes to the journal)
    closing: bool = False # True when it only reduces an open position (always allowed, even after the kill switch)
    tag: str = ""         # the strategy's own label, e.g. "condor-entry"
    hedge: bool = False   # a bought wing that caps a sold leg's loss: no stop-loss (a stop would remove the cap)
    exits: dict | None = None   # the strategy's exits for the position this opens (trader/engine.py default_exits)
    regime: str | None = None   # market condition at entry (trader/regime.py), for records by condition


@dataclass
class Fill:
    contract: Contract
    side: str
    qty: int              # units, not lots
    price: float
    at: datetime
    charges: float
    order_id: str = ""
    tag: str = ""


@dataclass
class Settings:
    """One run's settings (a JSON file on the machine; defaults are deliberately small)."""
    strategy: str = ""                    # empty: watch only, never trade
    params: dict = field(default_factory=dict)
    max_lots_per_order: int = 1
    max_open_legs: int = 4
    max_orders_per_day: int = 20
    max_daily_loss: float = 10000.0       # rupees, booked plus open; reaching it closes everything and stops entries
    entry_from: str = "09:20"
    entry_until: str = "15:25"
    stale_seconds: float = 10.0           # a price older than this is not traded on
    max_spread_share: float = 0.25        # bid-ask gap above 25% of the middle price: too thin to trade
    # Every option BUY that opens a position goes with an attached stop-loss (owner, 14 Nov 2026). Once the price is up
    # by trail_after_gain on the entry, that stop is replaced by a trailing stop trail_by below the highest price since.
    # Shares of the entry price; starting values, to be tuned on the ICICI minute history before they are trusted.
    stop_loss: float = 0.25               # stop 25% below the entry price
    trail_after_gain: float = 0.20        # switch to trailing once 20% up
    trail_by: float = 0.10                # trailing stop 10% below the highest price since
