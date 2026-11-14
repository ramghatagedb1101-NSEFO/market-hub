"""On-time starts for the GitHub jobs (14 Nov 2026).

Since Fri 6 Nov 2026 GitHub has started this repo's scheduled runs 6-9 hours late (close-estimate's 09:20 run at
17:06 IST, market-loop's 08:45 run at 16:26, the 06:15 stock library at ~12:40, live quotes twice a day). GitHub does
not delay a run started by hand (`workflow_dispatch`): those start within seconds. This runs once a minute on the
always-on trading machine (`kicker.timer`) and, at each job's time, asks the relay (`?mode=kick`) to start it; the relay
holds the GitHub key (GH_PAT) that already starts daily.yml and algo-sync.yml. Nothing GitHub-side is stored here.

Every 10 minutes it also calls the relay with no job, so the relay knows the clock is alive. The jobs' own GitHub
schedules stay as backups: a scheduled run asks the relay first (`?mode=kick_seen`) and stops when this clock is alive
and started that job without error.

The times are the workflows' own cron lines in IST (keep them in step: `python -m trader.selftest` checks it).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

WEEKDAYS = (0, 1, 2, 3, 4)          # Mon-Fri (datetime.weekday())
MON_SAT = (0, 1, 2, 3, 4, 5)
EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)


def _every(step: int, start: str, end: str) -> list[str]:
    """Every `step` minutes from start to end inclusive, as HH:MM."""
    h, m = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    out, t, last = [], h * 60 + m, eh * 60 + em
    while t <= last:
        out.append(f"{t // 60:02d}:{t % 60:02d}")
        t += step
    return out


# workflow file -> list of (days, times in IST). Same as each workflow's cron, except daily.yml at 18:05 (the time
# market-loop.yml used to start it: NSE's day files are in by then).
SCHEDULE: dict[str, list[tuple[tuple[int, ...], list[str]]]] = {
    "library.yml": [(EVERY_DAY, ["06:15"])],
    "expiry-history.yml": [((5,), ["07:30"])],
    "kite-reminder.yml": [(WEEKDAYS, ["07:36", "08:33"])],
    "insights.yml": [(MON_SAT, ["08:05"])],
    "summaries.yml": [(EVERY_DAY, ["09:00"])],
    "source-health.yml": [(MON_SAT, ["09:10"])],
    "live.yml": [(WEEKDAYS, _every(5, "08:30", "17:25"))],
    "market-loop.yml": [(WEEKDAYS, ["08:45", "11:45"])],
    "expiry-tape.yml": [(WEEKDAYS, ["09:08", "12:33"])],
    "close-estimate.yml": [(WEEKDAYS, ["09:20", "11:00", "13:00", "14:45"])],
    "expiry-theta.yml": [((0, 1), ["10:00", "12:30", "14:45"])],
    "algo-sync.yml": [(WEEKDAYS, _every(10, "08:30", "15:20") + ["15:35", "16:10"])],
    "breeze.yml": [(EVERY_DAY, ["16:00", "21:00"])],
    "daily.yml": [(WEEKDAYS, ["18:05", "20:30"])],
}

HEARTBEAT_EVERY_MIN = 10


def due(now: dt.datetime) -> list[str]:
    """Workflows to start in this IST minute."""
    now = now.astimezone(IST)
    hm, wd = now.strftime("%H:%M"), now.weekday()
    return sorted(wf for wf, rules in SCHEDULE.items() if any(wd in days and hm in times for days, times in rules))


def call_relay(wfs: list[str], timeout: int = 90) -> dict:
    url = os.environ["RELAY_URL"]
    q = urllib.parse.urlencode({"mode": "kick", "key": os.environ["RELAY_KEY"], "wf": ",".join(wfs)})
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + q, headers={"User-Agent": "market-hub-kicker"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # Apps Script answers through a redirect; urllib follows it
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    now = dt.datetime.now(IST)
    wfs = due(now)
    if not wfs and now.minute % HEARTBEAT_EVERY_MIN:
        return 0
    stamp = now.strftime("%a %d %b %Y %H:%M IST")
    try:
        res = call_relay(wfs)
    except Exception as e:  # noqa: BLE001 -- logged; the next minute tries again, GitHub's own schedule is the backup
        print(f"{stamp} relay not reached ({type(e).__name__}: {str(e)[:120]}); wanted: {', '.join(wfs) or 'heartbeat'}")
        return 1
    if res.get("error"):
        print(f"{stamp} relay refused: {res['error']}")
        return 1
    started = res.get("started") or {}
    bad = {k: v for k, v in started.items() if v not in (204, "already")}
    if wfs:
        print(f"{stamp} " + ", ".join(f"{k} {v}" for k, v in started.items()))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
