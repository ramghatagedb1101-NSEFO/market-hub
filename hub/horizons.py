"""Target-date logic for the four horizons, and how each one is settled."""
import calendar
from bisect import bisect_right
from datetime import date, timedelta

from . import config


def _last_weekday_of_month(year: int, month: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def target_for(horizon: str, index: str, asof: date) -> date:
    """The date whose close we are forecasting, given the last close we know (asof)."""
    if horizon == "day":
        t = asof + timedelta(days=1)
        while t.weekday() >= 5:
            t += timedelta(days=1)
        return t
    if horizon == "expiry":
        wd = config.EXPIRY_WEEKDAY[index]
        t = asof + timedelta(days=1)
        while t.weekday() != wd:
            t += timedelta(days=1)
        return t
    if horizon == "month":
        t = _last_weekday_of_month(asof.year, asof.month)
        if t <= asof:
            ny, nm = (asof.year + 1, 1) if asof.month == 12 else (asof.year, asof.month + 1)
            t = _last_weekday_of_month(ny, nm)
        return t
    if horizon == "year":
        t = _last_weekday_of_month(asof.year, 12)
        if t <= asof:
            t = _last_weekday_of_month(asof.year + 1, 12)
        return t
    raise ValueError(f"unknown horizon: {horizon}")


def settle_value(horizon: str, target: date, dates: list, closes: list):
    """
    Return (date, close) that settles a forecast, or None if the data is not there yet.
    day / expiry: first close on or after the target (absorbs exchange holidays).
    month / year: last close on or before the target, once data has moved past it.
    """
    if horizon in ("day", "expiry"):
        i = bisect_right(dates, target - timedelta(days=1))
        if i < len(dates):
            return dates[i], closes[i]
        return None
    if not dates or dates[-1] < target:
        return None
    i = bisect_right(dates, target) - 1
    return dates[i], closes[i]
