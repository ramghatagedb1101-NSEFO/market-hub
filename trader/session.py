"""
When index options trade (IST). SEBI circular HO/47/11/11(3)2025-MRD-POD2/I/23843/2026 of 15 Oct 2026 (paras 4.2.4,
4.9.1, 6.1; read from SEBI's PDF on 14 Nov 2026; effective Mon 7 Dec 2026): index derivatives trade until 15:45 on normal days and until 15:30 on their own expiry day; expiring contracts
settle at a price built from the last 30 minutes of the cash market (15:00-15:30), not the closing price. Before 7 Dec
2026 everything closed at 15:30. The index itself (cash market) trades continuously until 15:30 throughout.

Every part of the program asks here instead of assuming 15:30: the live loop, the replay, the recorder, the back-test
worker and research bot's "market hours", and the exit time on an expiry day.
"""
from datetime import date

LONGER_FROM = date(2026, 12, 7)
OPEN = "09:15"
INDEX_CLOSE = "15:30"                 # the cash market's continuous session


def _d(day) -> date:
    return day if isinstance(day, date) else date.fromisoformat(str(day)[:10])


def option_close(day, expiry_day: bool = False) -> str:
    """Last trading time of an index option on that day."""
    return "15:45" if _d(day) >= LONGER_FROM and not expiry_day else "15:30"


def session_close(day) -> str:
    """The latest any index option trades that day (the program's market hours)."""
    return option_close(day, False)


def last_minute(day, expiry_day: bool = False) -> int:
    """Minutes after 09:15 of the last one-minute bar (375 = 15:30, 390 = 15:45)."""
    h, m = map(int, option_close(day, expiry_day).split(":"))
    return h * 60 + m - 555


def exit_cap(day, expiry: str | None) -> str | None:
    """On a contract's own expiry day it stops trading at 15:30: exits must happen before (15:28 leaves time to fill)."""
    return "15:28" if expiry and str(expiry)[:10] == _d(day).isoformat() else None


def busy_until(day) -> str:
    """End of the window kept free for the trading program (5 minutes after the last option trade)."""
    h, m = map(int, session_close(day).split(":"))
    m = h * 60 + m + 5
    return f"{m // 60:02d}:{m % 60:02d}"
