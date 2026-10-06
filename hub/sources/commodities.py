"""
MCX gold and crude prices through Kite (the user's existing subscription).

Picks the nearest unexpired monthly futures contract for each commodity and quotes it. The
futures price is the price people trade, so it is the right figure for a brief. Prices are in
rupees per unit of the contract (gold per 10 g, crude per barrel).
"""
from datetime import date

from . import kite

COMMODITIES = {"Gold (MCX, ₹/10g)": "GOLD", "Crude oil (MCX, ₹/bbl)": "CRUDEOIL"}


def _front_month(rows: list, name: str, today: date) -> dict | None:
    fut = [r for r in rows if r["name"] == name and r["instrument_type"] == "FUT" and r["expiry"] >= today]
    return min(fut, key=lambda r: r["expiry"]) if fut else None


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


if __name__ == "__main__":
    import json
    print(json.dumps(main(), indent=2, ensure_ascii=False))
