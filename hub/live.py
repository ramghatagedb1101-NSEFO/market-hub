"""
Live index quotes for the phone page. Runs every few minutes during market hours (see live.yml).

Writes docs/data/live.json: last traded level, previous close and change for NIFTY and SENSEX.
Needs KITE_API_KEY and KITE_ACCESS_TOKEN in the environment (the workflow fetches the token).
"""
import json
from datetime import datetime

from . import config
from .sources import kite

LIVE_FILE = config.SITE_DIR / "data" / "live.json"
SYMBOLS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "SENSEX": "BSE:SENSEX"}


def main() -> dict:
    k = kite.client()
    quotes = k.quote(list(SYMBOLS.values()))
    out = {
        "ts": datetime.now(config.IST).isoformat(timespec="seconds"),
        "indices": {},
    }
    for name, sym in SYMBOLS.items():
        q = quotes[sym]
        last = float(q["last_price"])
        prev = float(q["ohlc"]["close"])
        out["indices"][name] = {
            "last": round(last, 2),
            "prev_close": round(prev, 2),
            "change": round(last - prev, 2),
            "change_pct": round((last / prev - 1) * 100, 2),
        }
    LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LIVE_FILE.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
