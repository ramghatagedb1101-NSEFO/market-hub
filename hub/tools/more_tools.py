"""Four more tools, closing the original "ten analytical tools" request (six were built first; see
core_tools.py). Each covers a signal type/timescale the first six don't: medium-term EMA momentum
(vs trend_sma's simple 20/50 crossover), a longer mean-reversion window (vs rsi_reversion's RSI(14)),
10-day continuation (vs short_reversal's 1-day reversal and drift_252's full-year drift), and
day-of-month seasonality (vs weekday_bias's day-of-week seasonality)."""
import calendar
import math

import numpy as np

from . import register, daily_sigma


def _ema(vals: np.ndarray, span: int) -> float:
    alpha = 2.0 / (span + 1)
    e = vals[0]
    for v in vals[1:]:
        e = alpha * v + (1 - alpha) * e
    return e


@register("macd_cross")
def macd_cross(c, d, target):
    """12/26-session EMA momentum (MACD line), scaled by volatility: medium-term trend-following,
    a different lens from trend_sma's simple 20/50-average crossover."""
    if len(c) < 120:
        return None
    sig = daily_sigma(c)
    if sig == 0:
        return None
    window = c[-120:]
    macd = (_ema(window, 12) - _ema(window, 26)) / c[-1]
    return math.tanh(macd / sig * 10)


@register("bollinger_reversion")
def bollinger_reversion(c, d, target):
    """Z-score of the close against a 20-session rolling mean/std: far above leans bearish (mean
    reversion), far below leans bullish. A longer, more standard reversion window than
    rsi_reversion's RSI(14)."""
    if len(c) < 20:
        return None
    window = c[-20:]
    mean, std = window.mean(), window.std(ddof=1)
    if std == 0:
        return None
    z = (c[-1] - mean) / std
    return float(np.clip(-z / 2, -1, 1))


@register("momentum_10d")
def momentum_10d(c, d, target):
    """Ten-session cumulative return in volatility units: medium-term continuation, a different
    timescale from short_reversal's one-day mean-reversion and drift_252's full-year drift."""
    if len(c) < 11:
        return None
    sig = daily_sigma(c)
    if sig == 0:
        return None
    r10 = math.log(c[-1] / c[-11])
    return float(np.clip(r10 / (sig * math.sqrt(10) * 2), -1, 1))


def _is_month_edge(day) -> bool:
    last_day = calendar.monthrange(day.year, day.month)[1]
    return day.day <= 3 or day.day >= last_day - 2


@register("turn_of_month")
def turn_of_month(c, d, target):
    """Average historical return on days in the first or last few sessions of the month (the
    well-documented "turn of the month" equity effect), in volatility units. Abstains with a
    neutral 0.0 when the target date itself isn't a turn-of-month date -- a different seasonal
    axis from weekday_bias's day-of-week effect."""
    if len(c) < 252:
        return None
    sig = daily_sigma(c)
    if sig == 0:
        return None
    if not _is_month_edge(target):
        return 0.0
    r = np.diff(np.log(c))
    mask = np.array([_is_month_edge(x) for x in d[1:]])
    if mask.sum() < 20:
        return None
    return math.tanh(r[mask].mean() / sig * 5)
