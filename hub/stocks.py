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

Not done here, on purpose: no tracker writes (no positions are booked), no settlement,
no PDF/report output.
"""
import json
import os
from datetime import datetime, timezone

from . import config

STOCKS_FILE = config.SITE_DIR / "data" / "stocks.json"


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
    return payload


if __name__ == "__main__":
    main()
