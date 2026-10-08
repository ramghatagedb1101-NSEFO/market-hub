"""
Nifty 50 option-selling screen (ported from the rg_option_selling tool, vendored in rg/).

Screens each Nifty 50 constituent for a defined-risk credit spread or iron condor and
writes docs/data/stocks.json: the recommendations, the per-stock diagnostics (why each
name was rejected or errored), and the run timestamp.

Run:      python -m hub.stocks
Live:     needs KITE_API_KEY and KITE_ACCESS_TOKEN (the daily workflow exports the token).
Replay:   RG_CHAIN_CACHE=read RG_CHAIN_REPLAY_DATE=2026-08-19 python -m hub.stocks
          serves the cached chains from rg/data/chain_cache and makes no Kite call.
Macro:    the LLM briefing runs only if ANTHROPIC_API_KEY is set; otherwise the
          deterministic briefing is used (RG_MACRO_LLM defaults to 0 without a key).

Also settles and tracks every qualifying recommendation (8 Oct 2026) via rg/tracker.py: appends new
picks as OPEN positions, settles anything past its expiry on the underlying's close, and publishes an
all-time win-rate/P&L summary to docs/data/stocks_track_record.json. This is the screen's own measured
HYPOTHETICAL performance, not the owner's real trading P&L -- nothing here knows which suggestions
were actually taken in Kite. Still not done here: no PDF/report output (vendored but not wired in).
"""
import json
import os
from datetime import datetime, timezone

from . import config

STOCKS_FILE = config.SITE_DIR / "data" / "stocks.json"
# Run history (8 Oct 2026): STOCKS_FILE is overwritten by every run, including manual re-dispatches
# used for testing -- the daily job ran four times on 8 Oct alone (pre-market, mid-morning, and the
# scheduled post-close run), and the mid-morning run's recommendations were gone by the time anyone
# asked what they actually were. One row per run, appended, so a recommendation is never lost just
# because a later run replaced it as "today's" current view.
LOG_FILE = config.REPO / "state" / "stocks_log.json"
LOG_MAX_ENTRIES = 1000


def _append_log(payload: dict) -> None:
    try:
        log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        if not isinstance(log, list):
            log = []
    except (OSError, ValueError):
        log = []
    log.append({
        "generated_at": payload["generated_at"],
        "mode": payload["mode"],
        "symbol_count": payload["symbol_count"],
        "recommendation_count": payload["recommendation_count"],
        "india_vix": payload["india_vix"],
        "recommendations": payload["recommendations"],
    })
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(log[-LOG_MAX_ENTRIES:], default=str), encoding="utf-8")


# Recommendation tracking (8 Oct 2026): hub/stocks.py used to call tracker.open_sector_counts()/
# open_position_keys() for READS (so the sector cap applies across runs) but never tracker.record_new()
# to WRITE to that same book -- it was permanently empty, so the cross-run sector cap had silently been
# a no-op the whole time (see rg/config.py's CAP_COUNTS_OPEN_POSITIONS for the incident that cap exists
# to prevent). Wiring in record_new()/evaluate_closed() fixes that AND answers a real question asked
# 8 Oct ("what would have happened on that recommendation") that this screen previously had no way to
# answer at all.
TRACK_RECORD_FILE = config.SITE_DIR / "data" / "stocks_track_record.json"
MIN_SETTLED_FOR_WIN_RATE = 10   # below this, publish counts only -- see MIN_N on the Desk tab for the
                                 # same idea at a bar fitted to this screen's much slower 30-66 DTE cadence


def _settle_fn(position: dict):
    """tracker.evaluate_closed()'s settle_fn: the underlying's LTP, for a position whose expiry has
    already passed (rg/config.py's SETTLE_WITH_HISTORICAL documents this as the intended approach).
    Returns (0, note) on any failure -- evaluate_closed() leaves the position OPEN and tries again next
    run rather than settling it on a bad read."""
    from rg import market_data
    try:
        spot = market_data.get_equity_spot(position["symbol"])["last"]
    except Exception as exc:
        return 0, f"settlement quote failed: {exc}"
    if not spot:
        return 0, "no settlement quote available"
    return spot, f"settled on LTP {spot}"


def _track_record() -> dict:
    """Published to docs/data/stocks_track_record.json and surfaced on the admin dashboard's
    Back-tests tab (hub/admin_publish.py's TESTS dict). This is the screen's own measured
    HYPOTHETICAL performance: every qualifying recommendation is tracked as if it had been traded,
    because nothing in this app knows whether the owner actually took a given trade (suggestions are
    shown, the owner trades manually in Kite, nothing writes back) -- same philosophy the index
    forecast's own track record already uses. Not the owner's real P&L."""
    from rg import tracker
    s = tracker.summary()
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "basis": "Every qualifying recommendation tracked as if traded, from entry to settlement. "
                 "Not the owner's actual trading P&L -- nothing here knows which suggestions were "
                 "really taken.",
        "total_recommended": s["total_recommended"],
        "open": s["open"],
        "closed": s["closed"],
        "wins": s["wins"],
        "losses": s["losses"],
        "realized_pnl": s["realized_pnl"],
        "capital_deployed": s["capital_deployed"],
        "roi_pct": s["roi_pct"],
        "open_capital_at_risk": s["open_capital_at_risk"],
    }
    if s["closed"] < MIN_SETTLED_FOR_WIN_RATE:
        out["win_rate_status"] = (f"too few settled trades ({s['closed']}/{MIN_SETTLED_FOR_WIN_RATE}) "
                                   f"to show a win rate yet")
    else:
        out["win_rate_pct"] = s["win_rate_pct"]
        if s["closed"] < 20:
            out["win_rate_note"] = f"still early -- only {s['closed']} settled trades so far"
    return out


def main() -> dict:
    if not os.getenv("ANTHROPIC_API_KEY"):
        os.environ.setdefault("RG_MACRO_LLM", "0")

    from rg import config as rc, market_data, strategy, tracker, risk_flags
    from rg import macro as macro_mod, earnings

    replaying = rc.CHAIN_CACHE_MODE == "read"
    day = None
    if replaying:
        day = market_data.replay_day()
        symbols = market_data.cached_chain_symbols(day)
        if not symbols:
            raise SystemExit(f"RG_CHAIN_CACHE=read but no cached snapshots for {day} "
                             f"({rc.CHAIN_CACHE_DIR}).")
        print(f"[STOCKS] REPLAY {day}: {len(symbols)} cached snapshot(s), no Kite calls")
    else:
        symbols = market_data.get_universe()        # NSE constituent list (nifty50 mode)
        if not symbols:
            raise SystemExit("No Nifty 50 universe resolved; nothing to screen.")
        print(f"[STOCKS] LIVE: {len(symbols)} symbols from the {rc.UNIVERSE_LABEL} list")

    if rc.BLOCK_EARNINGS_IN_CYCLE and rc.EARNINGS_ESTIMATE and not replaying:
        earnings.refresh(symbols)

    # Settle anything past expiry BEFORE this run's own open-book reads just below, so the sector cap
    # and the published track record both reflect the latest state. Skipped during a replay: that mode
    # tests the selection layer against a cached chain and must not mutate real position state or make
    # a live settlement call.
    if not replaying:
        settled = tracker.evaluate_closed(_settle_fn)
        if settled:
            print(f"[STOCKS] settled {len(settled)} position(s): " +
                  ", ".join(f"{p['symbol']} {p['status']} (Rs.{p['realized_pnl']})" for p in settled))

    context = market_data.get_market_context()
    macro = macro_mod.get_macro_briefing(context)
    flags = risk_flags.ingest(macro.get("key_risks"))
    open_counts = tracker.open_sector_counts(market_data.get_sector)
    open_keys = tracker.open_position_keys()
    vix = context.get("india_vix")

    recos, diagnostics, cap_rows = strategy.generate_recommendations(
        symbols, market_data.get_chain_snapshot, flags=flags,
        open_counts=open_counts, open_keys=open_keys, india_vix=vix)
    print(f"[STOCKS] {len(recos)} recommendation(s) from {len(symbols)} symbol(s)")

    if not replaying:
        admitted = tracker.record_new(recos)
        print(f"[STOCKS] tracker: added {admitted['added']}, skipped {admitted['skipped']} "
              f"(already open), rejected {admitted['rejected']}")
        for note in admitted["notes"]:
            print(f"  [STOCKS] {note}")
        track_record = _track_record()
        TRACK_RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)
        TRACK_RECORD_FILE.write_text(json.dumps(track_record, indent=2, default=str), encoding="utf-8")
        print(f"[STOCKS] wrote {TRACK_RECORD_FILE}")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe": rc.UNIVERSE_LABEL,
        "mode": "replay" if replaying else "live",
        "replay_date": str(day) if replaying else None,
        "symbol_count": len(symbols),
        "india_vix": vix,
        "macro_source": macro.get("source"),
        "recommendation_count": len(recos),
        "recommendations": recos,
        "diagnostics": diagnostics,
        "portfolio_caps": cap_rows,
    }
    STOCKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOCKS_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"[STOCKS] wrote {STOCKS_FILE}")
    _append_log(payload)
    print(f"[STOCKS] appended to {LOG_FILE}")
    return payload


if __name__ == "__main__":
    main()
