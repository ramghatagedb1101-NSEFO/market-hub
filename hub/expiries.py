"""
Expiry calendar for NIFTY, BANK NIFTY and SENSEX (14 Oct 2026; from the 13 Oct audit). Before, hub/config.py had one
weekday per index -- NIFTY Tue, BANK NIFTY Wed, SENSEX Mon -- of which only NIFTY's was right (as of Oct 2026: NIFTY
weekly Tuesday, SENSEX weekly Thursday, BANK NIFTY monthly only, last Tuesday), and no holiday moves (NIFTY expires
Mon 19 Oct and Mon 9 Nov 2026 because of holidays), so the forecast hub's "expiry" horizon aimed BANK NIFTY and SENSEX
forecasts at the wrong day.

Now the dates come from Kite's own contract lists (NFO for NIFTY / BANK NIFTY, BFO for SENSEX; one download a day per
list through hub/sources/kite.PacedKite), so rule changes and holiday moves are followed by themselves -- the same
source the relay's expiry meter uses (relay/Expiry.gs). If the lists cannot be read (no Kite login, a back-test of
past dates), config.EXPIRY_RULE gives the date by rule, moved back from a weekend.
"""
import calendar
from datetime import date, datetime, timedelta, timezone

from . import config

_IST = timezone(timedelta(hours=5, minutes=30))
EXCHANGE = {"NIFTY": "NFO", "BANKNIFTY": "NFO", "SENSEX": "BFO"}
_listed = {}                      # index -> sorted option expiry dates (None = lists unavailable)


def _client():
    from .sources import kite
    return kite.client()


def listed(index: str) -> list | None:
    """Option expiry dates Kite lists for the index (today and later), or None if the list cannot be read."""
    if index in _listed:
        return _listed[index]
    out = None
    try:
        rows = _client().instruments(EXCHANGE[index])
        out = sorted({r["expiry"] for r in rows if r.get("name") == index and r.get("instrument_type") in ("CE", "PE")
                      and r.get("expiry")}) or None
    except Exception:
        out = None
    _listed[index] = out
    return out


def _by_rule(index: str, after: date) -> date:
    kind, wd = config.EXPIRY_RULE[index]
    if kind == "weekly":
        t = after + timedelta(days=1)
        while t.weekday() != wd:
            t += timedelta(days=1)
        return t
    y, m = after.year, after.month
    while True:                                   # monthly: the month's last such weekday
        last = date(y, m, calendar.monthrange(y, m)[1])
        while last.weekday() != wd:
            last -= timedelta(days=1)
        if last > after:
            return last
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def next_expiry(index: str, after: date) -> date:
    """The first expiry strictly after `after`. Kite's list knows only today's and later contracts, so a rule date
    that has already passed (a back-test, or a run days after `after`) is taken by rule."""
    rule = _by_rule(index, after)
    today = datetime.now(_IST).date()
    if rule < today:
        return rule
    dates = listed(index)
    later = [d for d in (dates or []) if d > after]
    return later[0] if later else rule
