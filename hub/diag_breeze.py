"""
First check of the ICICI Breeze connection (13 Nov 2026): sign-in through the Oracle fixed address, then a few
minute-candle requests -- NIFTY spot, a NIFTY option on a current expiry and one about three years back, Bank Nifty
and Sensex options -- to see what the free history really covers. Prints counts and first/last times only, never
prices (the job log is public).
    gh workflow run breeze.yml -f module=diag_breeze
"""
from .breeze import Breeze

TESTS = [
    ("NIFTY spot, 1 day", dict(stock_code="NIFTY", exch="NSE", interval="1minute", product="cash",
                                start="2026-11-13T03:45:00.000Z", end="2026-11-13T10:00:00.000Z")),
    ("NIFTY 25,200 call, expiry 17 Nov 2026", dict(stock_code="NIFTY", exch="NFO", interval="1minute", product="options",
                                                  expiry="2026-11-17T07:00:00.000Z", right="call", strike=25200,
                                                  start="2026-11-13T03:45:00.000Z", end="2026-11-13T10:00:00.000Z")),
    ("NIFTY 21,500 call, expiry 28 Dec 2023", dict(stock_code="NIFTY", exch="NFO", interval="1minute", product="options",
                                                  expiry="2023-12-28T07:00:00.000Z", right="call", strike=21500,
                                                  start="2023-12-27T03:45:00.000Z", end="2023-12-27T10:00:00.000Z")),
    ("Bank Nifty 61,000 put, expiry 23 Nov 2026", dict(stock_code="CNXBAN", exch="NFO", interval="1minute", product="options",
                                                      expiry="2026-11-23T07:00:00.000Z", right="put", strike=61000,
                                                      start="2026-11-13T03:45:00.000Z", end="2026-11-13T10:00:00.000Z")),
    ("Sensex 81,600 call, expiry 19 Nov 2026", dict(stock_code="BSESEN", exch="BFO", interval="1minute", product="options",
                                                   expiry="2026-11-19T07:00:00.000Z", right="call", strike=81600,
                                                   start="2026-11-13T03:45:00.000Z", end="2026-11-13T10:00:00.000Z")),
    ("NIFTY futures, 1 second, 5 minutes", dict(stock_code="NIFTY", exch="NFO", interval="1second", product="futures",
                                                expiry="2026-11-23T07:00:00.000Z", right="others", strike=0,
                                                start="2026-11-13T04:00:00.000Z", end="2026-11-13T04:05:00.000Z")),
]


def main():
    b = Breeze()
    print("signed in to ICICI through the fixed address")
    for label, kw in TESTS:
        try:
            rows = b.history(**kw)
            first = rows[0].get("datetime") if rows else None
            last = rows[-1].get("datetime") if rows else None
            keys = sorted(rows[0].keys()) if rows else []
            print(f"{label}: {len(rows)} candles, {first} -> {last}; fields {keys}")
        except Exception as e:                      # noqa: BLE001
            print(f"{label}: failed: {str(e)[:160]}")
    print("calls:", b.calls)


if __name__ == "__main__":
    main()
