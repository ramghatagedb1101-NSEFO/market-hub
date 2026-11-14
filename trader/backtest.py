"""
Back-test of one strategy from the builder (14 Nov 2026), on the ICICI minute history in the private repo:
option prices for the day before and the day of every downloaded expiry (hub/breeze_history.py) and the index's own
one-minute bars for every session (hub/breeze_index.py; the session before is included so averages and RSI have
history). The same engine, limits, stops and charges as the live program (trader/replay.py).

Coverage: the sessions that have option prices, nearest expiry only (a strategy set to "next" or "monthly" cannot be
tested yet; the result says so): every session of each expiry from the owner's files (hub/icici_files.py, NIFTY and
BANK NIFTY Jan 2024 - Oct 2026), else the day before and the day of each downloaded expiry.

    python -m trader.backtest STRATEGIES_JSON ID [--print]   (writes state/backtests/<ID>.json to the private repo)
"""
import json
import sys
from datetime import date, datetime, timedelta

from hub.breeze_history import DIR as EXP_DIR, INDEX as EXP_DONE, load_gz
from hub.icici_files import WEEKS
from hub.breeze_index import DIR as IDX_DIR
from hub.expiry_history import load, save

from .journal import Journal
from .model import Settings
from .replay import run
from .strategies.rules import Rules, clean
from .summary import build

OUT = "state/backtests/{id}.json"
INDEX = "state/backtests/_index.json"


class IndexMinutes:
    """The index's one-minute bars by date, read a month at a time."""

    def __init__(self, index: str):
        self.index, self.months = index, {}

    def day(self, d: str) -> list | None:
        m = d[:7]
        if m not in self.months:
            body = load_gz(f"{IDX_DIR}/{self.index}/{m}.json.gz") or {}
            self.months[m] = body.get("days") or {}
        return self.months[m].get(d)

    def around(self, days: list) -> dict:
        out, d, got = {}, date.fromisoformat(days[0]), 0
        for k in range(1, 15):                                  # five sessions before, for history (14 Nov 2026: the
            back = (d - timedelta(days=k)).isoformat()          # Range Filter needs about four sessions to settle)
            bars = self.day(back)
            if bars:
                out[back] = bars
                got += 1
                if got == 5:
                    break
        for x in days:
            bars = self.day(x)
            if bars:
                out[x] = bars
        return out


def backtest(defn: dict, limits: dict | None = None, progress=print) -> dict:
    d = clean(defn)
    idx, limits = d["index"], limits or {}
    done = load(EXP_DONE) or {}
    expiries = sorted(k.split("_", 1)[1] for k in done if k.startswith(idx + "_"))
    months = defn.get("months")                     # Back-tests page: "the last N months" (none = all the data)
    if isinstance(months, (int, float)) and months > 0:
        cut = (date.today() - timedelta(days=int(months * 30.44))).isoformat()
        expiries = [e for e in expiries if e >= cut]
    since = defn.get("from")                       # Back-tests page: "since Aug 2026" (14 Nov 2026)
    if isinstance(since, str) and len(since) == 10:
        expiries = [e for e in expiries if e >= since]
    recs = load("state/expiry_history/records.json") or {}
    minutes = IndexMinutes(idx)
    rows, sessions, skipped = [], [], 0
    s = Settings(strategy="rules", params=d, stale_seconds=300,
                 max_lots_per_order=int(limits.get("max_lots_per_order") or max(d["lots"], 1)),
                 max_daily_loss=float(limits.get("max_daily_loss") or 10000))
    for n, e in enumerate(expiries, 1):
        week = (done.get(f"{idx}_{e}") or {}).get("source") == "owner files" or (done.get(f"{idx}_{e}") or {}).get("weeks")
        entry = (load_gz(f"{WEEKS}/{idx}/{e}.json.gz") if week else None) or load_gz(f"{EXP_DIR}/{idx}/{e}.json.gz")
        if not entry:
            continue
        sess = entry.get("days") or [entry["prev_day"], e]
        if isinstance(since, str) and len(since) == 10 and entry.get("days"):
            keep = [x for x in sess if x >= since]          # "since 1 Aug": an expiry week starting in July is trimmed
            if not keep:
                continue
            if keep != sess:
                entry, sess = dict(entry, days=keep), keep
        days = minutes.around(sess)
        if any(x not in days for x in sess):
            skipped += 1
            continue
        j = Journal()
        run(idx, entry, (recs.get(f"{idx}_{e}") or {}).get("close"), Rules(d), s, j, index_days=days)
        rows += j.lines
        sessions += sess
        if n % 10 == 0:
            progress(f"{n} of {len(expiries)} expiries")
    summary = build(rows, now=datetime.now())
    for k in ("open", "pending", "pending_at", "status", "today", "month"):
        summary.pop(k, None)
    note = None
    if d["expiry"] != "nearest":
        note = f"Expiry set to '{d['expiry']}': this data has only the nearest expiry, so no trades could be tested."
    return {"id": d["id"], "name": d["name"], "ran": datetime.now().isoformat(timespec="minutes"),
            "strategy": d, "coverage": {"sessions": len(sessions), "expiries": len(expiries) - skipped,
                                        "from": min(sessions) if sessions else None,
                                        "to": max(sessions) if sessions else None, "skipped": skipped},
            "note": note, "months": months if isinstance(months, (int, float)) and months > 0 else None,
            "from": since if isinstance(since, str) and len(since) == 10 else None,
            "query": defn.get("query") or None, "summary": summary}


def main() -> int:
    src, sid = sys.argv[1], sys.argv[2]
    data = json.loads(open(src, encoding="utf-8").read())
    defn = next((x for x in data.get("items") or [] if x.get("id") == sid), None)
    if not defn:
        print(f"no strategy {sid}")
        return 1
    res = backtest(defn, data.get("limits"))
    t = res["summary"]["totals"]
    print(f"back-test: {res['coverage']['sessions']} sessions, {t['trades']} trades, {t['wins']} won")
    if "--print" in sys.argv:
        print(json.dumps(res["summary"]["totals"], indent=1))
    else:
        publish(sid, res)
    return 0


def publish(sid: str, res: dict) -> None:
    """The result to the private repo (state/backtests/<id>.json) and the page's index of latest results."""
    t = res["summary"]["totals"]
    save(OUT.format(id=sid), res, f"Back-test: {res['name']}")
    idx = load(INDEX) or {}                     # the latest result of each strategy, for the page's cards
    idx[sid] = {"ran": res["ran"], "trades": t["trades"], "wins": t["wins"], "profit": t["booked"],
                "worst_drop": t["worst_drop"], "sessions": res["coverage"]["sessions"],
                "by_regime": (res["summary"].get("by_strategy_regime") or {}).get(sid, {})}
    save(INDEX, idx, f"Back-tests index: {len(idx)} strategies")


if __name__ == "__main__":
    sys.exit(main())
