"""
Prices and orders through the IBKR gateway on market-hub-trader (127.0.0.1:4002, paper). Written 14 Nov 2026; names and
quantities confirmed against the paper account by infra/trader/check.py the same day. Order behaviour on NSE options
(stop and trailing orders) is confirmed only once the first paper orders go through.

Safety:
  - connect() refuses any account whose number does not start with "DU" (IBKR paper accounts); nothing is sent.
  - an option BUY that opens a position goes as a bracket: the limit order, plus a child stop-loss (good till
    cancelled) that IBKR holds on its own servers -- it works even if this program or the machine is down.
  - the child stop sits in its own one-cancels-other group. trail() first places a trailing stop in the same group,
    then cancels the fixed stop: at no moment can both sell. If IBKR refuses a trailing stop on that contract, the
    fixed stop is kept and moved up by the program instead (ratchet), never down.
  - orders are limit orders: "no limit" means a marketable limit two ticks through the far side of the quote.
"""
import math
from datetime import date, datetime, timedelta

from ib_async import IB, Index, LimitOrder, Option, Order, StopOrder

from hub.holidays import is_session
from hub.rule_test import charges as table_charges

from .model import Contract, Fill, OrderRequest, Quote

IB_SYMBOL = {"NIFTY": "NIFTY50", "BANKNIFTY": "BANKNIFTY"}     # confirmed by check.py, Sat 14 Nov 2026
# IBKR lists NSE index options with multiplier 1 (check.py, 14 Nov 2026): order quantities are units, not lots.
TICK = 0.05


def _tick(px: float, up: bool) -> float:
    n = px / TICK
    return round((math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)) * TICK, 2)


class IBKR:
    def __init__(self, host="127.0.0.1", port=4002, client_id=11):
        self.ib = IB()
        self.host, self.port, self.cid = host, port, client_id
        self.params: dict[str, object] = {}        # index -> option-chain description from IBKR
        self.ib_contract: dict[Contract, Option] = {}
        self.tickers: dict[Contract, object] = {}
        self.children: dict[Contract, dict] = {}   # protective sell per long position: order, kind, oca group
        self.seen: set[str] = set()                # execution ids already reported
        self.tags: dict[int, str] = {}
        self.index_t: dict[str, object] = {}       # index -> live index ticker (for the builder's signals)
        self.bars: dict[str, list] = {}            # index -> one-minute bars (time, o, h, l, c), last three sessions

    # ---- connection -------------------------------------------------------------------------------------------
    def connect(self) -> list[str]:
        self.ib.connect(self.host, self.port, clientId=self.cid, timeout=20)
        accts = self.ib.managedAccounts()
        if not accts or not all(a.startswith("DU") for a in accts):
            self.ib.disconnect()
            raise SystemExit("not a paper account (paper account numbers start with DU): stopped, nothing sent")
        self.ib.reqMarketDataType(1)
        return accts

    def chain(self, index: str):
        if index not in self.params:
            und = Index(IB_SYMBOL[index], "NSE", "INR")
            self.ib.qualifyContracts(und)
            ps = self.ib.reqSecDefOptParams(und.symbol, "", und.secType, und.conId)
            self.params[index] = next((p for p in ps if p.exchange == "NSE"), ps[0] if ps else None)
        return self.params[index]

    def _ib(self, c: Contract) -> Option | None:
        if c not in self.ib_contract:
            p = self.chain(c.index)
            if not p:
                return None
            o = Option(IB_SYMBOL[c.index], c.expiry.replace("-", ""), c.strike, c.right, p.exchange, p.multiplier,
                       "INR", tradingClass=p.tradingClass)
            got = self.ib.qualifyContracts(o)
            self.ib_contract[c] = got[0] if got else None
        return self.ib_contract[c]

    def _ours(self, ib_c) -> Contract | None:
        for c, o in self.ib_contract.items():
            if o is not None and o.conId == ib_c.conId:
                return c
        return None

    # ---- feed ---------------------------------------------------------------------------------------------------
    def expiries(self, index: str) -> list[str]:
        p = self.chain(index)
        return sorted(f"{e[:4]}-{e[4:6]}-{e[6:]}" for e in (p.expirations if p else []))

    def strikes(self, index: str, expiry: str) -> list[float]:
        p = self.chain(index)
        return sorted(p.strikes) if p else []

    def _index(self, index: str):
        """Live index price, started with the last three sessions of one-minute bars so signals have history."""
        if index not in self.index_t:
            und = Index(IB_SYMBOL[index], "NSE", "INR")
            self.ib.qualifyContracts(und)
            try:
                hist = self.ib.reqHistoricalData(und, endDateTime="", durationStr="3 D", barSizeSetting="1 min",
                                                 whatToShow="TRADES", useRTH=True, formatDate=1)
            except Exception:
                hist = []
            self.bars[index] = [(b.date.astimezone().replace(tzinfo=None) if b.date.tzinfo else b.date,
                                 b.open, b.high, b.low, b.close) for b in hist or [] if isinstance(b.date, datetime)]
            self.index_t[index] = self.ib.reqMktData(und, "", False, False)
        return self.index_t[index]

    def index_bars(self, index: str) -> list:
        t = self._index(index)
        px = t.last if t.last == t.last and t.last and t.last > 0 else None
        if px:
            m = datetime.now().replace(second=0, microsecond=0)
            bars = self.bars[index]
            if bars and bars[-1][0] == m:
                b = bars[-1]
                bars[-1] = (m, b[1], max(b[2], px), min(b[3], px), px)
            elif not bars or bars[-1][0] < m:
                bars.append((m, px, px, px, px))
            cut = m - timedelta(days=5)
            if bars and bars[0][0] < cut:
                self.bars[index] = [b for b in bars if b[0] >= cut]
        return self.bars[index]

    def prev_close(self, index: str) -> float | None:
        t = self._index(index)
        return t.close if t.close == t.close and t.close and t.close > 0 else None

    def is_day_before(self, expiry: str) -> bool:
        """True when the next trading session after today is that expiry."""
        d = date.today() + timedelta(days=1)
        while not is_session(d):
            d += timedelta(days=1)
        return d.isoformat() == expiry

    def subscribe(self, contracts) -> None:
        want = set(contracts)
        for c in [c for c in self.tickers if c not in want and c not in self.children]:
            self.ib.cancelMktData(self.ib_contract[c])
            del self.tickers[c]
        for c in want - set(self.tickers):
            o = self._ib(c)
            if o is not None:
                self.tickers[c] = self.ib.reqMktData(o, "", False, False)

    def quotes(self) -> dict[Contract, Quote]:
        out = {}
        for c, t in self.tickers.items():
            ok = lambda x: x if x is not None and not math.isnan(x) and x > 0 else None
            when = t.time.astimezone().replace(tzinfo=None) if t.time else None
            if when:
                out[c] = Quote(ok(t.bid), ok(t.ask), ok(t.last), when)
        return out

    # ---- broker -------------------------------------------------------------------------------------------------
    def submit(self, r: OrderRequest, q: Quote | None, now: datetime, stop: float | None = None,
               validity: str = "GTC") -> str:
        o = self._ib(r.contract)
        if o is None:
            return ""
        px = r.limit
        if px is None:
            base = (q.ask if r.side == "BUY" else q.bid) if q else None
            base = base or (q.mid if q else None)
            if not base:
                return ""
            px = _tick(base + 2 * TICK, True) if r.side == "BUY" else max(_tick(base - 2 * TICK, False), TICK)
        qty = r.lots * r.contract.lot                  # units: IBKR's NSE option multiplier is 1
        parent = LimitOrder(r.side, qty, px, orderRef=r.tag or "entry", tif="DAY")
        parent.orderId = self.ib.client.getReqId()
        self.tags[parent.orderId] = r.tag
        if stop is None:
            self.ib.placeOrder(o, parent)
            return str(parent.orderId)
        oca, action = f"mh-{parent.orderId}", "SELL" if r.side == "BUY" else "BUY"
        child = StopOrder(action, qty, _tick(stop, action == "BUY"), orderRef="stop", tif=validity,
                          parentId=parent.orderId, ocaGroup=oca, ocaType=1)
        child.orderId = self.ib.client.getReqId()
        parent.transmit = False                        # the pair goes together
        self.ib.placeOrder(o, parent)
        trade = self.ib.placeOrder(o, child)
        self.tags[child.orderId] = "stop"
        self.children[r.contract] = {"trade": trade, "kind": "stop", "oca": oca, "qty": qty, "stop": child.auxPrice,
                                     "action": action, "tif": validity}
        return str(parent.orderId)

    def trail(self, c: Contract, by: float, now: datetime, by_type: str = "pct") -> str:
        """Trailing stop `by` (% or points) behind the best price; then the fixed stop is cancelled (same OCA group)."""
        ch = self.children.get(c)
        o = self._ib(c)
        if not ch or ch["kind"] != "stop" or o is None:
            return ""
        t = Order(action=ch["action"], orderType="TRAIL", totalQuantity=ch["qty"], tif=ch["tif"],
                  ocaGroup=ch["oca"], ocaType=1, orderRef="trail")
        if by_type == "pct":
            t.trailingPercent = round(by, 2)
        else:
            t.auxPrice = round(by, 2)                  # trailing amount in points
        t.orderId = self.ib.client.getReqId()
        trade = self.ib.placeOrder(o, t)
        self.ib.sleep(2)
        if trade.orderStatus.status in ("Cancelled", "ApiCancelled", "Inactive"):
            ch.update(kind="ratchet", by=by, by_type=by_type, best=None)   # IBKR refused: keep the stop, move it ourselves
            return f"ratchet-{ch['trade'].order.orderId}"
        self.ib.cancelOrder(ch["trade"].order)
        self.tags[t.orderId] = "trail"
        self.children[c] = {"trade": trade, "kind": "trail", "oca": ch["oca"], "qty": ch["qty"],
                            "action": ch["action"], "tif": ch["tif"]}
        return str(t.orderId)

    def ratchet(self, quotes: dict[Contract, Quote]) -> None:
        """Fallback trailing: move a kept fixed stop behind the best price seen, only ever towards profit."""
        for c, ch in self.children.items():
            q = quotes.get(c)
            if ch["kind"] != "ratchet" or not q or not q.mid:
                continue
            sell = ch["action"] == "SELL"              # protects a long
            ch["best"] = (max if sell else min)(ch["best"] or q.mid, q.mid)
            d = ch["best"] * ch["by"] / 100 if ch["by_type"] == "pct" else ch["by"]
            new = _tick(ch["best"] - d, False) if sell else _tick(ch["best"] + d, True)
            order = ch["trade"].order
            if (new > order.auxPrice) if sell else (new < order.auxPrice):
                order.auxPrice = new
                self.ib.placeOrder(self._ib(c), order)

    def cancel_children(self, c: Contract) -> None:
        ch = self.children.pop(c, None)
        if ch:
            self.ib.cancelOrder(ch["trade"].order)

    def working(self) -> set[Contract]:
        out = set()
        for t in self.ib.openTrades():
            if t.order.orderRef in ("stop", "trail"):
                continue
            c = self._ours(t.contract)
            if c:
                out.add(c)
        return out

    def open_orders(self) -> list[dict]:
        """Orders still working at IBKR (entries, stop-losses, trailing stops), for the screens' Pending tab."""
        kinds = {"LMT": "Limit", "STP": "Stop-loss", "TRAIL": "Trailing stop", "MKT": "At market"}
        out = []
        for t in self.ib.openTrades():
            c = self._ours(t.contract)
            if not c:
                continue
            o, st = t.order, t.orderStatus
            price = o.lmtPrice if o.orderType == "LMT" else (st.__dict__.get("trailStopPrice") or o.auxPrice)
            ok = lambda x: round(x, 2) if x is not None and not math.isnan(x) and 0 < x < 1e9 else None
            out.append({"id": str(o.orderId), "contract": c.key(), "side": o.action,
                        "qty": int(o.totalQuantity - (st.filled or 0)), "type": kinds.get(o.orderType, o.orderType),
                        "price": ok(price), "tag": o.orderRef, "status": st.status,
                        "trail_pct": o.trailingPercent if o.orderType == "TRAIL" else None})
        return out

    def poll_fills(self) -> list[Fill]:
        out = []
        for f in self.ib.fills():
            if f.execution.execId in self.seen:
                continue
            c = self._ours(f.contract)
            if not c:
                continue
            self.seen.add(f.execution.execId)
            side = "BUY" if f.execution.side == "BOT" else "SELL"
            units = int(f.execution.shares)
            # Charges: the full Indian table (brokerage Rs 20 an order, STT, exchange charges, stamp duty, SEBI fee, GST;
            # hub/rule_test.py), not IBKR's simulated paper commission, which may leave out the taxes (owner, 14 Nov
            # 2026: "brokerage, STT, taxes etc needs to be considered"). Same table as the back-tests, so they compare.
            fee = table_charges(f.execution.price, units, side.lower(), c.exchange)
            tag = f.execution.orderRef or self.tags.get(f.execution.orderId, "")
            if tag in ("stop", "trail") and c in self.children:
                del self.children[c]
            out.append(Fill(c, side, units, f.execution.price, f.time.astimezone().replace(tzinfo=None), fee,
                            str(f.execution.orderId), tag))
        return out

    def restore(self) -> int:
        """After a restart: pick up the protective stops IBKR is still holding, so they are managed again."""
        n = 0
        for t in self.ib.openTrades():
            if t.order.orderRef not in ("stop", "trail"):
                continue
            c = self._ours(t.contract)
            if c:
                self.children[c] = {"trade": t, "kind": t.order.orderRef, "oca": t.order.ocaGroup,
                                    "qty": int(t.order.totalQuantity), "stop": t.order.auxPrice,
                                    "action": t.order.action, "tif": t.order.tif or "GTC"}
                n += 1
        return n

    def held(self) -> dict[Contract, int]:
        """Open positions at IBKR in units (used on a restart, so the program never forgets what it holds)."""
        out = {}
        for p in self.ib.positions():
            c = self._ours(p.contract)
            if c is None and p.contract.secType == "OPT":
                idx = next((k for k, v in IB_SYMBOL.items() if v == p.contract.symbol), None)
                if idx:
                    e = p.contract.lastTradeDateOrContractMonth
                    c = Contract(idx, f"{e[:4]}-{e[4:6]}-{e[6:8]}", float(p.contract.strike), p.contract.right)
                    self.ib_contract[c] = p.contract
            if c and p.position:
                out[c] = int(p.position)
        return out
