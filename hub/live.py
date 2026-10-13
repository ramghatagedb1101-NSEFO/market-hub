"""
Live index quotes for the phone page. Runs every few minutes during market hours (see live.yml).

Writes docs/data/live.json: last traded level, previous close and change for NIFTY, BANK NIFTY and SENSEX (plus VIX,
gold, crude and USD/INR when present). Since 13 Oct 2026 it reads the relay's ?mode=quote, which comes from the
platform's one shared Kite snapshot (relay/Market.gs), instead of calling Kite itself. Needs RELAY_URL.
"""
import json
import os
import time
import urllib.request

from . import config

LIVE_FILE = config.SITE_DIR / "data" / "live.json"


def main() -> dict:
    url = os.environ["RELAY_URL"] + "?mode=quote&t=" + str(int(time.time()))
    last = None
    for attempt in range(3):                       # Google occasionally answers a web-app call with a transient error
        try:
            out = json.loads(urllib.request.urlopen(url, timeout=40).read())
            if out.get("indices"):
                LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
                LIVE_FILE.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
                return out
            last = out.get("error") or "no indices"
        except Exception as e:                     # noqa: BLE001 -- report and retry
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise SystemExit(f"Relay quote unavailable: {last}")


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
