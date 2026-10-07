# Changelog

Newest first. Dates are IST. "Login" covers how the Kite access token gets from your morning login into the daily job.

## 2026-10-07

### Stock library (hub/library.py, hub/parameters.py, private repo)
- Full build: a 124-parameter registry (`b6768c2`, `8fed6f3`) and a scoring engine that gives every stock a met/not-met/not-testable verdict per parameter, with the literal rule shown (`6b8d686`). Universe is every NSE EQ/BE equity (2,570 names), not just Midcap150+Smallcap250; ACC is included (`60bda68`). Output goes to the private repo `market-hub-private` (`library.json`), never the public site, since it holds BharatStock-derived figures.
- **Root cause found and fixed: the first run showed real data for only 2 of 2,570 companies.** The shared page-fetcher raised immediately on any non-2xx status, including 429, so a single rate-limit hit silently killed that company's entire entry (recorded as a bare error, not partial data). Added a 4-try backoff (2s/4s/6s) (`bc94edf`). A fast 10-company sample test (`hub/diag_library_sample.py`, `dd80108`) now checks a fix in under a minute instead of a 25-70 minute full-universe run.
- Cash-flow parameters (`cfo`, `cfo_to_pat`, `cfo_margin`, `cfo_growth`, `fcf`, `capex_to_sales`) were always "not testable": BharatStock fills `cash_flow_operating` and `capex` only on annual financial rows, never quarterly, but only quarterly data was ever fetched. Added a separate annual-financials fetch; the same fix applied to the multi-bagger screen's `cash_backed` gate, which had the identical bug (`64cdc9e`, `67db96e`).
- PE, PB, price/sales and market value added, computed free from fields already fetched (shares outstanding = paid-up equity capital ÷ face value, from the financials endpoint) rather than BharatStock's `ratios` endpoint, which turned out to be unreachable (`f9ab27e`; see below).
- Promoter holding %, and its quarter-over-quarter and year-over-year change, added from NSE's own `corporate-share-holdings-master` API — confirmed reachable from GitHub Actions, no cookie workaround needed beyond a plain homepage GET first (`8d3a1f3`). Revised/duplicate filings for the same quarter are de-duplicated by broadcast date before computing change.
- BharatStock's `shareholding`, `ratios` and `corporate-actions` endpoints 429 on every attempt, with or without backoff — not a burst issue, almost certainly not included in the current plan tier. Flagged for the owner to check; not guessed around.
- Dashboard: added pagination to the Library tab (100 per page, 1–2,570) (`f438aab`), and the stock-detail panel now shows the actual error text for a failed company instead of a blank panel (`268b835`).
- **BharatStock's daily quota (10,000 requests, plan "developer") was fully exhausted** by the day's testing — confirmed via the 429 response body itself (`{"message": "Daily rate limit of 10000 requests exceeded...", "resets_at": "2026-10-08T00:00:00+00:00"}`), not guessed. A fast 10-company test (`hub/diag_library_sample.py`) caught this in under two minutes instead of discovering it 70 minutes into a full run.
- **Resumable batching, chained automatically.** Even on a healthy quota, one GitHub Actions run cannot finish the ~2,570-company universe once real calls are happening instead of instant-failing (about 300 fit in the 70-minute time budget). `hub/library.py` now reads `cursor_next` from the last published `library.json`, resumes from there, and merges its batch into the prior stocks instead of overwriting the file. `library.yml` dispatches itself again via `GITHUB_TOKEN` (permission confirmed with a one-hop test first) until a full pass completes — no more waiting a week between Saturday cron fires. A one-time schedule entry fires the first clean batched run at 00:05 UTC / 5:35 AM IST on 2026-10-08, right after the quota resets.
- Promoter data taken one step further, all free from NSE, no BharatStock dependency: `public_float` (NSE's summary API already returned it alongside promoter %, just wasn't read), and `fii_holding`/`dii_holding`/`pledge_pct` from each filing's detailed XBRL (confirmed field names against a zero-pledge company and a company with an active pledge — the zero case is a boolean flag in the filing, not an omitted fact treated as a guess).
- `dividend_yield` and `buyback_flag` added from NSE's corporate-actions feed (free text subject lines like "Dividend - Rs 6 Per Share", parsed with a regex; a subject that doesn't match is skipped, not guessed).
- Trend parameters added on the same free NSE data, reusing filings already fetched: `promoter_holding_change_3q` (no extra fetch at all), `fii_change_qoq`/`dii_change_qoq`/`pledge_change` (one extra XBRL fetch for the previous quarter and a year-ago filing, via a new `institutional_targets()`).
- **Named-holder extraction and investor-registry matching.** NSE's XBRL shareholding filing discloses public shareholders above the 2-lakh nominal-value threshold by exact legal name and share count -- confirmed the SEBI taxonomy gives these a distinct element name from promoter-family members (a real filing with both in the same document parses correctly, so a promoter's spouse is never picked up as an independent public holder). Matching against `hub/registry.json` is name + word order (tolerates a filing's middle name, no fuzzy spelling correction) and is evidence to review, never an automatic confirmation: `registry_holders`/`registry_new_entrants` only count investors whose registry status is already `confirmed` (all 23 are `unconfirmed` today, so these are honestly 0 everywhere until reviewed). Every match is published as a per-symbol review list (`investor_matches`) and shown on the admin dashboard's Registry tab. `holder_count_change` and `top10_holding_change` added from the same already-parsed holder lists, no new fetch.
- Refactored the XBRL reader so institutional facts and named holders share one download of the same filing instead of fetching it twice.
- `holder_count_change` and `top10_holding_change` added from the same already-parsed holder lists (no new fetch): change in the number of publicly disclosed (>2-lakh) holders, and change in the ten largest disclosed holders' combined stake.
- `sector_news_count` and `regulatory_events` closed via Google News' public RSS search, computed once per sector (17 NSE sectors) per batch and shared across every company in it. PIB's own RSS turned out to be Hindi-only and not ministry-specific (tested live, dead end). Coarse and keyword-based, not backtested — real and verified to discriminate across all 17 sectors (7–100 for news, 6–97 for regulatory), but the pass/fail thresholds are a written judgment call.
- Parameter registry coverage: 74 → 101 of 124 parameters now have a confirmed source. What's left (`dividend_paid`, `sector_ret_3m`, BSE-only companies) either needs BharatStock's quota to reset or a structurally blocked source.

### Phone app (docs/index.html)
- FII/DII institutional-flow panel didn't say whether the figure was live or stale. It's NSE's own provisional figure for the previous session's settled cash-market trades, published once a day, not live — the date was already in the data but discarded when reducing to net values. Now shown in the panel header (replacing a redundant "₹ crore" label, since each row already shows "cr"), with a one-line note underneath.

### Admin dashboard (relay/Admin.gs, private, email-code login)
- Built from scratch: six-digit email code (ten minutes, one per minute), six-hour session, tabs for Status/Library/Parameters/Registry/Bulk deals/Back-tests (`ba7aa98`, `c428b7c`). Data read from the private repo via a Contents-API read-only token, not the legacy Drive relay (`3072e0d`, `4f75dd6`).
- Library tab: search, sort, minimum-met/minimum-data-quality filters, filter by one parameter's result (`78a171b`); fixed a quoting bug that broke the whole page's script (`33b3957`).
- Visual redesign: color palette, card layout, status badges (met/not-met/not-testable/available/gap color-coded), proper toolbar (today, unlogged commit — see `relay/Admin.gs`).

### Daily job fixes
- Admin-summary publish step was still reading the old relay environment variables after the switch to the private-repo publisher; fixed to pass `PRIVATE_REPO_TOKEN` (`08f2f11`).
- **Stale intraday price lock-in.** If the Kite-login trigger fires the daily job mid-session (owner logging in before 15:30 IST close), Kite's "today" candle is a partial-day value. The old incremental price-fetch logic stored it under today's date and never revisited it, because the next run's starting point always moved past any date already present — the wrong mid-session value for SENSEX would have stayed final forever. Fixed: today's entry is dropped and re-fetched every run, so it only becomes final once a run actually happens after the close (unreleased fix, `hub/sources/prices.py`).
- NIFTY/BANKNIFTY bhavcopy confirmed working as intended: it shows the latest *published* trading day, which lags by one day until NSE releases the current day's file after close — not a bug.

### Multi-bagger (hub/multibagger.py)
- ACC exclusion removed; every NSE EQ/BE equity scored (`60bda68`).
- 70-minute time budget with checkpoints every 200 companies, so a run near the 90-minute job limit never loses all its work (`9be621d`).
- Same 429-retry and annual-financials fixes as the stock library, since both share `hub/multibagger.py`'s fetch functions.

### Bulk deals and investor registry
- Daily bulk-deal collector from NSE's archive CSV; client names are kept only when they match a `status: confirmed` registry entry, otherwise stored as `OTHER` (`e17354e`). No free historical source exists, so history only accumulates from 2026-10-06 forward.
- Investor registry seeded with 23 researched "marquee investors," all `status: unconfirmed` until a filing or bulk-deal match confirms one.

## 2026-10-06 (late)

Changes since the night entry. Commit references are on `main`.

### Multi-bagger (hub/multibagger.py, docs/data/multibagger.json)
- New screen for Midcap 150 and Smallcap 250 names, on BharatStock quarterly financials. Gates: revenue growth above 10%, profit growth above 15%, profit growth in at least 6 of the last 8 quarters, operating cash at least 0.8 times profit. A gate with missing data is listed as a gap, never a pass. Publishes derived scores and gates only. (`f46f6e8`)
- Derived promoter trade signal from insider trades (signal only, not a gate). (`2da32a3`)
- Mutual fund counts per stock: schemes holding, added, reduced. No scheme names are published. (`26966bc`)
- Multi-bagger tab in the phone app. (`1e529c0`)
- Back-test: manual workflow, summary statistics only (`e6df6f7`, summary in `f2c43c7`). Financials are used 60 days after quarter-end, so no later information leaks in. Caveat: survivorship bias from today's index members.
- BharatStock test workflow removed once the screen was verified (`e3476b1`).

### Indicator test (hub/indicator_test.py, manual workflow)
- Tests NIFTY and BANK NIFTY direction signals over five sessions. The first 60% of history selects, the last 40% tests. A signal is listed as shown to work only if it beats the baseline on both halves with a z above 1.64 on the test half. (`a0e2595`, summary `63f6e68`)
- Kite history is fetched in chunks under the 2000-day limit. (`dfd7e16`)

### IV-rank threshold test (hub/threshold_test.py, IV history)
- IV history extended: Aug 2023 to Jul 2025 prepended (`9b5a30b`), and 20 Aug to 6 Oct 2026 appended from NSE bhavcopy (`89e2609`). Both list and dict file formats are read.
- Threshold test: breach rates and average premium by IV-rank band and threshold (20, 30, 40, 50, 60), selection and test halves. Summary only. (`1832fa2`, `02705e4`, `e3ca6c0`)

### Nifty 50 option screen (rg/, F&O tab)
- The delivery-rule rejection now states the exact reason for each name. (`a186fe2`)
- Estimated results dates no longer block a trade; they are shown as "results date not confirmed". Confirmed dates still block. (`5e354cc`)

### Daily job (.github/workflows/daily.yml)
- Save step rebases and retries if main moved during the run. (`d9a29f3`)

### Option-close research (not in the repo)
- Spread simulation on NSE option closes, Aug 2023 to Oct 2026: 4,521 trades, average return on risk −5.1%, win rate 57.6%. The IV-rank 30 gate did not separate outcomes. Put spreads are the weak side. Results are in the scratchpad, not published. Limits: closing prices, assumed 10% slippage, one structure, overlapping trades.

## 2026-10-06 (night)

Changes since the evening entry. Commit references are on `main` unless noted.

### Phone app (docs/index.html)
- Brief tab rebuilt as a graphic summary: six tiles (gold, crude US$, USD/INR, India VIX, S&P 500, Bitcoin US$), bars for moves, bars for FII and DII cash flows, and the written brief behind a toggle. Index figures are not repeated, since the ticker shows them. (`e425bd7`, `7688e84`, `08d582f`)
- Settings is a gear icon only. The logo is larger (44 px). The top bar clears the phone's status bar. Quote figures are bolder. (`e425bd7`, `16221e5`)
- Tab bar: icons with labels (Home, Brief, F&O, Desk). (`16221e5`)
- F&O tab now shows the Nifty 50 stock option screen under the index suggestions: a summary, the trades (if any), why names were rejected, and the rejected names grouped by reason. (`5d1919a`)
- Gold, crude, USD/INR and India VIX redraw on each live quote, using the relay values when present and the daily snapshot otherwise. (`1027f76`)
- Bitcoin US$ from CoinGecko's public API (no key), refreshed with the quotes. (`08d582f`)
- Tile text wraps, so dates are not clipped. (`08d582f`)

### Market data (hub/context.py, hub/sources/commodities.py)
- USD/INR live from Kite's nearest currency future (CDS), with the ECB reference rate as fallback. (`95df99d`)
- India VIX from Kite. (`7688e84`)
- WTI from Alpha Vantage (`a72fc4c`). Its latest price is 29 Sep 2026, so it is no longer on the page.
- Crude in US$ for today, derived as MCX crude (₹/bbl) divided by the live USD/INR rate. It is labelled as derived. (`027d32a`)
- Alpha Vantage free tier: 25 requests a day and 5 a minute. The daily run uses one request. Each manual run also uses one.

### Relay (Apps Script)
- Quote endpoint now also returns gold, crude and USD/INR contracts (nearest expiry, from Kite's public instrument lists, cached 6 h) and India VIX. (`1027f76`)
- New version deployed by the owner (version 5, Manage deployments). Checked: the live quote returns the extra fields.
- The web address is unchanged.

### Nifty 50 option screen
- Merged from `stocks-port` into `main` (`5c5419c`), after resolving conflicts in the daily workflow, `.gitignore` and the generated data files (main's versions kept).
- Live run on `stocks-port` (run 37477650063): all steps passed; 0 trades; most names blocked by earnings inside the contract window.
- Open: the IV history still ends on 19 Aug 2026, so the IV-rank check uses old data. The August 2025 to today pass is still to do.

### Multi-bagger screen (not on `main`)
- Still ranks on data to March 2025. The NSE structured results feed stops at December 2024, so the June 2026 quarter must come from the result PDFs.
- Pilot: ACC's June-quarter board outcome is a readable text PDF. The pilot (20 names) is running in the background; the match rate will be reported when it finishes.
- The dedicated agent was rate-limited and is now resumed with the June 2026 target, the pilot, and a management-direction section (board and shareholder meeting outcomes).

### Owner decisions recorded
- Earnings gate on the Nifty 50 screen: kept.
- Multi-bagger Core rule: loosened version kept (no failed gate and at least four passes).
- Multi-bagger local data: excluded from git (`7c69a8f`).
- Crude: real time from MCX, converted at the live rupee rate. No free same-day WTI source yet.

### Still open
- Multi-bagger: June 2026 parser, pilot match rate, Screener cross-check, then all 401 names.
- Nifty 50 screen: IV history from Aug 2025 to today, and the backtest on it.
- Same-day WTI: no free source yet.
- US indices: one day old (FRED).
- Kite login each morning, before the 16:30 run (owner).
- Confirm the relay setup check with the real key in the next daily run.
- Confirm the trade-row fields in the F&O tab against the first real trade.

## 2026-10-06 (evening)

Five changes since the last changelog update.

### Phone app (docs/index.html)
- Bottom tab bar now has icons with labels (Home, Brief, F&O, Desk). The icons are inline SVG, so nothing new loads.
- The header clears the phone's status bar and notch (`env(safe-area-inset-top)`), so the top bar is no longer partly hidden.
- The logo is back in the header.
- The status line is readable normal text, not small grey monospace, and it can wrap.

### Relay (Apps Script)
- Setup check (`mode=check`) now requires the key. Without it, the relay returns only `{"error":"forbidden"}`. Commit `814e291`; a duplicate `relayKey` declaration was fixed in `5831f83`.
- The new code was pasted into the Apps Script editor and deployed as a new version, by the owner, through Manage deployments. The URL is unchanged. Checked: the relay returns "forbidden" without a key and still serves quotes.

### Nifty 50 option screen (stocks-port branch)
- Pushed to `stocks-port` (`cd10281`) by the owner from the agent's worktree. `main` is unaffected.
- Live run on `stocks-port` (run 37477650063) passed every step. Mode: live, India VIX 13.61, universe 50 names.
- Result: 0 recommendations, 50 rejected. Most rejections come from earnings falling inside the contract window (results season, expiry 23 Nov 2026). The screen's rule is to avoid earnings inside the cycle.
- Open: the IV history still ends on 19 Aug 2026, so the IV-rank check uses old data.
- Decision for the owner: keep the earnings gate as it is, or loosen it.

### Still open
- IV history from August 2025 to today.
- Multi-bagger screen: owner decisions on the Core rule (loosened, kept), PDF parsing for results after December 2024, and excluding the 105 MB data folder from git.
- Kite login each morning (owner).
- Confirm the relay's setup-check output with the real key in the next daily run.

## 2026-10-06 (later in the day)

### Prices and the daily job
- **Official closes.** NIFTY and BANK NIFTY closes now come from NSE's official daily index file. Kite is used only for SENSEX and for live quotes. The old source used Kite's day candle, which could hold a mid-session value.
- **Wrong closes corrected.** The job had stored 22,687.0 (NIFTY) and 55,179.45 (BANK NIFTY) for 6 Oct. Official closes are 22,776.10 and 55,128.40. The wrong closes and the predictions built on them were removed, and the next run rebuilt them.
- **Run time moved to 16:30 IST** (cron `0 11 * * 1-5`), after the close and after NSE publishes the file. It was 15:45 IST before.
- **Relay token step fixed.** An edit had dropped `-L` from curl, so the relay's 302 redirect was not followed and the run failed. Restored in commit `1e7700f`. Run 37469038868 failed for this reason.

### Brief
- Adds FII/DII cash flows (NSE), USD/INR (ECB reference rate), S&P 500, Dow, Nasdaq and WTI crude (FRED, needs the `FRED_API_KEY` secret), MCX gold and crude futures (Kite), and news headlines (RSS).
- New prompt with fixed sections. It says "not available today" rather than filling gaps.
- Each index's estimate is compared with the actual close, and the brief says whether the close fell inside the range.
- The brief now has its own tab.
- Model output limit raised to 6,000 tokens (`max_tokens`).

### Relay (Apps Script)
- Added `mode=check`, a setup check that reports which script properties are set, their lengths, and whether the key matches. It never returns values.
- The token response now names the exact failure: RELAY_KEY not set, key mismatch with both lengths, or no token for today with the stored date.
- The token step in `daily.yml` prints the same diagnostics (names, lengths and HTTP codes only) before fetching the token.
- **Open:** `mode=check` is public. It reveals which properties exist and their lengths, not their values. It should require the key. This is not yet fixed in the deployed script.

### Phone app (docs/index.html)
- Settings gear on the home page. It holds the Kite login link and a note on the 2FA step. The 2FA code is not entered in the app, and no password is stored.
- Layout rebuilt as a desk-style app: ticker strip, one panel per index, four bottom tabs (Home, Brief, F&O, Desk), no horizontal scrolling.
- Track record, method and the NIFTY chart moved to the Desk tab. Band-multiplier and tool-weight charts removed.

### Research
- **IV-rank test (copied history, Aug 2025 to Aug 2026).** Breach rate, the share of 21-day moves beyond one standard deviation of implied, was 35% at IV rank below 30 and 13% at 70 and above. One year only, overlapping windows, and ATM IV rather than spread prices. Not conclusive.
- **IV backfill** for 1 Aug 2023 to 31 Jul 2025 from NSE bhavcopy, running in scratch space. Not yet merged into the live `iv_history/`. A final pass from Aug 2025 to today is still needed.

### Nifty 50 option screen (not pushed)
- Ported from `rg_option_selling` into `rg/`, with `hub/stocks.py` and `STOCKS.md`. Lives in worktree `agent-adbbfe36a8ef347ea`, branch `worktree-agent-adbbfe36a8ef347ea`, uncommitted.
- Offline replay on the 19 Aug 2026 chain ran cleanly: 2 recommendations from 50 names. The live Kite path has not run.
- The push to `stocks-port` was blocked by the safety check (copied data folders flagged). Waiting on the owner.
- The copied IV and price history end 19 Aug 2026, so the screen is not on current data yet.

### Multi-bagger screen (in progress, not pushed)
- Worktree `agent-aeb30a28c5495613a`. Has `hub/multibagger/` with collection, NSE client, screen and Screener cross-check modules. No method note or test report yet.
- Parameters changed to a two-list design: a core list with practical gates, and an early list for inflection signals. The back-test is still to run.

### Still open
- Push the brief, settings and layout changes (on `main`, pushed).
- Paste the relay setup-check change into Apps Script and deploy a new version.
- Require the key for `mode=check`.
- Confirm the redirect URL in the Kite developer console.
- Start a run to check gold and crude and the new closes.

## 2026-10-06

### Login (Kite) changes, in order
1. **Client ID fixed.** The Active Kite app had no Zerodha Client ID, so Kite answered "user is not enabled for the app". The field is now `EZQ363`. A partial value (`EZQ36`) had been saved earlier and was corrected.
2. **Redirect URL moved to the relay.** The Kite app's redirect URL points to the Apps Script web app (`/exec`), not to the GitHub Pages `kite.html` page. The Kite login now lands on the relay, which exchanges the one-time `request_token` for the access token.
3. **Relay stores the token.** The relay saves `KITE_ACCESS_TOKEN` and `KITE_TOKEN_DATE` in Apps Script's private properties. The token never goes into the public repo or public pages.
4. **Daily job fetches the token from the relay.** Each run calls `?mode=token&key=RELAY_KEY`. If the key doesn't match the relay's `RELAY_KEY`, the relay returns `{"error":"forbidden"}` and the run fails at the token step. This happened in runs #3, #7 and #8 and again in #12, before the key was re-entered.
5. **Relay quote endpoint.** `?mode=quote` returns NIFTY, BANK NIFTY and SENSEX last price, previous close and change. It is public by design and never returns the token. Results are cached for 10 seconds. The phone page reads it on every refresh and falls back to a saved file if the relay is unavailable.
6. **Auto-start after login not working.** The relay tries to start the daily run with `GH_PAT`, but that token lacks **Actions: Read and write**, so it reports "daily run did not start". The 15:45 schedule still runs the job, but GitHub's scheduler has not fired it in practice. Runs so far were started by hand.
7. **Old GitHub-side login still present.** The `kite-login` workflow (paste a token into GitHub) still exists. It is no longer the intended path.
8. **Key exposure.** On 6 Oct, a screenshot of Apps Script's script properties showed the Kite API secret, the GitHub token and the relay key in full. The secrets should be rotated. Rotation is not confirmed.
9. **Key format.** `RELAY_KEY` values containing special characters (such as `$`) were the likely cause of the mismatch. The advice is letters and digits only, typed by hand into both places.

### Hosting and pages
- Phone app moved to a clear dashboard. Desktop shows the three indices side by side with today's estimate in the hero cards. Detail tables stack below.
- Service worker is now network-first, so the phone gets the newest page when online. The cache is only a fallback.
- Pull-to-refresh added. Dragging down from the top reloads forecasts, quotes and F&O.
- Quote label changed from "Live" to "Quotes as of [time]", because the data was not tick-by-tick.
- Cloudflare Pages deployment created at `market-hub-4dq.pages.dev`. It is **not gated yet**.

### Forecasting
- Bank Nifty added: config, live quotes, forecasts, F&O.
- Year-end horizon hidden on the page (the engine still computes it).
- Month-close now shows the range only, with no point call. The backtest showed the month model is no better than the "last close" baseline.
- Today's close estimate added to the feed and the hero card. It is an estimate from the prior close, not a stored pre-open record.

### F&O
- F&O module added (`hub/fno.py`): iron condors and directional spreads for the nearest and monthly expiries, using the forecast bands.
- Fixes after review: same-day expiry skipped, directional calls only on tight bands (≤1.5% half-width), iron condor requires credit ≥10% of wing width and short premiums ≥ ₹5.
- Data-only chain added for an expiry that settles today (±3% of spot, no trade suggestion).

### Daily brief (Gemini)
- Brief module added (`hub/narrate.py`). Model changed from `gemini-2.0-flash` (404) to `gemini-2.5-flash` (404: no longer available to new users) to `gemini-flash-latest`.
- Brief failures no longer stop the job. Retries on 429/503 with backoff.
- Gemini is currently returning 503 (high demand). The page now says "Brief pending" instead of showing the raw error.

## Earlier (summary)
- Forecast engine: six analytical tools, learned weights and bands, backtest, tracking.
- Hosting on GitHub Pages; daily job and manual triggers; feed JSON.
- Kite login via GitHub workflow (`kite-login`) and the `kite.html` redirect page; daily token paste.
