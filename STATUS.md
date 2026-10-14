# Build status and to-do

As of Wed 14 Oct 2026, ~14:10 IST. Read the HANDOVER below first, then `CHANGELOG.md` (newest first) and `CLAUDE.md`.

## HANDOVER -- Wed 14 Oct 2026, for a new Claude session (e.g. the owner's second laptop)

**Start here (in order):**
1. Accounts: only Google `ramghatagedb1101@gmail.com`, GitHub `ramghatagedb1101-NSEFO`. The `gh` keyring on the
   owner's machines also holds `ramghatage-ux` and the *active* account can flip to it (it did on 14 Oct and a push got
   403). Never switch it globally; name the account in every command (see CLAUDE.md "Making changes"):
   `export GH_TOKEN=$(gh auth token -u ramghatagedb1101-NSEFO)` then check `gh api user --jq .login`.
   If that account is not logged in on this laptop: the owner runs `gh auth login` and picks ramghatagedb1101-NSEFO.
2. `git status` (tell the owner before touching anything uncommitted), then pull with rebase (CLAUDE.md command).
3. Market days: **no relay push (`relay/*`) between 09:15 and 15:30 IST** (pushing relay files deploys at once).
   Python/workflow changes are safe any time; `daily.yml` runs at 18:00 IST and right after each Kite login.
4. Clasp on a new laptop is not needed: relay deploys from GitHub (`relay-deploy.yml`). Run `node relay/check.js`
   (check its exit code) before every relay push.

**Done today (all pushed, details in CHANGELOG 14 Oct 2026):**
- Kite audit fixes (commit 24be95d): one paced Kite client for every job (`hub/sources/kite.PacedKite`, also used by
  `rg/market_data.get_kite`): quote calls >= 1.05 s apart, "Too many requests" retried, quotes split at 500,
  instrument lists downloaded once a day (`.cache/kite_instruments/`). Expiry calendar from Kite's contract lists
  (`hub/expiries.py`; fallback `config.EXPIRY_RULE`: NIFTY weekly Tue, SENSEX weekly Thu, BANK NIFTY monthly last Tue;
  the old `EXPIRY_WEEKDAY` had BANK NIFTY Wed and SENSEX Mon). F&O chains read once; theta legs in one quote;
  `expiry-theta.yml` now Mon+Tue (NIFTY expires Mon 19 Oct and Mon 9 Nov 2026). Verified on GitHub: daily run
  38500211113 (no Kite refusals, nearest NIFTY expiry 2026-10-19).
- BharatStock shared budget (`hub/bs_budget.py`, ledger `state/bs_usage.json` in the private repo): library counts the
  other jobs; manual `multibagger.yml` and `backtest-multibagger.yml` stop at what is left of 9,000 (the back-test had
  no limit). BharatStock reports no usage (probe 14 Oct: no headers, no endpoint), so the count is ours.
- Expiry history kept in full: `state/expiry_history/records.json` (399 expiries: NIFTY 159, BANK NIFTY 82, SENSEX 158,
  Oct 2023 - Oct 2026), raw chains in `state/expiry_history/chains/<INDEX>_<YEAR>.json` (+-5% of spot, day before,
  two days before, next expiry), `summary.json`. Records are never dropped (older layouts kept until replaced).
  Analyses: `hub/expiry_history.py` (workflow `expiry-history.yml`, manual; NSE + BSE), `hub/expiry_patterns.py`,
  `hub/expiry_rules_test.py`.
- Findings (CHANGELOG 13-14 Oct): walls/max pain from the evening before do not beat the open as a point forecast for
  any index, even with per-index rules; real patterns: BANK NIFTY pins to max pain when the open is near it; SENSEX
  walls act as intraday barriers; NIFTY moves away from max pain from the previous close; expiry straddles overpriced
  (sellers keep 11-17%). Live meter starting weights = history fit (relay Version 65: NIFTY 0.18/-0.13/0.17,
  BANK NIFTY -0.23/0.19/0.04, SENSEX 0.18/0.10/-0.13).

**Also done today, same session continued (commits 259b09b pushed; 18f4960 and the push-notification
commit local-only, held for market hours -- see "Next up" below for exact state of each):**
- Removed the one-off `hub/diag_quota_headers.py` probe; kept `diag.yml`'s `BHARATSTOCK_API_KEY` line
  (two other diag modules need it) and fixed its comment.
- Relay counts its own BharatStock calls (`relay/Code.gs`'s `bsCount_`/`bsUsage_`, `?mode=bs_usage`;
  counted in `Report.gs`, `Funds.gs`, `Research.gs`). Code done, **not deployed** (market hours).
- Market Hub push notifications: phone app (`docs/sw.js`, `docs/index.html` Settings), relay
  (`relay/Push.gs`, new file), sender (`hub/push.py`, `kite-reminder.yml`). Code done, phone app half
  verified in a static preview; relay half **not deployed** (market hours); sender **not run** (needs
  the owner's VAPID keys first). Full detail in "Next up" 1 below.

**Owner decisions on record:**
- Range calibration (a quarter narrower at the right hit rate on history): **wait for a few recorded expiries first**;
  then compare the live range's hit rate (state/expiry/) before changing it.
- Kite login reminder must come **from the Market Hub app** on the owner's **iPhone**, not from Claude. Switch off the
  claude.ai routine "Kite login reminder" (`trig_011gp21txucmWGZPKqpR2FEu`) **once a Market Hub push has reached the
  phone** (owner said yes). It ran today at 07:37 and "sent" a Claude-app push that never arrived.

**Next up -- build in this order:**
1. **Market Hub push notifications (iPhone PWA) -- code done 14 Oct, ~14:10 IST. Three things left, all
   the owner's: generate VAPID keys, add two GitHub secrets, and test on the phone (below).**
   - `docs/sw.js`: `push` handler (`showNotification` with title/body/icon, `data.url`) and
     `notificationclick` (always opens a new tab at `data.url` -- the Kite login link is an external
     site, same as the in-app button's `target="_blank"`, so focusing an already-open Market Hub tab
     instead would silently do nothing useful). Cache bumped to v31.
   - `docs/index.html` Settings: "Turn on notifications" button, wired to `refreshPushUi()` (checks
     support, an existing subscription, and `navigator.standalone === false` specifically -- iOS Safari
     not opened from the Home Screen -- to show "Add Market Hub to the Home Screen first (Share → Add to
     Home Screen), then open it from there" instead of a confusing failure) and `togglePush()`
     (`Notification.requestPermission()`, then `pushManager.subscribe({userVisibleOnly, applicationServerKey})`
     with the key from `app_push_key`, then `app_push_subscribe`). Stale text fixed too ("before the
     16:30 run" -> "after 07:35 and before 09:05 IST"). Verified in a plain static preview (gate overlay
     hidden via devtools, not a real sign-in): the button renders, `refreshPushUi()` runs with no
     console errors and correctly reports "no subscription yet" in a browser that supports the APIs.
     Real push delivery needs the owner's actual phone -- not something this preview can exercise.
   - `relay/Push.gs` (new file) + `Code.gs`/`Admin.gs` wiring: `app_push_key`/`app_push_subscribe`/
     `app_push_unsubscribe` (session-gated, routed through the existing `appApi_`), key-protected
     `push_state` (subscriptions + `kiteStatus_().state` + login link, for `hub/push.py`), `push_key`
     (POST: the sender workflow stores the public key here from its own secret -- the owner never opens
     Apps Script's script-properties page), `push_drop` (POST: drops endpoints Web Push reports gone).
     `PUSH_SUBS` script property, de-duplicated by endpoint, newest 5 kept. `node relay/check.js` clean.
     **Not deployed**: committed locally, held for the market-hours rule (same as item 2 above) -- push
     after 15:30 today, alongside item 2's commit.
   - `hub/push.py` + workflow `kite-reminder.yml` (cron 02:06 and 03:03 UTC = 07:36 and 08:33 IST,
     Mon-Fri; `workflow_dispatch` with `mode=test` skips the holiday/already-logged-in checks): skips NSE
     holidays (`is_nse_holiday()`, NSE's own `holiday-master` API, same Akamai-cookie session as
     `hub/shareholding.py` -- **untested against a live response**, NSE blocks the laptop; fails toward
     *not* skipping on any error, since an occasional reminder on a holiday is a minor nuisance and a
     missed one on a real trading day is not), skips if Kite is already logged in today, sends "Log in to
     Kite" (tap opens the Kite login link) with `pywebpush`, drops 404/410 endpoints back to the relay.
     `pywebpush>=2.0` added to `requirements.txt`. Syntax-checked (`py_compile`); **not run end to end**
     (needs real VAPID keys and a real subscription -- can't be tested until the owner's steps below).
   - **Owner, next (never hand Claude the private key):**
     1. `npx web-push generate-vapid-keys` (on their laptop or any machine with Node).
     2. Add GitHub repo secrets `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` from that output.
     3. Open Market Hub from the Home Screen (Add to Home Screen first if not done), Settings, tap "Turn
        on notifications", allow when iOS asks.
     4. Run `kite-reminder.yml` manually with `mode=test`; confirm the notification arrives and tapping
        it opens the Kite login page.
     5. Only after that's confirmed: disable the claude.ai routine ("Kite login reminder",
        `trig_011gp21txucmWGZPKqpR2FEu`, `RemoteTrigger` update `enabled=false`).
2. **Code done 14 Oct, ~13:20 IST -- not deployed yet (market hours).** Relay counts its own BharatStock
   calls: `bsCount_(n)`/`bsUsage_(p)`/`utcDay_()` added to `Code.gs` (script property `BS_USAGE`
   `{date_utc, requests}`, reset on a new UTC day); `?mode=bs_usage` routed in `doGet`, key-protected like
   `handleCheck_`, returns `{date, requests}` -- matches `hub/bs_budget.relay_used()` exactly (already
   written, already calls this, already treats a missing/wrong-day response as 0). Counted at every real
   BharatStock fetch: `Report.gs` (`adminStock`: 2 upfront for fin+fina if the key is set, 1 per
   quarterly-pagination page), `Funds.gs` (`adminFunds`: 1 per mf-holdings page), `Research.gs`
   (`bsChart_`: 1 per prices page). `node relay/check.js` clean (exit 0): all files parse, no name clashes,
   all 22 `AdminPage.html` server calls still resolve. **Committed locally, not pushed** -- CLAUDE.md's
   market-hours rule (no `relay/*` push 09:15-15:30 IST; it deploys at once). Push after 15:30 today.
3. **Done 14 Oct**, ahead of item 2 (no real dependency between them -- `diag_quota_headers.py` was a
   finished one-off probe, not something item 2 needed first). The `diag.yml` key line stayed: two other
   diag modules still use it. See group A3 below.
4. Audit item left open by design: `rg/market_data.py` still sends one quote call per stock chain (~100 a run, now
   paced, so ~2 min); batching several stocks per 500-instrument call would shorten the run (optional).

## NEXT STEPS -- the full list (Wed 14 Oct 2026; replaces the 9 Oct "To-do, in order" further down)

Grouped by what each step waits for. "Build" items are detailed in "Next up" above.

**A. Build now (approved by the owner)**
1. **Code done 14 Oct** (phone app + relay + sender workflow); relay half not deployed yet (market
   hours). Owner still needed for VAPID keys, two GitHub secrets, and the on-phone test ("Next up" 1).
2. **Code done 14 Oct, not deployed** (market hours block `relay/*` pushes until 15:30 IST -- see "Next up" 2).
3. **Done 14 Oct.** Removed the one-off `hub/diag_quota_headers.py`. Its `BHARATSTOCK_API_KEY` line in
   `diag.yml` stayed -- `diag_library_sample.py` and `diag_shareholding.py` both still need it; only the
   comment was wrong (named the deleted module), fixed to name the two real users.
4. Optional: batch several stocks per quote call in `rg/market_data.py` (shorter daily run; "Next up" 4).

**B. Owner actions**
1. Thu 15 Oct 2026: log in to Kite between 07:35 and 09:05 IST (first live SENSEX expiry with the walls record).
2. **Push notification code is ready (14 Oct)**: run `npx web-push generate-vapid-keys`, add GitHub secrets
   `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`, open Market Hub from the Home Screen and tap "Turn on
   notifications"; run `kite-reminder.yml` manually with `mode=test`, confirm it arrives and opens the Kite
   login page. Then the claude.ai "Kite login reminder" routine is switched off.
3. Still open from 6 Oct: rotate the credentials that were exposed then (owner's call; never done by Claude).
4. Optional: a weekly copy of the private repo onto the laptop as a second backup (offered 14 Oct, not decided).

**C. First live checks of today's changes (next few days)**
1. Once A1/A2 are pushed and deployed (after 15:30 today): open the dashboard's stock report / mutual
   funds / price chart once each (exercises `Report.gs`/`Funds.gs`/`Research.gs`), then check `?mode=bs_usage&key=...`
   returns a non-zero `requests` for today -- confirms the relay's own BharatStock counting is live, not
   just committed. Separately: `is_nse_holiday()` in `hub/push.py` has never run against a real NSE
   response (laptop-blocked); the first `kite-reminder.yml` run (test or scheduled) is the first real
   check that it parses `holiday-master`'s shape correctly -- read its log once.
2. Thu 15 Oct 06:15 library run: `state/bs_usage.json` appears in the private repo with the library's count
   (relay counts 0 until A2); tracker shows `others_today`.
3. Thu 15 Oct 18:00 daily run (and the post-login run): no Kite refusals, F&O expiries right (SENSEX expiry horizon
   targets Thu, BANK NIFTY Tue 27 Oct).
4. Mon 19 Oct 2026 (NIFTY's holiday-moved expiry): `expiry-theta.yml` runs on Monday and finds the expiry; the meter
   opens on NIFTY; `expiry-tape.yml` saves `state/expiry/2026-10-19_NIFTY.json`.
5. After every expiry day: the day file exists in `state/expiry/` (if not, re-run `expiry-tape.yml` before ~21:30 IST),
   and the track record shows the meter against the forward.

**D. Waiting for data (do not build before the data exists)**
1. After 3-5 recorded expiries per index: decide the range calibration (history: about a quarter narrower at the right
   2-in-3 hit rate; owner chose to wait). Compare the live +-1 sd range's hit rate first (`hub/expiry_rules_test.py`
   logic on `state/expiry/` days).
2. After ~10 recorded expiry days: test wall movement within the day (rolls, reinforcement, abandonment) -- only our own
   record has it; check whether BANK NIFTY's near-max-pain pin and SENSEX's wall barriers also show within the day;
   re-fit the meter's weights on live readings.
3. Monthly (first: mid-Nov 2026): re-run `expiry-history.yml` (fetches only new expiries), then
   `hub/expiry_patterns.py` and `hub/expiry_rules_test.py`; re-test the BANK NIFTY / FII net index puts candidate
   (monthly expiries only, so slow).
4. Expiry theta: 50-100 settled sessions before any thought of more than 1 lot (`state/expiry_theta_log.json`).
5. Forecast track record: 20 settled outcomes per horizon before the app shows a verdict.
6. `sector_pe_vs_history`: 8 weekly observations (started 8 Oct; about early Dec 2026).

**E. Watch (outside events)**
1. SEBI circular on expiry settlement (expected Oct 2026): if it returns to a 30-minute average, set `EXP_SETTLE` in
   `relay/Expiry.gs` to `method: 'average'` with the window it names (built and tested, switched off).
2. Exchange expiry calendar changes and holidays: followed by themselves from Kite's lists now; nothing to do unless a
   check in C fails.
3. Since the closing auction (Aug 2026) NIFTY's close sat between the walls 4 of 10 expiries vs ~6 expected: keep an
   eye on it as expiries accumulate.

**F. Not started, by design (groundwork first)**
1. ROCE gate on the multibagger screen (needs clean 3-year annual ROCE in BharatStock's responses).
2. Adaptive band-learning step in the forecast engine (`hub/engine.py`; through `hub/backtest.py` first).

**G. Still unverified (check when convenient)**
1. Phone sign-in tested on the phone itself (the owner has used the phone app since 8 Oct, so likely fine).
2. Admin dashboard: reopening the tab within six hours stays signed in.
3. Position tracker: a full live run.
4. BharatStock field-name guesses (`dividend_paid`, volume / delivery, working-capital receivable / inventory /
   payable): confirm against a live response; they fail safe (stay a gap) if wrong.
5. Expiry theta's first real expiry-day behaviour (Mon 19 Oct is the next chance).

**Closed since the 9 Oct list:** first real email alert arrived (discovery email, 11 Oct, fact-checked by the owner);
the multibagger screen scores on live data (174 early multibaggers on the dashboard); the daily run and library batch
read and save `state/` and `site/` through the private repo (daily runs succeed and publish since 8 Oct); the Kite
login day starts 07:35 (13 Oct).

**Owner, Thu 15 Oct 2026 (first live SENSEX expiry with the walls record):** log in to Kite after 07:35 and before
09:05 (the Market Hub reminder will not exist yet). Then check: `expiry-tape.yml` ran (09:08 and 12:33 runs), the meter
shows both expiries' walls, and `state/expiry/2026-10-15_SENSEX.json` exists in the private repo after 15:46. If the
day file is missing, re-run `expiry-tape.yml` by hand before ~21:30 IST (the relay keeps the minute rows 6 hours).

**Not running:** the 13 Oct cloud session's 19:30 claude.ai routine ("Batch daily jobs' Kite and BharatStock calls",
`trig_01XasAeQgzBU9dsq3cQ3oY2A`) did not run and pushed nothing; its work was done in this session (above). Ignore
older notes that say to wait for it.

### Earlier handover notes (13 Oct 2026 and before; dated, partly superseded)

**Expiry meter items 1-3: LIVE (Tue 13 Oct 2026, ~17:52 IST, relay Version 62, commit b13c14e, deployed by relay-deploy run 38396704530; see CHANGELOG 13 Oct, "judged against the forward").** Track record now shows the meter beside the forward ("meter closer than the forward: X of Y"); each reading's uncertainty comes from its ATM straddle (stored from Thu 15 Oct 2026); the chart covers the whole session with Day / 2h / 1h / 30m and nothing after 15:30; after the close the meter shows the actual close. **Settlement averaging is built but OFF** (`EXP_SETTLE` in `relay/Expiry.gs`): since 3 Aug 2026 NIFTY, BANK NIFTY and SENSEX constituents close in a 15:15-15:35 auction at both NSE and BSE, so a 15:00-15:30 average does not match today's rule. **Watch for SEBI's circular on derivatives settlement (expected Oct 2026)**; if it returns to a 30-minute average, set `method: 'average'` and the window it names. On the one real expiry so far (13 Oct) the forward beat the meter at 14:00 and 15:00. Phone expiry range now labelled ±1 standard deviation (about 2 in 3), phone cache v30.

**Item 4 history test: DONE (13 Oct 2026 night, CHANGELOG "Expiry history test").** 240 expiries since Oct 2023: walls and max pain from the evening before do not beat the open (NIFTY: open 49.9 bp mean error, meter formula 50.2 fitted walk-forward, 52.3 with today's starting weights; close moved toward max pain 47.7% of days). **Starting weights set to the history fit (owner, 13 Oct 2026; relay Version 64):** NIFTY k 0.18 / m -0.13 / v 0.17, BANK NIFTY -0.23 / 0.19 / 0.04, SENSEX 0.18 / 0.10 / -0.13 (own BSE history fit, relay Version 65, 14 Oct 2026 ~01:15 IST; `EXP_START` in relay/Expiry.gs). SENSEX is in the history test (158 expiries from BSE's files): same answer, walls and max pain do not beat the open. Re-run `expiry-history.yml` monthly (fetches only new expiries).

**Step 5 signals: TESTED on history (13 Oct 2026 night, CHANGELOG "Step-5 signals").** Wall moves day over day, gamma, participant OI, event days: none beats the open; nothing added to the meter. One candidate to watch: FII net index puts vs BANK NIFTY (robust correlation -0.3 to -0.5, but walk-forward gain under 1 bp). Event days are already priced by the straddle. Still needs our own record (~10 expiry days): wall moves within the day.

**Second look at the history (14 Oct 2026, CHANGELOG "Expiry history, second look"):** four patterns hold in both halves: BANK NIFTY pins to max pain when the open is near it; SENSEX walls act as barriers through the day; NIFTY moves away from max pain from the previous close; expiry-day straddles overpriced on all three (sellers keep 11-17%). Next, if the owner agrees: index-specific meter rules, walk-forward tested before going live.

**Was:** (4) history test on NSE's free F&O end-of-day files (about 3 years of weekly expiries; morning walls and max pain from the previous day's OI against the open and the close; next week's chain from the day-before file), run on GitHub (NSE blocks the laptop); fit the starting weights from it. (5) Only after ~10 recorded expiry days: wall movement (rolls, reinforcement or abandonment), gamma exposure from the chain, NSE's participant-wise OI (client / FII / pro / DII), event days (wider range only).

**Still unverified:** rotation of the credentials exposed on 6 Oct; phone sign-in tested on the phone itself; position tracker full live run. In the 13 Oct cloud session the `gh` CLI token was invalid: pushes went through the session's git connection, and workflow results were read from GitHub's public API.

**Dashboard market strip (all pages, every 10 s in market hours): live 13 Oct 2026.** **Expiry meter for NIFTY, SENSEX and BANK NIFTY (dashboard, Analysis → Expiry meter; phone F&O tab): live 13 Oct 2026 evening.** Adapts by itself to whatever expires that day (stacked on double days); one Kite request; learns per index (Bayesian ridge, one expiry only nudges the weights). First NIFTY close recorded 13 Oct (22,721.95); first SENSEX run Thu 15 Oct 2026. **Option sellers' walls tracked through the day (13 Oct 2026 evening):** walls, max pain, sellers' settlement payout and the next expiry's walls recorded every minute (`expiry-tape.yml` keeps it going when nobody watches; each day saved to `state/expiry/` in the private repo). Next expiry's walls feed the learning with weight 0 until expiries show they help. First live run: SENSEX, Thu 15 Oct 2026; log in to Kite before 09:05 that day so OI changes are measured from the previous close.

**Kite 06:00 fix: LIVE (Tue 13 Oct 2026, relay Version 48, commit 166cd18), deployed by the new GitHub
relay deploy (`relay-deploy.yml`, run 38353884709), on both deployments.** A Kite login is now dated by
Kite's morning clear-out: the Kite day starts at 07:35 IST (corrected from 06:00 the same day; log in after 07:35). Relay changes now deploy by themselves on push to `main` (no approval step, owner's
choice); the laptop route still works. See CHANGELOG 13 Oct.

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
serves parses (the same check fails on the broken 9 Oct code). **Confirmed by the owner 9 Oct: "Email me a code"
delivers the code and login works.** Not yet confirmed: reopening the tab within six hours stays signed in.

**7-day sign-in: live (9 Oct, 22:18 IST, Version 24 on both `AKfycbwQZxgg…` and `AKfycbye12r6…`).**
Deployed with `clasp` as ramghatagedb1101@gmail.com (no Chrome). Verified live: both serve a page whose
script parses, `app_data` refuses an unknown session, `app_logout` answers, quotes still served. Each
device signs in once more (old six-hour sessions don't carry over), then lasts 7 days.

**Admin dashboard rebuilt (9 Oct, late):** research-terminal design, Proven compounders screen, clickable
stock report -- see CHANGELOG. Owner to add `BHARATSTOCK_API_KEY` to the relay's script properties for the
report's price and quarterly charts. Corporate actions, sectors and company names fill in as the weekly
batch revisits companies.

**Analysis tools added (10 Oct):** Factor rankings, Screener (saved screens on the relay), Scatter explorer,
What changed, Sectors, and factor profile + peers on each stock report -- see CHANGELOG 10 Oct. "What changed"
since-last-scoring events start once companies are re-scored by the batch.

**Stock library fetches only what changed (10 Oct).** BharatStock (10,000 requests/day) is now asked only
for companies that have filed new results at NSE, within a 9,000/day budget; prices come from NSE's free
daily price file; the library runs daily at 06:15 IST. Per-company stored figures and what each still needs
are in `state/library_state.json` (private repo); the summary is `tracker` in `library.json` and "Data
freshness" on the dashboard Overview. **Before adding any new BharatStock call, add it to the tracker's
stages (`needs()` in `hub/library.py`) with a refresh rule -- never fetch per company per run.** See
CHANGELOG 10 Oct.

**Stock report research tools (11 Oct):** interactive Kite charts, 10-year results, NSE documents and AI
summaries -- see CHANGELOG 11 Oct. AI summaries run on Gemini's free tier (`GEMINI_API_KEY` secret, present since 6 Oct); first real
summaries (Titan) confirmed 10 Oct.

**Chart indicators and email alerts (11 Oct):** RSI / MACD / Bollinger / 52-week lines on the stock report;
daily digest and watchlist-move emails, switchable on Overview. No Telegram (owner does not use it). See CHANGELOG 11 Oct.

**Relay deploys now go through `clasp`, not Chrome** -- see `relay/README.md`, "Deploying with clasp".

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

## To-do, in order (9 Oct 2026; SUPERSEDED by "NEXT STEPS" at the top, kept for history)

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
