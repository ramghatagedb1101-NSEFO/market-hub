"""
strategy.py — deterministic credit-spread selection. NO Claude.

Builds two defined-risk premium-selling structures:
  BULL_PUT_SPREAD  — sell OTM put, buy further-OTM put   (lean bullish/neutral)
  BEAR_CALL_SPREAD — sell OTM call, buy further-OTM call  (lean bearish/neutral)

For each watchlist symbol both sides are attempted; the better-scoring side
that clears every risk gate wins. Direction is anchored to OI walls (sell
BEYOND the dominant wall) rather than a directional guess — the "balanced,
low-risk" stance.

Macro risk flags: generate_recommendations() optionally takes a pre-resolved
flag list (see risk_flags.py) and demotes the score of a flagged name. Selection
stays deterministic and makes no LLM call — the flags are data computed upstream
in run.py before this module is entered.
"""

import math
from datetime import date, datetime

from . import config, market_data, risk_flags, earnings


def _step(strikes: dict) -> float:
    """
    Tightest strike gap in the chain — a LIQUIDITY/SANITY probe only (is this a
    real chain?). It is NOT the spacing at any particular strike and must not be
    used to compute a neighbouring strike: NSE spacing is non-uniform, tighter
    around ATM and wider in the wings, so short_strike +/- _step() routinely
    names a strike that does not exist. Use _adjacent_strike for that.
    """
    ks = sorted(strikes.keys())
    diffs = [round(b - a, 2) for a, b in zip(ks, ks[1:]) if b - a > 0]
    return min(diffs) if diffs else 0.0


def _adjacent_strike(strikes: dict, short_k: float, side: str, n_steps: int):
    """
    The strike `n_steps` positions further OTM than `short_k`, chosen by POSITION
    in the sorted strike list. Returns None if the chain runs out.

    Positional, not arithmetic, because strike spacing varies WITHIN one chain.
    ASIANPAINT on 17-Aug-2026: 20-point spacing near a 2700 spot but 40 points
    out at the 2360 put, so the old `short_k - _step()` asked for 2340 — absent
    from the chain — and the whole symbol was rejected as having "no
    constructible spread". Counting one position down instead yields 2320 and a
    real, tradeable spread. This was rejecting roughly a third of the universe.

    Consequence to keep in mind: `width` is now whatever the chain's local
    spacing gives, so it varies per symbol and is no longer SPREAD_WIDTH_STEPS x
    a single step size. Every downstream user already derives width from the two
    strikes (`abs(short_k - long_k)`), so this needs no other change — but it is
    why width is not a constant per symbol.
    """
    ks = sorted(strikes.keys())
    try:
        i = ks.index(short_k)
    except ValueError:
        return None
    j = i - n_steps if side == "PUT" else i + n_steps
    if not (0 <= j < len(ks)):
        return None
    return ks[j]


def _call_wall(strikes: dict) -> float:
    return max(strikes, key=lambda k: strikes[k].get("call_oi", 0), default=0)


def _put_wall(strikes: dict) -> float:
    return max(strikes, key=lambda k: strikes[k].get("put_oi", 0), default=0)


def _leg_mid(row, side):
    """
    Mid price of one leg — the basis for the credit the gates are measured on.

    A vertical is worked as ONE combo order, so the realistic fill is near the
    combo's mid, not "sell my leg at the bid and buy the other at the ask". That
    pessimistic pairing (the previous _short_price/_long_price) charged the full
    per-leg spread twice on a structure whose whole value is the difference
    between two adjacent strikes, which drove the credit NEGATIVE and discarded
    the spread. Live NIFTY 50, 17-Aug-2026: CIPLA 1350/1340 put priced to -0.50
    bid/ask but +2.35 on mids; TITAN 4450/4400 to -4.65 vs +4.95.

    Falls back to LTP when either side of the quote is missing. Genuinely
    untradeable legs are still caught — _bid_ask_pct gates on the two-sided
    quote and returns its 999 sentinel when there isn't one, so pricing at mid
    does not let a one-sided quote through.
    """
    p = side.lower()
    bid = row.get(f"{p}_bid") or 0
    ask = row.get(f"{p}_ask") or 0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    return row.get(f"{p}_ltp") or 0


def _short_price(row, side):
    """Worst-case price we RECEIVE selling the short leg (bid, else LTP)."""
    if side == "PUT":
        return row.get("put_bid") or row.get("put_ltp") or 0
    return row.get("call_bid") or row.get("call_ltp") or 0


def _long_price(row, side):
    """Worst-case price we PAY buying the long leg (ask, else LTP)."""
    if side == "PUT":
        return row.get("put_ask") or row.get("put_ltp") or 0
    return row.get("call_ask") or row.get("call_ltp") or 0


def _gate_credit(sp):
    """
    (credit, label) the REWARD GATE is measured on: always mid, the price a
    limit/combo order is meant to achieve, and the same basis sizing, score and
    the management prices already use.

    2026-10-08: this used to read config.USE_WORST_CASE_CREDIT and gate on the
    worst case (crossing both spreads with market orders) when that flag was on
    -- a real, deliberate fix for a CIPLA spread once priced to a negative
    worst-case credit (see the flag's own comment in config.py). But gating on
    worst-case alone means a wide-but-real market (ADANIENT, BEL, ETERNAL and
    others had a positive MID credit the whole time) silently reads as "no
    trade qualifies" when the honest statement is "this needs a limit order
    near mid, not a market order." The CIPLA risk is now carried forward as a
    warning instead of a rejection: see fill_risk() and generate_recommendations,
    which stamps "worst_case_unsafe" on the card rather than discarding it.
    """
    return sp["net_credit"], "mid"


def fill_risk(sp) -> bool:
    """True when a market order crossing both legs' quotes would net zero or a
    debit -- the trade is real at the mid, but only a limit/combo order captures
    it. The card must say this explicitly, not bury it in a RoR number."""
    return sp["net_credit_worst"] <= 0


def _ror_fields(credit, max_loss, credit_worst, max_loss_worst):
    """
    Both Return-on-Risk readings, plus which one HEADLINES the report.

    Both are always carried — same shape as score_pre_flag / risk_flag_score_live —
    so flipping USE_WORST_CASE_CREDIT changes which number leads, never what is
    knowable from the reco or from positions.json.

    `return_on_risk_pct` is the field every existing display path already reads
    (report._reco_summary, both reco cards), which is what makes "all displayed RoR
    uses the worst case" one assignment rather than an edit at each call site.

    The worst-case pair is used only when it describes a coherent structure —
    positive credit against a positive max loss. A non-positive worst-case credit
    is a real condition on a thin far-OTM chain (CIPLA 1350/1340 priced to -0.50 on
    17-Aug-2026) and it is REJECTED by _spread_reject_reason with its own message;
    falling back to the mid here just keeps the arithmetic sane until that gate is
    reached, instead of publishing a negative RoR. `credit_basis` still reports the
    CONFIGURED basis, so the fallback cannot read as a mid-priced pass.
    """
    mid = round(credit / max_loss * 100, 1) if max_loss > 0 else 0.0
    worst = (round(credit_worst / max_loss_worst * 100, 1)
             if credit_worst > 0 and max_loss_worst > 0 else None)
    use_worst = config.USE_WORST_CASE_CREDIT and worst is not None
    return {
        "return_on_risk_pct":       worst if use_worst else mid,
        "return_on_risk_pct_mid":   mid,
        "return_on_risk_pct_worst": worst,
        "credit_basis":             "worst" if config.USE_WORST_CASE_CREDIT else "mid",
    }


def _prefer_single_side(india_vix):
    """
    (True, note) when a LOW-VOL regime says stand the iron condor down —
    config.LOW_VIX_THRESHOLD.

    A condor carries two short strikes for its extra credit (POP = 100 - put_delta
    - call_delta, ~50% at the 0.25 target, against ~75% single-sided). Below the
    threshold both wings are priced off the same compressed vol, so the second wing
    adds little credit while still adding a strike that can be breached — and a low
    VIX is where a vol expansion is most likely to run one side through.

    Returns (False, None) when the threshold is disabled (None) OR when the VIX is
    missing/unparseable. "We could not read the VIX" is not evidence of low vol, and
    the condor branch is the long-standing default — so an absent macro snapshot
    must not silently reshape every structure in the run.
    """
    thr = config.LOW_VIX_THRESHOLD
    if thr is None:
        return False, None
    try:
        v = float(india_vix)
    except (TypeError, ValueError):
        return False, None
    if v >= thr:
        return False, None
    return True, f"India VIX {v:.2f} < {thr:.1f}"


def _pick_short_strike(strikes, side, spot):
    """OTM strike whose |delta| is inside the blueprint 10–20 band, closest to target."""
    cands = []
    for k, row in strikes.items():
        if side == "PUT":
            if k >= spot:
                continue
            d = abs(row.get("put_delta", 0))
        else:
            if k <= spot:
                continue
            d = abs(row.get("call_delta", 0))
        if config.SHORT_DELTA_MIN <= d <= config.SHORT_DELTA_MAX:
            cands.append((k, d))
    if not cands:
        return None
    return min(cands, key=lambda kd: abs(kd[1] - config.SHORT_DELTA_TARGET))[0]


def _bid_ask_pct(row, side) -> float:
    """Bid-ask width of the short leg as % of its mid price (liquidity gate)."""
    if side == "PUT":
        bid, ask = row.get("put_bid", 0), row.get("put_ask", 0)
    else:
        bid, ask = row.get("call_bid", 0), row.get("call_ask", 0)
    mid = (bid + ask) / 2
    if mid <= 0 or ask <= 0 or bid <= 0:
        return 999.0   # untradeable / no two-sided quote
    return round((ask - bid) / mid * 100, 2)


def _margin_leg(tradingsymbol, transaction_type, qty):
    """One 1-lot leg formatted for market_data.get_span_margin's basket-margin call."""
    return {"tradingsymbol": tradingsymbol, "exchange": "NFO",
            "transaction_type": transaction_type, "quantity": qty,
            "order_type": "MARKET", "product": "NRML"}


def _vertical_legs_1_lot(short_row, long_row, side, lot):
    """
    1-lot SELL/BUY leg pair for a vertical, or None when either strike's
    tradingsymbol is missing from the chain (a snapshot taken before that field
    existed, or a row this strict never populated) — get_span_margin cannot
    price a structure it cannot name, and the caller degrades to the max_loss
    proxy in that case exactly as it would on any other margin-lookup miss.
    """
    tside = "call" if side == "CALL" else "put"
    short_ts = short_row.get(f"{tside}_tradingsymbol")
    long_ts  = long_row.get(f"{tside}_tradingsymbol")
    if not short_ts or not long_ts:
        return None
    return [_margin_leg(short_ts, "SELL", lot), _margin_leg(long_ts, "BUY", lot)]


def _size_by_margin(span_margin, max_loss_per_lot):
    """
    Shared lot-sizing decision for both _build_spread and _build_iron_condor:
    size against the live SPAN reading when one came back, else fall back to
    the max-loss proxy. Returns (lots, capital_at_risk, margin_source).

    floor(), not the previous `int(... // ...)` — identical for positive
    operands, but floor() states the intent (round DOWN, never over-commit
    capital) rather than relying on integer-division truncation to do it.
    """
    if span_margin is not None and span_margin > 0:
        lots = math.floor(config.CAPITAL_PER_STRATEGY / span_margin)
        return lots, round(lots * span_margin, 2), "span"
    lots = math.floor(config.CAPITAL_PER_STRATEGY / max_loss_per_lot)
    return lots, round(lots * max_loss_per_lot, 2), "max_loss_fallback"


def _build_spread(chain, side):
    """side='PUT' -> bull put spread; side='CALL' -> bear call spread."""
    strikes = chain["strikes"]
    spot    = chain["spot"]
    step    = _step(strikes)
    if step <= 0:
        return None

    short_k = _pick_short_strike(strikes, side, spot)
    if short_k is None:
        return None

    long_k = _adjacent_strike(strikes, short_k, side, config.SPREAD_WIDTH_STEPS)
    if long_k is None:
        return None

    short_row, long_row = strikes[short_k], strikes[long_k]
    # Gates run on the mid-price credit (the realistic combo fill); the bid/ask
    # pairing is kept alongside as the pessimistic fill, reported not enforced.
    credit = round(_leg_mid(short_row, side) - _leg_mid(long_row, side), 2)
    credit_worst = round(_short_price(short_row, side) - _long_price(long_row, side), 2)
    width  = abs(short_k - long_k)
    if credit <= 0 or width <= 0:
        return None

    max_loss   = round(width - credit, 2)
    if max_loss <= 0:
        return None
    max_loss_worst = round(width - credit_worst, 2)
    short_delta = abs(short_row.get("put_delta" if side == "PUT" else "call_delta", 0))
    pop_pct     = round((1 - short_delta) * 100, 1)
    ror = _ror_fields(credit, max_loss, credit_worst, max_loss_worst)

    # Wall protection: is the short strike beyond the dominant wall?
    call_wall, put_wall = _call_wall(strikes), _put_wall(strikes)
    if side == "PUT":
        protected = short_k <= put_wall
        breakeven = round(short_k - credit, 2)
        strategy  = "BULL_PUT_SPREAD"
    else:
        protected = short_k >= call_wall
        breakeven = round(short_k + credit, 2)
        strategy  = "BEAR_CALL_SPREAD"

    # Position sizing to the capital-at-risk cap. Prefer the ACTUAL SPAN +
    # exposure margin Kite would block for 1 lot of this structure over the
    # max-loss proxy — max_loss is a worst-case terminal payoff, not what the
    # exchange requires to hold the position, and is typically a large
    # overstatement of it. Falls back to max_loss whenever a live reading is
    # unavailable (config.USE_SPAN_MARGIN off, a chain-cache replay, or the
    # margin API call itself failing) — see market_data.get_span_margin.
    lot = chain["lot_size"]
    if lot <= 0:
        return None
    max_loss_per_lot = max_loss * lot
    legs_1_lot = _vertical_legs_1_lot(short_row, long_row, side, lot)
    span_margin = market_data.get_span_margin(legs_1_lot) if legs_1_lot else None
    lots, capital_at_risk, margin_source = _size_by_margin(span_margin, max_loss_per_lot)
    if lots < 1:
        return None  # a single lot already breaches the cap
    credit_total    = round(credit * lot * lots, 2)
    max_loss_total  = round(max_loss * lot * lots, 2)

    liquidity_pct = _bid_ask_pct(short_row, side)

    score = round((pop_pct / 100) * (credit / max_loss)
                  * (chain["iv_rank"] / 100)
                  * (1.2 if protected else 1.0), 4)

    return {
        # The RoR pair (and which of the two headlines) is merged in FIRST so the
        # explicit keys below cannot shadow it — return_on_risk_pct lives in
        # _ror_fields and nowhere else.
        **ror,
        "symbol":             chain["symbol"],
        "strategy":           strategy,
        "index_membership":   chain.get("index_membership", "NIFTY50"),
        "dte_preferred":      chain.get("dte_preferred", True),
        "expiry":             str(chain["expiry"]),
        "dte":                chain["dte"],
        "as_of":              chain.get("as_of"),
        "spot_at_entry":      spot,
        "short_strike":       short_k,
        "long_strike":        long_k,
        "width":              round(width, 2),
        "net_credit":         credit,          # per share, at mid (what gates use)
        "net_credit_worst":   credit_worst,    # per share, paying both spreads
        "max_loss":           max_loss,        # per share
        "max_loss_worst":     max_loss_worst,
        "max_profit":         credit,          # per share
        "pop_pct":            pop_pct,
        "short_delta":        round(short_delta, 3),
        "iv_rank":            chain["iv_rank"],
        "iv_quality":         chain["iv_quality"],
        "lot_size":           lot,
        "lots":               lots,
        "capital_at_risk":    capital_at_risk,
        "margin_source":      margin_source,
        "credit_collected":   credit_total,
        "max_loss_total":     max_loss_total,
        "breakeven":          breakeven,
        "protected_by_wall":  protected,
        "liquidity_pct":      liquidity_pct,
        "call_wall":          call_wall,
        "put_wall":           put_wall,
        "stop_loss_debit":    round(credit * config.STOP_LOSS_CREDIT_MULT, 2),
        "profit_target_debit":round(credit * (1 - config.PROFIT_TARGET_PCT / 100), 2),
        "score":              score,
    }


def _build_iron_condor(chain, bp, bc):
    """
    Combine a qualifying bull-put and bear-call into an iron condor — sell both
    sides of a range-bound, high-IV name. Defined risk (only one side can be
    breached at expiry). bp/bc are already-built, already-filtered spreads.

    Field contract: every IC-specific value is computed explicitly below, and any
    OTHER field the legs carry is then copied across (see the merge at the end).
    This function used to be a closed dict literal, which meant anything attached
    to a spread upstream survived on single spreads and silently vanished on
    IC-eligible names only — the harder half of the bug to notice, and the same
    rebuild-drops-fields pattern as phase_filters._build_candidate. If you add a
    key here, add it to the literal; do not remove the merge.
    """
    credit = round(bp["net_credit"] + bc["net_credit"], 2)
    # Must be summed explicitly, NOT left to the setdefault merge below: that
    # would copy bp's value alone and report a two-sided condor's worst-case fill
    # as if only the put wing had been paid for. Exactly the field-contract
    # hazard the docstring warns about.
    credit_worst = round(bp["net_credit_worst"] + bc["net_credit_worst"], 2)
    width  = max(bp["width"], bc["width"])
    max_loss = round(width - credit, 2)
    if credit <= 0 or max_loss <= 0:
        return None
    pop = round((1 - bp["short_delta"] - bc["short_delta"]) * 100, 1)
    if pop < config.IC_MIN_POP_PCT:
        return None
    lot = chain["lot_size"]

    # Position sizing — same SPAN-first, max-loss-fallback policy as
    # _build_spread (see _size_by_margin), but priced on the CONDOR'S OWN
    # 4-leg structure: the exchange nets margin across both wings, so summing
    # bp's and bc's individually-priced margins would overstate what 1 lot of
    # the combined structure actually requires.
    strikes = chain["strikes"]
    put_short_row  = strikes.get(bp["short_strike"], {})
    put_long_row   = strikes.get(bp["long_strike"], {})
    call_short_row = strikes.get(bc["short_strike"], {})
    call_long_row  = strikes.get(bc["long_strike"], {})
    put_short_ts  = put_short_row.get("put_tradingsymbol")
    put_long_ts   = put_long_row.get("put_tradingsymbol")
    call_short_ts = call_short_row.get("call_tradingsymbol")
    call_long_ts  = call_long_row.get("call_tradingsymbol")
    legs_1_lot = None
    if put_short_ts and put_long_ts and call_short_ts and call_long_ts:
        legs_1_lot = [
            _margin_leg(put_short_ts, "SELL", lot), _margin_leg(put_long_ts, "BUY", lot),
            _margin_leg(call_short_ts, "SELL", lot), _margin_leg(call_long_ts, "BUY", lot),
        ]
    span_margin = market_data.get_span_margin(legs_1_lot) if legs_1_lot else None
    lots, capital_at_risk, margin_source = _size_by_margin(span_margin, max_loss * lot)
    if lots < 1:
        return None
    max_loss_worst = round(width - credit_worst, 2)
    ror = _ror_fields(credit, max_loss, credit_worst, max_loss_worst)
    ic = {
        # Merged first, for the same reason as in _build_spread — and note the
        # setdefault carry-over at the end would otherwise copy the PUT WING's RoR
        # onto a two-sided condor.
        **ror,
        "symbol":             chain["symbol"],
        "strategy":           "IRON_CONDOR",
        "expiry":             str(chain["expiry"]),
        "dte":                chain["dte"],
        "as_of":              chain.get("as_of"),
        "spot_at_entry":      chain["spot"],
        # explicit four legs
        "put_short":          bp["short_strike"], "put_long":  bp["long_strike"],
        "call_short":         bc["short_strike"], "call_long": bc["long_strike"],
        # legacy pair (put side) for any generic display path
        "short_strike":       bp["short_strike"], "long_strike": bp["long_strike"],
        "width":              round(width, 2),
        "net_credit":         credit, "max_profit": credit, "max_loss": max_loss,
        "net_credit_worst":   credit_worst,
        "max_loss_worst":     max_loss_worst,
        "pop_pct":            pop,
        "put_delta":          bp["short_delta"], "call_delta": bc["short_delta"],
        "short_delta":        max(bp["short_delta"], bc["short_delta"]),
        "iv_rank":            chain["iv_rank"], "iv_quality": chain["iv_quality"],
        "lot_size":           lot, "lots": lots,
        "capital_at_risk":    capital_at_risk,
        "margin_source":      margin_source,
        "credit_collected":   round(credit * lot * lots, 2),
        "max_loss_total":     round(max_loss * lot * lots, 2),
        "breakeven":          round(bp["short_strike"] - credit, 2),
        "breakeven_low":      round(bp["short_strike"] - credit, 2),
        "breakeven_high":     round(bc["short_strike"] + credit, 2),
        "protected_by_wall":  bp["protected_by_wall"] and bc["protected_by_wall"],
        "liquidity_pct":      max(bp["liquidity_pct"], bc["liquidity_pct"]),
        "call_wall":          bc["call_wall"], "put_wall": bp["put_wall"],
        "stop_loss_debit":    round(credit * config.STOP_LOSS_CREDIT_MULT, 2),
        "profit_target_debit":round(credit * (1 - config.PROFIT_TARGET_PCT / 100), 2),
        "score":              round((pop / 100) * (credit / max_loss)
                                    * (chain["iv_rank"] / 100) * 1.3, 4),
    }

    # Carry over any leg field this dict doesn't already define. setdefault, so an
    # IC-specific value is never clobbered by a per-leg one. Today this is a
    # no-op — the literal above is a superset of _build_spread's keys — which is
    # the point: it costs nothing now and stops the next field added upstream
    # from disappearing on condors. Every leg-specific field is set explicitly
    # above, so in practice this only ever copies symbol-level data; bp wins an
    # exact key collision, which cannot differ anyway since both legs are built
    # from the same chain.
    for leg in (bp, bc):
        for key, value in leg.items():
            ic.setdefault(key, value)
    return ic


def _is_next50(obj) -> bool:
    return str(obj.get("index_membership") or "NIFTY50").upper() == "NEXT50"


def _tier_limits(obj):
    """
    Entry thresholds for this candidate's index tier — control (a).

    A NIFTY Next 50 name is a smaller, thinner underlying: wider option spreads,
    patchier delivery, more gap risk. Score does not capture any of that, so a
    thin name can post an attractive score and still be untradeable at a fair
    price. Returns (max_bid_ask, min_delivery, min_iv_rank, label).
    """
    if config.NEXT50_STRICTER_GATES and _is_next50(obj):
        return (config.NEXT50_MAX_BID_ASK_PCT, config.NEXT50_MIN_DELIVERY_5D,
                config.NEXT50_MIN_IV_RANK, "NEXT50")
    return (config.MAX_BID_ASK_PCT, config.MIN_DELIVERY_5D,
            config.MIN_IV_RANK, "NIFTY50")


def _spread_reject_reason(sp):
    """
    Per-spread gate. Returns None if it passes, else a short reason string.

    The reward gate reads the mid credit (see _gate_credit) -- the reward a
    careful limit/combo order is meant to capture. A trade whose worst-case
    (market-order) fill is unsafe is not rejected here; it is flagged as
    fill_risk() on the final card instead, so the user decides with the real
    number in front of them rather than never seeing the trade at all.
    """
    max_ba, _, _, tier = _tier_limits(sp)
    if sp["pop_pct"] < config.MIN_POP_PCT:
        return f"POP {sp['pop_pct']:.0f}% < {config.MIN_POP_PCT:.0f}%"
    credit, basis = _gate_credit(sp)
    # Defensive only: _build_spread already discards a non-positive mid credit,
    # so this should never fire now that _gate_credit always reads mid. Left in
    # case that invariant ever changes upstream.
    if credit <= 0:
        return (f"{basis} credit Rs.{credit:.2f} <= 0 — pays nothing at the mid; "
                f"stand aside")
    if (credit / sp["width"]) < config.MIN_CREDIT_TO_WIDTH:
        return (f"{basis} credit {credit/sp['width']*100:.0f}% of width < "
                f"{config.MIN_CREDIT_TO_WIDTH*100:.0f}%")
    if config.REQUIRE_WALL_PROTECTION and not sp["protected_by_wall"]:
        return "short strike not beyond OI wall"
    if sp["liquidity_pct"] > max_ba:
        extra = f" ({tier} limit)" if tier == "NEXT50" else ""
        return f"bid-ask {sp['liquidity_pct']:.1f}% > {max_ba:.1f}%{extra}"
    return None


def _symbol_reject_reason(chain):
    """Symbol-level gates that apply before building any spread."""
    _, min_dlv, min_ivr, tier = _tier_limits(chain)
    extra = f" ({tier} limit)" if tier == "NEXT50" else ""
    # An unmeasured IV rank is not permission to sell. Without history,
    # calculate_iv_rank assumes a band around the current reading and returns a
    # CONSTANT 33.3 — which used to clear MIN_IV_RANK=30 on arithmetic alone, so
    # 32 of the 50 NIFTY 50 names passed the "only sell rich premium" gate having
    # never been measured against anything. Standing aside is the fail-safe
    # direction for short premium: the whole edge is that the premium is
    # historically expensive, and here we do not know that it is.
    if chain.get("iv_quality") != "sufficient":
        return (f"IV rank not measurable [{chain.get('iv_quality')}] — "
                f"{chain.get('iv_samples', 0)} clean sample(s), "
                f"{chain.get('iv_samples_dropped', 0)} dropped as implausible; "
                f"run backfill_iv_history.py for {chain['symbol']}")
    if chain["iv_rank"] < min_ivr:
        return (f"IV rank {chain['iv_rank']:.0f} < {min_ivr:.0f}{extra} "
                f"(premium too cheap to sell)")
    dlv = chain.get("delivery_5d")
    if min_dlv and dlv is not None and dlv < min_dlv:
        return f"5d delivery {dlv:.0f}% < {min_dlv:.0f}%{extra}"
    if config.BLOCK_EARNINGS_IN_CYCLE:
        today = date.today()
        # (i) A date from the buying tool's supplementary feed still wins when
        #     present: it is a confirmed filing, same as tier 1 below.
        if chain.get("next_earnings"):
            try:
                ed = datetime.strptime(str(chain["next_earnings"])[:10], "%Y-%m-%d").date()
                if today <= ed <= chain["expiry"]:
                    return f"earnings {ed} inside contract cycle (expiry {chain['expiry']})"
                return None
            except (ValueError, TypeError):
                pass                      # unparseable — fall through to the window
        # (ii) earnings.py's three-tier resolution. A confirmed OR estimated
        #      window that overlaps the cycle is a reject; the reason names which
        #      tier it came from, because "estimated" is a materially weaker
        #      claim than "confirmed" and the diagnostics must not blur them.
        win = chain.get("earnings_window") or {}
        status = win.get("status")
        if status in ("confirmed", "estimated") and earnings.collides(
                win, today, chain["expiry"]):
            if status == "confirmed":
                return (f"earnings {win['date']} inside contract cycle "
                        f"(expiry {chain['expiry']}, confirmed filing)")
            if config.BLOCK_ON_ESTIMATED_EARNINGS:
                return (f"estimated earnings {win['lo']}..{win['hi']} overlaps contract "
                        f"cycle (expiry {chain['expiry']}, projected from "
                        f"{win['anchor']} ±{win['buffer_td']} sessions)")
            # Not blocked: the trade carries earnings_basis="estimated" so the page can say so.
            return None
        if status in ("confirmed", "estimated"):
            return None                   # window resolved and sits clear
        # (iii) Genuinely unverifiable — no filing and no usable periodic history.
        if config.REQUIRE_EARNINGS_DATA:
            return (f"earnings date unverifiable ({win.get('reason', 'no filing history')}) "
                    f"— cannot confirm the cycle is clear")
    return None


def _earnings_unverified(chain) -> bool:
    """
    True when the earnings blocker is ON but could resolve NO window at all.

    Split out so this fails LOUDLY rather than silently: a name in this state is
    recommended having skipped the blueprint's hardest gate, and the report says
    so on the card instead of letting an absent field read as "no earnings due".

    Note an `estimated` window is NOT unverified. It is a real, checked claim
    about the cycle — weaker than a filing, and labelled as such on the card by
    _earnings_basis — so lumping it in here would put the loud "NOT VERIFIED"
    banner on the majority of cards and train the reader to ignore it.
    """
    if not config.BLOCK_EARNINGS_IN_CYCLE:
        return False
    if chain.get("next_earnings"):
        return False
    return (chain.get("earnings_window") or {}).get("status") not in ("confirmed", "estimated")


def evaluate_symbol(chain, india_vix=None):
    """
    Return (best_spread_or_None, reject_reason_or_None) for one symbol.

    `india_vix` is the LIVE index level from market_data.get_market_context (passed
    down by generate_recommendations, injectable for testing). Below
    config.LOW_VIX_THRESHOLD the iron condor is stood down in favour of the
    higher-POP single side — see _prefer_single_side. Omit it and that check simply
    does not fire, so every existing caller keeps its behaviour.

    Why the level is threaded in rather than read here: this module makes no I/O
    call and no clock call, which is what lets selftest.py drive it offline. The VIX
    is data the orchestrator already fetched before selection (run.py step 2).
    """
    if chain is None:
        return None, "no chain data"
    sym_reason = _symbol_reject_reason(chain)
    if sym_reason:
        return None, sym_reason
    passed = {}
    reasons = []
    for side in ("PUT", "CALL"):
        sp = _build_spread(chain, side)
        if not sp:
            continue
        r = _spread_reject_reason(sp)
        if r:
            reasons.append(f"{side.lower()}-side {r}")
        else:
            passed[side] = sp
    if not passed:
        return None, ("; ".join(reasons) if reasons else "no constructible spread")

    # Both sides clear -> range-bound premium available -> prefer an iron condor,
    # UNLESS the vol regime says one side is the better structure.
    if config.ENABLE_IRON_CONDOR and "PUT" in passed and "CALL" in passed:
        low_vol, vix_note = _prefer_single_side(india_vix)
        ic = _build_iron_condor(chain, passed["PUT"], passed["CALL"])
        if low_vol:
            # By POP, not by score: score rewards credit/max_loss and IV rank, so
            # ranking on it would hand the slot back to whichever side collects more
            # premium — the exact trade-off this branch exists to decline. Score
            # breaks a POP tie only.
            best = max(passed.values(), key=lambda s: (s["pop_pct"], s["score"]))
            # State what was passed over, with both POPs. A structure choice that
            # silently differs from every other run's is the kind of thing that gets
            # read as a bug in the condor branch.
            versus = (f"IRON_CONDOR POP {ic['pop_pct']:.0f}%" if ic
                      else "an iron condor (which did not build)")
            best["structure_note"] = (
                f"LOW VOL: {vix_note} — {best['strategy']} POP "
                f"{best['pop_pct']:.0f}% preferred over {versus}")
            return best, None
        if ic:
            return ic, None
    return max(passed.values(), key=lambda s: s["score"]), None


def _apply_risk_flags(spread, flags, today):
    """
    Attach macro risk flags to a finished recommendation and, in LIVE mode,
    demote its score.

    Applied at SYMBOL level, after side selection and after the iron-condor
    branch — never inside _build_spread, where a condor rebuild would drop the
    fields (see _build_iron_condor's field contract).

    Shadow and live differ by exactly one value: `applied`. Flag resolution, the
    lookup, the multiplier itself, attachment, persistence and printing all run
    identically in both, so going live executes no new code.

    Both the real multiplier and the score it WOULD have produced are recorded,
    which is what makes the shadow period analysable from positions.json alone —
    tracker.record_new does dict(rec), so these ride along with no tracker change.
    """
    sector = market_data.get_sector(spread["symbol"])
    hits = risk_flags.flags_for(flags, spread["symbol"], sector, today)
    mult, detail = risk_flags.score_multiplier(hits, today)
    applied = mult if config.RISK_FLAG_MODE == "live" else 1.0

    worst = min(detail, key=lambda d: d["multiplier"]) if detail else None
    pre = spread["score"]

    spread["score_pre_flag"]       = pre
    spread["score"]                = round(pre * applied, 4)
    spread["risk_flag_mode"]       = config.RISK_FLAG_MODE
    spread["risk_flag_multiplier"] = mult                    # what live would apply
    spread["risk_flag_applied"]    = applied                 # what actually applied
    spread["risk_flag_score_live"] = round(pre * mult, 4)    # the counterfactual score
    spread["risk_flag_severity"]   = worst["effective_severity"] if worst else None
    # Flat strings, not nested dicts — keeps positions.json diffable and sidesteps
    # any aliasing question from record_new's shallow copy.
    spread["risk_flags"] = [
        f"{d['effective_severity'] or 'UNRATED'}: {str(d['risk'])[:120]}" for d in detail
    ]
    spread["market_risk_flags"] = [
        f"{risk_flags.effective_severity(f, today) or 'UNRATED'}: {str(f.get('risk'))[:120]}"
        for f in risk_flags.market_flags(flags, today)
    ]
    return spread


def _sector_cap_for(sector, override=None) -> int:
    """
    Effective MAX_PER_SECTOR for one sector.

    `override` is the caller's explicit per-call figure (e.g. cap_suppressed
    passing an "unlimited" value to lift the cap for a simulation) and always
    wins when given, uniformly across every sector — a simulation that means
    "no sector cap at all" must not have config.SECTOR_CAP_OVERRIDE quietly
    re-impose one. Absent that, config.SECTOR_CAP_OVERRIDE supplies a
    sector-specific figure where NSE's own Industry label lumps genuinely
    distinct businesses into one bucket (FINANCIAL SERVICES is 23 names in the
    NIFTY 100 — see config.SECTOR_CAP_OVERRIDE and REFERENCE.md §7); every
    other sector falls through to the flat config.MAX_PER_SECTOR.
    """
    if override is not None:
        return override
    return config.SECTOR_CAP_OVERRIDE.get(sector, config.MAX_PER_SECTOR)


def _apply_caps(picks, score_of=None, *, max_per_sector=None, max_recos=None,
                sector_of=None, open_counts=None, open_keys=None):
    """
    Rank by `score_of`, then apply the sector-concentration cap and the top-N cut.
    Pure. Returns (selected, drops) where drops maps symbol -> reason.

    `open_counts` ({sector: positions already OPEN}) seeds the sector tally, which
    is what makes MAX_PER_SECTOR a PORTFOLIO limit instead of a per-run one. It
    was per-run, and consecutive runs therefore stacked one sector: on 17-Aug-2026
    the 11:00 run recommended BAJFINANCE (Financial Services) and capped HDFCLIFE
    out; 13 minutes later BAJFINANCE re-priced from a condor into a lower-scoring
    bull put spread, HDFCLIFE won the slot on its own merits and was recorded —
    with BAJFINANCE still open. Each run's cap was applied correctly to the
    candidates it could see; the book still ended up with two Financial Services
    positions under a 1-per-sector rule. See tracker.open_sector_counts.

    `open_keys` ({(symbol, expiry)} already OPEN — tracker.open_position_keys())
    excludes a candidate that is ALREADY a live position before it ever reaches
    the top-N or sector-cap checks. Without this, a symbol that is already open
    but re-clears every gate this run reappears as a "new" recommended card
    (tracker.record_new correctly refuses to book it twice, so nothing is
    double-counted on the book — but the report would show it as a fresh trade,
    and it would consume a sector-cap slot a genuinely new candidate could have
    used instead). Surfaced 18-Aug-2026 once SECTOR_CAP_OVERRIDE widened
    FINANCIAL SERVICES to 2: HDFCBANK, already open from 17-Aug, re-cleared and
    took the sector's spare slot ahead of SBIN — a real new candidate.

    `max_per_sector`, if passed, is a UNIFORM per-call override (see
    _sector_cap_for) — the per-sector config.SECTOR_CAP_OVERRIDE table only
    applies when this is left at its default None.

    Run against a different score key this doubles as a counterfactual: that is how
    _attribute_drops can tell a name that lost its slot TO A RISK FLAG from one that
    simply ranked too low on its own merits.

    Note the top-N check sits at the head of the loop rather than as a break after
    the append. Same selection, but every remaining pick now gets an explicit drop
    reason instead of being silently abandoned mid-list — previously anything past
    MAX_RECOMMENDATIONS stayed marked CANDIDATE in the report while never actually
    being recommended.
    """
    score_of = score_of or (lambda s: s["score"])
    max_recos = config.MAX_RECOMMENDATIONS if max_recos is None else max_recos
    sector_of = sector_of or market_data.get_sector
    open_keys = open_keys or set()

    # Control (b): tier before score, so every qualifying NIFTY 50 name outranks
    # every Next 50 name and Next 50 can only BACKFILL slots the core index left
    # empty. A score multiplier would not guarantee that — a strong Next 50 name
    # would still displace a weaker core one, which is not the role it plays.
    def _rank(sp):
        tier = 1 if (config.NEXT50_TIERED_FILL and _is_next50(sp)) else 0
        return (tier, -score_of(sp))

    held = dict(open_counts or {}) if config.CAP_COUNTS_OPEN_POSITIONS else {}
    ordered = sorted(picks, key=_rank)
    selected, drops, sector_count = [], {}, dict(held)
    for sp in ordered:
        sector = sector_of(sp["symbol"])
        if (sp["symbol"], str(sp.get("expiry"))) in open_keys:
            drops[sp["symbol"]] = ("already an open position on this symbol/expiry — "
                                   "not re-recommended; see the Performance Tracker")
            continue
        if len(selected) >= max_recos:
            reason = f"outside top {max_recos} by score"
            if config.NEXT50_TIERED_FILL and _is_next50(sp):
                reason += " (NEXT50 backfill — NIFTY 50 filled every slot)"
            drops[sp["symbol"]] = reason
            continue
        cap = _sector_cap_for(sector, max_per_sector)
        count = sector_count.get(sector, 0)
        if count >= cap:
            is_override = max_per_sector is None and sector in config.SECTOR_CAP_OVERRIDE
            reason = (f"sector cap: {sector} already at capacity ({count}/{cap} "
                      f"allowed by override)" if is_override else
                      f"sector cap: {sector} already at capacity ({count}/{cap})")
            # Name the OPEN BOOK when that is what is binding. "already at
            # capacity" against an empty candidate tally reads as a bug
            # otherwise, and the reader has no way to tell a same-run
            # displacement from a position taken days ago.
            if held.get(sector, 0):
                reason += (f" — {held[sector]} held by an open position"
                           f"{'s' if held[sector] > 1 else ''}, not by this run")
            drops[sp["symbol"]] = reason
            continue
        sector_count[sector] = count + 1
        selected.append(sp)
    return selected, drops


def _cap_diagnostic_rows(picks, open_counts, open_keys, today=None):
    """Gate for the time-boxed concentration diagnostic (cap_suppressed): config.CAP_DIAGNOSTIC_UNTIL
    documents that past that date the diagnostic should stop and be "replaced by a prompt to make
    the MAX_PER_SECTOR decision" -- but nothing ever actually read the date (found 8 Oct 2026, by
    then 8 days past its own expiry), so the diagnostic (which simulates _apply_caps three times
    over) had been running unconditionally the whole time. Implemented as originally designed: past
    the date, skip the simulation and surface the pending decision instead of computing it again.
    `today` is injectable for testing; defaults to the real clock."""
    today = today or date.today()
    cap_until = None
    try:
        cap_until = date.fromisoformat(config.CAP_DIAGNOSTIC_UNTIL) if config.CAP_DIAGNOSTIC_UNTIL else None
    except ValueError:
        print(f"  [STRATEGY] CAP_DIAGNOSTIC_UNTIL={config.CAP_DIAGNOSTIC_UNTIL!r} is not a valid "
              f"date -- treating the diagnostic window as expired")
    if cap_until is not None and today > cap_until:
        print(f"  [STRATEGY] concentration-limit diagnostic window ended {cap_until} -- "
              f"decide whether to keep MAX_PER_SECTOR={config.MAX_PER_SECTOR} "
              f"(see rg/config.py CAP_DIAGNOSTIC_UNTIL) rather than extending the measurement")
        return [{"status": "DIAGNOSTIC_EXPIRED",
                 "detail": f"Diagnostic window ended {cap_until}. Decide whether to keep "
                           f"MAX_PER_SECTOR={config.MAX_PER_SECTOR} (rg/config.py) instead of "
                           f"extending RG_CAP_DIAGNOSTIC_UNTIL to keep measuring it."}]
    return cap_suppressed(picks, config.CAP_DIAGNOSTIC_TOP_N, open_counts=open_counts, open_keys=open_keys)


def cap_suppressed(picks, top_n=10, sector_of=None, open_counts=None, open_keys=None):
    """
    TIME-BOXED DIAGNOSTIC — what the concentration limits actually cost us.

    PURE: no I/O, no config mutation, no clock. Pass `sector_of` to inject a
    lookup; the default resolver reads a process-memoised dict.

    Answers one question the Screen Diagnostics cannot: of the spreads that
    cleared every underlying risk gate, which were held back by PORTFOLIO rules
    (sector cap, top-N) rather than by trade quality — and which limit was
    actually binding. Three simulations, each lifting one limit:

        actual    both limits on              -> what was recommended
        cap_off   sector cap lifted only      -> in here but not actual
                                                 => the SECTOR CAP blocked it
        topn_off  top-N lifted only           -> in here but not actual
                                                 => the TOP-N cut blocked it
        neither in cap_off nor topn_off       => both limits had to give

    Deliberately preserved, NOT bypassed:
      - every underlying risk gate (only already-qualifying `picks` come in);
      - the Next 50 tier hierarchy — lift it and thin satellite names dominate
        the table on raw score, which is the ranking we rejected;
      - post-flag scores — ranking on score_pre_flag would quietly resurrect
        names the macro risk-flag layer deliberately pushed down.

    This is EVIDENCE FOR TUNING MAX_PER_SECTOR, not a second recommendation
    list. Trading the blocked rows wholesale rebuilds the concentration the cap
    exists to prevent — and in short premium, five names in one sector is one
    bet with five tickets that all realise together on a sector gap.
    """
    if not picks:
        return []
    sector_of = sector_of or market_data.get_sector
    unlimited = len(picks) + 1
    kw = {"sector_of": sector_of, "open_counts": open_counts, "open_keys": open_keys}

    actual, _   = _apply_caps(picks, **kw)
    # `cap_off` lifts the sector cap, so the open book must not be counted either
    # — leaving open_counts in place would keep blocking on the very limit this
    # simulation exists to lift, and the row would then be attributed to the
    # top-N cut instead of the sector cap it was really held back by.
    # open_keys stays on regardless: an already-open symbol is excluded on
    # IDENTITY, not on sector capacity, so lifting the sector cap must not
    # un-exclude it.
    cap_off, _  = _apply_caps(picks, max_per_sector=unlimited, sector_of=sector_of,
                              open_keys=open_keys)
    topn_off, _ = _apply_caps(picks, max_recos=unlimited, **kw)
    display, _  = _apply_caps(picks, max_per_sector=unlimited, max_recos=top_n,
                              sector_of=sector_of, open_keys=open_keys)

    sel  = {s["symbol"] for s in actual}
    capo = {s["symbol"] for s in cap_off}
    tno  = {s["symbol"] for s in topn_off}

    rows = []
    for rank, sp in enumerate(display, 1):
        sym = sp["symbol"]
        if sym in sel:
            status, blocked = "RECOMMENDED", ""
        elif sym in capo:
            status, blocked = "BLOCKED", f"sector cap ({sector_of(sym)})"
        elif sym in tno:
            status, blocked = "BLOCKED", f"top-{config.MAX_RECOMMENDATIONS} cut"
        else:
            status, blocked = "BLOCKED", f"sector cap + top-{config.MAX_RECOMMENDATIONS}"
        rows.append({
            "rank": rank, "symbol": sym, "strategy": sp["strategy"],
            "sector": sector_of(sym),
            "index_membership": sp.get("index_membership", "NIFTY50"),
            "score": sp["score"], "score_pre_flag": sp.get("score_pre_flag", sp["score"]),
            "pop_pct": sp.get("pop_pct"), "credit_collected": sp.get("credit_collected"),
            "capital_at_risk": sp.get("capital_at_risk"),
            "risk_flag_severity": sp.get("risk_flag_severity"),
            "status": status, "blocked_by": blocked,
        })
    return rows


def _attribute_drops(picks, final, drops, diagnostics, open_counts=None, open_keys=None):
    """
    Write drop reasons into diagnostics, naming a macro risk flag whenever the flag
    is what actually cost the name its slot.

    Attribution is a counterfactual, not a guess: re-run the same caps on
    score_pre_flag, and if the dropped name WOULD have been selected unflagged,
    the flag is the cause and the cap is only the mechanism. Without this the
    report blames the sector cap for a demotion the flag caused.

    In shadow mode score == score_pre_flag, so no drop is ever attributed to a flag
    (nothing was actually displaced — which is the honest answer). Instead the
    reverse counterfactual runs on risk_flag_score_live, so a name that survived
    only because the penalty was pinned off is labelled as such. That line is the
    burn-in signal: it names, per run, exactly what going live would have changed.
    """
    flagged = {s["symbol"] for s in picks if s.get("risk_flags")}
    if not flagged:
        for sym, reason in drops.items():
            _mark(diagnostics, sym, reason)
        return

    # Both counterfactuals must run against the SAME open book (counts AND
    # identities) as the real selection, or a name blocked by an existing
    # position would look as though the flag had displaced it.
    unflagged_sel, _ = _apply_caps(picks, lambda s: s.get("score_pre_flag", s["score"]),
                                   open_counts=open_counts, open_keys=open_keys)
    live_sel, _      = _apply_caps(picks, lambda s: s.get("risk_flag_score_live", s["score"]),
                                   open_counts=open_counts, open_keys=open_keys)
    would_unflagged  = {s["symbol"] for s in unflagged_sel}
    would_live       = {s["symbol"] for s in live_sel}

    for sym, reason in drops.items():
        note = ""
        if sym in flagged and sym in would_unflagged:
            sev = next((s.get("risk_flag_severity") for s in picks if s["symbol"] == sym), None)
            mult = next((s.get("risk_flag_multiplier") for s in picks if s["symbol"] == sym), None)
            mech = ("the sector cap" if reason.startswith("sector cap")
                    else f"the top-{config.MAX_RECOMMENDATIONS} cut")
            note = (f" — CAUSE: macro risk flag [{sev or 'UNRATED'}] x{mult} demoted it; "
                    f"it would have cleared {mech} unflagged")
        _mark(diagnostics, sym, f"{reason}{note}")

    for sp in final:
        if sp["symbol"] in flagged and sp["symbol"] not in would_live:
            for d in diagnostics:
                if d["symbol"] == sp["symbol"]:
                    d["detail"] += (f" | SHADOW: live would have DROPPED this "
                                    f"(flag x{sp.get('risk_flag_multiplier')})")


def _mark(diagnostics, symbol, detail):
    for d in diagnostics:
        if d["symbol"] == symbol and d["status"] == "CANDIDATE":
            d["status"] = "REJECTED"
            d["detail"] = detail


def generate_recommendations(symbols, snapshot_fn, flags=None, today=None,
                             open_counts=None, open_keys=None, india_vix=None):
    """
    Snapshot each symbol, pick its best qualifying spread, enforce the sector
    cap. Returns (recommendations, diagnostics, cap_rows):
      recommendations — the top-N picks after both caps
      diagnostics     — {"symbol", "status", "detail"} per name, every drop
                        attributed to a named cause
      cap_rows        — the time-boxed concentration diagnostic (cap_suppressed)

    `flags` is the resolved macro risk-flag list from risk_flags.ingest(); omit it
    (or pass []) and every multiplier is 1.0, so the screen behaves exactly as it
    did before flags existed. `today` is injectable for testing.

    `open_counts` is the live book's per-sector tally from
    tracker.open_sector_counts, so the concentration cap spans runs.

    `open_keys` is the live book's {(symbol, expiry)} identity set from
    tracker.open_position_keys(). A candidate already held is excluded before
    ranking — see _apply_caps — so it neither reappears as a "new" recommended
    card nor consumes a sector-cap slot a genuinely new candidate could use.

    `india_vix` is the live index level from the market context run.py already
    fetches before selection. Below config.LOW_VIX_THRESHOLD it makes the screen
    prefer the higher-POP single side over an iron condor; omitted or unreadable, the
    check does not fire (see _prefer_single_side).

    ONLY the returned `recommendations` carry `recommended is True`, and the stamp
    is applied here — after the caps and after every counterfactual has been
    computed. tracker.record_new refuses anything without it, so no simulated or
    pre-cap list can reach the position book (see tracker's module docstring).
    """
    today = today or date.today()
    picks, diagnostics = [], []
    for sym in symbols:
        try:
            chain = snapshot_fn(sym)
        except Exception as e:
            diagnostics.append({"symbol": sym, "status": "ERROR", "detail": str(e)[:60]})
            print(f"  [STRATEGY] {sym}: snapshot failed — {e}")
            continue
        best, reason = evaluate_symbol(chain, india_vix=india_vix)
        if best:
            _apply_risk_flags(best, flags, today)
            # Symbol-level, after the iron-condor branch, for the same reason the
            # risk flags are applied here: a condor rebuild would drop it.
            best["earnings_unverified"] = _earnings_unverified(chain)
            # The trade qualifies on its mid credit (see _gate_credit); this says
            # explicitly when a market order crossing both legs would not -- the
            # card must show this, not bury it in a RoR number.
            best["fill_risk"] = fill_risk(best)
            # The basis fields ride along so the card, the diagnostics and
            # positions.json all state HOW the cycle was cleared. Without them a
            # reco cleared on a ±5-session estimate is indistinguishable from one
            # cleared on a filed date, which is the whole distinction this
            # feature introduces.
            _win = chain.get("earnings_window") or {}
            best["earnings_basis"] = ("supplementary" if chain.get("next_earnings")
                                      else _win.get("status", "unverified"))
            best["earnings_detail"] = earnings.describe(_win) if _win else None
            best["earnings_date_est"] = str(_win["date"]) if _win.get("date") else None
            note = ""
            if best.get("structure_note"):
                note += f" | {best['structure_note']}"
            if not best.get("dte_preferred", True):
                note += (f" | TENOR {best['dte']}d beyond preferred "
                         f"{config.PREFERRED_MAX_DTE}d (monthly ladder)")
            if best["earnings_unverified"]:
                note += " | EARNINGS DATE UNKNOWN (blocker could not run)"
            elif best["earnings_basis"] == "estimated":
                note += f" | earnings est {_win['lo']}..{_win['hi']} (clear of cycle)"
            if best["risk_flags"]:
                # += not =, or a flagged name silently loses the tenor and
                # earnings notes already accumulated above.
                note += (f" | FLAG {best['risk_flag_severity'] or 'UNRATED'} "
                         f"x{best['risk_flag_multiplier']} [{best['risk_flag_mode']}]"
                         + ("" if best["risk_flag_mode"] == "live"
                            else f" would score {best['risk_flag_score_live']}"))
            picks.append(best)
            diagnostics.append({"symbol": sym, "status": "CANDIDATE",
                                "detail": f"{best['strategy']} score {best['score']}{note}"})
            print(f"  [STRATEGY] {sym}: {best['strategy']} "
                  f"{best['short_strike']:.0f}/{best['long_strike']:.0f} "
                  f"POP {best['pop_pct']}% credit Rs.{best['credit_collected']:,.0f} "
                  f"risk Rs.{best['capital_at_risk']:,.0f} score {best['score']}{note}")
        else:
            diagnostics.append({"symbol": sym, "status": "REJECTED", "detail": reason})
            print(f"  [STRATEGY] {sym}: rejected — {reason}")

    # Rank, apply the caps, then attribute every drop.
    final, drops = _apply_caps(picks, lambda s: s["score"], open_counts=open_counts,
                               open_keys=open_keys)
    _attribute_drops(picks, final, drops, diagnostics, open_counts=open_counts,
                     open_keys=open_keys)
    cap_rows = _cap_diagnostic_rows(picks, open_counts, open_keys)

    # Stamp LAST. Every candidate is explicitly marked, not just the winners, so
    # a missing stamp means "never went through the caps" rather than "might be an
    # older dict" — and the tracker's gate can treat absence as a hard refusal.
    selected_ids = {id(sp) for sp in final}
    for sp in picks:
        sp["recommended"] = id(sp) in selected_ids
    for rank, sp in enumerate(final, 1):
        sp["recommendation_rank"] = rank

    blocked = sum(1 for r in cap_rows if r["status"] == "BLOCKED")
    if blocked:
        print(f"  [STRATEGY] concentration limits held back {blocked} qualifying "
              f"spread(s) — see the diagnostic section")
    if open_counts and config.CAP_COUNTS_OPEN_POSITIONS:
        # Per-sector cap named inline, not a blanket MAX_PER_SECTOR — a sector
        # carrying a config.SECTOR_CAP_OVERRIDE (e.g. FINANCIAL SERVICES) is
        # capped at its own figure, not the flat default, and stating the wrong
        # one here would contradict the Screen Diagnostics wording below.
        held = ", ".join(f"{s} x{n} (cap {_sector_cap_for(s)})"
                         for s, n in sorted(open_counts.items()))
        print(f"  [STRATEGY] open book already holds: {held}")
    return final, diagnostics, cap_rows
