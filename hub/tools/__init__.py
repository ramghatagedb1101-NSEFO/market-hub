"""
Analytical tools. Each tool is one function in its own module under hub/tools/.

    @register("my_tool")
    def my_tool(closes, dates, target):   # closes: np.ndarray, dates: list[date], target: date
        return score                      # float in [-1, 1]: +1 bullish, -1 bearish, 0 neutral
        return None                       # abstain when there is not enough data

Drop a new .py file in this folder and it is loaded automatically. The engine learns how much
to trust each tool from its track record, so a weak tool is down-weighted, not hand-deleted.
"""
import importlib
import pkgutil

import numpy as np

from .. import config

TOOLS: dict = {}


def register(name: str):
    def deco(fn):
        if name in TOOLS:
            raise ValueError(f"duplicate tool name: {name}")
        TOOLS[name] = fn
        return fn
    return deco


def daily_sigma(closes: np.ndarray) -> float:
    """Std-dev of daily log returns over the volatility window."""
    window = closes[-(config.VOL_WINDOW + 1):]
    r = np.diff(np.log(window))
    return float(r.std(ddof=1)) if len(r) > 2 else 0.0


for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
