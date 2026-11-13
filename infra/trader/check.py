"""
First check of the IBKR paper connection on market-hub-trader (13 Nov 2026). Places no orders.

Connects to the gateway on this machine (127.0.0.1:4002, paper), refuses to go on unless the account is a paper account
(IBKR paper account numbers start with "DU"), then looks up how IBKR lists NIFTY, BANK NIFTY and SENSEX and their
option expiries and strikes -- the names and exchanges the paper trading program will need. Prints names, counts and
dates only.
    /opt/trader/venv/bin/python /opt/trader/check.py
"""
import sys

from ib_async import IB


def main() -> int:
    ib = IB()
    ib.connect("127.0.0.1", 4002, clientId=7, timeout=20, readonly=True)
    accounts = ib.managedAccounts()
    print("accounts:", accounts)
    if not accounts or not all(a.startswith("DU") for a in accounts):
        print("STOP: not a paper account (paper accounts start with DU). Nothing else checked.")
        ib.disconnect()
        return 1
    for query in ("NIFTY", "BANKNIFTY", "SENSEX"):
        for d in ib.reqMatchingSymbols(query)[:6]:
            c = d.contract
            print(f"{query}: {c.symbol} {c.secType} {c.primaryExchange or c.exchange} {c.currency} conId={c.conId} "
                  f"derivatives={sorted(d.derivativeSecTypes)}")
            if c.secType == "IND" and "OPT" in d.derivativeSecTypes:
                for p in ib.reqSecDefOptParams(c.symbol, "", c.secType, c.conId)[:3]:
                    exps = sorted(p.expirations)
                    print(f"   options on {p.exchange}: trading class {p.tradingClass}, multiplier {p.multiplier}, "
                          f"{len(exps)} expiries ({exps[:3]}...), {len(p.strikes)} strikes")
    ib.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
