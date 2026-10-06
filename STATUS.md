# Build status and to-do

As of 6 Oct 2026, 16:10 IST. Read this together with `CHANGELOG.md`.

## Where we are

| Area | State |
|---|---|
| Forecast engine (NIFTY, BANK NIFTY, SENSEX) | Working. Day, expiry and month horizons. Year-end computed but hidden. |
| Backtest | Done. Model does **not** beat the "last close" baseline on any horizon yet. |
| Track record | Running. **Zero outcomes settled so far**, so no verdict is possible yet. |
| Daily job | Works when started by hand. **The 15:45 schedule has not fired.** |
| Live quotes | Working through the relay (`?mode=quote`). Quotes are a few seconds delayed, not tick-by-tick. |
| Kite login | Works through the relay, but the daily key check fails when the two `RELAY_KEY` copies differ. |
| F&O suggestions | Published. Iron condor and spreads, with thresholds. Expiry chain data included. **No backtest yet.** |
| Daily brief (Gemini) | Blocked. Gemini returns 503 (high demand). Page shows "Brief pending". |
| Phone page | Live on GitHub Pages. Hero cards, track record, charts, F&O, method, pull-to-refresh. |
| Cloudflare Pages | Deployed at `market-hub-4dq.pages.dev`. **Not gated.** |
| Zero Trust gate (password) | Not started. Needs the Cloudflare free plan signup and possibly a payment method on file. |
| Multi-bagger screen | Not started. Source chosen: NSE/BSE filings, verified against Screener. Blocked on NSE access (see below). |
| News | Not built. |
| Analytical tools | 6 of the 10 you asked for. |

## To-do, in order

### A. Stop the login failures (blocking everything daily)
1. **Choose `RELAY_KEY`:** 30+ characters, letters and digits only, typed by hand.
2. **Set it in Apps Script:** Project settings → Script properties → `RELAY_KEY`.
3. **Set it in GitHub:** Actions secrets → `RELAY_KEY`. Same text.
4. **Rotate exposed secrets.** Regenerate the Kite API secret; create a new GitHub token; set both in Apps Script and GitHub.
5. **Give the GitHub token Actions permission** (Actions: Read and write), so the relay can start the run after login.
6. **Test:** run the daily job by hand. Expect the token step to pass.

### B. Make the schedule actually run
7. Confirm why GitHub's cron doesn't fire (check the repo's Actions settings and the workflow's `on:` block). If it can't be fixed, use a free external trigger, which needs the same token with Actions permission.

### C. Gemini brief
8. Decide: keep Gemini and accept "pending" during overloads, or switch to another free service. Gemini retries are already in place.

### D. Multi-bagger screen (the chosen plan: NSE/BSE filings, verified against Screener)
9. **Test NSE access first.** A request to NSE's public site hung for over two minutes in this environment. Confirm whether NSE blocks cloud or scripted requests. If it does, the plan needs a different official route (for example, BSE's own API) before anything else.
10. Build the quarterly-results fetcher (revenue, net profit, margins, return on equity, debt), storing history.
11. Build the shareholding fetcher (promoter holding and changes).
12. Build the screen: rank small and mid caps on growth, profitability, leverage and ownership. Show each stock's reasons.
13. Cross-check a sample of picks against Screener by hand. Record any mismatches.
14. Track each pick against the index over time, the same way as the forecasts.

### E. Gate the phone page (privacy)
15. Create the Cloudflare Zero Trust account (free plan). Check whether it needs a payment method.
16. Put an Access policy on `market-hub-4dq.pages.dev` allowing only your email (one-time code).
17. Turn off or limit the public `github.io` address, so the gate can't be bypassed.

### F. Analytics quality
18. Add the remaining four analytical tools (to reach the ten you asked for).
19. Backtest the F&O suggestions before trusting them. Until then, label them as unvalidated.
20. Let the track record accumulate. Do not present any horizon as beating the baseline until it does.

### G. Housekeeping
21. Remove the old `kite-login` GitHub workflow, or mark it deprecated.
22. Verify expiry weekdays in `hub/config.py` against current NSE and BSE circulars (Bank Nifty weekly expiries were discontinued, so only monthly is used there).
23. Stray files in `forecast_hub/`: `backfill.log` and a test `0` file in the parent project. Delete when convenient.

## Known problems
- Relay key mismatch causes "forbidden" at the token step.
- Scheduled runs don't fire; runs are manual.
- Browser automation here is unreliable for clicking the Run button, so use the GitHub page directly.
- The brief is blocked by Gemini's load, not by our code.
- F&O has no track record yet.
- The month-end and expiry estimates have not beaten the baseline in backtests.
- Pages on `github.io` is public. Anyone with the link can see the data.

## Decisions waiting on you
1. Gemini brief: keep Gemini (pending during overloads), or switch to another free service?
2. Privacy: accept the public `github.io` page for now, or gate it (needs Cloudflare Zero Trust and a possible payment method)?
3. Multi-bagger: go ahead with NSE/BSE once the NSE access test passes?
