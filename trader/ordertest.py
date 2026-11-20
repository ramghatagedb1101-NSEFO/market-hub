"""
Will IBKR take an order from the program? (owner, 20 Nov 2026: "We can try a manual order"). On Fri 20 Nov 2026 IBKR
refused autopilot's order: "API orders for NSE instruments are not allowed" (error 201), though the same kind of order
filled on 16-17 Nov. This sends two PAPER test orders that cannot fill, reports what IBKR answers, and cancels them:
  1. buy 1 lot of a far-from-the-money NIFTY call at Rs 0.05 (the lowest price)
  2. buy 1 RELIANCE share at Rs 1 (is it every NSE order, or only options?)
Paper only: IBKR.connect() refuses any account not starting "DU". Prints no account number.
    /opt/trader/venv/bin/python -m trader.ordertest      (bt-worker-setup.yml order_test)
"""
from ib_async import Index, LimitOrder, Option, Stock

from .ibkr import IB_SYMBOL, IBKR
from .model import LOT


def _try(br: IBKR, contract, qty: int, px: float, label: str) -> None:
    ib, said = br.ib, []
    got = ib.qualifyContracts(contract)
    if not got:
        print(f"{label}: IBKR does not know this contract (nothing sent)")
        return
    hook = lambda rid, code, text, *rest: said.append(f"{code}: {text}")   # noqa: E731
    ib.errorEvent += hook
    o = LimitOrder("BUY", qty, px, tif="DAY", orderRef="test")
    t = ib.placeOrder(got[0], o)
    ib.sleep(12)
    st = t.orderStatus.status
    print(f"{label}: IBKR status {st}")
    for m in dict.fromkeys(said + [e.message for e in t.log if e.message]):
        print("   ", str(m)[:300])
    if st in ("Submitted", "PreSubmitted", "PendingSubmit", "ApiPending"):
        ib.cancelOrder(o)
        ib.sleep(5)
        print(f"    cancelled: {t.orderStatus.status}")
    ib.errorEvent -= hook
    verdict = ("ACCEPTED (the program can place this kind of order)" if st in ("Submitted", "PreSubmitted", "Cancelled", "ApiCancelled")
               and not any(s.startswith("201") for s in said) else "REFUSED" if any(s.startswith("201") for s in said) or st == "Inactive"
               else "unclear")
    print(f"    => {verdict}")


def main() -> None:
    br = IBKR(client_id=19)                     # its own connection; the trading program (11) is not touched
    br.connect()                                # paper-only guard
    print("connected to the paper account")
    und = Index(IB_SYMBOL["NIFTY"], "NSE", "INR")
    br.ib.qualifyContracts(und)
    bars = br.ib.reqHistoricalData(und, "", "3 D", "1 day", "TRADES", True, timeout=30)
    close = bars[-1].close if bars else 26000.0
    p = br.chain("NIFTY")
    exp = sorted(p.expirations)[0]
    far = [s for s in sorted(p.strikes) if s >= close * 1.06 and s % 100 == 0] or sorted(p.strikes)[-1:]
    strike = far[0]
    print(f"NIFTY last close {close:.0f}; test option NIFTY {exp} {strike:.0f} CE")
    _try(br, Option(IB_SYMBOL["NIFTY"], exp, strike, "C", p.exchange, p.multiplier, "INR", tradingClass=p.tradingClass),
         LOT["NIFTY"], 0.05, "1. NIFTY option, 1 lot at Rs 0.05")
    _try(br, Stock("RELIANCE", "NSE", "INR"), 1, 1.0, "2. RELIANCE share, 1 at Rs 1")
    br.ib.disconnect()


if __name__ == "__main__":
    main()
