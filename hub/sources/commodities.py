"""
MCX gold and crude prices through Kite (the user's existing subscription).

Picks the nearest unexpired monthly futures contract for each commodity and quotes it. The
futures price is the price people trade, so it is the right figure for a brief. Prices are in
rupees per unit of the contract (gold per 10 g, crude per barrel).
"""
import re
from datetime import date

from . import kite

COMMODITIES = {"Gold (MCX, ₹/10g)": "GOLD", "Crude oil (MCX, ₹/bbl)": "CRUDEOIL"}


ROLL_DAYS = 3   # move to the next month this many days before expiry: trading leaves an expiring contract early


def _front_month(rows: list, name: str, today: date) -> dict | None:
    """Nearest MONTHLY futures contract, rolled ROLL_DAYS before expiry (15 Oct 2026). Monthly only: NSE's weekly
    USDINR futures (e.g. USDINR26O16FUT) barely trade, so the nearest one showed last = previous close, 0.00%."""
    pat = re.compile(rf"^{re.escape(name)}\d{{2}}[A-Z]{{3}}FUT$")
    fut = sorted((r for r in rows if r["name"] == name and r["instrument_type"] == "FUT" and r["expiry"] >= today
                  and pat.match(r["tradingsymbol"])), key=lambda r: r["expiry"])
    live = [r for r in fut if (r["expiry"] - today).days > ROLL_DAYS]
    return (live or fut or [None])[0]


def main() -> dict:
    k = kite.client()
    rows = k.instruments("MCX")
    today = date.today()
    picked = {label: _front_month(rows, name, today) for label, name in COMMODITIES.items()}
    symbols = [f"MCX:{r['tradingsymbol']}" for r in picked.values() if r]
    quotes = k.quote(symbols) if symbols else {}
    out = {}
    for label, r in picked.items():
        if not r:
            raise RuntimeError(f"no open MCX futures found for {label}")
        q = quotes[f"MCX:{r['tradingsymbol']}"]
        last = float(q["last_price"])
        prev = float(q["ohlc"]["close"])
        out[label] = {
            "contract": r["tradingsymbol"],
            "expiry": r["expiry"].isoformat(),
            "last": round(last, 2),
            "prev_close": round(prev, 2),
            "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
        }
    return out


def usd_inr() -> dict:
    """Live USD/INR from the nearest NSE currency future (CDS segment). Futures track spot closely."""
    k = kite.client()
    rows = k.instruments("CDS")
    today = date.today()
    r = _front_month(rows, "USDINR", today)
    if not r:
        raise RuntimeError("no open USDINR currency futures found")
    q = k.quote([f"CDS:{r['tradingsymbol']}"])[f"CDS:{r['tradingsymbol']}"]
    last = float(q["last_price"])
    prev = float(q["ohlc"]["close"])
    return {"contract": r["tradingsymbol"], "expiry": r["expiry"].isoformat(), "last": round(last, 4),
            "prev_close": round(prev, 4), "change_pct": round((last / prev - 1) * 100, 2) if prev else None}


if __name__ == "__main__":
    import json
    print(json.dumps(main(), indent=2, ensure_ascii=False))
