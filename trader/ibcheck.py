"""
Is the trading machine signed in to IBKR right now? (16 Nov 2026). Read-only, places nothing, prints no account number:
connects to the gateway, confirms a paper account (DU...), and asks IBKR for NIFTY's last daily close, which only
answers when the gateway is signed in and connected to IBKR's servers.
    /opt/trader/venv/bin/python -m trader.ibcheck           (bt-worker-setup.yml log_only runs it)
    /opt/trader/venv/bin/python -m trader.ibcheck --repair  (ibguard.timer, weekday mornings before 09:15 IST)
With --repair, a failed check restarts the gateway (a fresh sign-in with the stored paper login) and checks again: on
16 Nov 2026 IBKR's Sunday reset left the gateway logged out ("Paper trading disclaimer must first be accepted", 10141)
until it was restarted. The trading program reconnects by itself (trader/live.py).
"""
import subprocess
import sys
import time

from ib_async import IB, Index


def check() -> int:
    ib = IB()
    try:
        ib.connect("127.0.0.1", 4002, clientId=9, timeout=20, readonly=True)
    except Exception as e:                                       # noqa: BLE001
        print(f"IBKR: gateway not reachable ({type(e).__name__})")
        return 1
    acc = ib.managedAccounts()
    paper = bool(acc) and all(a.startswith("DU") for a in acc)
    bars = ib.reqHistoricalData(Index("NIFTY50", "NSE", "INR"), "", "3 D", "1 day", "TRADES", True, timeout=30)
    if "--minutes" in sys.argv:                                  # 24 Nov 2026: what one-minute history IBKR gives now
        und = Index("NIFTY50", "NSE", "INR")
        ib.qualifyContracts(und)
        t0 = time.time()
        mins = ib.reqHistoricalData(und, "", "6 D", "1 min", "TRADES", True, formatDate=1, timeout=60)
        today = [b for b in mins or [] if str(b.date)[:10] == time.strftime("%Y-%m-%d")]
        print(f"IBKR minutes: {len(mins or [])} bars in {time.time() - t0:.1f}s; today {len(today)}"
              + (f" ({today[0].date} .. {today[-1].date}, open {today[0].open})" if today else ""))
        tk = ib.reqMktData(und, "", False, False)
        ib.sleep(5)
        print(f"IBKR live NIFTY: last {tk.last} close {tk.close} at {tk.time}")
    ib.disconnect()
    if not paper:
        print("IBKR: signed in, but NOT a paper account")
        return 1
    if not bars:
        print("IBKR: paper account connected, but IBKR's servers gave no prices (not signed in yet?)")
        return 1
    print(f"IBKR: signed in (paper); NIFTY last close {bars[-1].close:,.2f} on {bars[-1].date}")
    return 0


def main() -> int:
    rc = check()
    if rc == 0 or "--repair" not in sys.argv:
        return rc
    print("IBKR: restarting the gateway for a fresh sign-in", flush=True)
    subprocess.run(["sudo", "docker", "compose", "-f", "/opt/trader/docker-compose.yml", "restart", "ib-gateway"], check=False)
    time.sleep(120)
    return check()


if __name__ == "__main__":
    sys.exit(main())
