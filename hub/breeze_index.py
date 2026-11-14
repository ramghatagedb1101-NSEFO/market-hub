"""
Index minute history from ICICI Breeze (14 Nov 2026, owner asked where to get "the NIFTY index itself, minute by
minute"). The expiry download (hub/breeze_history.py) has option candles for two days around each expiry only; intraday
strategies need the index itself on every trading day.

For NIFTY 50, NIFTY BANK and SENSEX, one-minute candles for every session from Oct 2023 (the start of the expiry
records) to yesterday, two days per request (about 750 candles; ICICI returns up to 1,000). About 400 requests per
index for the whole span, so the whole thing fits inside one run's budget.

state/breeze/index/<INDEX>/<YYYY-MM>.json.gz =
  {"index", "month", "fields": [min, open, high, low, close, volume], "days": {"YYYY-MM-DD": [[min, o, h, l, c, v], ...]}}
  (min = minutes after 09:15). Progress: state/breeze/index/_done.json; the current month is fetched again each run.
Private repo only; the public log shows counts.
    gh workflow run breeze.yml -f module=breeze_index
"""
import os
import sys
import time
from datetime import date, timedelta

from .breeze import Breeze
from .breeze_history import _num, load_gz, save_gz
from .expiry_history import load, save

SPOT = {"NIFTY": ("NIFTY", "NSE"), "BANKNIFTY": ("CNXBAN", "NSE"), "SENSEX": ("BSESEN", "BSE")}
DIR = "state/breeze/index"
DONE = f"{DIR}/_done.json"
START = date(2023, 10, 1)
OPEN, CLOSE = "09:15", "15:30"
FIELDS = ["min", "open", "high", "low", "close", "volume"]


def months(until: date) -> list[str]:
    out, d = [], START.replace(day=1)
    while d <= until:
        out.append(d.strftime("%Y-%m"))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def weekdays(month: str, until: date) -> list[date]:
    y, m = map(int, month.split("-"))
    d, out = date(y, m, 1), []
    while d.month == m and d <= until:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def rows_to_days(rows: list) -> dict:
    days: dict[str, list] = {}
    for r in rows:
        dt = str(r.get("datetime", ""))
        d, t = dt[:10], dt[11:16]
        if not (OPEN <= t <= CLOSE):
            continue
        m = (int(t[:2]) * 60 + int(t[3:5])) - (9 * 60 + 15)
        o, h, l, c = (_num(r.get(k)) for k in ("open", "high", "low", "close"))
        if c is None:
            continue
        days.setdefault(d, []).append([m, o, h, l, c, int(_num(r.get("volume")) or 0)])
    return {d: sorted(v) for d, v in days.items()}


def fetch_month(b: Breeze, index: str, month: str, until: date) -> dict:
    code, exch = SPOT[index]
    body = {"index": index, "month": month, "fields": FIELDS, "days": {}, "errors": 0}
    wd = weekdays(month, until)
    for i in range(0, len(wd), 2):
        a, z = wd[i], wd[min(i + 1, len(wd) - 1)]
        try:
            rows = b.history(code, exch, "1minute", f"{a}T{OPEN}:00.000Z", f"{z}T{CLOSE}:00.000Z", product="cash")
        except RuntimeError as e:
            if "no data" in str(e).lower():
                continue
            body["errors"] += 1
            if body["errors"] >= 5:
                raise RuntimeError(f"ICICI kept failing on {index} {month}: {str(e)[:120]}")
            continue
        body["days"].update(rows_to_days(rows))
    return body


def run(b: Breeze | None, budget: int, stop_at: float):
    """Fetch what is missing within the budget. Returns (Breeze used, error text or None)."""
    until = date.today() - timedelta(days=1)
    this_month = date.today().strftime("%Y-%m")
    done = load(DONE) or {}
    queue = [(i, m) for i in SPOT for m in months(until) if f"{i}_{m}" not in done or m == this_month]
    print(f"index minutes: {len(done)} index-months saved, {len(queue)} to fetch")
    if not queue:
        return b, None
    b = b or Breeze()
    for index, month in queue:
        need = (len(weekdays(month, until)) + 1) // 2
        if b.calls + need > budget or time.time() > stop_at:
            print(f"budget or time reached before {index} {month}; the next run carries on from there")
            break
        try:
            body = fetch_month(b, index, month, until)
        except RuntimeError as exc:
            return b, str(exc)
        n = sum(len(v) for v in body["days"].values())
        if body["days"]:
            size = save_gz(f"{DIR}/{index}/{month}.json.gz", body, f"ICICI index minutes: {index} {month}")
        else:
            size = 0
        if not body["errors"]:                      # a month with errors is fetched again next run
            done[f"{index}_{month}"] = {"days": len(body["days"]), "candles": n}
            save(DONE, done, f"ICICI index minutes: {len(done)} index-months")
        print(f"{index} {month}: {len(body['days'])} days, {n} candles ({size // 1024} KB), {body['errors']} errors; "
              f"{b.calls} requests")
    return b, None


def main() -> int:
    budget = int(os.getenv("BUDGET") or 4000)
    b, failed = run(None, budget, time.time() + 60 * int(os.getenv("MAX_MINUTES") or 300))
    print(f"run done: {b.calls if b else 0} requests")
    if failed:
        print(f"::error title=ICICI index download::{failed[:200]} (work up to here is saved)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
