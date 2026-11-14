"""
Today's market condition, read from the index's own one-minute bars (14 Nov 2026, for autopilot: "based on market
conditions the engine should be able to take a call and decide which is the best strategy").

One of five, checked in this order:
  expiry_day   the traded expiry is today
  volatile     today's 5-minute bars swing much wider than the session before's over the same minutes after the open
               (average true range 1.5 x or more)
               without a steady direction (efficiency under the day's typical level)
  trend_up     the index has moved further from today's open than on 70% of days at this time of day, and more
  trend_down   steadily than on half of them (efficiency: net move over the path travelled, on 5-minute bars)
  range        anything else

Efficiency (Kaufman's ratio) is 1 for a straight line and near 0 for back-and-forth; it falls through the day by
nature, so the thresholds depend on the time. Set from NIFTY's own history, 767 sessions Oct 2023 - Nov 2026
(state/breeze/index/), 14 Nov 2026: |move from open| 70th percentile 0.23% at 09:30, 0.40% at 11:00, 0.47% at
13:00; efficiency median 0.68, 0.21, 0.14. In between, straight-line steps; after 13:00, the 13:00 values.
Needs the first 15 minutes of the day; before that there is no reading.
"""
from datetime import date, datetime

from .indicators import resample

REGIMES = {"trend_up": "Trend up", "trend_down": "Trend down", "range": "Range-bound", "volatile": "Volatile",
           "expiry_day": "Expiry day"}
WIDE = 1.5
CAL = [(15, 0.23, 0.68), (105, 0.40, 0.21), (225, 0.47, 0.14)]    # (minutes after 09:15, move %, efficiency)


def thresholds(minutes: int) -> tuple[float, float]:
    if minutes <= CAL[0][0]:
        return CAL[0][1], CAL[0][2]
    for (m0, v0, e0), (m1, v1, e1) in zip(CAL, CAL[1:]):
        if minutes <= m1:
            f = (minutes - m0) / (m1 - m0)
            return v0 + f * (v1 - v0), e0 + f * (e1 - e0)
    return CAL[-1][1], CAL[-1][2]


def _atr(bars: list) -> float | None:
    if len(bars) < 2:
        return None
    tr = [max(b[2] - b[3], abs(b[2] - bars[i - 1][4]), abs(b[3] - bars[i - 1][4])) for i, b in enumerate(bars) if i]
    return sum(tr) / len(tr)


def classify(bars: list, now: datetime, expiry: str | None) -> tuple[str | None, str]:
    """(condition, words). bars: completed one-minute bars, the session before and today."""
    today = now.date()
    if expiry and date.fromisoformat(expiry) == today:
        return "expiry_day", "the traded expiry is today"
    day = [b for b in bars if b[0].date() == today]
    if len(day) < 15:
        return None, "first 15 minutes of the day not over"
    before = [b for b in bars if b[0].date() < today]
    prev_day = [b for b in before if b[0].date() == before[-1][0].date()] if before else []
    o, last = day[0][1], day[-1][4]
    move = (last / o - 1) * 100
    five = resample(day, 5)
    closes = [o] + [b[4] for b in five]
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    eff = abs(closes[-1] - closes[0]) / path if path else 0.0
    # the session before, over the same minutes after the open: opening swings are wider than the day's average
    span = len(day)
    a_now, a_prev = _atr(five), _atr(resample(prev_day[:span], 5))
    wide = a_now / a_prev if a_now and a_prev else None
    MOVE, EFF = thresholds(now.hour * 60 + now.minute - 555)
    if wide is not None and wide >= WIDE and eff < EFF:
        return "volatile", f"swings {wide:.1f}x yesterday's, going nowhere (efficiency {eff:.2f})"
    if eff >= EFF and move >= MOVE:
        return "trend_up", f"index {move:+.2f}% since the open, moving steadily (efficiency {eff:.2f})"
    if eff >= EFF and move <= -MOVE:
        return "trend_down", f"index {move:+.2f}% since the open, moving steadily (efficiency {eff:.2f})"
    return "range", f"index {move:+.2f}% since the open (efficiency {eff:.2f})" + (f", swings {wide:.1f}x yesterday's" if wide else "")
