"""
black_scholes.py
Computes option greeks using Black-Scholes model.
Used when Kite WebSocket does not provide greeks (base plan).

Inputs per option:
- S: underlying spot price
- K: strike price
- T: days to expiry (converted to years internally)
- r: risk-free rate (RBI repo rate — update if RBI changes)
- sigma: annualised volatility (use HV_30d or ATM IV if available)
- option_type: 'CE' or 'PE'

Outputs:
- iv: implied volatility (if market price provided, else uses sigma)
- delta: rate of change of option price vs spot
- theta: daily time decay in rupees per share (negative)
- gamma: rate of change of delta
- vega: sensitivity to 1% change in IV
"""

import math
from scipy.stats import norm
from scipy.optimize import brentq

RISK_FREE_RATE = 0.065  # RBI repo rate — update when RBI changes policy


def d1_d2(S, K, T, r, sigma):
    """Compute d1 and d2 for Black-Scholes"""
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0, 0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return d1, d2


def bs_price(S, K, T, r, sigma, option_type="CE"):
    """Black-Scholes theoretical price"""
    if T <= 0:
        if option_type == "CE":
            return max(0, S - K)
        else:
            return max(0, K - S)

    d1, d2 = d1_d2(S, K, T, r, sigma)

    if option_type == "CE":
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def implied_volatility(market_price, S, K, T, r, option_type="CE") -> float:
    """
    Compute implied volatility using Brent's method.
    Returns IV as a percentage (e.g. 18.5 for 18.5%).
    Returns 0 if computation fails.
    """
    if T <= 0 or market_price <= 0:
        return 0.0

    intrinsic = max(0, S - K) if option_type == "CE" else max(0, K - S)
    if market_price <= intrinsic:
        return 0.0

    try:
        iv = brentq(
            lambda sigma: bs_price(S, K, T, r, sigma, option_type) - market_price,
            1e-6, 10.0,  # Search between 0.0001% and 1000% IV
            xtol=1e-6,
            maxiter=100
        )
        return round(iv * 100, 2)  # Return as percentage
    except Exception:
        return 0.0


def compute_greeks(S, K, T_days, sigma_pct, option_type="CE", market_price=0.0) -> dict:
    """
    Main function — compute all greeks for one option.

    Args:
        S: spot price
        K: strike price
        T_days: days to expiry
        sigma_pct: volatility as percentage (e.g. 18.5 for 18.5%)
        option_type: 'CE' or 'PE'
        market_price: actual market price (LTP) — used to compute IV

    Returns dict with: iv, delta, gamma, theta, vega
    """
    T = T_days / 252.0
    r = RISK_FREE_RATE

    # Use market price to compute IV if available, else use sigma
    if market_price > 0:
        iv_pct = implied_volatility(market_price, S, K, T, r, option_type)
        sigma = iv_pct / 100.0 if iv_pct > 0 else sigma_pct / 100.0
    else:
        sigma = sigma_pct / 100.0
        iv_pct = sigma_pct

    if T <= 0 or sigma <= 0:
        return {"iv": 0, "delta": 0, "gamma": 0, "theta": 0, "vega": 0}

    d1, d2 = d1_d2(S, K, T, r, sigma)

    # Delta
    if option_type == "CE":
        delta = norm.cdf(d1)
    else:
        delta = norm.cdf(d1) - 1

    # Gamma (same for CE and PE)
    gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))

    # Theta (per calendar day, in rupees per share)
    theta_annual = (
        -(S * norm.pdf(d1) * sigma) / (2 * math.sqrt(T))
        - r * K * math.exp(-r * T) * (norm.cdf(d2) if option_type == "CE" else norm.cdf(-d2))
    )
    theta_daily = theta_annual / 365  # Per calendar day

    # Vega (per 1% change in IV)
    vega = S * norm.pdf(d1) * math.sqrt(T) / 100

    return {
        "iv":    round(iv_pct, 2),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta_daily, 4),  # Negative number — daily decay per share
        "vega":  round(vega, 4)
    }


def enrich_strikes_with_greeks(strikes_data: dict, spot: float, T_days: int, hv_30d: float) -> dict:
    """
    Adds BS greeks to every strike in the chain.
    Called from payload_builder before sending to Claude.

    Args:
        strikes_data: dict of {strike: {call_ltp, put_ltp, call_iv, put_iv, ...}}
        spot: current spot price
        T_days: days to expiry
        hv_30d: 30-day historical volatility as percentage

    Returns enriched strikes_data with greeks added.
    """
    # Use HV as fallback sigma if IV not available
    fallback_sigma = hv_30d if hv_30d > 0 else 20.0  # Default 20% if no HV

    for strike, data in strikes_data.items():
        T = max(T_days, 1)  # Minimum 1 day

        # Call greeks
        call_ltp   = data.get("call_ltp", 0)
        call_iv_ws = data.get("call_iv", 0)  # From WebSocket (0 on base plan)
        sigma_call = call_iv_ws if call_iv_ws > 0 else fallback_sigma

        call_greeks = compute_greeks(
            S=spot, K=strike, T_days=T,
            sigma_pct=sigma_call,
            option_type="CE",
            market_price=call_ltp
        )

        data["call_iv"]    = call_greeks["iv"] if call_greeks["iv"] > 0 else sigma_call
        data["call_delta"] = call_greeks["delta"]
        data["call_gamma"] = call_greeks["gamma"]
        data["call_theta"] = call_greeks["theta"]
        data["call_vega"]  = call_greeks["vega"]

        # Put greeks
        put_ltp   = data.get("put_ltp", 0)
        put_iv_ws = data.get("put_iv", 0)
        sigma_put = put_iv_ws if put_iv_ws > 0 else fallback_sigma

        put_greeks = compute_greeks(
            S=spot, K=strike, T_days=T,
            sigma_pct=sigma_put,
            option_type="PE",
            market_price=put_ltp
        )

        data["put_iv"]    = put_greeks["iv"] if put_greeks["iv"] > 0 else sigma_put
        data["put_delta"] = put_greeks["delta"]
        data["put_gamma"] = put_greeks["gamma"]
        data["put_theta"] = put_greeks["theta"]
        data["put_vega"]  = put_greeks["vega"]

    return strikes_data
