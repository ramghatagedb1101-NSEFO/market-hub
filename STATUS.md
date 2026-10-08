# Build status and to-do

As of 8 Oct 2026, 13:15 IST. Read this together with `CHANGELOG.md`.

## Where we are

| Area | State |
|---|---|
| Forecast engine (NIFTY, BANK NIFTY, SENSEX) | Working. Day, expiry and month horizons. Ten analytical tools now (was six; the four missing since the original "ten tools" request were added 8 Oct: `macd_cross`, `bollinger_reversion`, `momentum_10d`, `turn_of_month`). |
| Daily job | Runs on schedule (weekdays 18:00 IST), via the Kite login relay. Daily brief confirmed healthy 8 Oct: NVIDIA primary, source field shows `nvidia/nemotron-3-super-120b-a12b`, no Gemini fallback needed. |
| Track record | Running, but still too early: 1 settled outcome per horizon so far, well short of the 20 needed before the app shows a verdict. |
| Live quotes | Working through the relay (`?mode=quote`), a few seconds delayed. |
| F&O suggestions | Published daily. Credit gate reads mid (limit/combo) price, not worst-case; `fill_risk` flag and stop-loss/profit-target prices show on each card. |
| Expiry-day theta harvest | **New 8 Oct, EXPERIMENTAL/UNVALIDATED.** `hub/expiry_theta.py`, a NIFTY 0-DTE iron condor, deliberately separate from the 30-66 DTE stock screen (different, higher risk profile -- severe gamma risk on expiry day). Runs three times on NIFTY's weekly expiry (10:00/12:30/14:45 IST, `expiry-theta.yml`). No backtest exists or is possible (no intraday historical options data). Not yet seen running on a real expiry day -- next NIFTY Tuesday expiry is the first live test. |
| Phone page | Live on GitHub Pages and Cloudflare Pages. Signed in with the admin dashboard's email code (relay Version 19). Its data and `state/` live in the private repo `market-hub-private`. |
| Stock library (124+ parameters) | Built and running, batched weekly (Saturdays, chains automatically). The resumable-batching bug (every batch after the first losing all progress) is confirmed fixed on two live runs. A second real bug (every company failing to get a multi-bagger score, from an unguarded zero-price division) was found and fixed 8 Oct -- not yet confirmed clean on a live run with the fix applied (checking). |
| Multi-bagger screen | Merged into the stock-library batch run (8 Oct) -- the two no longer fetch the same BharatStock financials twice a week. |
| Admin dashboard | Built (Google Apps Script, six-digit email code login, six-hour session). Status/Library/Parameters/Registry/Bulk deals/Back-tests tabs. |
| Smart-money (bulk deals) | Collecting daily; the `bulk_*`/`registry_buys_20d` parameters need more history before they're usable. |
| Email alerts | Built and deployed (relay Version 19). Not yet seen firing on a real batch. |
| News | Not built as a standalone feature; `hub.context` pulls FII/DII, FX, US markets and headlines for the daily brief. |

## To-do, in order

### A. Confirm this week's fixes actually hold under real conditions
1. Confirm the multibagger zero-price-division fix actually resolves `multibagger_batch_written: 0` on the next live batch — checking now.
2. Confirm the best-effort BharatStock field-name guesses (`dividend_paid`, volume/delivery, working-capital receivable/inventory/payable) actually matched real field names once a live batch runs them — they fail safe (stay a gap) if wrong, worth confirming either way.
3. Confirm the first real email alert arrives after a library batch finds a qualifying tier 1/2 stock.
4. Confirm the expiry-theta workflow actually fires and behaves sanely on the next NIFTY Tuesday expiry — this is unvalidated by design, so the first live run is also the first real test of the code path itself, not just the strategy.

### B. Privacy rollout (live 8 Oct) — confirm it's holding
5. Sign in on the phone and confirm every tab loads (owner; needs the emailed code).
6. Confirm the 18:00 daily run and the library batch are both correctly pulling/saving `state/` and `site/` from the private repo (first week on the new path).

### C. Housekeeping
7. `sector_pe_vs_history` needs 8 accumulated weekly observations before it produces a value (`state/sector_pe_history.json`, started 8 Oct) — nothing to do but wait.
8. `working_capital_days`/`working_capital_change` field-name guesses need confirming against a live BharatStock response (see A2).

## Known problems
- Track record has too little settled history to mean anything yet (by design).
- Data committed before 8 Oct (phone app files and `state/`) stays readable in this public repo's git history.
- The daily brief's reliability depends on NVIDIA/Gemini API availability, outside our control.
- Expiry-theta is deliberately unvalidated and higher-risk than the rest of this codebase's F&O suggestions — treat every output as a hypothesis, not a track record, until real expiry days accumulate.

## Decisions waiting on you
1. Email alerts: the trigger (tier 1/2 discovery + at least 60% of testable library gates passed) is a reasonable default, not yet confirmed against a real alert — easy to tighten/loosen once you've seen one fire.
2. Expiry-theta: review the risk parameters in `hub/expiry_theta.py` (3x daily-sigma OTM distance, 1.5x stop-loss, 1 lot) once you've seen a real suggestion — these were my own conservative judgment calls, not something you specified numerically.
