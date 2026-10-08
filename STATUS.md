# Build status and to-do

As of 8 Oct 2026, 11:45 IST. Read this together with `CHANGELOG.md`. Updated after the phone app
sign-in went live and the working data (phone app files and `state/`) moved to the private repo.

## Where we are

| Area | State |
|---|---|
| Forecast engine (NIFTY, BANK NIFTY, SENSEX) | Working. Day, expiry and month horizons. |
| Daily job | **Runs on schedule** (weekdays 18:00 IST), via the Kite login relay. Retry logic added 8 Oct for a transient relay failure; verified working since. |
| Track record | Running, but still too early: 1 settled outcome per horizon so far, well short of the 20 needed before the app shows a verdict (gate added 8 Oct). |
| Live quotes | Working through the relay (`?mode=quote`), a few seconds delayed. |
| F&O suggestions | Published daily. Credit gate now reads mid (limit/combo) price instead of worst-case, so real tradeable spreads (ADANIENT, BEL, ETERNAL and others) stop being silently discarded; a `fill_risk` flag and stop-loss/profit-target prices now show on each card. |
| Daily brief | NVIDIA primary, Gemini fallback (`hub/narrate.py`). Not re-verified since the Gemini 503 issue noted 6 Oct — confirm it's no longer showing "Brief pending" before relying on it. |
| Phone page | Live on GitHub Pages (`docs/index.html`) and Cloudflare Pages (`market-hub-4dq.pages.dev`). **Signed in with the admin dashboard's email code** (live 8 Oct, relay Version 19). Its data and the daily job's `state/` live in the private repo `market-hub-private`; nothing but index quotes is public now. |
| Private data | `market-hub-private/site/` (phone app files) and `/state/` (forecast state, prices, bulk deals), synced by `hub/site_data.py` in every job. |
| Stock library (124 parameters) | Built and running. Batched weekly (Saturdays, chains automatically across however many ~70-minute runs the ~2,570-company universe needs). A real bug meant every batch after the first silently lost all prior progress and reset to 0 — found and fixed 8 Oct; not yet confirmed clean on a live run (checking). |
| Multi-bagger screen | Built — NOT "not started" as this file used to say. Previously ran as its own independent weekly job (Sundays); as of 8 Oct it's merged into the stock-library batch run instead, so the two no longer fetch the same BharatStock financials twice a week. |
| Admin dashboard | Built (Google Apps Script, six-digit email code login, six-hour session). Status/Library/Parameters/Registry/Bulk deals/Back-tests tabs. |
| Smart-money (bulk deals) | Collecting daily; the `bulk_*`/`registry_buys_20d` parameters need more history before they're usable. |
| Email alerts | Built 8 Oct (`hub/alerts.py`, relay `mode=alert`); live since the relay redeploy (Version 19). Not yet seen firing on a real batch. |
| News | Not built as a standalone feature; `hub.context` pulls FII/DII, FX, US markets and headlines for the daily brief, but there's no separate news screen. |
| Analytical tools | Last counted 6 of 10 requested; not recounted since. |

## To-do, in order

### A. Confirm this week's fixes actually hold under real conditions
1. Confirm the library-batching fix holds on a live run (company count should climb past 658 instead of resetting to 0) — checking now.
2. Confirm the best-effort BharatStock field-name guesses added 8 Oct (`dividend_paid`, volume/delivery on the prices endpoint) actually matched real field names once a live batch runs them — they fail safe (stay a gap) if wrong, but worth confirming either way.
3. Confirm the daily brief isn't still stuck on Gemini's 503s now that NVIDIA is primary.

### B. Email alerts for "new finding" stocks (built 8 Oct)
4. Confirm the first real alert email arrives after a library batch finds a tier 1/2 stock passing its gates.

### C. Privacy (phone app sign-in and private data, live 8 Oct)
5. Sign in on the phone and confirm every tab loads (owner; needs the emailed code).
6. Confirm today's 18:00 daily run pulls `state/` from the private repo and saves back to it (first run on the new path).
7. Library batch chain: the batch running at the switch finished cleanly and chained on; the next batch (run 37737062142) is the first on the new workflow -- confirm its save step sends `site/multibagger.json` to the private repo.

### D. Housekeeping
8. `working_capital_days`/`working_capital_change` are genuine gaps (field names for receivable/inventory/payable days on the BharatStock balance sheet were never confirmed) — worth a live check if there's ever a reason to prioritise it.
9. `sector_pe_vs_history` needs a persisted multi-year sector-PE time series that doesn't exist yet; not worth building until there's a real use for it.
10. Analytical tools count (6 of 10) hasn't been rechecked in a while — worth a fresh pass if the original ten are still the target.

## Known problems
- Track record has too little settled history to mean anything yet (by design — the app won't show a hit rate below 20 settled outcomes per horizon).
- Data committed before 8 Oct (phone app files and `state/`) stays readable in this public repo's git history.
- The daily brief's reliability depends on NVIDIA/Gemini API availability, outside our control.
- `working_capital_days`, `working_capital_change`, `sector_pe_vs_history` are honest gaps, not silently faked.

## Decisions waiting on you
1. Email alerts: once built, what should actually trigger a send — tier 1 discovery alone, or tier 1 combined with a minimum number of library/multi-bagger gates passed? (Building a reasonable default now; easy to tighten later.)
