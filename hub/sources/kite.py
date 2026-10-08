"""
Zerodha Kite Connect source (paid API, the user's existing subscription).

Needs three environment secrets:
  KITE_API_KEY, KITE_API_SECRET   from the Kite developer console (static)
  KITE_ACCESS_TOKEN               issued each morning by the login flow (expires daily)
"""
import os
import time
from datetime import date

from kiteconnect import KiteConnect


def client() -> KiteConnect:
    k = KiteConnect(api_key=os.environ["KITE_API_KEY"])
    k.set_access_token(os.environ["KITE_ACCESS_TOKEN"])
    return k


def _retry(fn, tries=4):
    """store.refresh_prices() deliberately raises rather than write a partial day, so a transient
    Kite/network blip here would otherwise skip the entire rest of the daily pipeline (same class of
    bug fixed 2026-10-08 on the Kite-token relay call). Does not retry a real auth/lookup error
    (KeyError from instrument_token), only the call itself."""
    last_exc = None
    for attempt in range(tries):
        try:
            return fn()
        except KeyError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
    raise last_exc


def instrument_token(k: KiteConnect, exchange: str, tradingsymbol: str) -> int:
    rows = _retry(lambda: k.instruments(exchange))
    for row in rows:
        if row["tradingsymbol"] == tradingsymbol:
            return int(row["instrument_token"])
    raise KeyError(f"{tradingsymbol} not found on {exchange}")


def daily_closes(k: KiteConnect, token: int, start: date, end: date) -> dict:
    """{ 'YYYY-MM-DD': close } for daily candles in [start, end]."""
    rows = _retry(lambda: k.historical_data(token, start, end, "day"))
    return {r["date"].date().isoformat(): float(r["close"]) for r in rows}
