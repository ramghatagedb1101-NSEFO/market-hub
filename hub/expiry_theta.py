"""
Expiry-day theta harvest: a NIFTY iron condor opened specifically on its own expiry morning, far
enough from spot to survive a realistic intraday move, profiting from the day's rapid time decay.

This is a deliberately SEPARATE module from rg/strategy.py, not a variant of it. The stock
credit-spread screen has a hard 30-DTE floor and force-closes at 21 DTE specifically to stay out of
the high-gamma final days before expiry (see rg/config.py). This module trades exactly the window
that choice avoids, so it carries a different, higher risk profile and must never be confused with
the validated-feeling language the rest of this codebase uses. It is EXPERIMENTAL and UNVALIDATED:
there is no intraday historical options data in this repo to backtest 0-DTE structures against, so
unlike the daily job's other suggestions this has not even been checked against the past. Treat
every output as a hypothesis, not a track record.

Meant to run several times during market hours (a new GitHub Actions workflow, not the once-daily
job), so the owner can see a fresh read as the session develops: morning, a new suggestion; later
runs, a HOLD/EXIT read on whatever was suggested that morning, from the stop-loss/profit-target
gates below. No real order is ever placed by this script -- same as the rest of this codebase, the
owner places trades manually in Kite.

Needs KITE_API_KEY/KITE_ACCESS_TOKEN (same relay-issued token the daily job uses) and the free NIFTY
close history in state/prices.json (for the day's own realized volatility).
"""
import json
from datetime import datetime

from . import config
from .sources import kite

OUT_FILE = config.SITE_DIR / "data" / "expiry_theta.json"
STATE_FILE = config.REPO / "state" / "expiry_theta_state.json"
SPOT_SYMBOL = "NSE:NIFTY 50"
UNDERLYING = "NIFTY"

MIN_OTM_SIGMA_MULT = 3.0     # short strikes at least 3x the index's own daily sigma from spot
WING_WIDTH_STRIKES = 2       # long wings this many strikes further out (defined risk)
CHAIN_RANGE_PCT = 10.0       # only look at strikes within this % of spot (liquidity)
MIN_CREDIT_TO_WIDTH = 0.15   # stricter than the daily F&O screen's 0.10: less room to be wrong same-day
MIN_SHORT_PREMIUM = 3.0
STOP_LOSS_MULT = 1.5         # tighter than the 30-66 DTE screen's 2.0x: 0-DTE losses escalate faster
PROFIT_TARGET_PCT = 60.0
LOTS = 1                     # fixed, conservative: this is unvalidated, not sized like the main screen

DISCLAIMER = ("EXPERIMENTAL, UNVALIDATED. Zero-days-to-expiry options carry severe gamma risk -- a "
              "small index move late in the session can erase most of the premium in minutes. There "
              "is no backtest behind this (no intraday historical options data exists in this repo). "
              "The owner places any trade manually; nothing here executes an order.")


def _daily_sigma_nifty() -> float | None:
    try:
        closes = json.loads(config.PRICES_FILE.read_text(encoding="utf-8")).get("NIFTY") or {}
    except (OSError, ValueError):
        return None
    vals = [v for _, v in sorted(closes.items())][-61:]
    if len(vals) < 30:
        return None
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1]]
    if len(rets) < 20:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return var ** 0.5


def _todays_expiry(opts, today):
    return next((i["expiry"] for i in opts if i["expiry"] == today), None)


def _chain(k, opts, expiry, spot):
    rows = [i for i in opts if i["expiry"] == expiry
            and abs(i["strike"] / spot - 1) * 100 <= CHAIN_RANGE_PCT]
    syms = [f"NFO:{i['tradingsymbol']}" for i in rows]
    quotes = {}
    for start in range(0, len(syms), 400):
        quotes.update(k.quote(syms[start:start + 400]))
    chain = {}
    lot = rows[0]["lot_size"] if rows else None
    for i in rows:
        q = quotes.get(f"NFO:{i['tradingsymbol']}")
        if not q:
            continue
        side = chain.setdefault(float(i["strike"]), {"CE": None, "PE": None})
        side[i["instrument_type"]] = float(q["last_price"])
    return chain, lot


def _select_condor(spot, sigma, chain, lot):
    strikes = sorted(s for s in chain if chain[s]["CE"] is not None and chain[s]["PE"] is not None)
    if len(strikes) < 6:
        return {"structure": None, "reason": "Not enough liquid strikes in the expiring-today chain."}
    step = strikes[1] - strikes[0]
    min_otm = spot * sigma * MIN_OTM_SIGMA_MULT
    ce_s = min((s for s in strikes if s - spot >= min_otm), default=None)
    pe_s = max((s for s in strikes if spot - s >= min_otm), default=None)
    if ce_s is None or pe_s is None:
        return {"structure": None,
                "reason": f"No strike {MIN_OTM_SIGMA_MULT:.0f}x today's realized volatility "
                          f"(~{min_otm:.0f} points) away from spot in the listed range."}
    ce_l, pe_l = ce_s + WING_WIDTH_STRIKES * step, pe_s - WING_WIDTH_STRIKES * step
    legs = [
        {"action": "SELL", "type": "CE", "strike": ce_s, "price": chain[ce_s]["CE"]},
        {"action": "BUY", "type": "CE", "strike": ce_l, "price": chain.get(ce_l, {}).get("CE")},
        {"action": "SELL", "type": "PE", "strike": pe_s, "price": chain[pe_s]["PE"]},
        {"action": "BUY", "type": "PE", "strike": pe_l, "price": chain.get(pe_l, {}).get("PE")},
    ]
    if any(l["price"] is None for l in legs):
        return {"structure": None, "reason": "Wing strikes are not quoted."}
    credit = legs[0]["price"] - legs[1]["price"] + legs[2]["price"] - legs[3]["price"]
    width = WING_WIDTH_STRIKES * step
    if credit <= 0:
        return {"structure": None, "reason": "No net credit at these strikes."}
    if credit < MIN_CREDIT_TO_WIDTH * width or min(legs[0]["price"], legs[2]["price"]) < MIN_SHORT_PREMIUM:
        return {"structure": None,
                "reason": "Credit too thin for the risk (below the width gate or short premium floor)."}
    return {
        "structure": "Iron condor (expiry-day theta harvest)",
        "legs": legs,
        "lots": LOTS,
        "lot_size": lot,
        "net_credit_per_unit": round(credit, 2),
        "max_loss_per_unit": round(width - credit, 2),
        "credit_collected": round(credit * lot * LOTS, 2) if lot else None,
        "max_loss_total": round((width - credit) * lot * LOTS, 2) if lot else None,
        "stop_loss_debit": round(credit * STOP_LOSS_MULT, 2),
        "profit_target_debit": round(credit * (1 - PROFIT_TARGET_PCT / 100), 2),
        "breakevens": [round(pe_s - credit, 2), round(ce_s + credit, 2)],
    }


def _cost_to_close(k, legs) -> float | None:
    """Current cost to close the same four legs: what it would take to buy back the shorts and sell
    the longs right now, at last traded price. Missing a quote makes the whole read untrustworthy,
    so it returns None rather than a partial number."""
    total = 0.0
    for l in legs:
        q = k.quote([f"NFO:{l['tradingsymbol']}"]) if "tradingsymbol" in l else None
        if not q:
            return None
        price = float(next(iter(q.values()))["last_price"])
        total += -price if l["action"] == "SELL" else price
    return total


def main() -> dict:
    k = kite.client()
    instruments = k.instruments("NFO")
    opts = [i for i in instruments if i["name"] == UNDERLYING and i["instrument_type"] in ("CE", "PE")]
    today = datetime.now(config.IST).date()
    expiry = _todays_expiry(opts, today)
    now_ts = datetime.now(config.IST).isoformat(timespec="seconds")

    if expiry is None:
        out = {"ts": now_ts, "active": False, "reason": f"No {UNDERLYING} expiry today.", "disclaimer": DISCLAIMER}
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(out, separators=(",", ":"), default=str), encoding="utf-8")
        return out

    spot = float(k.quote([SPOT_SYMBOL])[SPOT_SYMBOL]["last_price"])
    sigma = _daily_sigma_nifty()
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    today_str = today.isoformat()

    if state.get("date") == today_str and state.get("legs"):
        # A position was already suggested earlier today: read its current cost to close and give a
        # hold/exit verdict from the stop-loss/profit-target gates, instead of screening again.
        legs = [dict(l, tradingsymbol=l.get("tradingsymbol")) for l in state["legs"]]
        # Re-resolve tradingsymbols against today's instrument list (strikes/expiry are fixed; the
        # morning run didn't persist a Kite tradingsymbol field, so look it up fresh each time).
        for l in legs:
            match = next((i for i in opts if i["expiry"] == expiry and i["instrument_type"] == l["type"]
                          and float(i["strike"]) == l["strike"]), None)
            l["tradingsymbol"] = match["tradingsymbol"] if match else None
        if any(l["tradingsymbol"] is None for l in legs):
            out = {"ts": now_ts, "active": True, "expiry": expiry.isoformat(), "spot": round(spot, 2),
                   "status": "error", "reason": "Could not re-resolve one or more legs' tradingsymbols.",
                   "entry": state, "disclaimer": DISCLAIMER}
        else:
            cost_now = _cost_to_close(k, legs)
            verdict = "hold"
            if cost_now is None:
                verdict, note = "unknown", "Could not get a live quote for one or more legs."
            elif cost_now >= state["stop_loss_debit"]:
                verdict, note = "exit", f"Cost to close ({cost_now:.2f}) has reached the stop-loss ({state['stop_loss_debit']:.2f})."
            elif cost_now <= state["profit_target_debit"]:
                verdict, note = "exit", f"Cost to close ({cost_now:.2f}) has reached the profit target ({state['profit_target_debit']:.2f})."
            else:
                note = f"Cost to close is {cost_now:.2f}, between the profit target ({state['profit_target_debit']:.2f}) and stop-loss ({state['stop_loss_debit']:.2f})."
            out = {"ts": now_ts, "active": True, "expiry": expiry.isoformat(), "spot": round(spot, 2),
                   "status": "management", "verdict": verdict, "note": note, "cost_to_close": cost_now,
                   "entry": state, "disclaimer": DISCLAIMER}
    elif sigma is None:
        out = {"ts": now_ts, "active": True, "expiry": expiry.isoformat(), "spot": round(spot, 2),
               "status": "no_trade", "reason": "Not enough NIFTY price history to compute today's realized volatility.",
               "disclaimer": DISCLAIMER}
    else:
        chain, lot = _chain(k, opts, expiry, spot)
        result = _select_condor(spot, sigma, chain, lot)
        if result.get("structure") is None:
            out = {"ts": now_ts, "active": True, "expiry": expiry.isoformat(), "spot": round(spot, 2),
                   "status": "no_trade", "reason": result["reason"], "disclaimer": DISCLAIMER}
        else:
            for l in result["legs"]:
                match = next((i for i in opts if i["expiry"] == expiry and i["instrument_type"] == l["type"]
                              and float(i["strike"]) == l["strike"]), None)
                l["tradingsymbol"] = match["tradingsymbol"] if match else None
            entry_state = {"date": today_str, "expiry": expiry.isoformat(), "spot_at_entry": round(spot, 2),
                           "legs": [{"type": l["type"], "strike": l["strike"], "action": l["action"]}
                                    for l in result["legs"]],
                           "net_credit_per_unit": result["net_credit_per_unit"],
                           "stop_loss_debit": result["stop_loss_debit"],
                           "profit_target_debit": result["profit_target_debit"]}
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(entry_state, indent=1), encoding="utf-8")
            out = {"ts": now_ts, "active": True, "expiry": expiry.isoformat(), "spot": round(spot, 2),
                   "status": "new_suggestion", **result, "disclaimer": DISCLAIMER}

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, separators=(",", ":"), default=str), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
