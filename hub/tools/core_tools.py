"""Six starter tools. Each returns a score in [-1, 1] or None to abstain."""
import math

import numpy as np

from . import register, daily_sigma


@register("trend_sma")
def trend_sma(c, d, target):
    """Price above its 20- and 50-session averages, scaled by volatility."""
    if len(c) < 50:
        return None
    sig = daily_sigma(c)
    if sig == 0:
        return None
    above20 = c[-1] / c[-20:].mean() - 1
    slope = c[-20:].mean() / c[-50:].mean() - 1
    return math.tanh((above20 + slope) / (2 * sig))


@register("rsi_reversion")
def rsi_reversion(c, d, target):
    """Classic RSI(14) mean reversion: overbought leans down, oversold leans up."""
    if len(c) < 15:
        return None
    diff = np.diff(c[-15:])
    gain, loss = diff[diff > 0].sum(), -diff[diff < 0].sum()
    if gain + loss == 0:
        return 0.0
    rsi = 100 - 100 / (1 + gain / max(loss, 1e-12))
    return float(np.clip((50 - rsi) / 25, -1, 1))


@register("short_reversal")
def short_reversal(c, d, target):
    """Yesterday's move tends to partly unwind after a large day."""
    sig = daily_sigma(c)
    if sig == 0:
        return None
    r1 = math.log(c[-1] / c[-2])
    return float(np.clip(-r1 / (2 * sig), -1, 1))


@register("range_position")
def range_position(c, d, target):
    """Where the close sits in the last 5 sessions' range (close-based approximation)."""
    if len(c) < 5:
        return None
    hi, lo = c[-5:].max(), c[-5:].min()
    if hi == lo:
        return 0.0
    p = (c[-1] - lo) / (hi - lo)
    return float(np.clip(1 - 2 * p, -1, 1))


@register("drift_252")
def drift_252(c, d, target):
    """One-year average daily drift in volatility units. Matters most for month/year horizons."""
    if len(c) < 252:
        return None
    sig = daily_sigma(c)
    if sig == 0:
        return None
    mean_r = np.diff(np.log(c[-253:])).mean()
    return math.tanh(mean_r / sig * 10)


@register("weekday_bias")
def weekday_bias(c, d, target):
    """Average historical return on the target weekday, in volatility units."""
    if len(c) < 120:
        return None
    sig = daily_sigma(c)
    if sig == 0:
        return None
    r = np.diff(np.log(c))
    days = np.array([x.weekday() for x in d[1:]])
    mask = days == target.weekday()
    if mask.sum() < 20:
        return None
    return math.tanh(r[mask].mean() / sig * 5)
