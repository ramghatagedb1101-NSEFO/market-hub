# Build status and to-do

As of 9 Oct 2026, 06:10 IST. Read this together with `CHANGELOG.md`.

## HANDOVER -- read this first if you are a new Claude session

**Accounts:** act only as Google `ramghatagedb1101@gmail.com` and GitHub `ramghatagedb1101-NSEFO`. Never
`ramghatage@gmail.com` / `ramghatage-ux`. Claude in Chrome only reaches profiles signed in to this session's
Claude account -- check GitHub's `user-login` and the Apps Script account popup before acting. Details in
CHANGELOG 9 Oct, "Accounts and browser access".

**Admin login button: fixed and deployed (9 Oct, ~19:50 IST).** Cause was a browser-side syntax error
in the new Multibagger/Matured code (`screen's` inside the `ADMIN_HTML` template literal), not
authorization -- see CHANGELOG 9 Oct. Fix `d7578a5` (plus: admin session now survives tab closes,
`localStorage`) is deployed as a new version on **both** `AKfycbwQZxgg…` (admin bookmark) and
`AKfycbye12r6…` (live relay), done from the Profile 5 / ramghatagedb1101@gmail.com Chrome window.
Verified live from outside: both addresses serve the fixed page, and the page script Google actually
serves parses (the same check fails on the broken 9 Oct code). Still to confirm by the owner: one real
"Email me a code" click delivers a code, and reopening the tab within six hours stays signed in.

**Always run `node relay/check.js` before pasting/deploying relay code.** It catches browser-side errors
inside `ADMIN_HTML` that `node --check` cannot see.

**git push works** from the owner's machine as `ramghatagedb1101-NSEFO` (fixed 9 Oct).

## Structure and capabilities audit (owner's request, 8 Oct)

Going module by module for "claims vs. reality" bugs -- a config value, parameter, or feature documented or labeled as working but the code never actually reading it or doing it. Found and fixed so far: `rg/strategy.py`'s dead `CAP_DIAGNOSTIC_UNTIL` date-check, `hub/context.py`'s one-feed-failure discarding all headlines, `hub/narrate.py`'s non-functional Gemini fallback (details in `CHANGELOG.md`). Checked and confirmed working as designed: `hub/fno.py`, `multibagger.py` constants, `hub/bulkdeals.py`, the admin relay's large-file handling, `docs/index.html`'s sign-in contract. Deleted confirmed-dead code: `kite-login.yml`, `diag.yml` and their dependencies.

**`rg/tracker.py`/`rg/mtm.py` were confirmed dormant 8 Oct, activated the same day, and confirmed live 9 Oct.** A real question ("did the SBIN recommendation work out") showed the dormancy was itself a gap, not just an intentional boundary. Also found while activating it: `hub/stocks.py` already read from that tracker's open-position book to enforce the cross-run sector cap, but since nothing ever wrote to it, the book was permanently empty and the cap had silently been a no-op since this screen went live. See the "Stock credit-spread screen" entry in `CHANGELOG.md` for the full story. **Confirmed live 9 Oct**: the 00:43 IST daily run added SBIN as the first tracked position (`tracker: added 1, skipped 0, rejected 0`, no errors) and the admin dashboard's Back-tests tab shows the new `STOCK_TRACK_RECORD` card exactly as designed -- `total_recommended: 1`, `open: 1`, win-rate correctly gated ("too few settled trades (0/10)"), with no `Admin.gs` change needed.

**Live admin dashboard walk-through done 8 Oct (signed in).** All six tabs (Status/Library/Parameters/Registry/Bulk deals/Back-tests) render real data correctly. One real but minor gap found: tapping a library row to see its parameter detail worked, but the panel renders below the full 100-row page and the page never scrolled to it -- looked broken until scrolled all the way down. Fixed with `scrollIntoView` in `relay/Admin.gs` (`showStock()`); **needs the relay redeployed by hand** (`relay/README.md` has the steps) before it's live, same as every other `Admin.gs` change.

**Live phone-app walk-through done 8 Oct (signed in) found the data bundle call (`app_data`) failing hard.** Every signed-in screen (Brief, F&O, Multi-bagger, Desk) showed "not available"/"unavailable" -- live index quotes still worked (separate endpoint), but `app_data` returned a mix of HTTP 404 and 503 over several minutes of testing, confirmed via the browser's network log. Same transient-relay class already fixed today in five GitHub Actions workflows, just never applied to `docs/index.html`'s own relay call -- added the same 3-attempt retry, client-side only, no relay redeploy needed. **Confirmed resolved by the owner on their actual phone shortly after** (Brief and Multi-bagger both loaded); most likely this was load-related -- today's heavy admin-dashboard and phone-page testing hitting the same free-tier Apps Script deployment repeatedly -- rather than a standing break. The retry fix stays regardless: it is the same class of transient failure already proven to happen on this relay today. **F&O and Desk checked directly once things settled -- both render real data correctly too** (F&O's credit/breakeven figures, Desk's track-record `MIN_N` gate and 250-session chart). All four signed-in screens now confirmed working.

**The all-zero `library.json` entries turned out to be much larger than expected: 1,397 of 1,896 published entries (74%), one contiguous block, all carrying the exact 429-quota error -- found, fixed and confirmed 8 Oct.** Ran a one-off repair (`cursor_next` moved from 1896 back to 499, the earliest corrupted entry's position); confirmed via the workflow's own log output. The repair function and its one-off workflow were removed after the run, same lifecycle as `diag.yml` earlier today. Triggered a fresh library batch the same day to start the re-walk early -- it hit BharatStock's quota wall immediately (`processed: 0`), already exhausted by this morning's scheduled one-time catch-up run plus the rest of today's testing. The clean-stop fix handled it correctly: no new corruption, cursor held at 499. Real progress resumes once the quota resets (00:00 UTC / 05:30 IST) -- folds into the 9 Oct morning check already planned. Worth a spot-check on the admin dashboard's Library tab after a batch or two land to confirm the zero-data block is actually shrinking.

## Outside review of the methodology document (8 Oct)

Prepared a methodology write-up for an outside options/quant reviewer; their feedback confirmed the
existing 0.20-0.30 delta band trade-off (no change) and flagged two implementable gaps, both shipped
same day: a 12.5% slippage haircut on the credit-spread qualification gate (`rg/strategy.py`,
`CREDIT_SLIPPAGE_HAIRCUT_PCT`) so a thin-liquidity name can't qualify on a mid-price fill it's
unlikely to actually get, and a settled-session log for the expiry-theta module
(`state/expiry_theta_log.json`) so the reviewer's "50-100 settled sessions before scaling past 1 lot"
condition can eventually be checked against real data instead of nothing. Both tested standalone
before landing.

Two further recommendations are **not yet started**, by design -- they need groundwork first: an ROCE
gate on the multi-bagger screen (needs confirming 3-year annual ROCE data actually exists cleanly in
BharatStock's responses, same as the existing cash-flow gate's own "best-effort guess" caveat), and an
adaptive band-learning step size in the core forecast engine (`hub/engine.py`, a change that should go
through `hub/backtest.py` before it ever reaches the live model). A third recommendation -- splitting
"Financial Services" into Private Banks/NBFCs/PSU Banks/Insurance/AMC sub-sectors for the concentration
cap -- was explicitly left as is by the owner: neither NSE's own constituent CSV nor BharatStock expose
that breakdown, and a prior hand-built sector taxonomy disagreed with NSE's own label on 24 of 25
names before it was removed for exactly that reason.

## Where we are

| Area | State |
|---|---|
| Forecast engine (NIFTY, BANK NIFTY, SENSEX) | Working. Day, expiry and month horizons. Ten analytical tools now (was six; the four missing since the original "ten tools" request were added 8 Oct: `macd_cross`, `bollinger_reversion`, `momentum_10d`, `turn_of_month`). |
| Daily job | Runs on schedule (weekdays 18:00 IST), via the Kite login relay. Daily brief confirmed healthy 8 Oct: NVIDIA primary, source field shows `nvidia/nemotron-3-super-120b-a12b`, no Gemini fallback needed. |
| Track record | Running, but still too early: 1 settled outcome per horizon so far, well short of the 20 needed before the app shows a verdict. |
| Live quotes | Working through the relay (`?mode=quote`), a few seconds delayed. |
| F&O suggestions | Published daily. Credit gate reads mid (limit/combo) price, not worst-case; `fill_risk` flag and stop-loss/profit-target prices show on each card. |
| Expiry-day theta harvest | **New 8 Oct, EXPERIMENTAL/UNVALIDATED.** `hub/expiry_theta.py`, a NIFTY 0-DTE iron condor, deliberately separate from the 30-66 DTE stock screen (different, higher risk profile -- severe gamma risk on expiry day). Runs three times on NIFTY's weekly expiry (10:00/12:30/14:45 IST, `expiry-theta.yml`). Risk parameters (3x daily-sigma OTM distance, 1.5x stop-loss, 1 lot) **reviewed and confirmed by the owner 8 Oct.** No backtest exists or is possible (no intraday historical options data). Not yet seen running on a real expiry day -- next NIFTY Tuesday expiry is the first live test. |
| Phone page | Live on GitHub Pages and Cloudflare Pages, signed in with the admin dashboard's email code (relay Version 19). **Owner confirmed 8 Oct: signed in, every tab loads.** Its data and `state/` live in the private repo `market-hub-private`. |
| Stock library (124+ parameters) | Built, batched weekly. The resumable-batching bug is confirmed fixed. **BharatStock's daily quota ran out 8 Oct** (plausibly from the day's own heavy live-batch testing) -- a company-by-company 429 was corrupting data (every company after the first failure got a worthless all-zero entry instead of being left for a retry) until a same-day fix stopped a batch cleanly on the first 429 instead. That fix then exposed a second bug (the auto-chain re-dispatching every ~45-70 seconds once batches started failing instantly) -- also fixed same-day, confirmed live: the chain is correctly **stopped** as of ~13:30 IST 8 Oct, and will stay stopped until manually restarted. A scheduled check will manually restart it the morning of 9 Oct once the quota resets (00:00 UTC) and confirm the multi-bagger-scoring fix (separate issue, zero-price-division bug) actually holds on a real successful batch -- it hasn't been proven yet, every run since that fix landed was quota-blocked before it could prove out. |
| Multi-bagger screen | Merged into the stock-library batch run (8 Oct). Scoring itself not yet confirmed working on live data -- see above. |
| Admin dashboard | Built (Google Apps Script, six-digit email code login, six-hour session). Status/Library/Parameters/Registry/Bulk deals/Back-tests tabs. |
| Smart-money (bulk deals) | Collecting daily; the `bulk_*`/`registry_buys_20d` parameters need more history before they're usable. |
| Email alerts | Built and deployed (relay Version 19). Not yet seen firing on a real batch. |
| News | Not built as a standalone feature; `hub.context` pulls FII/DII, FX, US markets and headlines for the daily brief. |

## To-do, in order

### A. Tomorrow morning (9 Oct), once BharatStock's quota resets
1. Manually restart the stock-library-weekly chain (stopped 8 Oct, won't auto-resume until Saturday's cron otherwise) -- scheduled.
2. Confirm the multibagger zero-price-division fix actually resolves `multibagger_batch_written: 0` on a real successful batch -- genuinely unproven so far, every run since the fix landed was quota-blocked first.
3. Confirm the best-effort BharatStock field-name guesses (`dividend_paid`, volume/delivery, working-capital receivable/inventory/payable) actually matched real field names — they fail safe (stay a gap) if wrong, worth confirming either way.
4. Confirm the first real email alert arrives after a library batch finds a qualifying tier 1/2 stock.

### B. Still pending
5. Confirm the expiry-theta workflow actually fires and behaves sanely on the next NIFTY Tuesday expiry — unvalidated by design, so the first live run is also the first real test of the code path itself.
6. Confirm the 18:00 daily run and the library batch are both correctly pulling/saving `state/` and `site/` from the private repo (first week on the new path).

### C. Housekeeping
7. `sector_pe_vs_history` needs 8 accumulated weekly observations before it produces a value (`state/sector_pe_history.json`, started 8 Oct) — nothing to do but wait.
8. `working_capital_days`/`working_capital_change` field-name guesses need confirming against a live BharatStock response (see A3).

## Known problems
- Track record has too little settled history to mean anything yet (by design).
- Data committed before 8 Oct (phone app files and `state/`) stays readable in this public repo's git history.
- The daily brief's reliability depends on NVIDIA/Gemini API availability, outside our control.
- Expiry-theta is deliberately unvalidated and higher-risk than the rest of this codebase's F&O suggestions — treat every output as a hypothesis, not a track record, until real expiry days accumulate.
- BharatStock's daily quota (10,000 requests) is easy to exhaust on a day with heavy manual/test batch runs, as happened 8 Oct. The pipeline now fails safe when it happens (clean stop, no chain hammering, no corrupted entries) but the quota itself is still a real, finite daily constraint.

## Decisions waiting on you
1. Email alerts: the trigger (tier 1/2 discovery + at least 60% of testable library gates passed) is a reasonable default, not yet confirmed against a real alert — easy to tighten/loosen once you've seen one fire.
