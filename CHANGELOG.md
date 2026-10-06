# Changelog

Newest first. Dates are IST. "Login" covers how the Kite access token gets from your morning login into the daily job.

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
