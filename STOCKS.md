# Nifty 50 option-selling screen (STOCKS)

## What was ported

The screen from the standalone `rg_option_selling` tool is vendored into `rg/`. It scans
each Nifty 50 constituent and recommends a defined-risk credit spread or iron condor.
The selection logic is unchanged. Only paths and imports were changed:

- `sys.path` hacks that pointed at the parent folder are gone. Modules import each other
  relatively (`from .black_scholes import ...`).
- `calculators.py` reads `iv_history/` and `price_history/` from `forecast_hub/`, not the
  working directory.
- `market_data.py` reads `supplementary_data/` from `forecast_hub/`.
- `.env` is loaded only from `forecast_hub/.env`, never from a folder higher up.
- The `kite_token.json` file fallback is removed. Kite credentials come from the
  environment only.
- The NSE holiday set is copied verbatim to `rg/nse_holidays.py`, so `backfill_iv_history.py`
  is not needed.

Vendored data:

- `rg/data/`: `nifty50.json`, `sector_map.json`, `index_membership.json`,
  `earnings_history.json`, `crude_history.json`, and the chain snapshot for 2026-08-19
  (Nifty 50 names only).
- `iv_history/`: all 102 per-stock IV history files.
- `price_history/`: the 50 Nifty 50 files.
- `supplementary_data/`: `market_context.json` and the per-symbol files that exist for
  19 of the 50 names.

Not vendored, on purpose: `positions.json` (the trading book), `kite_token.json`,
`kite_tokens.json`, `risk_flags.json`, `macro_briefing.json`, reports and PDFs.
`report.py`, `docs.py`, `run.py` and `selftest.py` are not vendored either.

## What runs

`hub/stocks.py` (`python -m hub.stocks`):

1. Builds the universe. Live: the Nifty 50 constituent list from NSE, with the vendored
   `nifty50.json` as fallback. Replay: the cached snapshot symbols.
2. Runs the earnings refresh (live only).
3. Reads the market context and the macro briefing. The LLM briefing runs only if
   `ANTHROPIC_API_KEY` is set. Otherwise the deterministic briefing is used.
4. Calls `rg.strategy.generate_recommendations` with `market_data.get_chain_snapshot`.
5. Writes `docs/data/stocks.json`: `generated_at`, `mode` (live or replay), `universe`,
   `india_vix`, `macro_source`, `recommendations`, per-stock `diagnostics` (status and
   reason for each name), and `portfolio_caps`.

It does not book positions in the tracker, does not settle anything, and produces no PDF.

The daily workflow runs it as a step right after the daily job. The step has
`continue-on-error: true`, so a failure does not block the other steps.

## How to run

Live (needs `KITE_API_KEY` and `KITE_ACCESS_TOKEN` in the environment):

    python -m hub.stocks

Offline replay of the cached 2026-08-19 chains (no Kite call):

    RG_CHAIN_CACHE=read RG_CHAIN_REPLAY_DATE=2026-08-19 python -m hub.stocks

Replay caveat: the replay serves the chains from that day. The earnings gate, DTE and
expiry still use today's date, so a replay tests the selection layer, not a faithful
re-run of that day.

## Still missing

- Live Kite testing. Only the offline replay was run. The live path (quotes, instruments,
  SPAN margin) has not been exercised against Kite.
- Earnings data for names outside the watchlist. 31 of the 50 names have no
  `supplementary_data/<SYM>.json`, so their earnings dates come only from the NSE
  board-meeting fetch, or show as "unverifiable".
- The IV-history daily update. The old `save_iv_snapshot` and `backfill_iv_history.py` are
  not in the hub. `iv_history/` is a snapshot as of the vendoring date, so IV rank ages
  until someone refreshes it.
- Persistent state across CI runs. `risk_flags`, `macro_briefing`, `earnings` and the
  chain cache are written to `rg/data/` but not committed (the workflow commits only
  `state` and `docs/data`). They start fresh on each runner.
- Open positions. The hub does not read the parent's `positions.json`, so the sector and
  open-position caps do not account for the live book. Results can differ from the old
  tool for that reason.
