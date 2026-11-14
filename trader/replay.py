"""
Replay: run the program over one downloaded expiry (ICICI one-minute candles for the day before expiry and the expiry
day, every strike in the stored chain; hub/breeze_history.py). The engine steps once a minute.

Prices: a contract's quote at a minute is its last one-minute close so far, dated at that candle (so the engine's
"price too old" limit applies). There is no bid or ask in the history; they are set at the close minus / plus the
back-tests' slippage (hub/rule_test.py: the larger of 0.10 or 2% of the price), and orders fill there.
Charges: hub/rule_test.py's table (Zerodha's published rates). Settlement: the index close on expiry day from the
expiry record (state/expiry_history/records.json).

    python -m trader.replay NIFTY 2026-11-03 [--strategy expiry_condor] [--echo]
"""
import argparse
import bisect
import sys
from datetime import datetime, timedelta

from hub.rule_test import charges, slip

from .engine import Engine
from .journal import Journal
from .model import Contract, Fill, OrderRequest, Quote, Settings

OPEN = (9, 15)
MINUTES = 376                   # 09:15 .. 15:30


def at(day: str, minute: int) -> datetime:
    d = datetime.strptime(day, "%Y-%m-%d")
    return d.replace(hour=OPEN[0], minute=OPEN[1]) + timedelta(minutes=minute)


class ReplayFeed:
    """
    index_days (optional): the index's own one-minute bars by date, {"YYYY-MM-DD": [[min, o, h, l, c, v], ...]}
    (hub/breeze_index.py), including at least one session before prev_day so the builder's signals have history.
    """

    def __init__(self, index: str, entry: dict, index_days: dict | None = None):
        self.index, self.e = index, entry
        self.days = [entry["prev_day"], entry["expiry"]]
        self.series: dict[Contract, list] = {}
        self.keys: dict[Contract, list] = {}
        for right, side in (("C", "call"), ("P", "put")):
            for k, rows in (entry.get(side) or {}).items():
                rows = [r for r in sorted(rows) if r[5]]
                if rows:
                    c = Contract(index, entry["expiry"], float(k), right)
                    self.series[c], self.keys[c] = rows, [(r[0], r[1]) for r in rows]
        self.pos = (0, 0)
        self.subscribed: set[Contract] = set()
        self.ibars, self.ikeys, self.prev = [], [], {}
        for d in sorted(index_days or {}):
            if d > self.days[1]:
                continue
            for m, o, h, l, c, *_ in index_days[d]:
                t = at(d, m)
                self.ibars.append((t, o, h, l, c))
            self.prev[d] = index_days[d][-1][4] if index_days[d] else None
        self.ikeys = [b[0] for b in self.ibars]

    def index_bars(self, index: str) -> list:
        """One-minute index bars up to and including the current minute (the engine's signals drop the last one)."""
        if index != self.index:
            return []
        return self.ibars[:bisect.bisect_right(self.ikeys, self.now())]

    def prev_close(self, index: str) -> float | None:
        today = self.days[self.pos[0]]
        before = [d for d in self.prev if d < today]
        return self.prev[before[-1]] if before and index == self.index else None

    def move(self, day: int, minute: int) -> None:
        self.pos = (day, minute)

    def now(self) -> datetime:
        return at(self.days[self.pos[0]], self.pos[1])

    def quote(self, c: Contract) -> Quote | None:
        ks = self.keys.get(c)
        i = bisect.bisect_right(ks, self.pos) if ks else 0
        if not i:
            return None
        last = self.series[c][i - 1]
        px = float(last[5])
        return Quote(max(px - slip(px), 0.05), px + slip(px), px, at(self.days[last[0]], last[1]))

    def quotes(self) -> dict[Contract, Quote]:
        out = {}
        for c in self.subscribed:
            q = self.quote(c)
            if q:
                out[c] = q
        return out

    def subscribe(self, contracts) -> None:
        self.subscribed = set(contracts)

    def expiries(self, index: str) -> list[str]:
        return [self.e["expiry"]] if index == self.index else []

    def strikes(self, index: str, expiry: str) -> list[float]:
        if index != self.index or expiry != self.e["expiry"]:
            return []
        return sorted({c.strike for c in self.series})

    def is_day_before(self, expiry: str) -> bool:
        return expiry == self.e["expiry"] and self.pos[0] == 0


class ReplayBroker:
    """
    Fills at once at the replay's bid / ask; a limit that is not reached waits and is cancelled at the day's end.

    Stops (attached to an entry, or the trailing stop that replaces it) are checked against each minute's candle: a
    sell-stop below a long is hit when the minute's low reaches it, a buy-stop above a short when the high does; it
    fills at the stop -- or at the minute's open when the price opened through it -- with slippage against us. Only
    then does a trailing stop follow the minute's best price (the cautious order, since a candle does not say whether
    its high or low came first). Trailing distance in % or points.
    """

    def __init__(self, feed: ReplayFeed):
        self.feed = feed
        self.waiting: list[tuple[str, OrderRequest]] = []
        self.stops: dict[Contract, dict] = {}      # one protective sell per long position
        self.done: list[Fill] = []
        self.n = 0

    def _id(self) -> str:
        self.n += 1
        return f"R{self.n}"

    def submit(self, r: OrderRequest, q: Quote | None, now: datetime, stop: float | None = None,
               validity: str = "GTC") -> str:
        oid = self._id()
        self.waiting.append((oid, r))
        if stop is not None:                       # child: works only once the parent has filled
            self.stops[r.contract] = {"id": self._id(), "parent": oid, "kind": "stop", "stop": stop,
                                      "side": "SELL" if r.side == "BUY" else "BUY", "validity": validity,
                                      "qty": r.lots * r.contract.lot, "live": False}
        self._try(now)
        return oid

    def trail(self, c: Contract, by: float, now: datetime, by_type: str = "pct") -> str:
        """Replace the stop with a trailing stop `by` (% or points) behind the best price from now on."""
        old = self.stops.get(c)
        if not old or not old["live"]:
            return ""
        q = self.feed.quote(c)
        best = q.last if q else old["stop"]
        st = {"id": self._id(), "parent": "", "kind": "trail", "by": by, "by_type": by_type, "best": best,
              "side": old["side"], "validity": old["validity"], "qty": old["qty"], "live": True, "from": self.feed.pos}
        st["stop"] = self._trail_stop(st)
        self.stops[c] = st
        return st["id"]

    @staticmethod
    def _trail_stop(st: dict) -> float:
        d = st["best"] * st["by"] / 100 if st["by_type"] == "pct" else st["by"]
        return st["best"] - d if st["side"] == "SELL" else st["best"] + d

    def cancel_children(self, c: Contract) -> None:
        self.stops.pop(c, None)

    def stop_of(self, c: Contract) -> dict | None:
        return self.stops.get(c)

    def _candle(self, c: Contract):
        ks = self.feed.keys.get(c)
        if not ks:
            return None
        i = bisect.bisect_left(ks, self.feed.pos)
        return self.feed.series[c][i] if i < len(ks) and ks[i] == self.feed.pos else None

    def _try(self, now: datetime) -> None:
        keep = []
        for oid, r in self.waiting:
            q = self.feed.quote(r.contract)
            px = None
            if q:
                px = q.ask if r.side == "BUY" else q.bid
                if r.limit is not None and ((r.side == "BUY" and px > r.limit) or (r.side == "SELL" and px < r.limit)):
                    px = None
            if px is None:
                keep.append((oid, r))
                continue
            qty = r.lots * r.contract.lot
            self.done.append(Fill(r.contract, r.side, qty, px, now,
                                  charges(px, qty, r.side.lower(), r.contract.exchange), oid, r.tag))
            st = self.stops.get(r.contract)
            if st and st.get("parent") == oid:
                st["live"], st["from"] = True, self.feed.pos
        self.waiting = keep
        self._stops(now)

    def _stops(self, now: datetime) -> None:
        for c, st in list(self.stops.items()):
            row = self._candle(c) if st["live"] else None
            if not row or (row[0], row[1]) == st.get("from"):
                continue                           # the minute it started in: its range may come from before
            o, h, l = float(row[2] or row[5]), float(row[3] or row[5]), float(row[4] or row[5])
            sell = st["side"] == "SELL"            # protects a long (stop below) or a short (stop above)
            if (l <= st["stop"]) if sell else (h >= st["stop"]):
                base = min(st["stop"], o) if sell else max(st["stop"], o)
                px = max(base - slip(base), 0.05) if sell else base + slip(base)
                self.done.append(Fill(c, st["side"], st["qty"], px, now,
                                      charges(px, st["qty"], st["side"].lower(), c.exchange), st["id"], st["kind"]))
                del self.stops[c]
                continue
            if st["kind"] == "trail" and ((h > st["best"]) if sell else (l < st["best"])):
                st["best"] = h if sell else l
                st["stop"] = self._trail_stop(st)

    def poll_fills(self) -> list[Fill]:
        self._try(self.feed.now())
        out, self.done = self.done, []
        return out

    def working(self) -> set[Contract]:
        return {r.contract for _, r in self.waiting}

    def open_orders(self) -> list[dict]:
        """Orders still working: entries not yet filled, and the stop or trailing stop of each long position."""
        out = [{"id": oid, "contract": r.contract.key(), "side": r.side, "qty": r.lots * r.contract.lot,
                "type": "Limit" if r.limit is not None else "At market", "price": r.limit, "tag": r.tag}
               for oid, r in self.waiting]
        out += [{"id": st["id"], "contract": c.key(), "side": st["side"], "qty": st["qty"],
                 "type": "Trailing stop" if st["kind"] == "trail" else "Stop-loss", "price": round(st["stop"], 2),
                 "tag": st["kind"], "waiting_for_entry": not st["live"]} for c, st in self.stops.items()]
        return out

    def end_of_day(self) -> int:
        """Unfilled entry orders are cancelled, and day-only stops; good-till-cancelled stops of open positions stay."""
        dropped = {oid for oid, _ in self.waiting}
        for c in [c for c, st in self.stops.items() if st.get("parent") in dropped or st.get("validity") == "DAY"]:
            del self.stops[c]
        n, self.waiting = len(self.waiting), []
        return n


def run(index: str, entry: dict, index_close: float | None, strategy, settings: Settings, journal: Journal,
        index_days: dict | None = None) -> Engine:
    feed = ReplayFeed(index, entry, index_days)
    broker = ReplayBroker(feed)
    eng = Engine(feed, broker, strategy, settings, journal)
    for day in (0, 1):
        for m in range(MINUTES):
            feed.move(day, m)
            eng.step(feed.now())
        if broker.end_of_day():
            journal.write(feed.now(), "note", text="unfilled orders cancelled at the day's end")
    if index_close is not None:
        eng.settle(feed.now(), index, entry["expiry"], index_close)
    else:
        journal.write(feed.now(), "note", text="no index close on record: open positions left unsettled")
    return eng


def main() -> int:
    from hub.breeze_history import DIR, load_gz
    from hub.expiry_history import load
    from .strategies import make

    ap = argparse.ArgumentParser()
    ap.add_argument("index")
    ap.add_argument("expiry")
    ap.add_argument("--strategy", default="expiry_condor")
    ap.add_argument("--echo", action="store_true")
    a = ap.parse_args()
    entry = load_gz(f"{DIR}/{a.index}/{a.expiry}.json.gz")
    if not entry:
        print("not downloaded yet")
        return 1
    rec = (load("state/expiry_history/records.json") or {}).get(f"{a.index}_{a.expiry}") or {}
    s = Settings(strategy=a.strategy, params={"indices": [a.index]}, stale_seconds=300)
    j = Journal(echo=a.echo)
    eng = run(a.index, entry, rec.get("close"), make(s), s, j)
    print(f"{a.index} {a.expiry}: {j.count('order')} orders, {j.count('fill')} fills, {j.count('refused')} refused, "
          f"profit after charges {eng.book.pnl():,.0f} (charges {eng.book.charges:,.0f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
