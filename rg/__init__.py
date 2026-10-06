"""
RG Option Selling screen, ported into the hub (forecast_hub/rg).

Vendored from the standalone rg_option_selling tool. The screen logic is unchanged;
only paths and imports were re-anchored to forecast_hub/ (no sys.path hacks).
Entry point for the hub: hub/stocks.py (python -m hub.stocks).

Modules:
  config        — all tunables in one place
  market_data   — Kite REST chain snapshot (or cached replay), universe, context
  strategy      — deterministic credit-spread selection + sizing (generate_recommendations)
  risk_flags    — macro risk-flag store
  macro         — daily macro briefing (LLM only if ANTHROPIC_API_KEY is set)
  earnings      — results-date cache
  tracker, mtm  — open-position book and marking (read-only in the hub)
  calculators, black_scholes — IV rank / HV and Greeks helpers
"""
