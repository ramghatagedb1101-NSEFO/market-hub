"""
calculators.py
All server-side computations before payload is sent to Claude.

Upgrades in this version:
- calculate_gex(): Notional Gamma Exposure with correct put sign convention
  Uses full ±15% strike range to avoid flip zone bias
  Returns gex_total, gex_flip_zone, gex_regime
- calculate_monthly_vwap(): Anchored to derivative contract start date
  (day after prior month expiry), not calendar month
  Requires OHLCV data from kite_history_pull.py
- _load_ohlcv(): Loads full OHLCV records from price_history/
  kite_history_pull.py must be re-run to include volume data

Existing functions unchanged:
- calculate_max_pain, calculate_iv_rank, calculate_hv_30d
- get_nifty_trend, save_iv_snapshot, save_price_snapshot
"""

import json
import numpy as np
from pathlib import Path
from datetime import date, datetime


# ── NSE contract start dates (day after prior expiry) ────────────────
# Used for anchored VWAP calculation.
# Update this dict at the start of each new contract month.
CONTRACT_START_DATES = {
    "2026-03": "2026-02-27",   # March contract: started after Feb 26 expiry
    "2026-04": "2026-03-31",   # April contract: starts after Mar 30 expiry
    "2026-05": "2026-04-29",   # May contract
    "2026-06": "2026-05-29",   # June contract
    "2026-07": "2026-06-26",   # July contract
    "2026-08": "2026-07-31",   # August contract
    "2026-09": "2026-08-28",   # September contract
    "2026-10": "2026-09-25",   # October contract
    "2026-11": "2026-10-30",   # November contract
    "2026-12": "2026-11-27",   # December contract
}


# ── File path helpers ─────────────────────────────────────────────────
def _price_history_path(symbol: str) -> Path:
    filename = symbol.replace(" ", "_").replace("&", "AND")
    # Anchored to forecast_hub/price_history (was CWD-relative in the old tool).
    return Path(__file__).resolve().parent.parent / "price_history" / f"{filename}.json"


def _load_closes(symbol: str) -> list:
    """Load closing prices. Handles both new list format and old dict format."""
    path = _price_history_path(symbol)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d["close"] for d in data if "close" in d]
        if isinstance(data, dict) and "daily_close" in data:
            return data["daily_close"]
        return []
    except Exception:
        return []


def _load_ohlcv(symbol: str) -> list:
    """
    Load full OHLCV records from price_history/.
    Returns list of dicts: [{date, open, high, low, close, volume}, ...]
    Returns empty list if volume data not present (old format).

    Requires kite_history_pull.py to be re-run with OHLCV mode.
    If only close prices exist, returns empty list — VWAP will be unavailable.
    """
    path = _price_history_path(symbol)
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, list):
            # Check if volume data is present
            sample = data[0] if data else {}
            if "volume" not in sample:
                return []   # Old format — close only, no volume
            return data
        return []
    except Exception:
        return []


# ── Max Pain ──────────────────────────────────────────────────────────
def calculate_max_pain(strikes_data: dict) -> float:
    """
    Max pain = strike where total option buyer loss is maximum.
    Writers pin the stock here to maximise their P&L at expiry.
    Uses max() — confirmed correct.
    """
    strikes = sorted(strikes_data.keys())
    if not strikes:
        return 0.0

    pain_at = {}
    for expiry_price in strikes:
        total_pain = 0
        for strike, data in strikes_data.items():
            call_oi = data.get("call_oi", 0)
            put_oi  = data.get("put_oi", 0)
            total_pain += max(0.0, expiry_price - strike) * call_oi
            total_pain += max(0.0, strike - expiry_price) * put_oi
        pain_at[expiry_price] = total_pain

    return float(max(pain_at, key=pain_at.get))


# ── IV Rank ───────────────────────────────────────────────────────────
# ── IV-rank robustness knobs ──────────────────────────────────────────
# An equity ATM IV above this is not a volatility reading, it is a bad sample —
# a stale close, an illiquid strike, or a price/tenor mismatch in the source
# data. Indian single stocks print 10-60% ATM IV; even a crisis print stays well
# under 150. Samples above the ceiling are DISCARDED before ranking rather than
# clamped, because clamping still lets them define the top of the range.
IV_SANITY_CEILING_PCT = 150.0
# Rank against the 5th-95th percentile, not raw min/max. min/max makes the whole
# scale hostage to two observations, so ONE surviving bad sample flattens every
# subsequent reading toward zero.
IV_RANK_LOW_PCTL  = 5
IV_RANK_HIGH_PCTL = 95

# Resolve iv_history/ relative to THIS FILE, not the process CWD. The old
# relative Path() silently returned the no-history fallback whenever the caller
# ran from anywhere other than the project root.
_IV_HISTORY_DIR = Path(__file__).resolve().parent.parent / "iv_history"   # forecast_hub/iv_history


def calculate_iv_rank(symbol: str, current_iv: float) -> dict:
    """
    IV Rank = where current_iv sits between the 5th and 95th percentile of the
    trailing 252 sessions of ATM IV, as a 0-100 figure.

    Reads from iv_history/ populated by backfill_iv_history.py.

    WHY THIS IS NOT (current - min) / (max - min): the source series carries bad
    samples. Measured on 18 NIFTY 50 names (17-Aug-2026), 59-116 of 252 entries
    per symbol exceeded 100% IV with maxima of 390-900%, against real ATM IV of
    13-32%. Ranking RELIANCE's genuine 15.3% against a 0.83-555.17 range returned
    2.6, and MIN_IV_RANK=30 then rejected the entire universe — the option-selling
    screen produced zero recommendations every run. Two independent defences:

      1. Drop samples above IV_SANITY_CEILING_PCT outright (see the note there).
      2. Rank against percentiles, so a bad sample that slips under the ceiling
         moves the bound instead of defining it.

    The upstream cause is fixed separately in backfill_iv_history.get_atm_iv;
    these guards are what keep a future data fault from silently zeroing the
    screen again, which is why both stay even once the history is clean.

    `iv_rank_data_quality` reports what the number is actually based on, so a
    caller can tell a measured rank from an assumed one:
      sufficient                      — >=30 clean samples, ranked on percentiles
      estimated_insufficient_history  — assumed range, NOT a measurement
      filtered_insufficient_history   — samples existed but too few survived the
                                        sanity ceiling; the data is bad, not thin
    """
    iv_history_path = _IV_HISTORY_DIR / f"{symbol}.json"
    quality = "estimated_insufficient_history"
    raw_count = clean_count = 0

    iv_series = []
    if iv_history_path.exists():
        try:
            with open(iv_history_path) as f:
                history = json.load(f)
            if isinstance(history, list):
                iv_series = [d["iv"] for d in history if "iv" in d]
            else:
                iv_series = history.get("daily_atm_iv", [])
        except Exception:
            iv_series = []

    recent_252 = iv_series[-252:]
    raw_count = len(recent_252)
    clean = [float(v) for v in recent_252
             if isinstance(v, (int, float)) and 0 < v <= IV_SANITY_CEILING_PCT]
    clean_count = len(clean)

    if clean_count >= 30:
        iv_52w_high = float(np.percentile(clean, IV_RANK_HIGH_PCTL))
        iv_52w_low  = float(np.percentile(clean, IV_RANK_LOW_PCTL))
        quality = "sufficient"
    else:
        # No usable history. Assume a plausible band around the current reading
        # — this yields a CONSTANT 33.3 for every symbol by construction
        # ((iv - 0.6iv) / (1.8iv - 0.6iv)), so it is a placeholder, not a
        # measurement. Callers gating on iv_rank must check the quality field:
        # 32 of the 50 NIFTY 50 names hit this branch and passed a
        # MIN_IV_RANK=30 gate on nothing but that arithmetic.
        iv_52w_high = round(current_iv * 1.8, 2)
        iv_52w_low  = round(current_iv * 0.6, 2)
        if raw_count:
            quality = "filtered_insufficient_history"

    if iv_52w_high <= iv_52w_low:
        iv_rank = 50.0
    else:
        iv_rank = (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100
        iv_rank = max(0.0, min(100.0, round(iv_rank, 1)))

    return {
        "iv_rank":              iv_rank,
        "atm_iv_52w_high":      round(iv_52w_high, 2),
        "atm_iv_52w_low":       round(iv_52w_low, 2),
        "iv_rank_data_quality": quality,
        "iv_rank_samples":      clean_count,
        "iv_rank_samples_dropped": raw_count - clean_count,
    }


# ── Historical Volatility ─────────────────────────────────────────────
def calculate_hv_30d(symbol: str) -> float:
    """
    30-day HV from daily log returns, annualised with sqrt(252).
    Reads from price_history/ populated by kite_history_pull.py.
    """
    closes = _load_closes(symbol)
    if len(closes) < 31:
        return 0.0

    recent = closes[-31:]
    log_returns = np.diff(np.log(recent))
    hv_daily = float(np.std(log_returns, ddof=1))
    return round(hv_daily * np.sqrt(252) * 100, 2)


# ── Nifty Trend ───────────────────────────────────────────────────────
def get_nifty_trend(lookback: int = 10) -> str:
    """
    10-session EMA comparison for Nifty trend.
    Replaces hardcoded 'downtrend' string.
    """
    closes = _load_closes("NIFTY 50")
    if not closes:
        return "UNKNOWN — run kite_history_pull.py"
    if len(closes) < lookback:
        return "INSUFFICIENT DATA"

    recent = closes[-lookback:]
    ema = recent[0]
    k = 2.0 / (lookback + 1)
    for price in recent[1:]:
        ema = price * k + ema * (1 - k)

    last = closes[-1]
    if last > ema * 1.005:
        return "uptrend"
    elif last < ema * 0.995:
        return "downtrend"
    else:
        return "sideways"


# ── GEX — Gamma Exposure ──────────────────────────────────────────────
def calculate_gex(strikes_data: dict, spot: float, lot_size: int) -> dict:
    """
    Notional Gamma Exposure (GEX) computation.

    Formula per strike:
        Call GEX = +gamma × call_oi × lot_size × spot² × 0.01
        Put GEX  = -gamma × put_oi  × lot_size × spot² × 0.01
        Net GEX  = Call GEX + Put GEX

    Sign convention:
        Positive GEX = dealers are net long gamma (stabilising)
            → they sell when price rises, buy when price falls
            → market mean-reverts, moves are dampened
        Negative GEX = dealers are net short gamma (amplifying)
            → they buy when price rises, sell when price falls
            → market trends, moves accelerate

    GEX Flip Zone = strike where cumulative GEX crosses zero
        → Above flip: dealers stabilise the market
        → Below flip: dealers amplify moves (gamma squeeze risk)

    Uses ALL available strikes (not just ±6% filter) to avoid
    mathematical skew in the flip zone calculation.
    Minimum 10 strikes required for meaningful output.

    Returns:
        gex_total:       float — total net GEX across all strikes
        gex_flip_zone:   float — strike where GEX crosses zero
        gex_regime:      str   — "STABILISING" | "AMPLIFYING" | "NEUTRAL"
        gex_by_strike:   list  — [{strike, call_gex, put_gex, net_gex}, ...]
        flip_confidence: str   — "HIGH" | "LOW" (based on number of strikes)
    """
    if spot <= 0 or not strikes_data:
        return {
            "gex_total": 0.0,
            "gex_flip_zone": 0.0,
            "gex_regime": "UNKNOWN",
            "gex_by_strike": [],
            "flip_confidence": "LOW",
        }

    spot2 = spot * spot
    scale = spot2 * 0.01

    # Compute GEX per strike
    gex_by_strike = []
    for strike, data in strikes_data.items():
        gamma    = data.get("call_gamma", data.get("gamma", 0))
        call_oi  = data.get("call_oi", 0)
        put_oi   = data.get("put_oi", 0)

        call_gex = gamma * call_oi * lot_size * scale
        put_gex  = -gamma * put_oi * lot_size * scale   # negative — puts destabilise
        net_gex  = call_gex + put_gex

        gex_by_strike.append({
            "strike":   strike,
            "call_gex": round(call_gex / 1e7, 3),   # in crores
            "put_gex":  round(put_gex / 1e7, 3),
            "net_gex":  round(net_gex / 1e7, 3),
        })

    gex_by_strike.sort(key=lambda x: x["strike"])

    # Total GEX
    total_gex = sum(g["net_gex"] for g in gex_by_strike)

    # GEX flip zone — find where cumulative GEX crosses zero
    # Method: compute cumulative GEX from lowest strike upward
    # Flip zone = strike where sign changes from negative to positive
    flip_zone = spot  # default to spot if no flip found
    flip_found = False

    if len(gex_by_strike) >= 5:
        cum = 0.0
        prev_sign = None
        for g in gex_by_strike:
            cum += g["net_gex"]
            curr_sign = 1 if cum >= 0 else -1
            if prev_sign is not None and curr_sign != prev_sign:
                flip_zone = g["strike"]
                flip_found = True
                break
            prev_sign = curr_sign

    # Regime: based on whether spot is above or below flip zone
    if not flip_found:
        regime = "NEUTRAL"
    elif spot > flip_zone:
        regime = "STABILISING"   # spot above flip = dealers long gamma
    else:
        regime = "AMPLIFYING"    # spot below flip = dealers short gamma, squeeze risk

    confidence = "HIGH" if len(gex_by_strike) >= 10 else "LOW"

    return {
        "gex_total":       round(total_gex, 3),
        "gex_flip_zone":   flip_zone,
        "gex_regime":      regime,
        "gex_by_strike":   gex_by_strike,
        "flip_confidence": confidence,
    }


# ── Monthly VWAP (Anchored to Contract Start) ─────────────────────────
def calculate_monthly_vwap(symbol: str, expiry_date_str: str) -> dict:
    """
    Computes anchored VWAP from the start of the current derivative contract.
    Contract start = day after prior month's expiry (institutional anchor point).

    Formula:
        VWAP = Σ(Typical Price × Volume) / Σ(Volume)
        Typical Price = (High + Low + Close) / 3

    Requires OHLCV data in price_history/ (run kite_history_pull.py with volume).

    Returns:
        vwap:          float — anchored VWAP value
        spot_vs_vwap:  str   — "above" | "below" | "at"
        vwap_pct_diff: float — (spot - vwap) / vwap * 100
        anchor_date:   str   — contract start date used
        days_used:     int   — number of sessions in VWAP calculation
        available:     bool  — False if OHLCV data not present
    """
    # Determine contract start date from expiry
    expiry = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
    month_key = expiry.strftime("%Y-%m")
    anchor_date_str = CONTRACT_START_DATES.get(month_key)

    if not anchor_date_str:
        return {"vwap": 0.0, "spot_vs_vwap": "unknown", "vwap_pct_diff": 0.0,
                "anchor_date": "unknown", "days_used": 0, "available": False}

    ohlcv = _load_ohlcv(symbol)
    if not ohlcv:
        return {"vwap": 0.0, "spot_vs_vwap": "unknown", "vwap_pct_diff": 0.0,
                "anchor_date": anchor_date_str, "days_used": 0, "available": False}

    # Filter to sessions from anchor date onward
    sessions = [d for d in ohlcv if d.get("date", "") >= anchor_date_str]
    if not sessions:
        return {"vwap": 0.0, "spot_vs_vwap": "unknown", "vwap_pct_diff": 0.0,
                "anchor_date": anchor_date_str, "days_used": 0, "available": False}

    # Compute cumulative VWAP
    cum_tp_vol = 0.0
    cum_vol    = 0.0

    for s in sessions:
        high   = s.get("high", s.get("close", 0))
        low    = s.get("low",  s.get("close", 0))
        close  = s.get("close", 0)
        volume = s.get("volume", 0)

        if volume <= 0 or close <= 0:
            continue

        typical_price = (high + low + close) / 3.0
        cum_tp_vol   += typical_price * volume
        cum_vol      += volume

    if cum_vol <= 0:
        return {"vwap": 0.0, "spot_vs_vwap": "unknown", "vwap_pct_diff": 0.0,
                "anchor_date": anchor_date_str, "days_used": len(sessions), "available": False}

    vwap = round(cum_tp_vol / cum_vol, 2)

    # Spot vs VWAP — use last close as proxy (live spot not available here)
    last_close = sessions[-1].get("close", 0)
    if last_close > 0 and vwap > 0:
        diff = round((last_close - vwap) / vwap * 100, 2)
        if abs(diff) < 0.3:
            relation = "at"
        elif diff > 0:
            relation = "above"
        else:
            relation = "below"
    else:
        diff     = 0.0
        relation = "unknown"

    return {
        "vwap":          vwap,
        "spot_vs_vwap":  relation,
        "vwap_pct_diff": diff,
        "anchor_date":   anchor_date_str,
        "days_used":     len(sessions),
        "available":     True,
    }


# ── IV Snapshot ───────────────────────────────────────────────────────
def save_iv_snapshot(symbol: str, atm_iv: float):
    """Called at 3:29 PM daily to accumulate IV history."""
    path = Path(f"iv_history/{symbol}.json")
    path.parent.mkdir(exist_ok=True)

    if path.exists():
        with open(path) as f:
            history = json.load(f)
        if isinstance(history, list):
            history = {
                "symbol":       symbol,
                "daily_atm_iv": [d["iv"] for d in history if "iv" in d],
                "dates":        [d["date"] for d in history if "date" in d],
            }
    else:
        history = {"symbol": symbol, "daily_atm_iv": [], "dates": []}

    today_str = str(date.today())
    if history["dates"] and history["dates"][-1] == today_str:
        history["daily_atm_iv"][-1] = atm_iv
    else:
        history["daily_atm_iv"].append(atm_iv)
        history["dates"].append(today_str)

    with open(path, "w") as f:
        json.dump(history, f, indent=2)


# ── Price Snapshot (legacy) ───────────────────────────────────────────
def save_price_snapshot(symbol: str, close_price: float):
    """
    Legacy daily accumulation — superseded by kite_history_pull.py.
    Kept for backward compatibility. Appends to existing format.
    """
    path = _price_history_path(symbol)
    path.parent.mkdir(exist_ok=True)
    today_str = str(date.today())

    if path.exists():
        with open(path) as f:
            data = json.load(f)
    else:
        data = []

    if isinstance(data, list):
        if data and data[-1].get("date") == today_str:
            data[-1]["close"] = close_price
        else:
            data.append({"date": today_str, "close": close_price})
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    else:
        if data.get("dates") and data["dates"][-1] == today_str:
            data["daily_close"][-1] = close_price
        else:
            data.setdefault("daily_close", []).append(close_price)
            data.setdefault("dates", []).append(today_str)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
