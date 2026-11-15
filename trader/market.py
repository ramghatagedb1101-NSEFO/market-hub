"""
Market signals for strategies (14 Nov 2026, strategy bot step 1): the previous session's India VIX, implied volatility
and its percentile, put-call ratio, open-interest change and FII / client positions from state/market/daily.json
(hub/market_daily.py), and scheduled event days. Values are the PREVIOUS session's close, known before today's open, so
a back-test can never peek at the day it is trading.

Back-tests load the whole table once (Market.from_repo); the live program reads /opt/trader/market.json, the table's
latest sessions copied to the machine by algo-sync.yml (Market.from_file, re-read when the file changes).
"""
import json
import os
from datetime import date, timedelta

# operand -> (label on the page, how it is read from a day's entry)
MARKET = {
    "vix": "India VIX", "vix_pct": "India VIX percentile (1 year)",
    "iv": "ATM implied volatility %", "iv_pct": "IV percentile (1 year)",
    "pcr": "Put-call ratio (near expiry)", "pcr_all": "Put-call ratio (all expiries)", "oi_chg": "Option OI change %",
    "fii_fut": "FII net index futures %", "fii_call": "FII net index calls %", "fii_put": "FII net index puts %",
    "client_fut": "Retail net index futures %", "pro_fut": "Pro traders' net index futures %",
    # official figures only (owner, 15 Nov 2026: "use only things that are 100% reliable"; news left out): NSDL's
    # confirmed FPI flows and dollar rate, FRED's US close (from 2023, hub/diary_history.py), NSE's DII flows (from
    # 14 Nov 2026), MCX's official daily closes for gold and crude (from 2023, same contract close to close).
    "fii_cash": "FII cash buying, rupees crore (NSDL)", "dii_cash": "DII cash buying, rupees crore (NSE)",
    "sp500_chg": "S&P 500 last session %", "nasdaq_chg": "Nasdaq last session %",
    "usdinr_chg": "US dollar vs rupee change % (NSDL rate)",
    "gold_chg": "Gold change % (MCX close)", "crude_chg": "Crude oil change % (MCX close)",
}
FLOW_KEYS = ("fii_cash", "dii_cash", "sp500_chg", "nasdaq_chg", "usdinr_chg", "gold_chg", "crude_chg")
LIVE_FILE = os.getenv("MARKET_FILE") or "/opt/trader/market.json"
LIVE_FLOWS = os.getenv("FLOWS_FILE") or "/opt/trader/flows.json"
MAX_AGE_DAYS = 7                    # a weekend plus the longest run of market holidays

# Scheduled days that move the market (dates checked against the official calendars; see hub/expiry_history.py EVENTS)
from hub.expiry_history import EVENTS  # noqa: E402

EVENT_KINDS = {"rbi": "RBI policy", "budget": "Union budget", "election": "Election result"}


def flat(entry: dict, index: str) -> dict:
    """One day's entry as operand values for one index (shares as %)."""
    x = entry.get(index) or {}
    out = {"vix": entry.get("vix"), "vix_pct": entry.get("vix_pct"), "iv": x.get("iv"), "iv_pct": x.get("iv_pct"),
           "pcr": x.get("pcr"), "pcr_all": x.get("pcr_all"), "oi_chg": x.get("oi_chg")}
    for g, k in (("fii", "fii_fut"), ("fii", "fii_call"), ("fii", "fii_put"), ("client", "client_fut"), ("pro", "pro_fut")):
        v = (entry.get(g) or {}).get(k.split("_")[1])
        out[k] = round(v * 100, 1) if isinstance(v, (int, float)) else None
    return out


class Market:
    def __init__(self, table: dict | None = None, flows: dict | None = None):
        self.f, self.fdays = {}, []
        self.load(table or {}, flows or {})

    def load(self, table: dict, flows: dict | None = None) -> None:
        self.t = table
        self.days = sorted(k for k, v in table.items() if isinstance(v, dict) and not v.get("holiday"))
        if flows is not None:
            self.f = flows
            self.fdays = sorted(flows)
        self.memo = {}

    @classmethod
    def from_repo(cls) -> "Market":
        from hub.expiry_history import load
        try:
            return cls(load("state/market/daily.json") or {}, load("state/market/flows.json") or {})
        except Exception:                                        # noqa: BLE001 -- no table: market signals stay unmet
            return cls({})

    def prev(self, index: str, day: date | str) -> dict:
        """The last session BEFORE day, as operand values (empty when the table has none)."""
        d = day.isoformat() if isinstance(day, date) else day
        key = (index, d)
        if key not in self.memo:
            import bisect
            # only a RECENT session counts (14 Nov 2026: with a gap in the table, "the last session before" was months
            # old and its figures were used as if current): within MAX_AGE_DAYS calendar days, else nothing
            oldest = (date.fromisoformat(d) - timedelta(days=MAX_AGE_DAYS)).isoformat()
            i = bisect.bisect_left(self.days, d)
            out = flat(self.t[self.days[i - 1]], index) if i and self.days[i - 1] >= oldest else {}
            j = bisect.bisect_left(self.fdays, d)                # the diary: the last session before the day
            if j and self.fdays[j - 1] >= oldest:
                out.update({k: self.f[self.fdays[j - 1]].get(k) for k in FLOW_KEYS})
            self.memo[key] = out
        return self.memo[key]


class LiveMarket(Market):
    """The machine's copy; re-read when algo-sync replaces the file."""

    def __init__(self, path: str = LIVE_FILE, flows_path: str = LIVE_FLOWS):
        self.path, self.fpath, self.mtime = path, flows_path, None
        super().__init__({})

    def prev(self, index: str, day) -> dict:
        try:
            m = (os.path.getmtime(self.path), os.path.getmtime(self.fpath) if os.path.exists(self.fpath) else 0)
            if m != self.mtime:
                with open(self.path, encoding="utf-8") as f:
                    table = json.load(f)
                fl = {}
                if os.path.exists(self.fpath):
                    with open(self.fpath, encoding="utf-8") as f:
                        fl = json.load(f)
                self.load(table, fl)
                self.mtime = m
        except (OSError, ValueError):
            pass
        return super().prev(index, day)


def event_today(day: date, kinds: list) -> list:
    d = day.isoformat()
    return [k for k in (kinds or list(EVENTS)) if d in EVENTS.get(k, [])]
