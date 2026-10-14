"""
One BharatStock budget for every caller (14 Oct 2026, from the 13 Oct Kite / BharatStock call audit).

BharatStock allows 10,000 requests a day (resets 00:00 UTC) and reports nothing about what has been used (checked
14 Oct 2026: no allowance headers, no usage endpoint), so the count is ours. Before, only the daily library run
counted itself (9,000 budget); the manual multibagger scan and the multibagger back-test had no limit at all (the
back-test reads every company's financials and prices: enough to use the whole day's allowance on its own), and the
relay's own calls (stock report, charts, fund holdings) were not counted anywhere.

Now every job records what it used in state/bs_usage.json (private repository; the jobs' site_data pull/push carry
it), the relay counts its own calls (script property, read here through ?mode=bs_usage), and a job may use only what
is left of SHARED_CAP after everyone else's use today. The last 1,000 of the 10,000 stay for the relay's live pages.
"""
import json
import os
from datetime import datetime, timezone

import requests

from . import config

PLAN_LIMIT = 10_000
SHARED_CAP = int(os.getenv("BS_DAILY_BUDGET", "9000"))     # all batch and manual jobs together; the rest: the relay
FILE = config.REPO / "state" / "bs_usage.json"


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if d.get("date") != utc_day():
        d = {"date": utc_day(), "jobs": {}}
    d.setdefault("jobs", {})
    return d


def relay_used() -> int:
    """The relay's own BharatStock requests today (0 if the relay cannot be asked)."""
    url, key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    if not url or not key:
        return 0
    try:
        r = requests.get(url, params={"mode": "bs_usage", "key": key}, timeout=30).json()
        return int(r.get("requests") or 0) if r.get("date") == utc_day() else 0
    except Exception:
        return 0


def used_by_others(job: str) -> int:
    d = load()
    return sum(int(n) for j, n in d["jobs"].items() if j != job) + relay_used()


def remaining(job: str) -> int:
    """Requests this job may still use today, after its own earlier runs and everyone else's."""
    d = load()
    return max(0, SHARED_CAP - used_by_others(job) - int(d["jobs"].get(job, 0)))


def record(job: str, requests_used: int, absolute: bool = False) -> dict:
    """Add this run's requests to the job's count for today (or set it, for a job that keeps its own daily total)."""
    d = load()
    d["jobs"][job] = int(requests_used) if absolute else int(d["jobs"].get(job, 0)) + int(requests_used)
    d["updated"] = datetime.now(config.IST).isoformat(timespec="minutes")
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=1), encoding="utf-8")
    return d
