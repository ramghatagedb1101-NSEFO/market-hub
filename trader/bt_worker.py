"""
Back-tests on the trading machine (14 Nov 2026; owner: back-tests in seconds, not GitHub's 2-6 minutes).

Runs as `bt-worker.service` on market-hub-trader. Every few seconds it asks the relay for a queued back-test
(?mode=bt_next, RELAY_KEY), reads that strategy (?mode=strategies), runs trader.backtest on the ICICI minute history
and saves the result to the private repo exactly as the GitHub job does. The minute files that no longer change are
kept on this machine's disk (BT_CACHE, hub/breeze_history.load_gz), so after the first run only the replay remains.

Never during market hours (09:10-15:35 IST, weekdays): the relay sends those to GitHub instead, and this worker does
not ask, so the trading program has the machine to itself.
Settings: /opt/trader/secrets/bt.env (PRIVATE_REPO_TOKEN, RELAY_URL, RELAY_KEY), written by bt-worker-setup.yml.
"""
import os
import time
import traceback
from datetime import datetime, timedelta, timezone

import requests

IST = timezone(timedelta(hours=5, minutes=30))
POLL = 4


def market_hours(now: datetime) -> bool:
    m = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 10 <= m <= 15 * 60 + 35


def relay(mode: str) -> dict:
    r = requests.get(os.environ["RELAY_URL"], params={"mode": mode, "key": os.environ["RELAY_KEY"]}, timeout=60)
    r.raise_for_status()
    return r.json()


def run_one(sid: str) -> None:
    from .backtest import backtest, publish
    data = relay("strategies")
    defn = next((x for x in data.get("items") or [] if x.get("id") == sid), None)
    if not defn:
        print(f"{sid}: no such strategy", flush=True)
        return
    t0 = time.time()
    res = backtest(defn, data.get("limits"), progress=lambda m: None)
    publish(sid, res)
    t = res["summary"]["totals"]
    print(f"{sid}: {res['coverage']['sessions']} sessions, {t['trades']} trades, {time.time() - t0:.0f} s", flush=True)


def main() -> None:
    print("bt-worker: start", flush=True)
    while True:
        try:
            if market_hours(datetime.now(IST)):
                time.sleep(30)
                continue
            job = relay("bt_next")
            if job.get("id"):
                run_one(job["id"])
                continue
        except Exception:                                        # noqa: BLE001 -- keep serving; the log says why
            traceback.print_exc()
            time.sleep(30)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
