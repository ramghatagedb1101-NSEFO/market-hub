"""Probe (26 Oct 2026): the recorder's GIFT Nifty cue for the last two sessions, on Kite's real candles (diag.yml)."""
import json

from . import close_estimate

if __name__ == "__main__":
    x = close_estimate._gift_move("2026-10-23", "2026-10-26")
    print(json.dumps({"asof": "2026-10-23", "day": "2026-10-26", "gift_move_pct": None if x is None else round(x * 100, 3)}))
