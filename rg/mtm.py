"""
mtm.py — position leg decomposition, live mark-to-market, and settlement payoff.

THE single place that knows what legs a persisted position actually holds. Every
consumer — the tracker, the performance report, the P&L maths — must come through
`structure_legs()` rather than reading `short_strike`/`long_strike` off the dict,
because those two fields are a LEGACY PAIR that on an iron condor name only the
put wing (see strategy._build_iron_condor). Reading them directly is what made
BAJFINANCE and TCS — both built and persisted as four-leg condors on 17-Aug-2026 —
render in the performance tracker as single-leg "Bear Call 1050 / 1040".

Two distinct valuations live here, and conflating them was the second fault:

  settlement_pnl_per_share(pos, S)   payoff AT EXPIRY, a function of the
                                     underlying alone. Correct for a SETTLED
                                     position; meaningless before expiry.

  mark_position(pos, snap)           live mark: each leg repriced by
                                     Black-Scholes at the CURRENT spot, the IV
                                     backed out of its own live quote, and the
                                     REMAINING time to expiry.

Marking an open position with the settlement payoff reports the full credit as
profit the moment the trade is booked, because at t=0 the spot sits inside the
profit zone by construction — that is the entry condition. On 17-Aug-2026 the
tracker showed +₹2,23,025 (75.5% return on capital) on three condors opened that
morning with 43 days left to run. Nothing had decayed yet; the number was the
credit, relabelled. A short spread only earns its credit as theta accrues, so an
open position must be valued at what it would cost to CLOSE it today.

Nothing here does I/O. `snap` is supplied by market_data.get_leg_snapshot(), so
every function below is unit-testable against a synthetic chain.
"""

from datetime import date, datetime

from .black_scholes import bs_price, enrich_strikes_with_greeks
from . import config


# ── Structure definitions ─────────────────────────────────────────────
# (field name on the position dict, contract type, signed quantity).
# qty -1 = SOLD (we owe it, buying it back is a debit), +1 = BOUGHT.
#
# The condor entry lists all four legs explicitly and deliberately does NOT
# mention short_strike/long_strike: those exist on a persisted condor only as a
# duplicate of the put wing, and treating them as the structure is exactly the
# bug this table exists to prevent.
LEG_SPECS = {
    "BULL_PUT_SPREAD":  (("short_strike", "PE", -1), ("long_strike", "PE", +1)),
    "BEAR_CALL_SPREAD": (("short_strike", "CE", -1), ("long_strike", "CE", +1)),
    "IRON_CONDOR":      (("put_short",  "PE", -1), ("put_long",  "PE", +1),
                         ("call_short", "CE", -1), ("call_long", "CE", +1)),
}

STRUCTURE_LABELS = {
    "BULL_PUT_SPREAD":  "Bull Put",
    "BEAR_CALL_SPREAD": "Bear Call",
    "IRON_CONDOR":      "Iron Condor",
}


def structure_label(pos) -> str:
    """Display name for a structure. Unknown strategies render their own key
    rather than silently borrowing another structure's label — the previous
    `"Bull Put" if strategy == BULL_PUT else "Bear Call"` turned every condor
    into a bear call spread."""
    strat = str(pos.get("strategy") or "")
    return STRUCTURE_LABELS.get(strat, strat.replace("_", " ").title() or "—")


def structure_reason(pos):
    """
    Validation gate: None if this position's legs are fully and coherently
    serialised, else a short reason. Used by tracker.record_new so a structure
    that cannot be decomposed is rejected AT THE BOUNDARY instead of being
    persisted and silently mis-rendered downstream for the rest of its life.
    """
    strat = str(pos.get("strategy") or "")
    spec = LEG_SPECS.get(strat)
    if spec is None:
        return f"unknown strategy {strat!r} — no leg specification"
    missing = [f for f, _t, _q in spec
               if not isinstance(pos.get(f), (int, float))]
    if missing:
        return f"{strat} is missing leg field(s): {', '.join(missing)}"
    if strat == "IRON_CONDOR":
        # A condor's legacy pair must mirror the put wing. If it does not, some
        # upstream path rebuilt the dict and the two disagree — the report and
        # the P&L would then be computed off different structures.
        for legacy, real in (("short_strike", "put_short"), ("long_strike", "put_long")):
            if pos.get(legacy) is not None and pos[legacy] != pos[real]:
                return (f"IRON_CONDOR {legacy}={pos[legacy]} contradicts "
                        f"{real}={pos[real]}")
        if not (pos["put_long"] < pos["put_short"] < pos["call_short"] < pos["call_long"]):
            return (f"IRON_CONDOR strikes out of order: "
                    f"{pos['put_long']}/{pos['put_short']}/"
                    f"{pos['call_short']}/{pos['call_long']}")
    return None


def structure_legs(pos) -> list:
    """
    The position's ACTUAL legs: [{role, strike, type, qty}, ...].
    Raises ValueError when the structure is not serialised well enough to
    decompose — callers that must not raise should pre-check structure_reason().
    """
    reason = structure_reason(pos)
    if reason:
        raise ValueError(f"{pos.get('symbol', '?')}: {reason}")
    return [{"role": field, "strike": float(pos[field]), "type": typ, "qty": qty}
            for field, typ, qty in LEG_SPECS[pos["strategy"]]]


def legs_label(pos) -> str:
    """
    Compact human leg description. A condor names BOTH short strikes — the pair
    that defines its profit zone — never just the put wing.
    """
    strat = pos.get("strategy")
    try:
        if strat == "IRON_CONDOR":
            return f"{pos['put_short']:.0f}P / {pos['call_short']:.0f}C"
        return f"{pos['short_strike']:.0f} / {pos['long_strike']:.0f}"
    except (KeyError, TypeError, ValueError):
        return "—"


def leg_signature(pos) -> str:
    """
    Unambiguous identity for the exact contracts held, e.g.
    "S1050P+B1040P+S1160C+B1170C".

    Used in the tracker's position id. The id previously read
    f"{short_strike}-{long_strike}", so a condor was identified by its put wing
    alone and was indistinguishable from the bull put spread on the same symbol
    and expiry.
    """
    try:
        legs = structure_legs(pos)
    except ValueError:
        return "UNDECOMPOSABLE"
    return "+".join(f"{'S' if l['qty'] < 0 else 'B'}{l['strike']:g}{l['type'][0]}"
                    for l in legs)


# ── Settlement payoff (EXPIRY ONLY) ───────────────────────────────────
def settlement_pnl_per_share(pos, S: float) -> float:
    """
    Payoff per share at expiry with the underlying settling at S.

    Valid ONLY at/after expiry. For a live position use mark_position().

    Each wing is capped at ITS OWN width less the credit, not at the position's
    single `max_loss` field. On a condor that field is max(put width, call width)
    — the conservative number sizing uses — so applying it to the narrower wing
    overstated a breach of that side. Symmetric condors (every one built to date)
    are unaffected; an asymmetric one was mispriced at settlement.
    """
    credit = float(pos["net_credit"])
    strat = pos.get("strategy")

    if strat == "IRON_CONDOR":
        ksp, klp = float(pos["put_short"]), float(pos["put_long"])
        ksc, klc = float(pos["call_short"]), float(pos["call_long"])
        if ksp <= S <= ksc:
            return credit                                  # both wings expire worthless
        if S < ksp:
            return max(round(credit - (ksp - klp), 2), round(credit - (ksp - S), 2))
        return max(round(credit - (klc - ksc), 2), round(credit - (S - ksc), 2))

    short_k, long_k = float(pos["short_strike"]), float(pos["long_strike"])
    max_loss = float(pos["max_loss"])
    if strat == "BULL_PUT_SPREAD":
        if S >= short_k:
            return credit
        if S <= long_k:
            return -max_loss
        return round(credit - (short_k - S), 2)
    # BEAR_CALL_SPREAD
    if S <= short_k:
        return credit
    if S >= long_k:
        return -max_loss
    return round(credit - (S - short_k), 2)


# ── Live mark-to-market ───────────────────────────────────────────────
def _days_left(pos, today=None) -> int:
    today = today or date.today()
    try:
        exp = datetime.strptime(str(pos["expiry"])[:10], "%Y-%m-%d").date()
    except (KeyError, ValueError, TypeError):
        return 0
    return (exp - today).days


def _leg_mark_price(row, typ) -> tuple:
    """
    Price to feed the IV solver: the two-sided MID when there is one, else LTP.

    Mid, not LTP, because entry credits are struck on mids (strategy._leg_mid) —
    marking a mid-priced entry against a stale last trade would book the
    difference as P&L that never existed. Returns (price, basis).
    """
    p = "call" if typ == "CE" else "put"
    bid = row.get(f"{p}_bid") or 0
    ask = row.get(f"{p}_ask") or 0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0, "mid"
    ltp = row.get(f"{p}_ltp") or 0
    if ltp > 0:
        return ltp, "ltp"
    return 0.0, "model"


def mark_position(pos, snap, today=None) -> dict:
    """
    Value an OPEN position at current market. PURE — `snap` comes from
    market_data.get_leg_snapshot().

        snap = {"spot": float, "hv_30d": float,
                "strikes": {strike: {call_bid, call_ask, call_ltp, put_*...}}}

    Method, in the order the numbers depend on each other:
      1. remaining time to expiry, on the trading-day basis the greeks engine
         expects (T_days/252) — the SAME rescale market_data applies at entry, so
         a mark is comparable with the entry IV instead of ~14% off it;
      2. enrich_strikes_with_greeks solves each leg's IV from its own live quote
         at the current spot and that remaining T;
      3. bs_price re-prices every leg at (current spot, solved IV, remaining T).
         Solving and pricing share one T on purpose — two conventions here would
         reintroduce exactly the calendar-vs-trading-day error the entry path
         documents;
      4. debit-to-close = what we pay to buy back the shorts and sell the longs;
      5. unrealised = credit received − debit-to-close.

    Where a leg has no usable quote its IV falls back to the underlying's 30-day
    HV, so the mark degrades to a model price instead of vanishing. `basis` says
    which happened, and the report prints it — a model mark must never be
    indistinguishable from a market one.

    Returns a dict with "ok": False and a "note" instead of raising, so one
    unquotable position cannot take down the performance report.
    """
    out = {"ok": False, "mark_type": "mtm", "note": "", "legs": [],
           "mark_spot": None, "days_left": _days_left(pos, today),
           "debit_per_share": None, "debit_total": None,
           "unrealised_per_share": None, "unrealised_total": None,
           "pct_of_credit_captured": None, "basis": None, "clamped": False,
           "net_delta": None, "net_theta": None}

    try:
        legs = structure_legs(pos)
    except ValueError as e:
        out["note"] = str(e)
        return out

    spot = (snap or {}).get("spot") or 0
    if not spot:
        out["note"] = "no live spot for the underlying"
        return out

    rem = out["days_left"]
    if rem <= 0:
        # At or past expiry the payoff IS the valuation — no time value left to
        # model. Reported as such rather than pretending to be a live mark.
        pnl_share = settlement_pnl_per_share(pos, spot)
        out.update(ok=True, mark_type="expiry", mark_spot=round(spot, 2),
                   basis="payoff", debit_per_share=round(float(pos["net_credit"]) - pnl_share, 2),
                   unrealised_per_share=pnl_share,
                   unrealised_total=round(pnl_share * pos["lot_size"] * pos["lots"], 2),
                   note="at/after expiry — valued on the settlement payoff")
        if pos.get("net_credit"):
            out["pct_of_credit_captured"] = round(pnl_share / float(pos["net_credit"]) * 100, 1)
        out["debit_total"] = round(out["debit_per_share"] * pos["lot_size"] * pos["lots"], 2)
        return out

    # Trading-day basis, matching market_data.get_chain_snapshot's entry convention.
    t_days_252 = max(rem * 252.0 / 365.0, 1.0)
    t_years = t_days_252 / 252.0

    # Feed the solver a chain containing only the legs we hold. Copy the rows —
    # enrich_strikes_with_greeks mutates in place and snap may be reused.
    chain = (snap or {}).get("strikes") or {}
    work, bases = {}, []
    for leg in legs:
        row = dict(chain.get(leg["strike"]) or {})
        px, basis = _leg_mark_price(row, leg["type"])
        key = "call" if leg["type"] == "CE" else "put"
        row[f"{key}_ltp"] = px          # 0 -> enrich falls back to HV sigma
        row.pop(f"{key}_iv", None)      # force a fresh solve at today's spot/T
        work.setdefault(leg["strike"], {}).update(row)
        bases.append(basis)

    hv = (snap or {}).get("hv_30d") or 0
    enrich_strikes_with_greeks(work, spot=spot, T_days=t_days_252, hv_30d=hv)

    debit = 0.0
    net_delta = net_theta = 0.0
    for leg, basis in zip(legs, bases):
        row = work[leg["strike"]]
        key = "call" if leg["type"] == "CE" else "put"
        sigma = (row.get(f"{key}_iv") or 0) / 100.0
        price = bs_price(spot, leg["strike"], t_years, config.RISK_FREE_RATE,
                         sigma, "CE" if leg["type"] == "CE" else "PE")
        price = max(price, 0.0)
        # Short leg (qty -1) is bought back -> pays out; long leg is sold -> takes in.
        debit += -leg["qty"] * price
        net_delta += leg["qty"] * (row.get(f"{key}_delta") or 0)
        net_theta += leg["qty"] * (row.get(f"{key}_theta") or 0)
        out["legs"].append({
            "role": leg["role"], "strike": leg["strike"], "type": leg["type"],
            "qty": leg["qty"], "price": round(price, 2),
            "iv": round(sigma * 100, 2), "basis": basis,
            "delta": round(row.get(f"{key}_delta") or 0, 4),
        })

    credit = float(pos["net_credit"])
    max_loss = float(pos["max_loss"])
    unreal = credit - debit

    # A defined-risk vertical is worth [0, width] at ANY time, so P&L is bounded
    # by [-max_loss, +credit] throughout the trade's life, not only at expiry.
    # Clamping therefore removes quote noise without hiding a real move; the flag
    # says when it bound, so a systematically clamped mark is visible rather than
    # comfortable.
    if config.MARK_CLAMP_TO_STRUCTURE:
        clamped = min(max(unreal, -max_loss), credit)
        out["clamped"] = abs(clamped - unreal) > 0.005
        unreal = clamped

    size = pos["lot_size"] * pos["lots"]
    out.update(
        ok=True,
        mark_spot=round(spot, 2),
        debit_per_share=round(debit, 2),
        debit_total=round(debit * size, 2),
        unrealised_per_share=round(unreal, 2),
        unrealised_total=round(unreal * size, 2),
        pct_of_credit_captured=round(unreal / credit * 100, 1) if credit else None,
        basis=("market" if all(b in ("mid", "ltp") for b in bases)
               else "model" if all(b == "model" for b in bases) else "mixed"),
        net_delta=round(net_delta * size, 1),
        net_theta=round(net_theta * size, 1),
    )
    if out["basis"] != "market":
        out["note"] = (f"{sum(1 for b in bases if b == 'model')} of {len(bases)} leg(s) "
                       f"had no usable quote — priced from 30-day HV, not the market")
    return out


def live_mark(pos, today=None) -> dict:
    """
    Convenience wrapper: fetch this position's legs from Kite and mark them.
    The one impure entry point — pass it to tracker.month_to_date_report().
    """
    from . import market_data          # local import: keeps the maths above
                                      # importable without a Kite session
    if not config.MARK_OPEN_WITH_BS:
        # Escape hatch to the legacy settlement-payoff marking. Kept only so the
        # change can be A/B'd against the old reports; it is NOT a valuation of a
        # live position (see the module docstring).
        try:
            spot = market_data.get_equity_spot(pos["symbol"])["last"]
        except Exception as e:
            return {"ok": False, "mark_type": "mtm", "note": f"spot fetch failed: {e}",
                    "legs": [], "mark_spot": None, "days_left": _days_left(pos, today),
                    "unrealised_total": None, "clamped": False}
        pnl = settlement_pnl_per_share(pos, spot)
        return {"ok": True, "mark_type": "settlement-proxy", "basis": "payoff",
                "mark_spot": round(spot, 2), "days_left": _days_left(pos, today),
                "legs": [], "debit_per_share": None, "debit_total": None,
                "unrealised_per_share": pnl,
                "unrealised_total": round(pnl * pos["lot_size"] * pos["lots"], 2),
                "pct_of_credit_captured": None, "clamped": False,
                "net_delta": None, "net_theta": None,
                "note": "MARK_OPEN_WITH_BS is off — expiry payoff, not a live mark"}
    try:
        legs = structure_legs(pos)
    except ValueError as e:
        return {"ok": False, "mark_type": "mtm", "note": str(e), "legs": [],
                "mark_spot": None, "days_left": _days_left(pos, today),
                "unrealised_total": None, "clamped": False}
    try:
        snap = market_data.get_leg_snapshot(
            pos["symbol"], pos["expiry"],
            [(l["strike"], l["type"]) for l in legs])
    except Exception as e:
        snap = None
        err = f"leg quote fetch failed: {e}"
    else:
        err = None
    if not snap:
        return {"ok": False, "mark_type": "mtm", "legs": [], "mark_spot": None,
                "days_left": _days_left(pos, today), "unrealised_total": None,
                "clamped": False,
                "note": err or "no live quotes for these contracts"}
    return mark_position(pos, snap, today=today)
