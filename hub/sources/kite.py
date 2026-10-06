"""
Zerodha Kite Connect source (paid API, the user's existing subscription).

Needs three environment secrets:
  KITE_API_KEY, KITE_API_SECRET   from the Kite developer console (static)
  KITE_ACCESS_TOKEN               issued each morning by the login flow (expires daily)
"""
import os
from datetime import date

from kiteconnect import KiteConnect


def client() -> KiteConnect:
    k = KiteConnect(api_key=os.environ["KITE_API_KEY"])
    k.set_access_token(os.environ["KITE_ACCESS_TOKEN"])
    return k


def instrument_token(k: KiteConnect, exchange: str, tradingsymbol: str) -> int:
    for row in k.instruments(exchange):
        if row["tradingsymbol"] == tradingsymbol:
            return int(row["instrument_token"])
    raise KeyError(f"{tradingsymbol} not found on {exchange}")


def daily_closes(k: KiteConnect, token: int, start: date, end: date) -> dict:
    """{ 'YYYY-MM-DD': close } for daily candles in [start, end]."""
    rows = k.historical_data(token, start, end, "day")
    return {r["date"].date().isoformat(): float(r["close"]) for r in rows}
