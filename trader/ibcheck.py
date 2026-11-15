"""
Is the trading machine signed in to IBKR right now? (16 Nov 2026). Read-only, places nothing, prints no account number:
connects to the gateway, confirms a paper account (DU...), and asks IBKR for NIFTY's last daily close, which only
answers when the gateway is signed in and connected to IBKR's servers.
    /opt/trader/venv/bin/python -m trader.ibcheck        (bt-worker-setup.yml log_only runs it)
"""
import sys

from ib_async import IB, Index


def main() -> int:
    ib = IB()
    try:
        ib.connect("127.0.0.1", 4002, clientId=9, timeout=20, readonly=True)
    except Exception as e:                                       # noqa: BLE001
        print(f"IBKR: gateway not reachable ({type(e).__name__})")
        return 1
    acc = ib.managedAccounts()
    paper = bool(acc) and all(a.startswith("DU") for a in acc)
    bars = ib.reqHistoricalData(Index("NIFTY50", "NSE", "INR"), "", "3 D", "1 day", "TRADES", True, timeout=30)
    ib.disconnect()
    if not paper:
        print("IBKR: signed in, but NOT a paper account")
        return 1
    if not bars:
        print("IBKR: paper account connected, but IBKR's servers gave no prices (not signed in yet?)")
        return 1
    print(f"IBKR: signed in (paper); NIFTY last close {bars[-1].close:,.2f} on {bars[-1].date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
