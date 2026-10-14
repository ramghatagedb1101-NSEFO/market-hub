"""
Forecast and learning. Pure functions only: no I/O, so live tracking and backtests share the code.

Model
  Each tool gives a score s_i in [-1, 1]. The blended view is
      z = DRIFT_SCALE * sum(w_i * s_i) / sum(w_i)      (in units of horizon sigma)
  so the predicted close is  base * exp(z * sig_h),  where sig_h = daily sigma * sqrt(h).
  The band is  base * exp((z +/- k) * sig_h),  with k calibrated so ~TARGET_COVERAGE of
  actual closes land inside it.

Learning (after each settlement)
  Tool weights: multiplicative weights on squared error. Tools that were wrong lose weight.
  Band k: nudged up when the actual close was outside the band, down when inside.
"""
import math
from datetime import date, timedelta

import numpy as np

from . import config, horizons
from .tools import TOOLS, daily_sigma

DEFAULT_WEIGHT = 1.0 / max(len(TOOLS), 1)


def _blend(signals: dict, weights: dict) -> float:
    if not signals:
        return 0.0
    ws = {t: weights.get(t, DEFAULT_WEIGHT) for t in signals}
    total = sum(ws.values())
    return config.DRIFT_SCALE * sum(ws[t] * s for t, s in signals.items()) / total


def forecast(index: str, horizon: str, asof: date, dates: list, closes: np.ndarray,
             weights: dict, band_k: float) -> dict:
    """Forecast the close for `horizon`, using only data up to and including `asof`."""
    target = horizons.target_for(horizon, index, asof)
    # Trading sessions in (asof, target]: weekdays only, exchange holidays not modelled.
    h = max(1, int(np.busday_count(np.datetime64(asof + timedelta(days=1)),
                                   np.datetime64(target + timedelta(days=1)))))
    sig = daily_sigma(closes)
    sig_h = max(sig * math.sqrt(h), 1e-4)
    signals = {name: s for name, fn in TOOLS.items()
               if (s := fn(closes, dates, target)) is not None}
    z = _blend(signals, weights)
    base = float(closes[-1])
    return {
        "index": index,
        "horizon": horizon,
        "asof": asof.isoformat(),
        "target": target.isoformat(),
        "base": base,
        "h": h,
        "sig_h": sig_h,
        "z": z,
        "pred": base * math.exp(z * sig_h),
        "lo": base * math.exp((z - band_k) * sig_h),
        "hi": base * math.exp((z + band_k) * sig_h),
        "band_k": band_k,
        "signals": signals,
    }


def learn(fc: dict, actual: float, weights: dict, band_k: float, n: int | None = None):
    """Update tool weights and band multiplier from one settled forecast. Returns (weights, k).

    n: settlements already seen for this (index, horizon), for an adaptive step size (Group F2,
    hub.band_step_test). A fixed step (n=None, the live default) never converges -- it keeps
    nudging the band by the same amount forever, so it oscillates around the target coverage
    indefinitely rather than settling near it. Passing n decays the step as eta0/sqrt(1+n), floored
    at ETA_BAND_MIN so the band stays able to react to a real regime change. Not switched on live
    until hub.band_step_test shows it actually improves (or at least doesn't worsen) calibration
    walk-forward against the real history -- see STATUS.md Group F2."""
    z_real = math.log(actual / fc["base"]) / fc["sig_h"]
    missed = not (fc["lo"] <= actual <= fc["hi"])
    eta = config.ETA_BAND if n is None else max(config.ETA_BAND_MIN, config.ETA_BAND / math.sqrt(1 + n))
    k = band_k + eta * ((1.0 if missed else 0.0) - (1 - config.TARGET_COVERAGE))
    k = min(max(k, 0.3), 4.0)

    new = dict(weights)
    for tool, s in fc["signals"].items():
        loss = min((z_real - config.DRIFT_SCALE * s) ** 2, 9.0)
        new[tool] = new.get(tool, DEFAULT_WEIGHT) * math.exp(-config.ETA_WEIGHT * loss)
    total = sum(new.values())
    if total > 0:
        new = {t: max(v / total, config.WEIGHT_FLOOR) for t, v in new.items()}
        total = sum(new.values())
        new = {t: v / total for t, v in new.items()}
    return new, k


def score(fc: dict, actual: float) -> dict:
    """Outcome metrics for one settled forecast."""
    err_pct = (actual / fc["pred"] - 1) * 100
    return {
        "err_pct": err_pct,
        "in_band": fc["lo"] <= actual <= fc["hi"],
        "direction_hit": (fc["pred"] - fc["base"]) * (actual - fc["base"]) > 0,
        "naive_err_pct": (actual / fc["base"] - 1) * 100,
    }
