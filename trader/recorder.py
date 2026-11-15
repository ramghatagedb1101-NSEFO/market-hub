"""
Records every trading day's minute prices from IBKR on market-hub-trader (owner, 14 Nov 2026: "keep recording every
trading day from 31 Oct on"). The ICICI history (owner's files) ends 30 Oct 2026; without this, later sessions exist only
for the two days around each expiry. Runs at 15:50 IST on trading days (infra/trader/recorder.timer), its own IBKR
connection (client 23) beside the trading program's.

For NIFTY and BANK NIFTY, the session's:
  - index one-minute bars                                  -> state/breeze/index/<INDEX>/<YYYY-MM>.json.gz (+ daily.json)
  - one-minute trade bars of the nearest and next expiry's options, strikes within 5% of the day's open
  - one-minute bid / ask (time-averaged) for the nearest expiry within 2% (the real cost of trading: ICICI has no bid/ask)
Raw day file: state/ibkr/days/<INDEX>/<day>.json.gz =
  {"day", "index", "source": "IBKR", "index_bars": [[min, o, h, l, c, v]], "expiries": [nearest, next],
   "options": {expiry: {"call": {strike: [[min, o, h, l, c, v]]}, "put": {...}}},
   "quotes": {expiry: {"call": {strike: [[min, bid, ask]]}, "put": {...}}}}      (min = minutes after 09:15)
The nearest expiry's day is also merged into state/breeze/expiry_weeks/<INDEX>/<expiry>.json.gz (the back-tests'
format, hub/icici_files.py; open interest 0: IBKR bars have none), and on its expiry day the expiry is marked complete
in state/breeze/expiry_days/_done.json ({"weeks": true, "source": "IBKR"}), so back-tests include it. A day already
stored (owner's files, the ICICI download) is never overwritten.

    python -m trader.recorder                 (today, after the close; does nothing on a holiday)
    python -m trader.recorder 2026-11-12 2026-11-13   (past sessions: only options not yet expired are still served; a
                                              day whose nearest expiry has expired keeps its raw file only)
    python -m trader.recorder --probe         (last session, NIFTY, a few strikes; prints counts and compares the
                                               index bars with ICICI's; writes nothing)
Private repo only (PRIVATE_REPO_TOKEN); the log prints counts.
"""
import sys
import time
from datetime import date, datetime, timedelta, timezone

from hub.breeze_history import DIR as EXP_DIR, INDEX as EXP_DONE, load_gz, save_gz
from hub.breeze_index import DIR as IDX_DIR, update_daily
from hub.expiry_history import load, save
from hub.holidays import is_session
from hub.icici_files import WEEKS

IST = timezone(timedelta(hours=5, minutes=30))
INDICES = ("NIFTY", "BANKNIFTY")
REACH, QUOTE_REACH = 0.05, 0.02
RAW = "state/ibkr/days"
CLIENT_ID = 23


def minute_of(dt: datetime) -> int:
    t = dt.astimezone(IST)
    return (t.hour - 9) * 60 + t.minute - 15


def end_utc(day: str) -> str:
    """One minute after the day's last option trade (15:31 IST, or 15:46 from 7 Dec 2026), in IBKR's UTC form."""
    from .session import last_minute
    m = 555 + last_minute(day) + 1 - 330                     # IST minutes -> UTC minutes
    return datetime.strptime(day, "%Y-%m-%d").strftime("%Y%m%d") + f"-{m // 60:02d}:{m % 60:02d}:00"


class Recorder:
    def __init__(self, ib_client=None):
        from .ibkr import IBKR
        self.k = ib_client or IBKR(client_id=CLIENT_ID)
        self.requests = 0

    def bars(self, contract, day: str, what: str = "TRADES") -> list:
        self.requests += 1
        for attempt in range(2):
            try:
                got = self.k.ib.reqHistoricalData(contract, endDateTime=end_utc(day), durationStr="1 D",
                                                  barSizeSetting="1 min", whatToShow=what, useRTH=True, formatDate=2,
                                                  timeout=60)
            except Exception:                                    # noqa: BLE001 -- one retry, then the contract is skipped
                got = None
            if got is not None:
                return [b for b in got if b.date.astimezone(IST).date().isoformat() == day]
            time.sleep(2)
        return []

    def index_bars(self, index: str, day: str) -> list:
        from ib_async import Index
        from .ibkr import IB_SYMBOL
        und = Index(IB_SYMBOL[index], "NSE", "INR")
        self.k.ib.qualifyContracts(und)
        return [[minute_of(b.date), b.open, b.high, b.low, b.close, int(b.volume or 0)]
                for b in self.bars(und, day) if 0 <= minute_of(b.date) <= 375]      # the index: cash session to 15:30

    def option_rows(self, index: str, expiry: str, strike: float, right: str, day: str, what: str) -> list:
        from .model import Contract
        o = self.k._ib(Contract(index, expiry, strike, right))
        if o is None:
            return []
        from .session import last_minute
        last = last_minute(day, expiry == day)
        out = []
        for b in self.bars(o, day, what):
            m = minute_of(b.date)
            if not 0 <= m <= last:
                continue
            if what == "TRADES":
                if b.close and b.close > 0:
                    out.append([m, b.open, b.high, b.low, b.close, int(b.volume or 0)])
            elif b.open and b.close and b.open > 0 and b.close > 0:
                out.append([m, round(b.open, 2), round(b.close, 2)])   # BID_ASK: open = average bid, close = average ask
        return out

    def day(self, index: str, day: str, probe: bool = False) -> dict | None:
        idx = self.index_bars(index, day)
        if not idx:
            print(f"{index} {day}: IBKR has no index bars for this day")
            return None
        open_ = idx[0][1]
        exps = [e for e in self.k.expiries(index) if e >= day][:2]
        if not exps:
            print(f"{index} {day}: no live expiries")
            return None
        body = {"day": day, "index": index, "source": "IBKR", "index_bars": idx, "expiries": exps, "options": {},
                "quotes": {}}
        strikes = self.k.strikes(index, exps[0])
        for n, exp in enumerate(exps):
            near = [k for k in strikes if abs(k - open_) <= open_ * REACH]
            if probe:
                near = sorted(near, key=lambda k: abs(k - open_))[:3]
            opt, quo = {"call": {}, "put": {}}, {"call": {}, "put": {}}
            for k in near:
                for right, side in (("C", "call"), ("P", "put")):
                    rows = self.option_rows(index, exp, k, right, day, "TRADES")
                    if rows:
                        opt[side][_key(k)] = rows
                    if n == 0 and abs(k - open_) <= open_ * QUOTE_REACH:
                        q = self.option_rows(index, exp, k, right, day, "BID_ASK")
                        if q:
                            quo[side][_key(k)] = q
            body["options"][exp], body["quotes"][exp] = opt, quo
            print(f"{index} {day} expiry {exp}: {len(opt['call'])} calls, {len(opt['put'])} puts with trades; "
                  f"{len(quo['call']) + len(quo['put'])} with bid/ask; {self.requests} requests so far")
        return body


def _key(k: float) -> str:
    return str(int(k)) if float(k).is_integer() else str(k)


def missed_expiry(index: str, day: str, first: str) -> str | None:
    """A past day: IBKR lists only live expiries, so its first one may not have been that day's nearest. Returns an
    expiry from the expiry records that fell between the day and IBKR's first, if any."""
    recs = load("state/expiry_history/records.json") or {}
    gone = sorted(k.split("_", 1)[1] for k in recs if k.startswith(index + "_") and day <= k.split("_", 1)[1] < first)
    return gone[0] if gone else None


def merge_week(body: dict) -> str:
    """Adds the day to the nearest expiry's week file (back-tests' format). Returns what happened."""
    index, day, exp = body["index"], body["day"], body["expiries"][0]
    if (gone := missed_expiry(index, day, exp)):
        return f"week file not changed: that day's nearest expiry was {gone} (expired, not served by IBKR)"
    path = f"{WEEKS}/{index}/{exp}.json.gz"
    e = load_gz(path) or {"days": [], "expiry": exp, "fields": ["day", "min", "open", "high", "low", "close", "volume",
                                                                    "oi"], "call": {}, "put": {}, "source": "IBKR"}
    if day in e["days"]:
        return f"{exp}: {day} already stored ({e.get('source')}), left as it was"
    days = sorted(e["days"] + [day])
    pos = {d: i for i, d in enumerate(days)}
    old = {i: d for i, d in enumerate(e["days"])}
    for side in ("call", "put"):
        for k, rows in list(e[side].items()):
            e[side][k] = [[pos[old[r[0]]]] + r[1:] for r in rows]
        for k, rows in body["options"][exp][side].items():
            e[side].setdefault(k, []).extend([pos[day], *r, 0] for r in rows)
            e[side][k].sort()
    e["days"] = days
    if e.get("source") and e["source"] != "IBKR" and "IBKR" not in e["source"]:
        e["source"] = f"{e['source']} + IBKR"
    save_gz(path, e, f"IBKR minutes: {index} {day} (expiry {exp})")
    if day == exp:                                            # the expiry is complete: back-tests may use it
        done = load(EXP_DONE) or {}
        key = f"{index}_{exp}"
        if key not in done:
            done[key] = {"weeks": True, "source": "IBKR", "days": len(days)}
        else:
            done[key]["weeks"] = True
        save(EXP_DONE, done, f"Expiry complete from IBKR minutes: {key}", merge=True)
    return f"{exp}: {day} added ({len(days)} sessions stored)"


def merge_index(body: dict) -> str:
    index, day = body["index"], body["day"]
    path = f"{IDX_DIR}/{index}/{day[:7]}.json.gz"
    m = load_gz(path) or {"index": index, "month": day[:7], "fields": ["min", "open", "high", "low", "close", "volume"],
                          "days": {}}
    if m["days"].get(day):
        return f"index {day}: already stored"
    m["days"][day] = body["index_bars"]
    save_gz(path, m, f"IBKR index minutes: {index} {day}")
    update_daily(index, [m])
    return f"index {day}: {len(body['index_bars'])} minutes added"


def probe(rec: Recorder) -> int:
    day = date.today()
    while True:
        day -= timedelta(days=1)
        if is_session(day):
            break
    d = day.isoformat()
    body = rec.day("NIFTY", d, probe=True)
    if not body:
        return 1
    ib = {r[0]: r[4] for r in body["index_bars"]}
    icici = {r[0]: r[4] for r in ((load_gz(f"{IDX_DIR}/NIFTY/{d[:7]}.json.gz") or {}).get("days") or {}).get(d, [])}
    print(f"index minutes {d}: IBKR {len(ib)}, ICICI {len(icici)}")
    for shift in (-1, 0, 1):
        both = [m for m in ib if m + shift in icici]
        if both:
            diff = sum(abs(ib[m] - icici[m + shift]) for m in both) / len(both)
            print(f"  IBKR minute m vs ICICI minute m{shift:+d}: average close difference {diff:.2f} points over {len(both)}")
    for exp, sides in body["options"].items():
        for side, ks in sides.items():
            for k, rows in ks.items():
                print(f"  {exp} {k} {side}: {len(rows)} minutes, first {rows[0][0]}, last {rows[-1][0]}")
    for exp, sides in body["quotes"].items():
        for side, ks in sides.items():
            for k, rows in ks.items():
                spread = sum(r[2] - r[1] for r in rows) / len(rows)
                print(f"  {exp} {k} {side}: bid/ask {len(rows)} minutes, average gap {spread:.2f}")
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rec = Recorder()
    rec.k.connect()
    try:
        if "--probe" in sys.argv:
            return probe(rec)
        now = datetime.now(IST)
        from .session import busy_until
        if not args and now.strftime("%H:%M") < busy_until(now.date()):
            print(f"the session is still open: run after {busy_until(now.date())} IST")
            return 1
        bad = tried = 0
        for d in args or [now.date().isoformat()]:
            if not is_session(date.fromisoformat(d)):
                print(f"{d}: not a trading day, nothing to record")
                continue
            for index in INDICES:
                tried += 1
                body = rec.day(index, d)
                if not body:
                    bad += 1
                    continue
                size = save_gz(f"{RAW}/{index}/{d}.json.gz", body, f"IBKR day record: {index} {d}")
                print(f"{index} {d}: day file {size // 1024} KB; {merge_week(body)}; {merge_index(body)}", flush=True)
        print(f"done: {rec.requests} IBKR requests")
        return 1 if tried and bad == tried else 0
    finally:
        rec.k.ib.disconnect()


if __name__ == "__main__":
    sys.exit(main())
