# Changelog

Newest first. Dates are IST. "Login" covers how the Kite access token gets from your morning login into the daily job.

## 2026-10-16

### First real run of the new features (16 Oct 2026, after the close)
- Relay Version 78 live (portfolio, paper trades, insights). Insights run: 452 s, 457 NSE calls, 450 followed companies,
  35 alerts, one phone notification. Every source answered: 298 companies on surveillance or F&O ban lists, 399 pledge
  disclosures, 876 board meetings, 1,864 filings, 13 volume spikes, 706 heatmap rows, 3 years of option prices.
- **Insider trades are nearly empty, and not because of a bug**: NSE's per-company insider list has no entries after
  Tue 28 Apr 2026 (checked on 30 large companies, `hub/diag_insider_check.py`). The feature stays, but it needs a new
  free source (BSE's insider list is the next to test).
- Fixes: positions stopped after one day because the shared NSE call cap was used up by the insider step; they now have
  their own allowance (60 days collected). The run's summary line failed on the hidden key-mask line; it now skips it.
  The results calendar listed each company twice (meeting notice plus results); now one row per company and day.
  Positions chart axis labels rounded.

### Fifteen new features from the world's best investing apps (built 16 Oct 2026)
Owner, on the research report: "That can be done for free. Build all of them." All run on data already collected or
free NSE lists; no new paid service.
- **Data** (`hub/insights.py`, new workflow `insights.yml`, Mon-Sat 08:05 IST, after the library run, same queue): ASM/GSM
  surveillance and F&O ban, promoter pledge disclosures (rising flag), board meetings for 45 days, 3 days of filings,
  insider market buys/sells over 180 days for the ~450 followed companies (NSE answers this per company only; probed from
  GitHub, `hub/diag_insights_probe.py`), FII/DII/Pro/Client index futures and options positions (60 days), volume spikes
  (3x volume, 50%+ delivery), heatmap rows, grades A+ to F within the industry (the dashboard's own factor rules,
  ported), P/E against industry quartiles and the company's own weekly history (starts today, shows after 8 weeks),
  investor portfolios from the registry matches, 3 years of index option prices (day-before straddle) with today's rank,
  and alerts. Written to the private repo `site/insights.json`; state in `state/insights_state.json`.
- **Alerts**: 52-week highs/lows, 200-day crossings, results filed, promoter buys/sells, new surveillance flags, rising
  pledges, and companies entering or leaving your saved screens. New alerts for your companies and screens are pushed to
  the phone once (same push keys as the Kite reminder).
- **Relay**: `Portfolio.gs` (Kite holdings, read-only; last-seen symbols kept for the morning job), `Paper.gs` (paper-trade
  journal in one Drive file; live Kite prices or a typed price; index options settle at the recorded index close),
  `adminInsights`, `batch_context` for the morning job, and per-strike option prices in the expiry meter's data.
- **Dashboard**: My portfolio, Heatmap, Insider trades, Results calendar, Filings, Volume spikes, Positions and option
  prices, Paper trades; Alerts on the Overview; investor portfolios on Investor registry; on each stock: surveillance
  and pledge badges, next board meeting, grades, valuation band, insider trades; Ask on the Screener (plain words to
  conditions, no AI needed); payoff builder on the Expiry meter (live prices, breakevens, chance of profit).
- **Phone** (cache v38): alerts, portfolio and coming-up on Home; positions, option prices and paper trades on F&O;
  industries today, promoters buying and volume spikes on Desk; badges, grades, valuation band and insider trades on
  each company. Ask stays on the dashboard (the phone does not hold the library).
- Tested in the local preview with sample data at laptop and 375 px widths (no script errors, nothing wider than the
  screen); the NSE parts are tested only by the first GitHub run.

## 2026-10-15

### Screen and wording audit: dashboard and phone (~16:45 IST)
Owner: "looks like something is overlapping, do a thorough audit of all the screens ... check the wordings. i dont
want any contextual wordings suggesting how the app is built or why is it that way. plain simple words minimal".
- Overlap fixed: on the Overview, long corporate-action names (and Shortlist reasons) could not wrap, so the table grew
  past its box and its header painted over "Data coverage", with a sideways scrollbar on the page. Those cells now
  wrap, and panels in a grid clip anything wider.
- Bug fixed: the multibagger screen has four gates (scores 0-4), but the dashboard counted score 5, so the menu and the
  Overview showed 0 (174 qualify) and stock reports said "x/5". Overview's compounders card said "six rules": eight.
- Wording, both screens and the relay's messages: every mention of how the app works or where data comes from was
  removed or made plain (relay, batch, daily/library run, BharatStock, Yahoo, CoinGecko, ECB, the AI model's name,
  UTC, "not stored", "live from ...", start dates and catch-up notes, the model formula, the phone's Method table).
  Kept: units, dates, "Not advice", and the "Log in to Kite" action. Timestamps now read "07:58 IST · Thu 15 Oct 2026".
  Phone cache v36.
- Second pass, page by page in the browser: the page name no longer repeats (top bar and heading); every date in the
  "07:58 IST · Thu 15 Oct 2026" style; Parameters without the source column and code names (status words: available,
  coming, planned, not available); Back-tests as tables instead of raw data dumps; a stock's fund list shows 10 with
  "See all"; no sideways scrolling on any page; shorter intros on Factor rankings, Scatter explorer and Sectors.
- Phone, checked at 375 px with today's real data (local copy, sign-in skipped): the F&O "rejected names" table (711 px)
  and the Desk track-record table (387 px) ran off the screen; both fit now. All five tabs, settings and a company page
  measured: nothing wider than the screen. Measures without a label read as words, not code names (both screens);
  F&O expiry dates as "Mon 19 Oct 2026"; a repeated "No track record yet" removed. Phone cache v37.

### Research collector: the next expiry's chain at each expiry-day close (~14:45 IST)
Owner, on the next-expiry chain the meter watches: "smart money is preparing for the next expiry after making money
today", then "ok" to testing it properly. The expiry history only holds the next expiry's chain as of the evening
BEFORE each expiry (a first test on that found nothing); the owner's signal is the build-up DURING expiry day. New
`hub/expiry_nextchain.py` fetches the same free end-of-day F&O files for each recorded expiry day (NSE on GitHub, which
blocks the laptop; BSE for SENSEX) and keeps the next expiry's chain at that close, plus NSE participant-wise OI, in the
private repo (`state/expiry_history/next_chains/`). Run by hand: `expiry-history.yml`, task `next_chains`. Research
only: nothing on the dashboard or phone reads it. Tested locally on BSE (new and old file formats).

### METHOD.md guard: false failure on GitHub fixed (~10:55 IST)
The USD/INR push below updated METHOD.md in the private repo first, yet the GitHub guard failed ("METHOD.md did
not" change). Cause, in this morning's guard: it read the private repo's history only when the copy sat OUTSIDE this
repo. On the laptop it sits beside it (so local checks passed); the GitHub job checks it out INSIDE (./market-hub-private),
so the private history was never consulted. Now any copy other than this repo's own METHOD.md path counts. Two new
tests reproduce the GitHub layout (the first fails on the old guard, passes on the new); all 14 pass. The red run
for commit 0637fd5 was this false alarm; nothing to fix there.

### USD/INR stuck at 0.00%: wrong futures contract (~10:40 IST)
Owner: "correct it now". USD/INR showed "Live" but 0.00% all morning: the relay (and the daily job's snapshot) quoted
the NEAREST USDINR future, which is now a weekly contract (USDINR26O16FUT, expires Fri 16 Oct 2026) that barely
trades: last = previous close = 96.14 in three samples 30 s apart (public quote endpoint, 10:29-10:30 IST). Crude was
fine (8,945 -> 8,936 in the same samples), gold too.
- Both pickers (`frontMonths_` in relay/Code.gs, `_front_month` in hub/sources/commodities.py) now take MONTHLY
  contracts only and roll to the next month 3 days before expiry, when trading leaves the old one. Checked on Kite's
  real instrument lists: today USDINR26OCTFUT, GOLD26DECFUT, CRUDEOIL26OCTFUT; from Fri 16 Oct CRUDEOIL26NOVFUT
  (October crude expires Mon 19 Oct). The relay's cached pick is renamed so the new rule applies at once.
- The shared Kite snapshot still asks for the same number of instruments; the expiry recorder's option quotes are
  untouched. Pushed in market hours on the owner's instruction.

### Overview: % / Points switch, heading not repeated (~10:15 IST)
Owner: "the word overview itself is repeating" and "a switch which shows absolute numbers for change or change in %
for all". The Overview's own heading is gone (the top bar already says Overview). A "% | Points" switch sits where the
"same as the phone's Brief tab" note was (owner's placement) and changes every tile at once; the dashboard remembers
the choice in this browser. Points use the quote's own change where Kite gives one (indices, VIX, gold, crude,
USD/INR) or the S&P's two closes, else work it back from the % and the price (overseas, Bitcoin). The Moves bars stay
in %, since they compare things priced in different units.

### Overview: market strip folded into the brief tiles (~10:00 IST)
Owner: "remove duplicates and make it also tiled like market brief". On the Overview the top strip repeated VIX, gold,
crude and USD/INR from the new tiles. The strip's quotes are now tiles there too (NIFTY 50, Bank NIFTY, SENSEX, India
VIX, gold, crude US$ with the ₹/bbl price beside it, USD/INR, S&P 500, DAX, FTSE 100, US futures when Yahoo has them,
Bitcoin), and the strip is hidden on the Overview only; every other page keeps it. Tiles fill the width (about six
across on a laptop, two on a phone). Owner allowed pushing in market hours (no expiry code touched).

### Dashboard Overview shows the phone's Brief (~09:45 IST; pushed at once, owner's go-ahead)
Owner: "overview on admin panel and brief on mobile needs to be same ... no changes on mobile needed, but add missing
components to admin". The dashboard's Overview had only library figures; the phone's Brief tab (market tiles, moves,
FII/DII flows, the AI-written brief) had no desktop equivalent.
- New relay call `adminBrief` (Admin.gs) returns the same three files the phone reads (`brief`, `context`, `stocks`).
- Overview now opens with "Market brief": gold, crude (US$), USD/INR, India VIX, S&P 500 and Bitcoin tiles, the Moves
  bars, the FII/DII bars and the written brief, with the phone's own rules: live Kite values from the market strip's
  10-second quote when there is one, else the daily snapshot; the phone's time labels. Only this box redraws on each
  quote, so an open brief stays open. Phone unchanged.
- Checked with today's real files from the private repo (rendered locally). Held until after 15:30 IST because a
  relay push deploys at once.

### METHOD.md moved to the private repo (~08:10 IST)
Owner: "move method to private". This repo is public (anyone can read it without signing in; checked), so the full
method document is now kept in the private repo `market-hub-private` only, and removed from here.
- Local copy for editing: `C:\nse_fo_analyser\market-hub-private`, a sparse clone that holds only METHOD.md (no
  data is downloaded), set to push as ramghatagedb1101-NSEFO.
- The push guard (`.github/workflows/method-doc.yml`, `hub/method_check.py`) checks the private copy out with the
  existing `PRIVATE_REPO_TOKEN` and prints only pass/fail. Settings check unchanged. Coverage rule: an engine change
  passes when METHOD.md was updated in the private repo after the pushed range's base commit (so: push METHOD.md
  first, then the code), or with `[method: no change]`. Tested both ways with scratch repos; the guard's 12 tests and
  the settings check pass. `.gitignore` keeps a checked-out copy from ever being committed here.
- **Not removed: history.** Earlier versions of METHOD.md (committed here this morning) and all the code remain
  readable in this public repo's history. Only making the repo private, or rewriting its history, removes them --
  owner's decision, pending (cost of Actions minutes for a private repo; see STATUS).

### METHOD.md merged to `main`, with its push guard (~07:40 IST)
Owner: "finish the METHOD.md merge to main". The laptop session (second Claude subscription) had finished all 9
sections on the `method-doc` branch and committed them (`69f61a0`), but its session limit hit during the push, so the
commit sat only on the laptop; it was found in this folder and pushed to `method-doc` first (after a private-data scan:
no keys or tokens, none of the 102 Shortlist/watchlist symbols, rupee figures are method settings).
- Checked before merging: every file:line reference in METHOD.md (207) against the code -- all files exist; one stale
  reference fixed (`hub/sources/kite.py:207-210` -> `:147-150`, the file was rewritten on 14 Oct). A sample of 10
  concrete claims in the four cloud-drafted sections (2 forecasts, 3 library, 4 Shortlist and multi-bagger, 5 F&O
  selection) read against the code: all correct; it turned up a stale code docstring instead (`hub/multibagger.py`
  said the score is 0-4; it is 0-5 since the ROCE gate on 14 Oct -- fixed). Not done: a line-by-line review of all
  1,779 lines; the settings table (189 rows) is checked by the guard itself (`python -m hub.method_check
  --settings-only`: in step with the code).
- Merged `method-doc` into `main` with `.github/workflows/method-doc.yml` (the guard: a push that changes a
  prediction-engine file without METHOD.md fails, unless the commit says `[method: no change]`). The guard's 12 tests
  moved from the temporary `handover/` folder to `hub/method_check_test.py` (all pass); `handover/` removed.
- CLAUDE.md: the owner-approved line (update METHOD.md in the same push as any engine change; run
  `python -m hub.method_check --base origin/main` first), and the one-folder rule below.
- Left: the private repo's `method-doc-drafts` branch (drafting scratch space, can be deleted); the drift items the
  drafters listed and did not fix (STOCKS.md, CLAUDE.md's feed list, live.yml's header time, hub/expiry_day.py's
  docstring after the 14 Oct pinning) -- see STATUS.

### One working folder for the project: `C:\nse_fo_analyser\forecast_hub` (~07:10 IST)
Owner asked why there were two folders. The project lived in `C:\nse_fo_analyser\forecast_hub` from 6 Oct (its
first commit); the long laptop session had started on 8 Oct without choosing a folder, so the desktop app gave it a
temporary folder, where it cloned the repo. Two copies syncing through GitHub is workable, but it caused this
morning's confusion (finished work sat unpushed in one copy while the other was checked), and the temporary folder is
deleted with its session. Decision (owner): one folder.
- Kept outside the repo in `C:\nse_fo_analyser\extras\` (README.txt there): the Market Hub showcase PDF and HTML,
  the dashboard/phone preview with its mock relay (holds sample data from the private repo, so never in this public
  repo), the test tools (simulated expiry day, learning checks, early analysis scripts) and old one-off edit scripts.
  Copies compared with the originals before the temporary folder was emptied; its repo copy had nothing uncommitted,
  unpushed or stashed.
- The session moved to `forecast_hub`; Claude's saved notes for Market Hub (accounts, relay deployments, email-only
  alerts, API budgeting) were copied to the notes used by sessions in `forecast_hub` and in `C:\nse_fo_analyser`.
- Rule (CLAUDE.md): one session at a time in that folder; pull before starting, push before stopping.

### Old Claude "Kite login reminder" routine switched off (06:50 IST)
`trig_011gp21txucmWGZPKqpR2FEu` set to disabled from the laptop session (the cloud session could not see it), as the owner approved on 14 Oct once Market Hub's own push reached the iPhone (confirmed 14 Oct ~21:50 IST). From today the 07:36 / 08:33 IST reminders come only from Market Hub (`kite-reminder.yml`).

### METHOD.md: one document for the whole prediction method, drafted and assembled (merged to `main` the same morning, entry above)
Owner asked for a single document explaining every technique the platform uses, that stays true as the code changes --
there was nothing like it (README is setup notes and partly stale, STOCKS.md is port notes, CHANGELOG/STATUS are
history/state, not method). A cloud session started this, drafted 4 of 9 sections (index, library, shortlist,
fno_select, via one read-only agent per section against a shared prompt) and built the keep-it-true guard before its
credits ran out; this session picked up its branch and finished the rest.

- Drafted the remaining 5 sections the same way (fno_data, expiry, live, data, principles) -- one read-only subagent
  per section, same prompt and schema as the cloud session's four, so the whole document reads as one piece.
- Assembled `METHOD.md` (`handover/method_doc_assemble.py`): 1,779 lines, 9 sections, a settings table built from the
  drafters' named constants with values read straight from the code (189 rows), and a source map of 86 files whose
  change should update this document. Two drafting snags fixed before assembly would run: three sections returned
  `constants` without the schema's required `file` key (resolved by searching the repo for each name's real
  definition, not guessed -- two names turned out genuinely ambiguous between two files with different values for
  different screens, e.g. `MIN_CREDIT_TO_WIDTH` is 0.10 in `hub/fno.py` and a stricter 0.15 for expiry-theta; checked
  by hand, not assumed); two jointly-named tuple constants split into one row each.
- `python -m hub.method_check --settings-only`: passes. The guard itself (`hub/method_check.py`,
  `.github/workflows/method-doc.yml`) checks every settings-table value against the code on every push to `main`, and
  fails the push if a file in the document's source map changes without the document, unless the commit says
  `[method: no change]`.
- Spot-checked several of the most load-bearing claims directly against the code (not just taken on a drafting
  agent's word): confirmed `rg/config.py`'s `SETTLE_WITH_HISTORICAL` flag is genuinely dead (the stock screen's
  settlement always reads a live spot quote, never the historical-close function the flag documents, which has no
  caller anywhere); confirmed `rg/screen_history.py` is never imported by anything; confirmed the relay's expiry
  weights (`k, m, v`) really are pinned to 0 as the 14 Oct entries said; found one more real piece of drift this way
  (below).
- Fixed five pieces of stale documentation the drafting agents surfaced, all comment/prose-only (no behaviour
  change): `hub/engine.py`'s adaptive-band-step docstring said "not switched on live" when it has in fact been live
  for the year horizon since 14 Oct 2026 (Group F2); `hub/config.py`'s index-price-source comment had the Kite/NSE
  precedence backwards; `hub/store.py` and `hub/tracker.py` comments still said "Yahoo" (NIFTY/BANK NIFTY/SENSEX
  prices have used NSE's free bhavcopy and Kite daily candles since well before today -- these two comments were just
  never updated); the phone's Method table said "Six price tools" (ten run, counted directly: 6 in
  `hub/tools/core_tools.py`, 4 in `hub/tools/more_tools.py`); `README.md` had several of the same stale claims
  (Yahoo, NIFTY/SENSEX only, 15:45 IST close, a weekday-mirror expiry-calendar note superseded by Kite's own contract
  lists since 14 Oct). Two other "Yahoo" mentions found in a repo-wide check (`relay/AdminPage.html`, `relay/
  README.md`) are correctly describing the *overseas-markets* panel, which really does use Yahoo -- left alone.
- **Not yet done** (see `handover/METHOD_HANDOVER.md` "Remaining steps"): the same direct-against-code check for the
  4 cloud-drafted sections and the rest of the 5 new ones; CHANGELOG/STATUS entries beyond this one; removing
  `handover/`; merging `method-doc` to `main`; the owner's one-line CLAUDE.md addition (approved today, see STATUS.md).

## 2026-10-14

### Expiry meter replay scoreboard: every recorded expiry re-scored with today's model (~23:00 IST, cache v34)
Owner asked to replay last Tuesday's NIFTY expiry (13 Oct) with the model as it is now, and to keep tracking that. On
13 Oct's 15 live readings (13:45-15:23) today's model (walls at 0, so the forward) was closer to the close at all 15:
average 86 points (38 bp) against the live meter's 102 (45 bp); the old meter was pulled toward max pain and the walls
(22,550-22,650) while NIFTY rallied through the 22,600 call wall to close at 22,721.95. Most of the error is a +75 bp move
after 14:00, about 3.6 times the typical late-afternoon move in the 399-expiry history: a tail day, not a missing input.

- `relay/Expiry.gs`: one formula for the expected close (`expiryFormula_`), used live and by the replay, so the two cannot
  drift apart (checked identical to the old inline formula). New `expiryScore_`: every stored expiry (last 30 per index)
  at 10:00/12:00/14:00/15:00 -- the meter as shown live, today's model replayed on the same reading, the forward, and the
  spot -- with how often the close fell inside the live +-1 sd band and inside a 0.88 sd trial band (a warning light
  for the range decision, not proof; see the review below). Fewer than 10 expiries at a time = too few to judge. Readings now also store the spot
  (p[9], as spot minus forward); spot and bands start with readings from 15 Oct (earlier ones lack them). Cached with the model (key exp_ma3_).
- Dashboard (Analysis -> Expiry meter): a scoreboard table under each index's track record, a single clear best column highlighted.
- Phone (F&O tab): "Expiry meter scoreboard", one collapsed row per index. `hub/expiry_day.py` writes it to the public
  `docs/data/expiry_score.json` from the relay's answer on any day (not only expiry days), with no timestamp so live.yml
  commits it only when a new close changes it.
- Tests: real `Expiry.gs` in node on 13 Oct's actual readings plus synthetic new-format ones (10 cases: formula identical,
  empty times, last reading at or before each time, bands, spot, too-few flag); `write_score` (not rewritten when
  unchanged, labels, no tracks); phone at 375 px (scoreboard, too-few label, empty index hidden, missing file, no overflow,
  no page errors). All pass.
- Independent review before deploy (2 reviewers, each finding checked by a skeptic): 4 confirmed, 2 refuted; all 4 fixed.
  (1) The dashboard's green "best" could crown spot just because spot skips 13 Oct (stored before spot existed, a big
  miss for everyone): spot now competes only when it covers the same expiries, and shows "k of n; forward on those".
  (2) With wall weights at 0 the model often equals the forward: ties are counted apart, and a shared best gets no
  highlight. (3) Real storage limit: the relay's script-property store is capped at 500 KB in total, and ~90 stored
  expiry days at ~5-6 KB each were already close to it; spot is now stored as spot minus forward (one decimal, a few
  characters), and readings from earlier days that never got a close are deleted when a close is recorded. Still a
  watch item (STATUS E). (4) The separate research review found the 0.75 trial band the wrong comparison: the history's
  ~0.76 factor came from the evening-before straddle, which also prices the overnight gap, so the trial band is 0.88;
  and with ~10 expiries a hit rate cannot tell 68% from 80%, so the band rows are a warning light, not the decision.
  12 more test cases (offset spot, forward on spot days, ties, 0.88, orphan cleanup, highlight rules): all pass.

### Expiry meter: wall and max-pain weights set to zero and pinned (owner's decision, ~22:20 IST)
From the intraday test below. `relay/Expiry.gs`: `EXP_START` k, m, v = 0 for all three indices (was the 13 Oct history
fit, e.g. NIFTY 0.18 / -0.13 / 0.17), and pinned there with a near-zero prior spread in `EXP_SPREAD` -- otherwise the
live re-fit would pull them off 0 again (one expiry moved m by 0.26 on 13 Oct, noise that 399 expiries outweigh).
Next week's wall midpoint (v) was checked the same way first: no help at any reading time, slightly worse on NIFTY
(t about -2 at 10:00, 12:00, 14:45). The meter's expected close is now the forward plus the Europe/US terms (which still
learn, starting at 0); what it adds is the range. Dashboard text says so. Test (real `Expiry.gs` loaded in node, script
properties mocked): with 6 made-up expiries closing exactly on the wall midpoint, k, m, v stay at 0 and the Europe weight
still learns. `node relay/check.js` clean. To re-open: only if the monthly intraday test shows a real gain.

### Expiry days, minute by minute: 399 intraday paths and what they show (~22:30 IST)
Owner asked what else the data could do for expiry-day prediction. Every history test so far compared the evening-before
chain with the expiry day's open and close only, while the meter reads at 10:00-15:00. New `hub/expiry_intraday.py`
(workflow `expiry-intraday.yml`) fetched Kite minute candles for the index on all 399 recorded expiry days (NIFTY 159,
SENSEX 158, BANK NIFTY 82; Oct 2023 - Oct 2026): full coverage, no gaps, 59 Kite requests, into the private repo's
`state/expiry_history/intraday/`. New `hub/expiry_intraday_test.py` tests, walk-forward (each expiry predicted only from
earlier ones, after 30), per index; a result "holds" only with gains in both halves and t >= 2. 78 cells tested, 12 hold
(about 2 would by chance) -- all 12 are the late-average mechanism below. Results: `state/expiry_history/intraday_test.json`.

- **Walls, max pain, morning momentum: no help from any checkpoint (10:00 to 15:15), any index.** "Close = spot now"
  wins or ties everywhere (e.g. NIFTY at 14:00: 20.4 bp error vs 20.7 with max pain). This extends the evening-before
  finding to the whole day: the meter's wall/max-pain terms add nothing beyond the current spot/forward.
- **The pre-auction close was the 15:00-15:30 average, and using the known part of it is a large, mechanical gain** (all
  three indices, t 5-12): NIFTY error at 15:15 3.1 -> 1.9 bp, at 15:25 6.0 -> 0.9 bp. Since 3 Aug 2026 the closing auction
  sets the close, so this applies only if SEBI returns to an average (STATUS E1) -- then switching on `EXP_SETTLE` in
  `relay/Expiry.gs` is now backed by the data, not just built.
- **Auction era (since 3 Aug 2026, only 23 expiries): the close sits further from the 15:00 price** -- NIFTY 24.6 bp vs
  8.5 bp before (the average used to smooth it). Small sample, but late meter readings should be read as less certain now.
- **Range**: the remaining move from each checkpoint is about 0.6-0.8x the evening-before straddle scaled by the square
  root of the time left (68% level, out of sample; coverage 56-69%, slightly under, so the band needs a little margin).
  Consistent with the earlier "about a quarter narrower" finding; the owner's decision to wait for recorded live
  expiries before changing the live range stands.
- **Expiry theta's 3x-daily-sigma strikes, first backtest of the index side** (no option prices exist, so no P&L):
  from 10:00, the close never ended beyond 3x on NIFTY (0 of 159) or SENSEX (0 of 158), 1 of 82 on BANK NIFTY; touches
  0-1.2%. At 2.5x: NIFTY 0 closes beyond, 1 touch. Worst 14:45-to-close move, auction era: 0.74 daily sigma (NIFTY).
  The rule is conservative on index risk; the sample has no election- or budget-type expiry, so tail risk is not
  measured. Strike distance stays an owner decision (paper record of 50-100 sessions first, STATUS D4).

### Push notifications live on the owner's iPhone; tapping now opens Market Hub on "Log in to Kite" (~21:40 IST, cache v33)
First real push confirmed by the owner (test run: `sent: 1, errors: 0`). Tapping it did not open the Kite
login: `sw.js` asked iOS to open the outside link (kite.zerodha.com) from the notification tap, and a Home
Screen app on iOS does not do that. Now a tap opens Market Hub itself -- an already-open app is focused
and messaged, otherwise it opens at `./?open=kite` -- straight onto Settings with the usual "Log in to Kite"
button highlighted (`openKiteLogin()` in `docs/index.html`), so login is one more tap, by the same route
the owner already uses each morning. The service worker never opens an outside URL itself any more. The
reminder text says so ("Tap, then "Log in to Kite""). Tests: 5-case unit test of the tap handler in a
simulated service-worker global (closed app, open app, focus failure, non-Kite, outside URL never opened);
browser test at 375 px now 9 cases (adds: opened from the reminder, message to an open app, normal open
not highlighted). All pass. **Confirmed live by the owner, ~21:50 IST:** test push arrived (`sent: 1,
errors: 0`), and the tap opened Settings with the Kite button highlighted.

### Phone app: "Turn on notifications" could show "On" while the relay had nothing (~21:00 IST, cache v32)
After the owner's tap, the second test run reported `no subscribed devices`. The phone code (`togglePush`)
sent the subscription to the relay (`app_push_subscribe`) but never checked the answer -- any refusal or
failure there still left the phone showing "On", because the screen reads the phone's own subscription,
not the relay's. Fixed: `registerPushSub()` requires the relay's `{ok: true}`; on a refusal the phone's
subscription is removed and the real reason shown; `session_expired` signs out like every other call.
Opening Settings now re-sends an existing subscription (the relay de-duplicates by endpoint), which also
repairs a phone in today's state with no extra taps. Browser test at 375 px with the relay and iOS push
APIs simulated, 6 cases (self-heal, relay refuses an existing or a new subscription, happy path, expired
session, no key on the relay): all pass, no page errors, no horizontal overflow.

### Push notifications: keys generated by the workflow and held by the relay -- no key-copying (~21:00 IST)
The owner asked for setup with only the clicks that are truly theirs. The browser route was out (Claude in
Chrome was not connected to this cloud session), and the old plan needed the owner to run
`npx web-push generate-vapid-keys` and paste two GitHub secrets. Owner approved the alternative, which is
an exception to CLAUDE.md's "the owner adds secrets themselves". CLAUDE.md itself is left unchanged for the
owner to word (a Claude session should not loosen its own rule file); until then this entry and STATUS.md
record the exception, which covers the VAPID pair only:

- `hub/push.py`: the first `kite-reminder.yml` run finds no pair on the relay, generates one on GitHub's
  runner (P-256, web-push's own format: 87-char public point, 43-char private scalar, base64url), masks
  the private key with `::add-mask::` before anything could print it, and stores it on the relay. Later
  runs read it back through the key-protected `push_state`. GitHub secrets, if ever added, take precedence.
  Failure reasons now print the exception type and HTTP status only: requests' own messages quote the
  full URL, which carries RELAY_KEY.
- `relay/Push.gs`: new key-protected `push_keys_init` (stores the pair only if no working pair exists, under
  a script lock, format-checked); `push_state` returns the pair to the key holder; `push_key` (GitHub
  secrets route) drops a relay-held private key that no longer matches, so the relay never holds a
  mismatched pair. The phone still only gets the public key (`app_push_key`).
- Risk, stated plainly: the private key now sits behind RELAY_KEY, the key that already guards the Kite
  access token (`mode=token`). Someone holding RELAY_KEY could at worst send notifications to the owner's
  own phone -- far less than the Kite token already exposes.
- Tests: real-crypto test with the real `pywebpush` (8 cases: formats match the relay's checks, the private
  key derives the published public key, a real `webpush()` call signs a VAPID JWT that verifies against
  our public key, payload encrypted), and a 12-case flow test against a fake relay mirroring `Push.gs`
  (first run creates, later runs reuse and never re-init, pair never replaced, init failures reported,
  HTTP errors never print RELAY_KEY, GitHub secrets override and drop the mismatched relay key, holiday and
  logged-in skips still apply, the private key appears only on the mask line). All pass. `node relay/check.js` clean.
- Independent review before deploy (3 reviewers by lens: leakage, relay access control, correctness; each
  finding then checked by a separate skeptic): 3 low-severity findings confirmed, 2 refuted, no access-control
  hole. All 3 fixed: (1) `push_state()` never raises now -- its response carries the private key, and an
  uncaught error on the redirect hop would have printed the one-time Google URL that serves it; (2) a
  public-key change (GitHub-secrets route only) now also clears stored subscriptions (`pushKeyChanged_`),
  instead of leaving them failing every morning with only `errors: 1`, and the docs say "turn off, then on";
  (3) GitHub-secret values are stripped, and a secrets-route private key whose public half the relay
  refused is never used to send. Flow test now 17 cases, all pass; real-crypto test 8/8.
- The owner's steps are now: tap "Turn on notifications" once after the first test run, and confirm the
  second test arrived (STATUS.md "Next up" 1).

### Push notification setup: step order corrected, sender reports its result (~20:00 IST)
Preparing the owner's push-notification setup found the documented order would fail: STATUS.md said to
tap "Turn on notifications" on the phone, then run `kite-reminder.yml`. But the phone asks the relay for
the VAPID public key (`appPushKey_` in `relay/Push.gs`), and the relay only gets that key when
`hub/push.py` posts it (`mode=push_key`) during a workflow run -- tapping first would show "Push is not
set up on the relay yet." Corrected order (STATUS.md "Next up" 1): secrets, one test run, phone tap,
second test run, then switch off the claude.ai routine.

`hub/push.py`: `publish_public_key()` used to swallow every failure silently -- including the relay's
`{"error": "forbidden"}`, which comes back as HTTP 200 and so passed `raise_for_status()`. It now returns
"ok" or the reason, reported as `key_published` in the run's result. The result is also emitted as a
`::notice` run annotation, readable through the check-runs API, because this cloud session cannot
download Actions logs (egress policy). 6-case offline test (network and `pywebpush` stubbed): first run
with no subscribers, relay error body surfaced, test mode sends even when Kite is logged in, a gone
(410) endpoint dropped, missing VAPID secrets reported, send mode still skips when logged in. All pass.

### Adaptive band step switched on live for the year horizon only, Group F2 (owner's decision, ~19:30 IST)
Owner confirmed, from the comparison below: switch the adaptive step on for `year` (the evidence-backed,
unanimous-across-all-three-indices fix), hold everywhere else. `hub/tracker.py`'s `settle_due()` now
passes `n` (settlements already recorded for that index/horizon, same counting rule as
`hub.backtest.run(adaptive_band=True)`) into `engine.learn()` only when `horizon == "year"` -- every
other horizon keeps calling `learn()` without `n`, so `day`/`expiry`/`month` are byte-for-byte unaffected
(confirmed by the existing `n=None` regression test, Group F2's engine.py change). Standalone test (fake
Store, `horizons.settle_value` mocked, no network): across NIFTY/BANKNIFTY day+year settlements, `n` is
`None` for every `day` call and the correct prior-settlement count for every `year` call. All pass.
**Not yet seen on a live run** -- the next time a `year`-horizon prediction actually settles is the first
real check (rare by design: once a year per index); watch `state.json`'s `band` entry for NIFTY/
BANKNIFTY/SENSEX `year` move toward the comparison's adaptive numbers (1.44-1.53) rather than drifting
further from them.

### Band-learning step comparison run, Group F2 (~19:10 IST): a real but horizon-specific finding
`hub.band_step_test` (dispatched via `band-step-test.yml`) ran the walk-forward backtest fixed vs.
adaptive for all three indices and four horizons (`site/band_step_test.json` in the private repo).
Not a clean "switch everything" result -- the live default (constant `ETA_BAND` step) turns out to be
fine for `day` and `expiry` (9 of 9 index/horizon pairs: fixed already sits within 1-2 points of the
80% target, second-half coverage no worse than first-half, i.e. already converged in practice, with
hundreds of settlements to work from). `month` is mixed (BANKNIFTY benefits from the adaptive step;
NIFTY and SENSEX don't). `year` is the real finding: **all three indices** show the fixed step
destabilising badly -- NIFTY and SENSEX's first-half coverage was 47-48% (band far too narrow) before
the constant step pushed `band_k` up to 2.0-2.02 (from a start of 1.2816) and second-half coverage
overshot to 100%, i.e. the band ended up far too wide, not actually calibrated; BANKNIFTY swung the
opposite way (`band_k` to 3.72, second half fell to 56.8%). The adaptive step's decaying nudge tempered
all three: `band_k` settled much closer to its start (1.44-1.53) and second-half coverage landed in the
80s-90s rather than at an extreme. This makes sense in hindsight -- `year`-horizon settlements are few
and highly overlapping (consecutive daily forecasts targeting almost the same date), so a step sized
for the frequent `day`/`expiry` horizons is far too aggressive there; a per-horizon fixed `n` never
distinguishes the two.

**Not switched on live yet.** The evidence supports switching the adaptive step on for the `year`
horizon specifically (unanimous across all three indices, a real instability, not a marginal
preference) -- not a global change, since `day`/`expiry` already work and `month` is ambiguous. Left
for the owner to confirm before touching `hub/tracker.py`'s live call to `engine.learn()`, since this
changes a live forecasting model's actual behaviour, not just adds a capability.

### ROCE gate added to the multi-bagger screen, Group F1 (~18:30 IST)
The two recommendations left "not started, by design" since the 8 Oct methodology review needed
groundwork before either could be built. Started on the owner's explicit go-ahead, 14 Oct evening.

Groundwork first: a new one-off `hub/diag_roce_fields.py` (`diag.yml`) checked whether BharatStock's
annual financials carry `operating_profit`, `total_equity`/`equity_attributable_to_owners` and both
`borrowings_current`/`borrowings_non_current` cleanly across the last three annual years (the existing
quarterly `roce` measure only ever looks at one quarter, annualised) -- not a given, since the identical
worry about guessed field names had just been confirmed true for `working_capital_days`/`dividend_paid`
earlier today. This cloud session's egress policy blocks reading an Actions run log directly (the
download redirects to Azure blob storage, denied by this session's proxy) -- worked around by having the
probe write its derived-only findings (field presence booleans, computed ROCE%, never raw financial
figures) to `diag_output/roce_fields.json` and `diag.yml` commit it, so the result reads back from git
instead. Real finding: RELIANCE/TCS/ITC/INFY all three years clean, consistent magnitudes (9-70% ROCE
range across the sample). HDFCBANK's `borrowings_current`/`equity_attributable_to_owners` are simply
absent from this endpoint for all three years -- not a wrong field-name guess this time, but a genuine
sector gap: banks don't carry conventional "borrowings" the way a capital-employed formula assumes.

Added the fifth gate (`hub/multibagger.py`'s `score()`): `roce_sustained`, true only if all of the last
three annual years clear 15% ROCE (`operating_profit / (equity + borrowings_current + borrowings_non_current)`,
the registry's existing ROCE threshold), false if any of the three misses it, and a gap -- never a
fabricated pass or fail -- if fewer than three annual rows exist or any required field is missing in any
of them (so every financial-sector company stays a permanent, correct gap on this one gate, same
missing-data philosophy as the existing `cash_backed` gate). `measures.roce_3y_pct` published alongside
the gate so the figures behind a pass/fail/gap aren't invisible and debugging a sector gap is possible.
Score range is now 0-5, not 0-4: renamed `rated_all_four_gates` to `rated_all_five_gates` (`hub/multibagger.py`,
`hub/library.py`'s `merge_and_write_multibagger` -- the same screen, reused since the 10 Oct library-batch
integration, not a second implementation) and `hub/admin_publish.py`'s mirrored key; updated the three
places `relay/AdminPage.html` hardcoded the old `score === 4` / "4/4" / "/4" (nav badge count, Overview
KPI, stock-report chip) to 5. `node relay/check.js` clean. 6-case standalone test (fake quarterly + annual
rows, no live calls): clean 3-year pass, one year below 15% fails correctly, bank-like missing-field case
stays a gap, fewer than 3 annual rows stays a gap, `annual_rows=None` stays a gap with no crash, and the
score can reach 5 with everything passing. All pass.

**Not yet seen on a live run** -- the next `library.yml` batch (or a manual `multibagger.yml` dispatch)
is the first real check; look for `roce_sustained` gaps clustering on financial-sector names (expected
and correct) rather than spread randomly (which would mean a field assumption was wrong after all).

### Held relay commits pushed and deployed after market close (~15:35 IST, relay Version 66)
Everything held for the 09:15-15:30 IST market-hours rule went out as soon as the window closed: push notifications
(phone app, `relay/Push.gs`, `hub/push.py`/`kite-reminder.yml`), the relay's own BharatStock call counting
(`?mode=bs_usage`), and A4's `prefetch_chain_data` batching -- six held commits pushed to `main` after
`git pull --rebase` skipped two already-applied duplicates. `relay-deploy.yml` created Apps Script Version 66 from
commit `c61245f`, moved both deployments to it, and its `mode=check` passed live (`token_ok_for_today: true`).
Still open then (STATUS "C. First live checks" 1): nobody had opened the dashboard's stock report / funds / price chart
since the deploy, so `?mode=bs_usage` read 0 for the day; the next `library.yml` run reads it through `relay_used()`.
(Written 14 Oct 18:24 IST by the laptop session but left unpushed in this folder; added here 15 Oct.)

### Phone app sign-in verified live; a Google-account mixup on the way there (~15:20 IST)
Checking G1 ("phone sign-in tested on the phone itself") hit the Google-side twin of the GitHub
account-flip problem documented above: Claude-in-Chrome landed on `ramghatage@gmail.com` for
`script.google.com`, not `ramghatagedb1101@gmail.com`, despite a cloud session having reportedly fixed
this before. Stopped immediately on noticing (the account avatar button in the corner said so),
confirmed via the Google account chooser that the connected profile does not even have
`ramghatagedb1101@gmail.com` as an option -- so this specific browser is a different profile, not just
a same-profile mixup. The actual fix needed neither a profile switch nor `switch_browser`: a second tab
with a `/u/3/` URL (Google's own same-profile multi-account addressing) was already signed in as the
right account. Added a HANDOVER note ("Start here" item 5) so the next session checks the account
button and tries `/u/N/` URLs before assuming a full browser reconnect is needed.

With the right account confirmed, verified the phone app for real: opened the public URL
(`https://ramghatagedb1101-nsefo.github.io/market-hub/`) fresh, requested a sign-in code, owner read it
from email, signed in. Home (forecast bands with settled-outcome counts, "What changed for your
stocks" with real shortlist moves) and F&O (live NIFTY/BANK NIFTY iron condor structures) both loaded
real data, no console errors. Signed out afterwards. This is a genuine live confirmation of the phone
app's own sign-in path (`app_code`/`app_verify`/`app_data`), not an inference from "the owner has used
it, so likely fine."

### Fixed working_capital_days and dividend_paid/dividend_policy_change (G4, confirmed broken then fixed, ~14:10 IST)
`working_capital_days`, `working_capital_change` and `dividend_paid` had been a gap for every one of
2,574 companies since they were added -- never noticed because the fail-safe design (never fabricate a
figure for a wrong field-name guess) made it look like silence rather than a bug. Found by reading
`library_compact.json` directly and checking: 2574/2574, zero exceptions, while a confirmed-field-name
annual measure (`cfo`) from the same response was healthy (1,809 met / 655 not-met / only 110 gap) --
ruling out a broader annual-data problem.

- New one-off `hub/diag_financials_fields.py` (`diag.yml`): prints real quarterly/annual field names
  for RELIANCE/TCS/HDFCBANK. Pushed via a clean side branch cherry-picked onto `main` (not the held
  relay commits sitting on top of local `main` this session -- see the push-notification/bs_usage
  entries above) so the probe could run without dragging relay changes live mid-market-hours.
- **Working capital: a wrong guess.** Real names: `trade_receivables_current`, `trade_payables_current`
  (`inventories` already matched). Fixed in `hub/library.py`'s `wc_days()`, old guesses kept as a
  fallback.
- **Dividends: not a wrong guess.** Confirmed BharatStock's financials endpoint has no dividend field
  at all, quarterly or annual, for any of the three sampled companies. Removed the dead `dps()` guess
  from `cash_flow_values()` entirely (it could never have produced a value) and moved
  `dividend_paid`/`dividend_policy_change` into `company_values()`, sourced from `hub.corporate_actions`
  -- the same confirmed-working NSE source `dividend_yield` already uses. `dividend_policy_change`
  needs a year-over-year comparison: a second `ca.values()` call at last year's `as_of`, which is free
  (pure local filtering over records already fetched for `dividend_yield`, no extra network call).
  Also dropped both keys from `ANN_KEYS` (they were never really tied to the annual-refresh cadence).
- 5-case standalone test, all pass: real-name computation, stays-a-gap without the fields,
  `cash_flow_values` no longer touches dividends with no dangling reference (the removal would have
  been a `NameError` on every run if done carelessly), `company_values` computes both dividend fields
  from fake corporate-actions records, stays a gap with none.
- **Not yet seen on a live run** -- the next `library.yml` batch is the first real check.

### Stock screen's Kite calls batched across the whole universe, not one pair per stock (~14:50 IST, pushed)
The last item on the 13-14 Oct Kite/BharatStock audit, left open as optional: `rg/market_data.py`'s
`get_chain_snapshot(symbol)` made two Kite `quote()` calls per stock (one for the equity spot, one for
its option legs) -- for the ~100-stock Nifty 50 universe, ~200 separately-paced round trips at
`PacedKite`'s >=1.05 s gap, well over 3 minutes before a single recommendation was evaluated.

- New `prefetch_chain_data(symbols)`: **two** `kite.quote()` calls total, not 200. `PacedKite.quote()`
  already splits and paces any size internally into 500-instrument calls (`hub/sources/kite.py`, the
  13-14 Oct audit's own work) -- so one call covering every symbol's spot, and one covering every
  symbol's option legs, is enough; PacedKite does the real chunking underneath.
- `get_equity_spot` and `get_chain_snapshot` both check the resulting cache first and fall back to
  their own original per-symbol call for anything missing -- **neither function's interface changed**,
  so `rg/mtm.py`'s settlement-time spot lookup (a single symbol, no prefetch) and any other caller that
  skips the prefetch keep working exactly as before, just at the old pace.
- New shared `_chain_legs(symbol)` helper (pure local filtering over the already-cached NFO instrument
  dump, no network call) replaces duplicated expiry-resolution code in `get_chain_snapshot` and backs
  the new prefetch -- the two can never resolve a different expiry for the same symbol now.
- Wired into `hub/stocks.py` right before `generate_recommendations`, skipped in replay mode (belt and
  braces: `prefetch_chain_data` already no-ops under `CHAIN_CACHE_MODE=read` too, since `get_kite()`
  refuses there).
- 6-case standalone test (fake Kite client, no live calls, scratchpad `test_prefetch_chain_data.py`):
  exactly 2 `quote()` calls for 20 symbols; `get_equity_spot` reads the warm cache with zero extra
  calls, and still works correctly with no prefetch at all (the pre-existing behaviour, unchanged);
  `get_chain_snapshot` reads a fully-warm leg cache with zero extra calls; a partially-warm cache (one
  symbol's legs evicted to simulate it) fetches only that symbol's missing legs, not re-fetching what
  was already cached; replay mode makes no Kite call. All pass.
- **Not yet confirmed on a live run** -- the next `hub.stocks` invocation (today's 18:22 IST daily job,
  or tomorrow's) is the first real check; its log should show a new `[STOCKS] prefetched ...` line and
  a noticeably shorter run.

### Market Hub push notifications: phone, relay and sender built (code done ~14:10 IST; three owner steps left)
Starting with the Kite login reminder, which was supposed to come from the app itself, not Claude
(owner decision, recorded above) -- the claude.ai routine sending it today never actually reached the
phone.

- **`docs/sw.js`** (cache bumped to v31): a `push` handler (`showNotification`, JSON payload
  `{title, body, url}`) and `notificationclick` that always opens a new tab at `url` -- the Kite login
  link is an external site, so focusing an already-open Market Hub tab instead (the more common
  service-worker pattern) would silently do nothing useful here.
- **`docs/index.html`** Settings: a "Turn on notifications" button. `refreshPushUi()` feature-detects,
  checks for an existing subscription, and specifically checks `navigator.standalone === false` (iOS
  Safari, not opened from the Home Screen) to show "Add Market Hub to the Home Screen first..." instead
  of letting `pushManager.subscribe()` fail with a confusing error. `togglePush()` does
  `Notification.requestPermission()` then subscribes with the relay's VAPID public key
  (`app_push_key`) and registers the subscription (`app_push_subscribe`). Also fixed stale copy there:
  "before the 16:30 run" (long gone) -> "after 07:35 and before 09:05 IST" (today's real window).
  Verified in a plain static preview (`.claude/launch.json` added: `python -m http.server` over `docs/`)
  with the sign-in gate hidden via devtools, not a real session: the button renders correctly and
  `refreshPushUi()` runs clean (no console errors, correctly reports no existing subscription). Real
  push delivery needs the owner's actual phone, which this preview cannot exercise.
- **`relay/Push.gs`** (new file): `appPushKey_`/`appPushSubscribe_`/`appPushUnsubscribe_` (session-gated,
  routed through the existing `appApi_` in `Admin.gs`), key-protected `pushState_` (subscriptions +
  `kiteStatus_().state` + login link, for `hub/push.py`), `pushKey_` (POST: the sender workflow stores
  `VAPID_PUBLIC_KEY` here from its own GitHub secret, so the owner never opens Apps Script's
  script-properties page to paste it in), `pushDrop_` (POST: removes endpoints Web Push reports gone).
  `PUSH_SUBS` script property, de-duplicated by endpoint, newest 5 kept. Routed in `Code.gs`'s
  `doGet`/`doPost`. `node relay/check.js`: clean, no name clashes, all `AdminPage.html` calls still
  resolve. **Not deployed**: committed locally (same commit as the `bs_usage` relay change), held for
  CLAUDE.md's market-hours rule -- push both together after 15:30 today.
- **`hub/push.py`** (new) + workflow **`kite-reminder.yml`** (new; cron 02:06 and 03:03 UTC = 07:36 and
  08:33 IST Mon-Fri, after Kite's own ~07:30 clear-out and before the 09:05 close of the login window;
  `workflow_dispatch` with `mode=test` skips the holiday/already-logged-in checks and sends a plain test
  notification): `is_nse_holiday()` reads NSE's own `holiday-master` API (same Akamai-cookie session
  pattern as `hub/shareholding.py`) and fails toward sending if it cannot tell -- an occasional reminder
  on a holiday is a minor nuisance, a missed one on a real trading day defeats the whole feature.
  **Untested against a live NSE response** (blocked from the laptop, same as everything else that talks
  to nseindia.com); the first `kite-reminder.yml` run is the first real check of its parsing.
  `pywebpush>=2.0` added to `requirements.txt`. Syntax-checked only (`py_compile`); the full send path
  needs real VAPID keys and a real subscription, so it has not run end to end yet.
- **Owner, next** (never hand Claude the private key): `npx web-push generate-vapid-keys`; add GitHub
  secrets `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`; open Market Hub from the Home Screen, Settings, "Turn
  on notifications"; run `kite-reminder.yml` with `mode=test` and confirm it arrives and opens the Kite
  login page; only then switch off the claude.ai routine (`trig_011gp21txucmWGZPKqpR2FEu`).

### Relay counts its own BharatStock calls, finishing the shared budget (code done ~13:20 IST, deploy held for market close)
`hub/bs_budget.remaining()` already subtracted `relay_used()` from the shared 9,000-a-day cap, but the
relay never answered `?mode=bs_usage`, so every job's math has been treating the relay's clicks-driven
BharatStock calls (stock report, mutual-fund holdings, price charts) as zero all along.

- `relay/Code.gs`: `bsCount_(n)` adds to a script property `BS_USAGE` (`{date_utc, requests}`, reset on a
  new UTC day -- BharatStock's own reset is 00:00 UTC); `bsUsage_(p)` is the key-protected reader (same
  pattern as `handleCheck_`), returning `{date, requests}` to match what `hub/bs_budget.relay_used()`
  already parses; routed as `?mode=bs_usage` in `doGet`.
- Counted at the real fetch, not estimated: `Report.gs`'s `adminStock` (2 for fin+fina, counted before
  `fetchAll` so a mid-batch failure still counts the attempt; 1 per quarterly-pagination page), `Funds.gs`'s
  `adminFunds` (1 per mf-holdings page, up to 5), `Research.gs`'s `bsChart_` (1 per prices page, up to 3).
- `node relay/check.js`: clean (all files parse, no top-level name clashes, all 22 `AdminPage.html` server
  calls resolve).
- **Not deployed yet**: CLAUDE.md's market-hours rule (no `relay/*` push 09:15-15:30 IST, since a push
  deploys at once) -- committed locally around 13:20 IST, well inside that window. Push and deploy after
  15:30 today, then re-check `?mode=bs_usage` live before marking this closed (group C in STATUS.md's
  NEXT STEPS should pick up a live-check item for it).

### Removed the one-off BharatStock quota-headers probe (~13:10 IST)
`hub/diag_quota_headers.py` had already answered its question (no usage headers, no `/v1/usage`
endpoint -- see the audit entry below) and wasn't needed again, so removed it. The handover note said
to also drop its `BHARATSTOCK_API_KEY` line in `diag.yml`, but checked first: `diag_library_sample.py`
and `diag_shareholding.py` both still read that key, so removing the line would have broken two
reusable diagnostics for one dead one. Kept the line, fixed its comment (named the deleted module) to
name the two real users instead.

### Kite / BharatStock audit, remaining fixes (done in this session; the cloud's 19:30 routine never ran) (~09:00-10:40 IST)
- **One paced Kite client for every job** (`hub/sources/kite.PacedKite`; `rg/market_data.get_kite` uses it too): quote / ltp / ohlc calls >= 1.05 s apart across the whole process (Kite: 1 a second), historical candles 0.35 s apart, a "Too many requests" refusal waited out and retried (3 tries), quotes over 500 instruments split into paced calls, each exchange's instrument list downloaded once a day (memory + `.cache/kite_instruments/`, shared by every step of a job). Before: `rg/market_data.py` sent ~100-150 quote calls back to back; `hub/fno.py`, `hub/expiry_theta.py`, `hub/sources/commodities.py`, `hub/context.py` unpaced; NFO downloaded several times per job. Tested with a fake Kite (1,203 instruments -> 500/500/203, gaps 1.05-1.1 s, a refusal retried; 3 list requests -> 1 download).
- **Expiry calendar** (`hub/expiries.py`): from Kite's contract lists (NFO for NIFTY / BANK NIFTY, BFO for SENSEX), so holiday moves and rule changes follow by themselves; fallback `config.EXPIRY_RULE` (NIFTY weekly Tue, SENSEX weekly Thu, BANK NIFTY monthly last Tue). The old `EXPIRY_WEEKDAY` had BANK NIFTY Wednesday and SENSEX Monday, so the forecast hub's "expiry" horizon aimed both at the wrong day (`hub/horizons.py`). Past dates (back-tests) use the rule.
- **F&O chains read once** per (index, expiry) in `hub/fno.py` (nearest = monthly in a month's last week); **theta job** closes its four legs with one quote; `expiry-theta.yml` runs Mon+Tue (NIFTY expires Mon 19 Oct and Mon 9 Nov 2026; Tuesday-only would have missed them; the script no-ops on days without an expiry).
- **Checked on GitHub**: daily run 38500211113 on the new code (no Kite refusals; F&O nearest NIFTY expiry 2026-10-19, monthly 2026-10-27; 52 per-stock strategy lines as in the morning run, 0 recommendations in both: results season, a real result, not dropped data).
- **BharatStock shared budget** (`hub/bs_budget.py`, ledger `state/bs_usage.json` in the private repo, carried by the jobs' site_data pull/push): the library counts the other jobs' and the relay's use today against its 9,000; the manual multibagger scan and the multibagger back-test stop at what is left (the back-test had no limit and could use the whole day's allowance on its own) and record what they used. BharatStock reports nothing about usage (probe `hub/diag_quota_headers.py` on GitHub, 3 requests: no allowance headers, `/v1/usage` 404), so the count is ours. Still to do: the relay counting its own calls (`?mode=bs_usage`; until then it counts as 0). Tested: 9,000 - library 5,000 - multibagger 1,500 - relay 120 = 2,380 left.
- **Accounts**: the `gh` CLI's active account had flipped to ramghatage-ux (a push got 403; nothing was written as that account; all of today's commits and runs are ramghatagedb1101-NSEFO). Commands now name the account explicitly; CLAUDE.md's push command updated.

### Expiry history: raw chains kept, nothing dropped (~07:30-10:40 IST)
Owner: "make sure no data is lost". Records were derived figures only (walls, max pain, straddle), so a new question needed fresh downloads; a layout change dropped old records until re-collected. Now (record version 3) each expiry's raw chains (+-5% of spot: expiring chain the day before and two days before, next expiry's chain the day before) are kept in `state/expiry_history/chains/<INDEX>_<YEAR>.json`, and older records stay until replaced. A first re-run stopped NSE at once (the NSE index reader choked on SENSEX's missing NSE name; fixed); the old records survived as designed. Final: 399 expiries (NIFTY 159 incl. 13 Oct, BANK NIFTY 82, SENSEX 158), 12 chain files (2023-2026 per index), runs 38498995725 (SENSEX) and 38500005123 (NSE, 1,166 requests).

### Kite login reminder did not reach the phone (~08:30 IST)
The claude.ai routine ran at 07:37 and sent a push through the Claude app ("Mobile push requested"), which never reached the owner's phone; the owner expected it from the Market Hub app. Market Hub has no notifications yet. Approved: build web push for the Market Hub app on the owner's iPhone (Home Screen app), then switch the Claude routine off once a Market Hub push arrives. Plan in STATUS.md "Next up". The owner logged in at 07:40 (the relay started daily run 38499675068).

### Index rules tested walk-forward: the pull toward max pain does not improve the forecast; a narrower range does (~08:00 IST)
Owner: "go ahead" (rules per index, tested strictly before going live). `hub/expiry_rules_test.py`: forecast at the open, each expiry predicted only from earlier ones; pull toward max pain fitted separately for each distance band (open within <0.25 / 0.25-0.5 / 0.5-1 / >1 sd of max pain), starting at 0.
- **Point forecast, mean error vs the close**: NIFTY open 49.9 bp vs rule 50.2; BANK NIFTY 55.3 vs 56.5; SENSEX 53.0 vs 53.7 (none better; differences within noise, t +0.3 to +1.1). Cutting the forecast at the walls changes nothing. Fitted pull per band on all expiries: BANK NIFTY +0.10 / +0.06 / 0 / -0.14 (small), NIFTY -0.03 / -0.14 / +0.01 / +0.28, SENSEX -0.02 / +0.08 / +0.17 / +0.16.
- **Why the patterns do not carry into a forecast**: BANK NIFTY lands within one strike of max pain more often than chance (30% vs 19%), but on the other 70% of days the miss is as large as the open's, so the average error does not fall; SENSEX's walls hold more often than chance, but they are far from the open (both held 87% vs 80%), so they rarely change a forecast. These are facts about where price tends NOT to go, not a better centre.
- **Range (target: catches the close about 2 in 3)**: today's +-1 sd range (straddle / 0.8) caught 82% (NIFTY), 84% (BANK NIFTY), 76% (SENSEX): too wide, since straddles are overpriced. Calibrated walk-forward (68th percentile of past misses): 65% / 72% / 68% with widths 129 / 150 / 139 bp instead of 169 / 201 / 171 bp (about a quarter narrower at the right hit rate). Cutting it at the walls: SENSEX 66% at 130 bp (fine), NIFTY 52% (too narrow: NIFTY's walls are not barriers), BANK NIFTY 63%.
- **Decision pending (owner)**: no live change made. Candidate: per-index range factor (~0.76 NIFTY, ~0.75 BANK NIFTY, ~0.81 SENSEX, SENSEX range cut at the walls). Caveat: history uses the day-before straddle (overnight plus the day); live readings use the expiry-day straddle, so the factor would need checking on our own records.

### Expiry history, second look: four patterns the straight-line test missed (~07:20 IST)
Owner: "you say it is not useful, but I don't think so. Probably we are not analysing the right way." Right. The first test asked one question (does a straight-line formula on max pain and walls forecast the close better than the open, averaged over all days). New `hub/expiry_patterns.py` asks the questions traders actually mean, on the same 398 expiries (no new downloads), each against a shuffle baseline (other days' walls / max pain, scaled to this day's one standard deviation, on this day's real path), then split into first and second half of the period:
- **BANK NIFTY pins to max pain**: close within one strike of max pain 30.5% of expiries vs 19.0% by chance (p 0.002); both halves (26.8% vs 17.8%; 34.1% vs 22.0%). Strongest when the open is already near it: within 0.25 sd, the median expiry closed the whole gap (+1.01); within 0.25-0.5 sd, half of it; beyond 1 sd, nothing. A pull that works only up close, which a straight line cannot represent.
- **SENSEX walls act as barriers through the day**: the high stayed below the call wall 96.2% vs 92.5% by chance (p 0.007), the low above the put wall 90.5% vs 86.1% (p 0.008); both walls held all day 87% vs 81% (first half), 86% vs 79% (second half), and in every era. SENSEX also moved toward max pain from the previous close 68% of the time (44 of 65; 76% first half, 61% second half).
- **NIFTY moves AWAY from max pain** from the previous close: only 25% of expiries ended closer to it (14 of 55, p ~0.0003); 24% first half, 27% second half. Max pain sits where the open interest was built, so on trending days it lags behind. NIFTY's walls are not barriers (close between walls 69.6% vs 73.3% by chance). Exception, small sample: when the open is more than 1 sd from max pain, 13 of 16 moved toward it.
- **Expiry-day straddles are overpriced on all three**: from the day-before forward to the close, the move averaged 89% of the day-before straddle on NIFTY and SENSEX (sellers kept ~11% of premium) and 83% on BANK NIFTY (~17%); the close was inside one standard deviation 75% (NIFTY, SENSEX) and 80% (BANK NIFTY) of days against a normal 68%. Before costs.
- **Since the closing auction (Aug 2026)**: NIFTY's close was between the walls 4 of 10 expiries vs ~6 expected; too few to conclude, worth watching.
- **Caveats**: about 40 comparisons were run; a couple of p-values near 0.05 can be chance. The three headline patterns hold in both halves; p-values are against the shuffle baseline. All from the evening-before chain and end-of-day prices.
- **Not changed yet**: the live meter. These point to index-specific rules (BANK NIFTY: pin only when near; SENSEX: walls as range limits; NIFTY: no pull to max pain), which need their own walk-forward test before going live.

### SENSEX in the expiry history test (BSE data); SENSEX starts from its own fit (~01:15 IST; relay Version 65, commit 4e6614e)
Owner: "add SENSEX to the history test using BSE data".
- **Data** (checked from GitHub with a one-off diag, now removed; curl_cffi, as BSE refuses plain requests): BSE's derivatives bhavcopy in UDiFF layout (`download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_YYYYMMDD_F_0000.CSV`, present from at least 2 Jan 2024), before that BSE's own zip (`download/Bhavcopy/Derivative/bhavcopyDD-MM-YY.zip`: Contract Type IO, Option Type CALL/PUT, Open Interest); SENSEX daily OHLC from BSE's `ProduceCSVForDate` (753 days in one request). BSE answers a missing day with its home page, not a 404: treated as a holiday. SENSEX50 excluded. No participant signals (NSE's file covers NSE only).
- **Run 38456243321**: 158 SENSEX expiries (6 Oct 2023 - 8 Oct 2026), 377 BSE requests; NSE needed 4 (all recorded).
- **SENSEX results** (mean absolute error vs the close, bp): open 53.0; max pain 60.9; wall midpoint 71.4; meter formula fitted walk-forward 53.5, old starting weights 53.8. Close between the walls 91.8% (wide walls); toward max pain 57.3% of 124 days (71 of 124; not significant, z ~1.6). Fit k 0.18, m 0.10, v -0.13. No direction signal with |t| >= 2. Move size: net gamma + 0.64 sd vs - 0.66; event days 0.73 sd (n 6, 33% outside 1 sd vs 23%), too few. Pin within half a step: max-gamma strike 9.5%, max pain 8.2%, strike nearest the open 9.5%.
- **Same answer as NIFTY and BANK NIFTY**: walls and max pain from the evening before do not beat the open.
- **Starting weights**: SENSEX had borrowed NIFTY's (no history); now its own fit, k 0.18, m 0.10, v -0.13 (`EXP_START`), following the owner's "set the weights to the history fit". Checked: `node relay/check.js` exit 0; simulated SENSEX day (Kite >= 1.1 s apart, cache max 52 KB, property max 4.7 KB, close recorded); deployed by relay-deploy (Version 65, content matched), before the first live SENSEX expiry (Thu 15 Oct 2026).

## 2026-10-13

### Expiry meter: starting weights from the history fit (night; relay Version 64, commit d1938dc)
Owner: "set the weights to the history fit".
- **Starting weights per index** (`EXP_START`, relay/Expiry.gs), from `hub/expiry_history.py` on 3 years of expiries: NIFTY k 0.18, m -0.13, v 0.17 (158 expiries); BANK NIFTY k -0.23, m 0.19, v 0.04 (82); SENSEX starts from NIFTY's (no BSE history yet). Europe and US (e, u) stay 0. Before: k 0.30, m 0.20, v 0 for every index (guesses). Spreads unchanged, so live expiries still re-fit them.
- **What it does now**: NIFTY with the one recorded expiry (13 Oct) re-fits to k 0.12, m -0.19, v 0.17 (was k 0.22, m 0.13 from the old start). In words: the meter now leans only slightly toward max pain, slightly away from the wall midpoint, and a little toward next week's wall midpoint.
- **Caveats, as before**: fitted at the open from the evening before, not on readings through the day; even fitted, the formula did not beat the open on history (NIFTY 50.2 bp vs 49.9 walk-forward). The track record against the forward is the judge from here.
- **Checks**: `node relay/check.js` exit 0; model with no expiries returns the starting values per index; with the real 13 Oct readings, as above; simulated SENSEX day (Kite requests >= 1.1 s apart, largest cache value 52 KB, largest property 4.7 KB, close recorded). The model cache key changed (`exp_ma2_`) so the new weights apply at once. Deployed by relay-deploy (Version 64, content matched).

### Step-5 signals tested on 3 years of expiries: none goes into the meter; one candidate to watch (night)
Owner: "yes, extend the history test". `hub/expiry_history.py` (record version 2) now also collects, for each of the 240 expiries, the expiring chain two trading days before (walls' day-over-day move, OI built or cut at the walls), gamma per strike from implied volatility (Black-76 on the day-before forward), NSE's participant-wise OI the day before (`fao_participant_oi`, client / DII / FII / pro; layout checked from GitHub with a one-off diag, now removed) and event days (RBI decisions from the RBI calendars, Union Budgets, 4 Jun 2024). Run 38401126652: 1,160 NSE requests. 14 direction signals per index, each judged by correlation with close - open and by walk-forward error with the signal added; then checked for robustness (rank correlation, without the 5 biggest moves, first half vs second half).
- **Wall movement (day over day)**: nothing. NIFTY |t| < 1.6 for all four forms. BANK NIFTY's OI-build signals showed t -3.3 / -4.1, but rank correlation ~0, ~0 without the 5 biggest moves, and the sign flips between halves: driven by a few big days (5 Jun 2024, 30 Mar 2026, 13 Nov 2024), and they made walk-forward error worse (61 bp vs open 55). Moves within the day can only come from our own record (from Thu 15 Oct 2026).
- **Gamma**: nothing. NIFTY max-gamma strike t 3.0, but rank correlation 0.06, 0.03 in the first half: outliers. Pinning: the close landed within half a step of the max-gamma strike 15.2% of NIFTY expiries, the same as the strike nearest the open (15.2%; max pain 10.8%). Move size did not shrink with positive net gamma (NIFTY 0.62 sd vs 0.56 negative, n 19) or with gamma concentrated near the forward (0.63 vs 0.53 sd); the market already prices those days with a smaller straddle (50 vs 91 bp).
- **Who holds index options**: one candidate. BANK NIFTY vs FII net index puts the day before: correlation -0.49 (t -5.0, n 82); holds up: rank -0.32, -0.28 without the 5 biggest moves, -0.59 and -0.50 in each half (FIIs net long puts -> BANK NIFTY lower at the close than the open). But it barely helps the forecast (walk-forward 54.6 bp vs open 55.3), it is a market-wide number (all index options, mostly NIFTY) yet shows nothing for NIFTY (t -0.4), and 28 signals were tried. Client net puts is its mirror image, not a second finding. Not added; re-tested as new monthly BANK NIFTY expiries arrive.
- **Event days**: on 4 NIFTY event expiries the straddle was already 103 bp vs 67 on other days, and the move in standard deviations was the same (0.63 vs 0.62): the market widens the range by itself, so a separate event adjustment would double-count. Too few days (4 + 1) for more.
- **Decision**: nothing added to the live meter; the dashboard keeps showing the walls record as information. Re-run `expiry-history.yml` monthly (fetches only new expiries) to re-test.

### Expiry meter: empty walls charts explained (night; relay commit c6001aa)
Owner, with a screenshot: "why these graphs are not showing any data even after market close". Cause: the minute record of the walls (relay Version 61) went live at ~17:15 IST, after today's close, and the relay records only 09:15-15:30, so today has no rows (the saved day file `state/expiry/2026-10-13_NIFTY.json` has 0). The "+0.0 L" changes come from the baseline being taken at 17:18, after the close. Not a drawing bug; Thursday 15 Oct 2026 (SENSEX) will be the first full day (the recorder starts 09:05). Now the empty charts say so instead of showing blank axes, and the baseline line reads "taken after the close: no changes to show". Checked in the preview: empty day (messages, no blank charts) and a normal day (all 12 charts drawn); `node relay/check.js` exit 0.

### Expiry history test (item 4): walls and max pain from the evening before do not beat the open (night)
New `hub/expiry_history.py` + `expiry-history.yml` (manual; NSE blocks the laptop). From NSE's free end-of-day files (old F&O bhavcopy to Jul 2024, UDiFF after, daily index file; formats checked from GitHub with a one-off diag, now removed): for every NIFTY and BANK NIFTY expiry since Oct 2023, the day-before chain within +-3% of the close (forward, ATM straddle, max pain, walls, next expiry's walls) against the expiry day's open and close. First run (run 38398089119): 240 expiries (NIFTY 158, BANK NIFTY 82), 617 NSE requests, saved to the private repo `state/expiry_history/` (records.json, summary.json); later runs fetch only new expiries.
Results (mean absolute error vs the close, bp):
- **NIFTY**: open 49.9; max pain 66.1; wall midpoint 75.2. Meter formula fitted walk-forward 50.2, with today's starting weights (k 0.30, m 0.20) 52.3: worse than the open. Close moved toward max pain on 47.7% of 109 days the open was a step or more away (a coin flip). Close between the walls 69.6%; within half a step of max pain 10.8%. Fit on all 158: k 0.18, m -0.13, v 0.17. Weekly k 0.33, monthly k -0.12; since Sep 2025 (Tuesday expiries, 58) k 0.33, beat the open 23 of 58.
- **BANK NIFTY**: open 55.3; max pain 74.2; wall midpoint 80.4; walk-forward fitted 56.4, starting weights 59.8. Toward max pain 57.1% of 63 days. Fit k -0.23, m 0.19.
- **Reading**: read the evening before, max pain and walls add nothing over the open; the starting weights make the 09:15 forecast slightly worse. Not tested (end-of-day data cannot): how the morning's own OI and the intraday readings do; that is what the live record (`state/expiry/`) is for. The weights were NOT changed: owner's decision (see STATUS).
- **Limits**: open used as the 09:15 forward; OI from the evening before, not the morning; within-1-sd 80% is measured from the open with the day-before straddle (which also covers the overnight move), so it overstates the range's coverage.

### Phone: expiry range labelled correctly (evening)
Owner: "fix the phone range label too".
- **Before**: the phone's F&O tab showed the ATM straddle range (±straddle) and called it "about 2 in 3". A straddle is about 0.8 standard deviations of the move left, so ±straddle catches the close only about 3 times in 5.
- **Now**: `hub/expiry_day.py` writes the relay's one-standard-deviation range (`likely`, straddle ÷ 0.8, relay Version 62) and its size (`sd`) to `expiry.json`. The phone row reads "Market's expected range (±115, about 2 in 3; ATM 25,300 straddle 91.8 ÷ 0.8)". If the file comes from an older relay answer without `sd`, the row falls back to the straddle range and says "about 3 in 5". The note under the panel says the same. "Likely close range" (that range clipped to the walls) now uses the one-standard-deviation range too, so it is a little wider than before. Phone cache v30.
- **Checked**: the file builder run on a simulated relay answer (NIFTY sd 114.75 from straddle 91.8; older answer falls back to ±straddle); phone rendered at 375 px (no sideways scroll).

### Expiry meter: judged against the forward, uncertainty from the straddle, settlement rule checked; whole-day chart (evening, laptop session; relay Version 62, commit b13c14e)
Items 1-3 of the agreed next steps, plus the owner's chart complaint.
- **Track record against the market** (`expiryAccuracy_`, page `expTrack`): at 10:00 / 12:00 / 14:00 / 15:00 each expiry shows the meter's error and, under it, the forward's error at the same moment (forward = strike + call - put at the ATM strike, already in every reading), with "meter closer to the close than the forward: X of Y" as the headline and "within 25 bp" demoted to a second line. On the one real expiry (NIFTY, Tue 13 Oct 2026, close 22,721.95): 14:00 meter -73 bp vs forward -70 bp; 15:00 meter -16 bp (inside the old 25 bp "hit") vs forward 0 bp. The forward was closer both times: so far the meter has not beaten the market's own estimate.
- **Uncertainty from the straddle** (`expirySd_`, `expiryModel_`): each reading now stores its ATM straddle (`p[8]`, from Thu 15 Oct 2026); its noise is straddle / 0.8 (about one standard deviation of the move left), floored at 0.05% of the level; older readings keep 0.4% of the level. Within an expiry late readings now count more than early ones; each expiry's total weight is kept as before, so one day still only nudges the weights. Dry run on synthetic expiries (true k 0.6, start 0.30): with the cap, k moves to 0.31 after 1 expiry, 0.44 after 12 and about 0.52 after 30 (old fixed noise: 0.32 / 0.46 / 0.55). Without the cap (the literal version), learning is faster (0.59 after 12) but one expiry moves k to 0.47-0.50, the swing the review rejected earlier. The cap is a choice, not a law: it can be loosened once expiries show the readings are less correlated than assumed.
- **Shown range**: "likely" is now pred ± one standard deviation (straddle / 0.8), about 2 in 3. The old ± straddle covers about 3 in 5, not 2 in 3. `range` (± straddle) is kept unchanged for the phone, whose label still says "about 2 in 3" (`docs/index.html`, `hub/expiry_day.py`; not changed here: they were outside this task's files).
- **Settlement averaging: checked, built, switched off.** The plan assumed the index close is each stock's volume-weighted price over 15:00-15:30. That stopped being true on **3 Aug 2026**: SEBI moved every stock with F&O contracts (all NIFTY 50, BANK NIFTY and SENSEX stocks) to a 15:15-15:35 closing auction at **both NSE and BSE**, and index options settle on the index close built from those auction prices. Before that, both exchanges used the 30-minute average, so SENSEX was never different from NIFTY here. SEBI's consultation (Sep 2026, comments closed 3 Oct, about 20,000 received) proposes settling derivatives on a 30-minute average of continuous trading again; as of 12-13 Oct 2026 reports expect guidelines "within a week" and no final rule or date. So `EXP_SETTLE` = auction, and the meter states the rule ("Settles on the 15:15-15:35 IST closing auction... the forward is the market's estimate of the auction") instead of blending. When SEBI's circular lands, set `method: 'average'` and its window (15:00-15:30, or 14:45-15:15 if continuous trading still stops at 15:15): the meter then blends expected close = (elapsed / window) x average so far + (left / window) x model, records the index once a minute (`exps_<IDX>_<date>`, under 1 KB, saved in the day file), and narrows the range to the part still unknown. Sources: SEBI/CAS coverage by Zerodha support, Business Standard (12 Sep 2026), marketseasy.in, Eastern Herald (12 Oct 2026).
- **Whole-day chart, nothing after the close** (owner, with a screenshot: the chart showed only 16:14-17:11 after the close): relay Version 60 (live ~16:10 to the evening update) wrote chart rows at any hour, and today's market-hours rows were under the morning's old cache name, so the chart showed only after-close minutes. Now: the relay sends only 09:15-15:30 rows (also in the saved day file); every chart on the meter has a minute axis over the whole session, with Day / 2h / 1h / 30m buttons; after 15:30 the panel shows the meter's final reading, and once the close is recorded (after 15:45) "Closed at <close>" with how far the meter and the forward were from it; the page stops polling once every expiring index's close is in. Today's (13 Oct) session minutes cannot be recovered; Thursday's SENSEX day will be complete.
- **Saved 13 Oct**: `expiry-tape.yml` run by hand at 17:36 IST (run 38394888767): `state/expiry/2026-10-13_NIFTY.json` (15 readings 13:45-15:23, close, and the after-close chart rows, which the new filter drops from future files).
- **Checks**: `node relay/check.js` exit 0. A new simulator (mocked Apps Script cache/properties/lock, mocked Kite with a priced option chain, fake clock) ran full days: Thu 15 Oct SENSEX watched and recorder-only, Tue 27 Oct NIFTY + BANK NIFTY watched, recorder-only with averaging on, Wed 14 Oct (no expiry). Every day: Kite requests at least 1.1 s apart (1,641 requests watched, 783 recorder-only, 0 on the non-expiry day), largest cache value 52 KB (`expw_*`, limit 100 KB), largest property 4.7 KB (`EXPD_*`, limit 9 KB), close recorded, day file built (76 KB per index). Averaging mode: the weight steps 0 -> 1/3 -> 2/3 -> 1 from 15:00 to 15:30 and the range narrows to 0. Planted after-hours rows are dropped. Dashboard rendered at 375 px (no sideways page scroll; the track table scrolls in its panel) and at desktop width: live meter, averaging note, auction note, 1h window (11:00-12:00), after-close view.

### Kite login reminder, and the next steps for the expiry meter (evening)
- **Kite login reminder** (owner's request): a phone notification every weekday at 07:36 IST (claude.ai Routine "Kite login reminder", a fresh cloud session each morning; first Wed 14 Oct 2026). It checks NSE's holiday list and says "no login needed" on a holiday; if NSE's list cannot be read it reminds anyway. 07:36 rather than the 07:30 asked for, agreed by the owner: Kite clears logins each morning until about 07:30 (the relay's Kite day starts 07:35), so a login made on a 07:30 ping could be wiped minutes later. No connectors, no repository access.
- **Expiry meter, agreed but not built yet** (owner: "what else can make the prediction better?"). Honest starting point: one expiry recorded, and no comparison with the market's own forecast, so today nobody can say whether the meter adds anything. Agreed order:
  1. Track record shows the meter's error beside the forward's (the market's own estimate) at each time, and "beat the forward in X of Y". At 15:00 the expected remaining move is only ~20-30 NIFTY points, so "within 25 bp" alone proves little.
  2. Each reading's uncertainty from its ATM straddle instead of a fixed 0.4% of the level (a 10:00 reading faces roughly four times the move left of a 15:00 one).
  3. From 15:00, use how the close is made: NSE's index close comes from each stock's volume-weighted price over 15:00-15:30, and expiry settles on it; by 15:20 two-thirds of it is fixed.
  4. Next: test max pain and walls on ~3 years of past expiries from NSE's free F&O end-of-day files (Kite has no data for expired options), and fit the starting weights from that instead of guesses.
  5. After ~10 recorded expiry days: wall movement, gamma exposure, NSE participant-wise OI, event days.
  Not planned: more indicators on one expiry of data; GIFT Nifty in market hours (it moves with NIFTY futures). A realistic target is beating the forward at 12:00 and 14:00 and being tight from 15:15; a steady 25 bp at 10:00 would mean out-forecasting the options market with public data.

### Option sellers' walls tracked through the day, with next week's walls beside them (evening)
Owner: sellers decide the expiry close; quantify the walls and max pain, track them (the meter refreshed every 10 s but kept none of it), and watch how next week's walls build, since sellers roll into it on expiry day.
- **Recorded every minute, 09:15-15:30, per expiring index** (`relay/Expiry.gs`, `expw_<IDX>_<date>`): spot, forward, straddle, max pain, call wall and put wall (strike and open interest), total call and put OI, what sellers would pay at settlement here, the extra for one step up and one step down, and the next expiry's walls, max pain and OI. Kite's OI is in units (checked: every NIFTY figure in today's file is a multiple of the 65 lot), so OI x points = rupees.
- **Baseline**: OI per strike at the day's first reading (`EXPB_<IDX>_<date>`, today's only); before 09:15 that is the previous close's OI, so changes read like NSE's "change in OI". Shown: each wall's change, total call and put OI change, strikes with the most writing and the most closing.
- **Next expiry's chain** (`relay/Market.gs`): one extra Kite request a minute on expiry days, inside the same lock, 1.1 s after the main one (never two requests in one second). Dry run: 7 requests a minute with the dashboard open (was 6), 2 a minute with only the recorder; longest URL 1,880 characters on the NIFTY + BANK NIFTY day (limit 2,000); contract lists now cached packed (31.6 KB for two indices' today + next expiries, under the 100 KB cache limit).
- **No gaps when nobody watches**: new `expiry-tape.yml` calls the relay once a minute from 09:05 to 15:46 IST on expiry days (two runs, 09:08 and 12:33, because a job may run only 6 hours), exits at once on other days, makes no Kite call of its own, and after the close saves the whole day per index to the private repository (`state/expiry/<date>_<IDX>.json`, ~75 KB). The relay keeps minute rows only 6 hours; these files are what a later test of "which signal actually predicted the close" needs.
- **Learning**: a fifth weight v on the next expiry's wall midpoint (starts at 0, spread 0.3), learned like Europe and US: it counts only once past expiries show it helps. Old readings carry no information on it. Dry run after two expiries: v 0.01.
- **Dashboard** (Expiry meter): an "Option sellers' walls" panel (today's expiry beside the next: walls with size and change, other walls, max pain, PCR, OI change, most writing and closing); "What sellers pay at settlement" (here vs max pain, cost of one step each way, rupees per step past each wall); charts of the walls and max pain through the day and of wall size through the day (dashed = next expiry); open interest by strike for both expiries behind a tap. Only new minute rows are sent every 10 s (4 KB instead of ~50 KB). Checked at 1366 px and 375 px, one and two expiring indices, charts drawn.
- **Phone** (F&O tab, cache v29): wall OI change, sellers' payout here and at max pain, extra per step, next expiry's walls and max pain.
- **Checks**: payout and max pain against a hand calculation; a simulated full NIFTY day (every 10 s, 09:05-15:50: 376 minute rows, close recorded, archive built), SENSEX day with only the recorder, NIFTY + BANK NIFTY day, contract lists failing (name fallback, no next-expiry request), non-expiry day (no Kite call; recorder exits after one relay call). Not yet seen on a live expiry: first run SENSEX Thu 15 Oct 2026.
- **Limits, stated plainly**: OI is two-sided and many sellers are hedged, so the payout figures are pressure, not a rule; walls move and break on news days, which is exactly what the record now shows. Strikes outside ±3% of spot are not read (Kite URL budget). If Kite is logged in after 09:05, the baseline is that later reading and the page says "since HH:MM".

### Expiry meter for NIFTY, SENSEX and BANK NIFTY, adapting by itself (built after the close)
Owner: the same meter for BANK NIFTY and SENSEX, weekly and monthly; the screen must adapt to the day (Tuesday, Thursday, month end with two expiries) without any switching.
- **Which expiries exist** (Kite's contract lists, checked 13 Oct 2026): NIFTY weekly (Tue; Mon 19 Oct and Mon 9 Nov 2026 for holidays) and monthly (last Tue); SENSEX weekly (Thu) and monthly (last Thu); BANK NIFTY monthly only (last Tue) -- the 2024 rule allows one weekly index per exchange.
- **One engine** (`relay/Expiry.gs`): a settings row per index (exchange NFO/BFO, spot, strike step 50/100); contract lists from Kite's public NFO and BFO files, read once a day per exchange (a failed download remembered 10 minutes, never cached as empty); holiday moves followed automatically. Name fallback per index if a list fails.
- **Still one Kite request** (`relay/Market.gs`): indices and watchlist first, then today's options for every expiring index, nearest strike first, taken in turn per index until the URL budget is used. Dry run: Tue 27 Oct (NIFTY + BANK NIFTY) = 1 request of 1,894 characters with a 60-stock watchlist (2 on a day's first call, to learn the spots).
- **Learning per index**: `EXPD_<IDX>_<date>`, `EXP_CLOSES_<IDX>`, own weights; this morning's NIFTY readings moved to the NIFTY names automatically.
- **Learning fixed before the first real expiry counted**: the dry run showed one expiry with 2 readings swinging k from 0.30 to -1.64 (the close differs from a reading mostly by the market's later move, which the old fit read as signal). Now a Bayesian ridge: each reading carries its real noise (0.4% of the level), each expiry counts once, each weight has a start value and spread, and weights stay within bounds. Check: one expiry moves k 0.30 -> 0.28; 12 synthetic expiries with a true k of 0.60 give 0.58 (other weights stay near 0).
- **Dashboard** (Analysis -> Expiry meter): opens on whatever expires today; on a double day each index gets its own meter, stacked; other days show the next expiry per index and every index's track record. Gauge end labels no longer cut off; a chart-library failure no longer shows as "could not reach the relay".
- **Phone and live job**: `expiry.json` now has one item per expiring index (`items`); the phone shows one block each. The live job prints each index's latest track record (`TRACK` notice).
- **Dry runs**: Tue 13 Oct NIFTY, Wed 14 Oct none (next: NIFTY Mon 19 Oct, SENSEX Thu 15 Oct, BANK NIFTY Tue 27 Oct), Thu 15 Oct SENSEX, Mon 19 Oct NIFTY, Tue 27 Oct NIFTY + BANK NIFTY, Thu 29 Oct SENSEX monthly, lists failing on 27 Oct (both found by name) and 28 Oct (correctly none); close recorded after 15:45. Page rendered at 1366 px and 375 px. First live run: SENSEX, Thu 15 Oct 2026.

### Kite / BharatStock call audit (7 reviewers incl. a completeness critic) and first fixes
- **Findings**: the live relay is at its floor (1 Kite request per 10 s). The daily GitHub jobs are the real Kite risk: `rg/market_data.py` sends ~100-150 quote calls back to back per run (2-4 a second against Kite's 1), so refusals quietly drop stocks from screens; `hub/fno.py` and `hub/expiry_theta.py` also send unpaced calls; instrument lists are downloaded more than once per job. BharatStock daily use is fine (relay ~20 of 1,000; the library's `needs()` budget holds); the only way to blow the 9,000 is a manual multibagger or back-test run, which no budget counts.
- **Fixed now (relay Version 59, phone v27)**:
  - Licence: a chart built from BharatStock prices was cached for 5 minutes; it is no longer cached at all.
  - Bad-day thrash: a failed NFO contract list or NSE token list is remembered 10 minutes (it was downloaded again on every 10-second build); a failed Kite snapshot is remembered 30 seconds (the public quote URL could otherwise retry Kite on every call); a snapshot request that waits past the lock serves the last good snapshot instead of fetching again.
  - Overseas: a market counts only when its last price is from today (before Europe opens, Yahoo's "today" is yesterday's session, already in NIFTY's open); a missing reading is stored as unknown, not as a flat market. The meter marks such markets "not open today yet".
  - Phone: no quote polling while the app is hidden, and every 5 minutes outside market hours (it polled every 60 s round the clock).
- **Scheduled for tonight** (with the multi-index meter): batch and pace the daily jobs' Kite calls (one quote for all spots, chains in 500-contract calls a second apart, one download per instrument list per job), one quote for the theta job's spot and legs, de-duplicated `fno.py` chains; budget the manual BharatStock runs against the shared cap and count the relay's own BharatStock calls.

### Expiry meter: fixes from an independent review (12 reviewers, each finding checked by a sceptic)
6 findings confirmed against the live code (others were rejected, mostly as already fixed):
- **Walls**: the ATM strike now counts on both sides. With strict above/below spot, a pinned strike flipped from call wall to put wall as spot crossed it, and the expected close could jump up to ~100 points on a 3-point move.
- **Close recording**: done as soon as the NIFTY level is known after 15:45, no longer only when the whole option chain also arrived.
- **Name fallback**: monthly contract names only on the month's last Tuesday (they made the Monday before look like an expiry day, with fake readings and a fake close).
- **Page**: errors are checked before "no expiry" (a missing Kite login no longer reads as "no expiry today" and stops the polling); a reading older than 30 s, or a failed call, shows "Stale · last good reading HH:MM IST" instead of "Live"; after 15:45 it says "After the close"; background data loads no longer restart the meter; the track record scrolls inside its panel on a phone.
- **Learning** (unverified finding, accepted on inspection): each expiry counts once whatever its number of readings, and the prior is worth 5 expiries (before: 20 readings, so one fully watched day outweighed it).

### Overseas markets in the expiry meter and the strip
Owner: does the meter consider overseas markets? Europe is open during Indian hours and moves India; so does the US.
- **Before**: no -- the meter used only NIFTY's option chain (which already prices overseas moves made so far, but nothing explicit).
- **Source**: one free Yahoo Finance request (`v8/finance/spark`) for DAX, FTSE 100, Euro Stoxx 50, CAC 40 and S&P 500, Nasdaq 100 and Dow futures, cached 60 s (`overseasSnapshot_`, `Market.gs`). Checked from GitHub: all seven answered in one call (13:58 IST: DAX +0.52%, FTSE +0.73%, S&P fut -0.03%, Nasdaq fut -0.56%). No Kite or BharatStock use.
- **Model**: expected close gains + e × F × Europe move % + u × F × US futures move %; e and u start at 0 and are learned with k and m (4-weight ridge fit; each reading now stores the Europe and US averages). They count only once past expiries show they help, so today's expected close is unchanged by them.
- **Shown**: an Overseas markets panel on the meter (each market, the Europe and US averages); DAX, FTSE 100, S&P 500 and Nasdaq futures on the dashboard strip.

### One Kite request for the live platform (`relay/Market.gs`)
Owner: "one Kite request should be used for multiple data points; never multiple calls for multiple data points" -- across the whole platform.
- **`marketSnapshot_()`**: one Kite quote request per 10 seconds, shared by every caller through the script cache, with a script lock so simultaneous callers wait for it instead of each calling Kite. It carries NIFTY 50, NIFTY BANK, SENSEX, INDIA VIX, front-month gold and crude, USD/INR and, on a NIFTY expiry day, today's NIFTY options within 3% of spot. Only last price, previous close and open interest are kept.
- **Readers**: `quoteData_` (dashboard strip, phone `mode=quote`, the live job's relay check) and `expiryNow_` (expiry meter) no longer call Kite themselves. Dry run: meter, quotes, meter, quotes in a row = 1 Kite request, same timestamp on both.
- **Folded in the same day**:
  - The watchlist rides in the snapshot: move emails (`watchCheck_`), the watchlist's returns and price-at-starring (`kiteLtp_`) read it. Only a company being starred that is not yet in it costs one small call.
  - The snapshot asks for options and watchlist stocks by Kite's numeric instrument token (accepted alongside names; probed on GitHub 13 Oct 2026). The request URL shrank from about 1,680 to 790 characters, so indices, today's options and a 60-company watchlist still fit one request.
  - The GitHub live job no longer logs in to Kite: `hub/live.py` writes live.json from the relay's `mode=quote`, and `hub/expiry_day.py` writes the phone's expiry.json from the relay's expiry reading (`mode=expiry_close`, which also records the meter's reading). Its three relay calls run back to back and share one snapshot.
  - Dry run: meter, quotes, watchlist prices and the move check = 1 Kite request.
- **Phone**: the expiry panel also shows the meter's expected close. Cache `market-hub-v26`.
- **Not changed** (separate by nature, all on demand or daily): the login itself, Kite's public contract lists (cached a day), Kite candle history for a chart you open, BharatStock figures for a stock report you open, and the daily batch jobs. A platform-wide inventory of every Kite and BharatStock call is being compiled.

### Dashboard market strip; call budget for the 10-second pages
Owner: current market levels were not visible on the dashboard; and none of this may exhaust the Kite, BharatStock or other limits.
- **Market strip** (every dashboard page, under the header): NIFTY, BANK NIFTY, SENSEX, VIX, and gold, crude, USD/INR when Kite has them, with change %, and "Live · HH:MM IST" or "Last quote · HH:MM IST · Day d Mon yyyy". Relay `adminQuotes` = the phone's quote call (`quoteData_`, `Code.gs`; the phone's `mode=quote` answer is unchanged). Wraps onto extra lines on a phone (checked at 1366 px and 375 px).
- **Budget** (worst case: one or more dashboards open on the expiry meter all session, 09:00-15:45 IST):
  - Kite: at most 1 quote request per 10 s for the strip (shared 10-second cache with the phone) and 1 per 10 s for the meter (its contracts now fit one request: range 3% of spot; a split request would go one per second with one retry on "too many requests"). About 0.2 requests a second against Kite's 1 a second; Kite has no daily cap on quotes.
  - Google Apps Script (consumer quotas): about 4,900 fetches against 20,000 a day; property reads cut by caching the session check (60 s), the model and track record (1 h, cleared when a close is recorded) and the sampling clock (cache, not a property).
  - Outside market hours the strip refreshes every 5 minutes and the meter every minute; hidden tabs make no calls.
  - BharatStock: none of today's features call it (the 9,000-a-day budget is untouched). GitHub Actions: public repo, no minute charge.

### Dashboard: NIFTY expiry meter that learns from each close
Owner: a meter on the dashboard's Analysis section showing the current expected close, refreshing every 10 seconds, with a graph of how it moves through the day; it should correct itself from how each expiry actually closed.
- **Relay `Expiry.gs`** (`adminExpiry`, cached 10 s): one Kite quote call for spot and today's NIFTY options within 4% (contract list from Kite's public instrument file, cached for the day). Expected close = forward + k × (max pain − forward) + m × (wall midpoint − forward); forward = ATM strike + call − put (put-call parity: the market's own expected settlement). Range = expected close ± ATM straddle (about 2 in 3).
- **Learning**: a reading at least every 5 minutes (09:15-15:30) is kept per expiry (script property `EXPD_<date>`); after 15:45 IST the close is recorded (`EXP_CLOSES`, last 30 expiries). k and m (start 0.30 / 0.20) are re-fitted from all readings against the closes by least squares, held towards the starting values while there are few expiries (prior worth 20 readings). `live.yml` calls `mode=expiry_close` every run, so readings and the close are recorded even when nobody has the meter open.
- **Dashboard** (Analysis → Expiry meter): big expected-close figure, a semicircle gauge (range, put wall, call wall, max pain, spot, needle at the expected close), a line chart of expected close vs spot vs max pain through the day, forward / max pain / PCR / walls, and a track record table (expected close at 10:00, 12:00, 14:00, 15:00 vs the close, with the error). On other days it shows the next expiry and the track record.
- **Checked**: `node relay/check.js` exit 0; a dry run with a simulated chain (walls at 22,500 / 22,600) gave expected close 22,528, range 22,440-22,616; after one simulated expiry closing at max pain, k and m moved from 0.30 / 0.20 to 0.36 / 0.26 as intended; the close was recorded after 15:45 and the accuracy table filled.
- **Same-day fix (Version 51 → 52)**: the first live view said "No NIFTY expiry today. Next expiry: –" on an expiry day. Kite's list itself was fine (checked from GitHub: 216 NIFTY contracts expiring 2026-10-13, next 2026-10-19), so the relay's download came back unreadable and the empty result was cached for 6 hours. Now the list is fetched with the Kite login, a gzip body is unpacked, an empty list is never cached (new cache key), and if the list still fails the meter builds today's contract names itself (`NIFTY26O13<strike>CE/PE`; monthly `NIFTY26OCT…` only in the month's last week) and asks Kite for those. Dry-run with the list and with the list failing: same reading (22,528).
- **Second same-day fix (Version 53)**: the page then said "Limit Exceeded: URLFetch URL length": one Kite quote URL listing ~80 contracts is longer than Apps Script's ~2,000-character limit. The request is now split into URLs under 1,900 characters sent together (`UrlFetchApp.fetchAll`; 2 requests for today's chain). Dry-run with a 2,000-character check: passes on both the list and the name-fallback paths.
- **Scored against 25 bp** (owner's target): each track-record cell shows the error in basis points (green within 25 bp) and the panel counts how many expiries landed within 25 bp at 10:00, 12:00, 14:00 and 15:00.
- **Limits**: it cannot be accurate to the point; with few expiries the weights barely move by design. Readings before today's deploy (about 14:00 IST) are not in today's history.

### NIFTY expiry-day read (first version)
Owner, on expiry day: what will today's close be? Nothing on the dashboard read today's expiring chain live.
- **`hub/expiry_day.py`**, run by `live.yml` on NIFTY expiry days (no-op otherwise): from Kite quotes of today's options within 4% of spot: call wall and put wall (top 3 OI strikes above / below spot), max pain, ATM straddle and the range it implies to the close, PCR near spot and overall, the highest-OI strike near spot, and a likely range (straddle range cut by the walls). Writes `docs/data/expiry.json`; prints a one-line summary as a run notice. `docs/data/expiry.json` is public like `live.json` (exchange OI data, nothing personal).
- **Phone** (F&O tab, top, only on expiry day): "NIFTY expiry today · As of HH:MM IST" with likely close range, the market's expected range, max pain, heaviest strike, call and put walls with OI in lakh, PCR, and OI bars by strike behind a tap; refreshes with the live quotes. Checked at 375 px with the 13:19 IST numbers. Cache `market-hub-v25`.
- **What it is not**: a prediction of the close. The straddle is the market's own one-standard-deviation estimate; walls and max pain are where price often sticks on expiry, not where it must end. No track record yet: start recording it against actual closes.

### Kite login day starts at 07:35 IST, not 06:00 (corrects this morning's fix)
Owner: why does the Kite login keep needing to be redone?
- **Evidence** (relay-started daily runs give the login time; live-quote runs show when Kite refused it): logins at 06:03 IST on Sat 10 Oct and Tue 13 Oct 2026 worked at first (the 06:03 daily run succeeded), then every live-quote run from 08:34 failed with Kite refusing the token, until a new login at 11:38. The login at 09:21 on Mon 12 Oct worked all day.
- **Cause**: Kite clears all access tokens each morning some time up to about 07:30 IST; Zerodha's staff advise logging in after 07:35. A 06:03 login is inside that window, so it dies within hours while the relay still dates it "today". The 06:00 cut-off written earlier today was too early; it would not have caught the 06:03 logins.
- **Fix** (`kiteDayIst_`, `relay/Code.gs`): the Kite day now starts at 07:35 IST. A login before 07:35 counts for the day before, so from 07:35 the phone and dashboard show "No Kite login yet today · tap to log in" instead of a dead login looking fine; the relay's login page says so at the time. Boundaries tested: 06:03 and 07:34 give 2026-10-12; 07:35, 09:21 and 23:59 give 2026-10-13. `node relay/check.js` exit 0.
- **Still needed every day**: one login after 07:35 IST. That is Kite's rule (the exchange requires a manual login daily); it cannot be automated away.

### Phone: the Kite login warning stays on screen
Owner: an amber warning flashed on opening the app and vanished too fast to read.
- **Cause** (`liveTick`, `docs/index.html`): when the relay said the Kite login was replaced or missing, the app showed the amber "tap to log in" line, then fell back to the last saved quotes and overwrote the line with their time in the same call. The forecast label could overwrite it too.
- **Fix**: the warning (amber text and amber dot, tap opens the Kite login) stays until a good quote arrives; the fallback quotes still fill the screen. Cache `market-hub-v24`.
- **Checked** at 375 px with a faked relay answer: "Kite login was replaced · tap to log in again" still showing after 4 s; with no warning the line reads "Last quote · 17:33 IST · Mon 12 Oct 2026" as before.

### Relay deploys from GitHub (live: Version 48)
Owner: wants Claude to do most of the work, including relay deploys, which until now needed `clasp` on the laptop.
- **`relay-deploy.yml`**: on a push that changes `relay/*.gs` or `relay/AdminPage.html` (or by hand), waits for the owner's approval (environment `relay`), signs `clasp` 2.4.2 (the laptop's version) in from the environment secret `CLASPRC_JSON`, refuses any Google account but ramghatagedb1101@gmail.com, runs the unchanged strict script `relay/tools/deploy_relay.sh`, checks the live relay (`mode=check`), and records the deployed commit in `.github/relay-deployed` (starts at 244af4a, Version 47).
- **Why this way**: Google's Apps Script API does not accept service accounts, and a narrow-scope OAuth client of our own would need signing in again every 7 days while in Google's testing mode. The trade-off: the secret can change any Apps Script project of that account; it lives only in the approval-gated environment.
- **First run (Tue 13 Oct 2026) failed** at the project-folder step, before any change to the relay: the job used clasp 3.4.1 while the sign-in file comes from the laptop's clasp 2.4.x, and the step hid clasp's output. Now pinned to 2.4.2, and clasp's output is shown. Second run: clasp 2.4.2 said "Could not read API credentials": the secret is not in the shape clasp 2 reads. The sign-in step now accepts either clasp's file format (and a stray BOM or line break from the clipboard), converts it, and prints only which shape it found. Tested with clasp 2.4.2 on dummy files of both shapes: both now reach Google.
- **No approval step** (owner, Tue 13 Oct 2026: "can't keep approving every time"): deploys run on every relay push to `main`. Safeguards left: only `main`, only ramghatagedb1101@gmail.com, the strict script's checks, and GitHub two-factor sign-in on the owner's account.
- **Laptop and cloud stay in step**: `deploy_relay.sh` now writes the commit it deployed to `.github/relay-deployed` (the laptop session commits it), so a GitHub deploy after a laptop deploy, or the reverse, starts from the right commit.
- **First successful deploy** (Tue 13 Oct 2026, run 38353884709): Version 48 from commit 166cd18 on both deployments; account check, every strict-script check and the live `mode=check` passed. Earlier failures, all before any change to the relay: clasp 3 against a clasp 2 sign-in file, then a secret that held 74 characters instead of the file (re-copied from Notepad).
- **Setup**: the owner's one-time setup (`relay/README.md`, "Deploying from GitHub"). Its first run deploys the 06:00 fix below.

### Kite login: dated by Kite's 06:00 IST cut-off, not midnight (relay; live in Version 48)
Owner: live quotes failed with "Incorrect `api_key` or `access_token`" although the token had been renewed earlier today.
- **Finding:** every relay check treated a token as valid if `KITE_TOKEN_DATE` equalled today's IST calendar date. Kite ends every access token at about 06:00 IST, not at midnight. A login between 00:00 and 06:00 was dated "today" and looked valid all day while Kite refused it. A daytime login was treated as gone at midnight although Kite honours it until 06:00. The deployment's "Execute as" setting was ruled out: every Kite value is a script property, shared by all users. Not proven to be today's cause: if no login happened before 06:00, the other cause is a second login with the same Kite app (see the `KiteWatch.gs` email).
- **Fix:** `kiteDayIst_()` (`relay/Code.gs`) gives the IST date 6 hours earlier, so 00:00-05:59 counts as the previous Kite day. It is used for saving the token, the token hand-out to the GitHub jobs (`mode=token`), the setup check (`mode=check`, which now also shows `kite_day`), live quotes, the research charts (`Research.gs`) and the login alarm (`KiteWatch.gs`). A login before 06:00 now says on the relay page that it stops working at about 06:00.
- **Check:** `node relay/check.js` exit 0. Boundaries tested: 00:30 and 05:59 on Tue 13 Oct 2026 give 2026-10-12; 06:00, 09:15 and 23:59 give 2026-10-13. Tokens already saved after 06:00 today keep working (same date).
- **Deploy:** Version 48 (commit 166cd18), by `relay-deploy.yml`. Previous: Version 47 (commit 244af4a).

### Project guide
- **`CLAUDE.md`**: a project guide any Claude session (local or cloud) loads automatically -- accounts, where code and data live, data sources and budgets, how to push and deploy, and the owner's preferences. Relay last deployed at Version 47 (commit 244af4a).

## 2026-10-12

### BSE as a third results source
Owner approved covering the ~280 companies that file no results data at NSE.
- **Access**: BSE's firewall answers only connections that look like a browser -- plain requests and curl get "Access Denied" from GitHub's servers and from home alike. `curl_cffi` (Chrome impersonation, added to requirements) gets through from both.
- **`hub/bse.py`**: `codes()` matches NSE symbols to BSE scrip codes through ISINs (NSE's equity list against BSE's `ListofScripData`; 2,492 matched); `results()` reads a company's results snapshot (`TabResults_PAR`): latest quarter, previous quarter and last full year -- revenue, net profit, EPS, operating and net margin. Checked: Titan's June 2026 quarter reads Rs 18,101 cr revenue / Rs 1,699 cr profit at BSE, the same as its NSE filing; Abbott India (nothing at NSE) reads Rs 1,813.68 cr / Rs 428.52 cr.
- **Check** (`verify_bse`, `hub/nse_results.py`): with no NSE results XBRL, BSE's latest quarter is used -- margin against BharatStock's when both have that quarter (within 2 points = match), "Figures from BSE results" when BharatStock has none, "BharatStock behind" when it lags. BSE's snapshot has no year-ago quarter, so it cannot rebuild growth.
- Labels on the phone, the dashboard (data freshness, badges), the Shortlist note and the weekly health email.
- **Same-day correction:** the first BSE run reported 88 margin "disagreements" against 98 matches, with a median gap of 11 points in both directions. Cause: BSE's snapshot is standalone only (Titan: Rs 18,101 cr standalone, consolidated Rs 21,356 cr; no parameter returns consolidated), while BharatStock uses consolidated results whenever a company files them. A gap now counts as a disagreement only when BharatStock's figure is also standalone; otherwise it is "basis_differs" (not comparable, BharatStock's figure kept). The library now records the basis of BharatStock's figures (`_basis`), filled in at each company's next results refresh.

### Results check: margin check without a year-ago filing; NSE figures where BharatStock has none
Owner: finish the 227 "not checked yet" and find an alternative for the 342 "couldn't be checked".
- **Findings** (three diagnostics run on GitHub, `diag.yml`, since NSE refuses this machine): the 228 "not checked yet" had no BharatStock results at all, so there was nothing to compare and they had no growth figures either (e.g. AASTHA, ADVAIT, AARNAV -- all of which do file at NSE). Of the 342: 88 lacked a year-ago filing in NSE's integrated format, and a quarter's XBRL holds only that quarter and the year to date (no comparison column); the 32 "bank or insurer format" were not banks but loss-making or small companies (growth from a loss is undefined; some file total "Income" instead of revenue); 222 file no results XBRL at NSE at all (e.g. Abbott India, ADDIND -- likely BSE only). NSE's older results APIs (results comparison, financial-results list) stopped at the December 2024 quarter, so they cannot fill the gap.
- **Level check** (`verify`, `hub/nse_results.py`): when growth cannot be compared, this quarter's net margin from the filing is checked against BharatStock's (within 2 points = match; a disagreement uses the NSE margin).
- **NSE-only figures**: when BharatStock has no results, revenue / profit growth (when a year-ago filing exists) and net margin come from the company's own filing ("Figures from NSE filing" on the phone and dashboard).
- **"Income"** is read as revenue when a company files no revenue-from-operations figure.
- Clearer reasons for what still cannot be checked: no results XBRL at NSE (may report only to BSE), or no revenue in the quarter.
- Every company that was not a match is re-checked once (`VERIFY_VERSION`); NSE only, no BharatStock requests.

### AI summaries say what the call was and what happened in it; every phone date shows its year
Owner: IOLCP's summary "doesn't talk about what actually happened in the earnings call"; dates showed day and month only.
- **Finding:** the document summarised was IOLCP's business-update call of 17 Sep 2026 (capex plan), not its quarterly earnings call -- the latest transcript filed -- and nothing said so. The summary also had no place for the quarter's numbers or the Q&A.
- **New summary parts** (`SCHEMA`, `hub/summaries.py`): what the document is and the period it covers; the period's reported results with their changes; what changed from before; the analysts' main questions with management's answers ("No direct answer" where avoided); plus the existing summary, key points, guidance, risks, numbers and what to watch next quarter. The phone shows them in that order, the Q&A as its own tap-to-open part, and flags a call that was not the quarterly earnings call. Asking for a summary again redoes one written in the old format.
- **Both summaries on the phone**: "AI summary · latest call" and "AI summary · annual report" are separate sections (before, a company with a call summary never showed its annual-report summary). Checked on IOLCP's new summaries: the call is labelled a business update with 6 analyst questions and answers; the FY26 annual report gives revenue +11.5% to Rs 2,319 cr, PAT +36.2% to Rs 137.6 cr, segment figures and what changed.
- **Dates with the year** everywhere on the phone (documents, corporate actions, news, fund portfolios, closes, digest), e.g. "Thu 17 Sep 2026"; the digest's move and ex-date lines too.

### AI summaries: retry when Gemini is busy; the phone shows a run's progress and failures
Owner: IOLCP's "Summarise latest with AI" said 1-3 minutes, but reopening kept showing "No AI summary yet".
- **Cause 1:** the free Gemini model answered 503 "high demand" and dropped a connection; the code fell back to the lighter model only on the daily rate limit and never retried, so the documents failed (the 21:40 run, PGIL). Now a rate limit, an overload or a dropped connection gets the same model again after 20 s, then the lighter model twice (`ask_gemini`, `hub/summaries.py`).
- **Cause 2:** the phone ignored the run's state, so a running or failed summary looked like nothing happened. The AI section now says "Summary run started at HH:MM IST..." with a **Check again** button (re-reads only the documents), or "Last attempt at HH:MM did not finish: Google's free AI service was busy" with **Try again**. Its closed line reads "Summary being written…" while a run is going.
- **Timing:** a run takes minutes per document (8 minutes for one company today); the message now says about 3-5 minutes for a transcript and up to 10 for an annual report (phone and dashboard).

### Phone: search any company; full company page in sections
Owner: the phone could open a company only from the Shortlist, the digest or the watchlist, with a few figures; everything should be reachable, arranged for the small screen with drill-down.
- **Search** (magnifier next to Settings): all 2,573 library companies by symbol or name (symbol matches first, then name words), recently opened companies when the box is empty. The list (with the measure catalogue) comes from the relay (`app_names`, `relay/Company.gs`) and is kept on the phone for a day.
- **Company page**: a summary card that is always visible (price and day change, industry, market value, P/E, distance from the 52-week high, Shortlist / watchlist / NSE-check / data-check / upcoming ex-date tags, checks passed) and sections that open on tap, each with a one-line summary so the closed page still reads as an overview:
  Price (open by default) · Why it's on the list (when listed) · Key figures (every library measure by group, "passes x of y", each with its value, the rule it is judged on and ✓ / ✗ / not testable) · Ownership (pledge, shareholding by quarter from NSE, and Mutual funds holding it) · Results (40 quarters and 10 years: revenue, profit, margin, EPS) · AI summary (with guidance, risks and numbers) · Documents (all filings) · News · Corporate actions · Data checks (NSE cross-check, flags, latest results, data completeness).
- **BharatStock requests only on demand**: Results (2 requests, with News) and Mutual funds (1 request) load when their section is opened; the rest comes from the library (`app_profile`, from library_compact.json) and costs none.
- Measure labels, groups and formats are read by the relay from the dashboard's own definitions, so phone and dashboard always describe a measure the same way.

### Mutual funds holding it (stock report); stricter discovery alert
Owner fact-checked the first Sunday discovery email (SESHAPAPER, SOUTHWEST, TIMETECHNO) and asked to see which funds hold a stock.
- **Fact check**: scheme counts were right for the two Tier 1 names (1 scheme; public trackers show 0% fund ownership), overstated for Time Technoplast (18 here vs 12 schemes on Trendlyne). The alert's logic was the real problem: Time Technoplast was sent as "watch" with funds owning 13.5% of it; Seshasayee Paper as "pounce" with profit up in only 2 of 8 quarters and Rs 1.5 cr traded a day.
- **Discovery alert** (`hub/alerts.py`) now also needs: domestic institutions owning under 5% (NSE shareholding; funds are part of it), Rs 2 cr+ traded a day, profit up in 5+ of the last 8 quarters, 70%+ of checks passed (was 60%) and 3+ of the 4 multi-bagger gates. None of the three original names would pass. The email says "worth a look" (no "pounce") and shows the ownership, profit and turnover figures.
- **Mutual funds holding it** (`relay/Funds.gs`, `adminFunds`; stock report): each scheme with shares held, % of the company (BharatStock's figure when given, else shares / shares outstanding from market value and the latest close), last month's change (new / added / cut), % of the scheme and the portfolio date. Live from BharatStock when the report opens, never stored (licence); one request per report. BharatStock gives no first-purchase date, so "new" means first seen in the latest monthly portfolio. The endpoint's field names were never logged, so the panel lists the fields returned when a column comes back empty.

### Compounders fixed: 10-year record required, ROE only where reported; digest gives the reason for each change
Found while adding reasons to the digest (owner: the list name under each change added nothing). The first catch-up run on the long-term rules replaced 7 of 8 compounders, and the new list held PNB, YES Bank and Vedanta.
- **Cause 1: the ROE rule could almost never be tested.** BharatStock reports shareholders' equity for very few companies: 5-year average ROE exists for 30 of 2,573 (current ROE for 91). A missing figure counted as a fail, so HAL, CAMS, Glaxo, Caplin Point and National Aluminium left for a number that was never computed. The rule now counts only where ROE is reported.
- **Cause 2: uneven rules during the switch.** Only 1,195 companies have their 10-year record so far. They were judged on the long-term rules while the rest fell back to the easier 8-quarter rules, and all 8 new compounders came from the second group. A company now qualifies only once its 10-year record is loaded (`compounder_rules` in `hub/shortlist.py`; the same on the dashboard), and the rest load with each company's annual refresh.
- **On today's data**: 68 companies pass all eight rules (e.g. Bajaj Finance, Adani Ports, HAL, NTPC, DMart, Eicher, Pidilite, Polycab, Persistent), 110 miss one.
- **Digest reasons** (`hub/digest.py`, shown under each change on the phone instead of "Compounders"/"Emerging"):
  - big move: stock-specific or with its industry, against NIFTY and the industry's median move that day; volume against its 20-day average; any announcement filed that day or the day before (every announcement subject from the run's existing market-wide request, `documents.new_filings(..., subjects)`), or "no company announcement";
  - left a list: the real cause -- a rule it fails, excluded (with the reason), still qualifies but overtaken (by whom), the two-per-industry limit, or not judged until its 10-year record loads;
  - joined: the Shortlist's first reason; a move between the two lists is one line ("Moved from Compounders to Emerging") instead of a "left" and a "joined";
  - routine compliance filings (Reg 74(5) certificates, newspaper notices, trading-window closures and similar) never count as the reason for a move; a compounder that joins is described by its record ("Profitable in 100% of the last 10 years; profit +19% a year over 5 years");
  - results filed: revenue and profit growth from the NSE filing once read; documents: the AI summary's headline; ex-dates: what the date means.

### Phone: index cards show the last close outside the target session; clearer digest header
Owner feedback on a weekend screenshot: "Pending close" and "after the 15:30 IST close" read as if a close was due that day.
- **Index forecast cards** (Home): until the forecast's target session, the badge and row show the last close ("Close · Fri 9 Oct" with its value). On the target day before the close they say "Closes 15:30 IST" / "today, after 15:30 IST"; after settling, "In band" or "Out of band" with the actual close, as before.
- **No duplicate rows** (owner, same day): outside market hours the first row is labelled with the close date ("Close · Fri 9 Oct") and the separate close row is dropped; the badge names the next session ("Next session · Mon 12 Oct"); "Next session est." appears only when it is a later day than the card's estimate, with its date.
- **What changed for your stocks, compacted** (owner: no long list on the landing page; the "+9 more" line led nowhere): moved below the index cards; one line of counts by type and the 3 most important items (watchlist first, then list changes, filings, big moves, ex-dates); "See all N" opens the full list grouped by type on its own screen, and Back from a company returns to that list.
- **Today box** renamed "What changed for your stocks", with "Shortlist and watchlist · As of HH:MM IST · Day d Mon" underneath.
- Service-worker cache bumped to v12 so phones pick up the change.

### Chart indicators; email alerts for the daily digest and watchlist moves
Owner approved two quick wins from the improvement list. Telegram was built first and dropped the same hour (owner: "I dont use telegram"); the alerts go to Gmail instead, which already reaches the phone.
- **Chart indicators** (dashboard stock report, `drawPriceChart`): one lower panel at a time -- Volume, RSI (14, Wilder; 70/30 lines) or MACD (12, 26, 9 with histogram) -- plus Bollinger bands (20, 2) and 52-week high/low lines as overlays. Computed in the page from the same candles (Kite, NSE closes or BharatStock), so nothing new is fetched. The hover legend shows the RSI or MACD reading. Checked against the textbook Wilder RSI example (70.46 vs 70.53 published, the difference is the published rounding).
- **Daily digest email** (relay `Alerts.gs`, `sendDigest_`): the first library run of the day posts the phone's Today digest to the relay (`mode=digest`), which emails it once a day: Shortlist changes, filings, 4%+ moves, coming ex-dates, for the Shortlist and the watchlist only. Nothing new = no email.
- **Watchlist move emails** (`watchCheck_`, `mode=watch_check`, called by the live-quotes job every 5 minutes in market hours): a starred company 4%+ up or down since yesterday's close (Kite OHLC quote), once a day per company, again at 8%; several in one check share one email.
- **Switches**: dashboard Overview, "Email alerts" panel (script properties `ALERT_DIGEST`, `ALERT_MOVES`; default on). Kite login, discovery and weekly-health emails are unchanged and always on.

### Long-term record: "proven compounders" now judged on years, not 8 quarters
- **New measures from each company's annual results** (`longterm_values` in `hub/library.py`, computed in the annual stage -- the full annual history is already fetched, so no extra BharatStock calls; only derived figures are stored): 5-year revenue, profit and EPS growth a year; 10-year profit growth; share of the last 10 years with a profit and with positive operating cash flow; operating cash over profit across 5 years; average and lowest ROE over 5 years; years of history. Growth rates need a positive start and end, otherwise they are gaps. 9 new library parameters with rules (e.g. profit growth 12%+ a year over 5 years, average ROE 15%+), shown in a new "Long-term record" group on the stock report, and usable in the Screener and Scatter explorer.
- **Proven compounders redefined** (dashboard and the batch's Shortlist, same rules): profitable in 90%+ of the last 10 years; profit growth 12%+ a year over 5 years; average ROE 15%+ over 5 years; operating cash 0.8x+ profit over 5 years (does not apply to banks and financials, whose cash flow is not comparable); still delivering -- profit up in 5+ of the last 8 quarters; 30+ fund schemes; pledge at most 5%; market cap Rs 5,000 cr+. Was: the last 8 quarters, latest net margin, latest year's cash, plus the same ownership and size gates.
- **Transition**: companies without long-term figures yet are judged on the earlier rules until their next annual refresh -- tomorrow's catch-up refreshes every company's annual results, so the long-term rules take over then. The compounder page says how many are still on the earlier rules. On 10 Oct data the screen gives 101 (one more than before: a financial company no longer failed on the cash rule).
- **Factor scores**: Quality gains 5-year ROE (average and lowest), profitable years and 5-year cash conversion; Growth gains the 5-year growth rates. They add evidence without raising the minimum number of inputs a factor needs. Shortlist reasons can cite them ("Profit grew 18.0% a year over 5 years").

### Results checked against each company's own NSE filing; data-health checks; weekly health email
Owner approved the first group of zero-cost improvements (data reliability scored 3/5, the weakest).
- **NSE cross-check** (`hub/nse_results.py`): after every new quarter, a free stage rebuilds year-on-year revenue, profit and EPS growth from the company's own machine-readable filing at NSE (SEBI integrated filing XBRL: latest quarter and the same quarter a year earlier, consolidated when filed) and compares it with BharatStock's. Bank, NBFC and insurer formats handled (profit compared; "revenue" differs for lenders). **Disagreement** -> NSE figures used, company flagged. **BharatStock behind** (NSE has a newer quarter) -> growth and net margin from the NSE filing, with a note.
- **Findings from the first 266 companies (dry run, 10 Oct):** 155 match exactly, **0 disagree** -- BharatStock's figures agree with the filings wherever both cover the same quarter. **OFSS's +68.7% revenue growth is genuine** (its own filing; profit +120.5%); the Shortlist's earlier "check the latest quarter" flag on it, from a size-based guess, was wrong, and that guess now applies only to figures not yet confirmed. The real problem is staleness: ~50 of 76 "different quarter" companies had BharatStock data one or more quarters behind NSE's June 2026 filings (some stuck at March 2022) -- now covered from NSE. 35 could not be checked (21 have no machine-readable filing, 11 lack a year-ago filing in the new format, 3 formats unreadable).
- **Data-health checks** (`hub/data_health.py`, per company, `flags` on the library entry): severe -- P/E below 1x, share count differing >10% from the NSE filing (market value and P/E off); notes -- profit above revenue (holding companies' associate income: genuine, e.g. Bajaj Holdings 687%), losses many times revenue, ROE / debt-equity distorted by tiny equity, results filed but not loaded, results older than ~200 days. A first version called margins over 100% "implausible"; reading the cases showed most are genuine, so they are notes.
- **Shortlist**: a disagreement or a severe flag holds growth at neutral, takes 4 points off and shows the reason; "Results confirmed against the company's NSE filing" appears as a reason when it matches.
- **Dashboard**: stock report badges ("✓ Matches NSE filing", "NSE filing disagreed · NSE figures used", "Data check: n"); Data freshness panel rows for the check counts and severe flags. **Phone**: the stock sheet notes the check.
- **Weekly data-health email** (first run of each week, through the relay `mode=health`): check counts, flagged companies, what is still pending, BharatStock use, and up to 15 companies to look at.
- The first full check runs with tomorrow's catch-up (about 0.7 s per company, free).

### Kite login alarm: a replaced login now announces itself
On 10 Oct the relay's Kite login (made at ~06:03 IST through the phone's "Log in to Kite" button -- the correct route) was cancelled some time before ~17:28 and nothing said so until a chart failed. Investigated: nothing in this project creates Kite logins except the relay (today: ~06:03 and ~18:00, each starting the daily run); `C:
se_fo_analyserorecast_hub` is an older local copy of this same repository and relay, its old copy-paste login script belonged to a workflow retired on 6 Oct, and nothing in it changed that day. So the cancelling login came from outside (another login with the same Kite developer app elsewhere, or a Zerodha-side logout); Kite does not say which.
- **`relay/KiteWatch.gs`**: every relay call to Kite (quotes, charts, watchlist prices) reports a refused login; the first refusal is recorded (script property `KITE_STATUS`) and **emailed once** with the login link; a fresh login through the relay clears it.
- **Phone**: the status bar turns amber -- "Kite login was replaced · tap to log in again" (or "No Kite login yet today · tap to log in") -- and opens the login link.
- **Dashboard**: a banner with a "Log in to Kite" button on every page while the login is missing or replaced (`adminKiteStatus`).
- **live-quotes workflow**: one quote call through the relay every run (every 5 minutes in market hours), so a replaced login is caught within minutes on a trading day even with the app closed.
- Deploy script now copies every `relay/*.gs` file (KiteWatch.gs added).

### Chart: when nothing is available, it says why -- source by source -- and what to do
Owner: "if nothing is available, investigate why it's not available."
- The chart (dashboard and phone) now asks every source and reports each answer when none can draw it: **Kite** (no login yet today / login rejected because a newer one replaced it / plan does not include historical data), **NSE daily closes** (not published yet -- written at 06:15 IST / company lists on a future date / no trades in the last year: suspended, delisted or renamed / the relay's read token is missing or refused), **BharatStock** (allowance used up, resets 05:30 IST / no prices for the company / key not set). Then one "What to do" line: log in through the Kite link; nothing to fix, it has not started trading; check the symbol is current; or which relay setting needs attention.
- NSE listing dates are now published with the closes (from NSE's equity list), so a company that has not started trading says "AGOL lists on NSE on Mon 12 Oct 2026; prices appear after its first trading day".
- Investigated today's gaps: 2,571 of 2,574 companies have NSE closes. The three without: **AGOL** (Ashapuri Gold Ornament) and **BELDING** (Belding India) list on 12 Oct 2026; **NATCO-RE** is a rights entitlement for Natco Pharma's rights issue. 218 more have under 60 trading days -- new listings (Nityas 8 Oct, Orient Cables 5 Oct) or rarely-traded BE-series shares (Kalyani Commercials traded on 1 day in the year).
- **Rights-entitlement lines ("-RE") are no longer in the universe** (`multibagger.universe`): temporary instruments, not companies -- the same kind as CENTEXT-RE that made the count read 2,575 of 2,574. Universe now 2,573.

- **Deploy slip, caught and fixed:** the first deploy of this change was rejected by Apps Script (an unescaped apostrophe in two messages). `relay/check.js` had reported it, but the deploy commands piped each check through `tail`, which hid the failure, so an unchanged Version 35 was created and deployed (identical to Version 34; nothing broke). Fixed in `c2bc791`, deployed as **Version 36** through a new strict script, now kept in the repo as `relay/tools/deploy_relay.sh` (with `verify_content.js`): no pipes, stops at the first failed step.

### Charts: free NSE fallback, plain wording, and Kite's real reason when it refuses
Owner saw "BharatStock daily limit reached and no Kite login today" although today's Kite login had been done. Two faults: the message was hard-coded (any BharatStock failure blamed "no Kite login"), and the chart had no free fallback.
- The actual cause on 10 Oct: **Kite was rejecting the relay's saved token** ("Incorrect `api_key` or `access_token`" -- the live quotes failed too). A Kite app has one valid token at a time, so a newer login made elsewhere (another link, a script, a token pasted by hand) invalidates the relay's copy even though it is dated today. Fix for the owner: log in once through the relay's Kite link.
- **Free fallback**: the library run now publishes a year of split/bonus-adjusted NSE daily closes for every company (`hub/price_shards.py`; 27 files, ~6 MB) to the private repo's `prices` branch, rewritten each run as one commit with no history so daily refreshes do not grow the repository. The relay's chart uses Kite candles when Kite accepts the login, these NSE closes otherwise, and BharatStock only if both are missing. First copy published 10 Oct.
- **Wording**: the chart line now reads "Prices: Kite" / "Prices: NSE daily closes (…reason…)" / "Prices: BharatStock daily", with the reason in plain words -- "candles and intraday appear after the morning Kite login", or "Kite rejected today's saved login, usually because a newer Kite login replaced it; log in again with the Kite link", or the plan message. When nothing is available: "The price chart is not available right now. It returns after the morning Kite login or the next daily run." Credit shortened to "chart: TradingView".

### Phone app: Today digest, Ideas tab, stock sheet, shared watchlist; one way of saying when
Owner asked whether the dashboard changes reach the phone (they did not: separate page and data, so nothing broke, but the phone still showed the raw top-30 multi-bagger list and downloaded the 1.1 MB file to do it) and to make the phone more meaningful; also to standardise the Brief tab's time wording.
- **Today** (top of Home, `hub/digest.py` -> `site/digest.json`, written by the daily library run): for the Shortlist's companies and the watchlist, what changed since the previous day -- joined / left a list, newly core, results filed, transcript / presentation / annual report filed (and whether an AI summary is ready), daily moves of 4%+, dividends / splits / buybacks with ex-dates in the next 14 days. The watchlist reaches the batch through the relay (`?mode=watchlist`, behind RELAY_KEY).
- **Ideas** tab (replaces Multi-bagger): the Shortlist's Compounders and Emerging lists as cards (score, core / weeks on list, since joining vs NIFTY, top two reasons, first caution, market cap, P/E, 1M with a stretched warning), the track record as tiles, and a Watchlist view. Loads the ~50 KB shortlist instead of the 1.1 MB multi-bagger file.
- **Stock sheet** (tap any card or digest line): price chart (Kite candles via the relay, 1M / 6M / 1Y / 5Y), the list's reasons and cautions, key figures, the AI summary (headline, summary, key points, guidance, risks) with a Summarise button, document links, and Star. Relay: `app_stock`, `app_summarise` (`relay/Phone.gs`; the chart, documents and summary code is shared with the dashboard).
- **Watchlist** shared by phone and dashboard (Star on the phone's sheet and on the dashboard's stock report; Watchlist panel on the dashboard Overview): return since starred against NIFTY, using Kite prices at starring.
- Shortlist items now carry the company name and key figures, for the sheet.
- **Time wording, one vocabulary** across the phone: "Live · 10:42 IST" (market-hours quote today), "Last quote · 15:30 IST · Fri 9 Oct", "As of 06:05 IST · Sat 10 Oct" (the morning snapshot), "Close · Fri 9 Oct" (end-of-day figures: S&P 500, ECB rate, FII/DII), "24 h · 10:42 IST" (bitcoin's rolling change). Replaces "live", "same day", "24h", "ECB 2026-10-09", bare dates and the F&O screen's UTC time; the Home forecast reads "Estimate · close Mon 12 Oct".
- Verified with a stand-in relay at phone size: Today, both lists, the watchlist, the sheet (both chart ranges, star, close) and the Brief tab render with no script errors; the digest was built from real data (HAL joining, Marksans' results, the 4% moves). The service worker cache was bumped so phones load the new page.

### Shortlist rebuilt: two lists by style, 6-12 month momentum, industry cap, weekly track record
Owner asked whether to trim further and to watch month-to-date returns for momentum. Analysis given: trimming the single list harder would only add false precision (top 15 scores were 72-78, within the noise of one-quarter inputs, and #1 OFSS rested on a doubtful +68.7% revenue figure); month-to-date is an arbitrary, resetting window, and the evidence (Jegadeesh-Titman; NSE's Nifty200 Momentum 30 uses 6- and 12-month returns relative to volatility) is that momentum lives in 6-12 month returns while the latest month tends to reverse. Built instead:
- **Computed in the daily batch** (`hub/shortlist.py`, published as `site/shortlist.json`; the dashboard only displays it, via `adminShortlist`), so it can be recorded and measured.
- **Two lists of 8 by style**: Compounders (proven compounders; 35% quality, 25% value, 15% growth, 15% momentum, 10% ownership) and Emerging (four-gate early multibaggers that are not compounders; 35% growth, 25% momentum, 20% quality, 10% value, 10% ownership). The old single list's bonus for being in both screens tilted it to the large and steady.
- **At most 2 per industry** (NSE industry or sector map; smaller companies often have neither, so the cap cannot apply to them), "next in line", held-back and left-out lists shown.
- **Momentum the NSE way, latest month skipped**: average of the 6- and 12-month returns to a month ago, divided by 1-year volatility, as a library percentile, from NSE's daily price files. The 1-month return is shown only as a "stretched" warning (over +20%). Trend checks (above 50/200-day averages, within 10% of the 52-week high) appear as reasons.
- **Input sanity**: growth that is implausible for the company's size (Rs 20,000 cr+ with revenue over +40% or profit over +80%) or a profit jump over 200% is not rewarded -- the growth score is held at neutral and the company flagged "check the latest quarter". Banks and financials carry a note that operating cash flow and net margin are not comparable, and those reasons are not cited.
- **Weekly record and track record** (`state/shortlist_history.json`): one record a week (first run of each ISO week); a pick's return is measured from its joining close (to its leaving close, or today) against NIFTY 50 over the same dates; per list: picks, still on, dropped, average vs NIFTY, how many beat NIFTY. "Core" = on the list in 3+ consecutive weekly records. Needs 3-6 months before it means anything.
- First weekly record published 10 Oct (week 2026-W41). Compounders: OFSS (flagged), CAMS, Caplin Point, GSK Pharma, National Aluminium, Yes Bank (financial note), Tech Mahindra, HAL. Emerging: Marksans Pharma, Venus Remedies, IOL Chemicals, Shilpa Medicare, Deep Industries, Pearl Global (PGIL), Sakar Healthcare, Happy Forgings. The low-base profit jumps (Manali Petrochemicals, Century Enka) fell out once suspect growth stopped scoring.

### Dashboard loads ~0.7 MB instead of ~22 MB
- 13 of library.json's 22 MB was repetition: each rule's wording (9.3 MB) and the words met / not_met / not_testable (3.4 MB) in every company's 66 cells. The batch now also publishes **`library_compact.json`** beside it (`hub/library_compact.py`): wording once, values as one list per company, statuses as one letter, holding history as rows, per-company refresh dates dropped -- 3.6 MB. The relay gzips it (and the multi-bagger file) and sends one base64 string, which google.script.run carries far faster than a large object; the page unpacks it in the browser (`DecompressionStream`) and rebuilds the original shape (`hydrateLib`), so nothing else on the page changed. **On the wire: 21.5 MB -> 0.68 MB.**
- Checked: rebuilding from the compact copy reproduces every company's cells and holding history exactly; the preview showed identical counts, factor scores and reports from both. library.json itself is unchanged (the batch reads it back). The first compact copy was published from the current library.json on 10 Oct; the batch keeps it current from the next run.

### Shortlist: the strongest of both screens, with reasons
Owner noticed Proven compounders = 100 and four-gate Early multibaggers = 150 and suspected a cap. Checked: **no cap** -- both are real counts over every company (multibagger scores 0/1/2/3/4 = 264/526/564/445/150 of 1,949; 181 more companies miss the compounder screen by exactly one rule, and dropping any single rule gives 102-180). The round numbers are a coincidence. But 250 names is too many to act on, and the multibagger gates (one quarter's growth plus a consistency count) are loose.
- **New Shortlist page** (first under Screens; top six on the Overview): companies in either screen, minus the hard to trade (under Rs 2 cr daily turnover), weakly cash-backed (operating cash under 0.6x profit), pledged (over 5%) and thinly covered; the rest ranked by a conviction score = 30% composite + 20% quality + 20% growth + 15% value + 15% momentum factor scores, +8 when in both screens, +/-4 for ownership trend, -6 for P/E over 1.5x the industry median, -4 each for high volatility, over 35% below the 52-week high, promoter selling, -3 for a profit jump over 200% (low base / one-off). Top 15 shown, with "why it ranks here" (the measures where it sits in the library's top fifth, valuation against the industry, being in both screens) and "watch" items; "All ranked" and "Left out" (with reasons) views.
- 10 Oct data: 191 in the two screens, 32 left out, 159 ranked; top of the list OFSS, National Aluminium, Manali Petrochemicals, Indian Bank, Atul, Century Enka, IOL Chemicals, Ipca Labs, ... A ranked screen of the owner's own rules, labelled as not a recommendation.

### AI summaries switched to Google Gemini's free tier
Owner: "why should I be spending money on Anthropic? There are so many free AI models." Agreed for this job: the inputs are public NSE filings, so a free tier's use of inputs for product improvement does not matter, and the summaries are checked against the source anyway.
- **Default now `AI_PROVIDER=gemini`**: Gemini 3.8 Flash on the free tier (listed "Free of charge" on Google's pricing page), retrying once on Gemini 3.5 Flash-Lite after a rate limit. Gemini reads PDFs up to 50 MB / 1,000 pages, so transcripts and most annual reports go in whole (Titan's 473-page FY26 report included); larger ones fall back to the extracted-text path.
- Checked the other free options: GitHub Models caps a request at about 8K tokens and Groq's free per-minute token limit is 6-12K, both smaller than one transcript (~40K); a model inside GitHub Actions has no GPU.
- Claude stays available: set the repository variable `AI_PROVIDER=anthropic` and the `ANTHROPIC_API_KEY` secret.
- **Live and confirmed (10 Oct, 15:05 IST).** The `GEMINI_API_KEY` secret already existed (added 6 Oct). Library run 38037749990 collected NSE document links for all 2,574 companies in one run (1 h 7 min, free); ai-summaries run 38041862845 then summarised Titan's Q1 FY27 transcript and its 473-page FY26 annual report, both sent whole, on `gemini-3.8-flash` at no cost. The output picks up the customs-duty gain (Rs 407 crore), the temporary 75-80 bps inventory benefit and the normalised 10.9% jewellery margin from the transcript, and the West Asia, gold-price and customs-duty risks from the report.
- Verified: a request with a deliberately invalid key reaches Google and is refused only for the key (request shape correct); the missing-key message is written for the requested company; the rate-limit fallback was tested with a stand-in client.

### Stock report: interactive charts, 10-year results, NSE documents, AI summaries
Owner asked to close the gaps found against the paid tools (Screener, Trendlyne, Tijori, Tickertape, StockEdge) and to add charting; picked all four.
- **Interactive price chart** (TradingView Lightweight Charts 4.2.0, Apache 2.0, credit line under the chart): candles or line, 1D / 5D / 1M intraday and 6M / 1Y / 3Y / 5Y / 10Y daily, 50- and 200-day averages, volume, comparison with NIFTY 50, OHLC read-out on hover, and markers for dividends (D), splits and bonuses (S), buybacks (B) and results calls (R). Data: **Kite historical candles** through the relay (`adminChart`, Research.gs) -- included in the paid Kite Connect plan that already serves the live quotes, so no extra cost and no BharatStock calls; BharatStock daily prices are the fallback before the day's Kite login (intraday needs Kite). TradingView's embeddable widgets were rejected: their licence can block NSE symbols.
- **10 years of results**: the report's results chart now shows up to 40 quarters and a 10-year annual view (revenue, profit, margin), fetched live from BharatStock when the report opens and never stored (the relay's note on BharatStock's licence). The stock report no longer fetches BharatStock prices, which saves a call per report.
- **Documents panel** (`hub/documents.py`): links to NSE's own PDFs -- annual reports (last 5), earnings-call transcripts, investor presentations, call recordings. A free stage in the library tracker: each company once (about a second), its annual reports once a year when the new one is due, and the whole market's new filings in one request a run. Only links are kept (`site/docs.json`, about 1 KB a company, roughly 3 MB in all), read one company at a time by `adminDocs`, so the dashboard's main load does not grow. Checked on Titan, ADF Foods and SBI Funds; the market-wide read found 26 new documents from 22 companies for 1-10 Oct.
- **AI summaries** (`hub/summaries.py`, `.github/workflows/summaries.yml`): the latest transcript (sent as the PDF) and annual report (text extracted with pypdf; when too long to send whole, the Management Discussion & Analysis section onwards, and the summary states the pages covered) summarised by Claude (`claude-opus-5-5`, server-side refusal fallback on) into a fixed structure: headline, summary, key points, guidance, risks, numbers mentioned, management tone, what to watch next quarter. Runs on the report's **Summarise latest with AI** button (the relay starts the workflow) and daily at 09:00 IST for new transcripts of companies scoring 3+ on the multi-bagger screen, at most 15 a day (`AI_DAILY_LIMIT`). **Needs an `ANTHROPIC_API_KEY` secret in the market-hub repo** (owner to add); until then the report says so. Rough cost at Claude Opus 5.5 prices ($4 / $20 per million tokens): about Rs 20 per transcript and Rs 50-60 per long annual report, so the daily cap of 15 is at most about Rs 300 a day; cheaper models can be set with `AI_MODEL`.
- Verified locally with a stand-in relay: every range, chart type, the NIFTY comparison, the annual view, the Documents panel (15 real Titan links) and the Summarise flow render with no script errors; a live dry run of the library batch filled documents for 91 companies in 2 minutes with nothing published.

## 2026-10-10

### Stock library: fetch only what changed -- BharatStock calls cut from ~7 per company per week to ~1 per company per quarter
Owner: "the calls are being wasted ... when something is scarce and limited, this should have been done on day one." Correct. BharatStock allows 10,000 requests a day; the batch re-read every company in full every time (about 7 requests each), so the allowance ran out after ~1,390 companies today. Where they went:
- **Prices: ~4 of the 7.** Read from 2010 for every company, though nothing uses more than the last 253 trading days.
- **Annual results** re-read weekly (they change once a year); **quarterly results** re-read when nothing new could be out.
- **~600 companies (a quarter of the universe) fetched and thrown away**: the code kept consolidated results only, so companies that file standalone results only had no figures at all, every week.

**What changed** (`hub/library.py`, new `hub/bhav.py`, `hub/nse_feeds.py`; `library.yml`):
- **Prices from NSE's free daily price file** (`sec_bhavdata_full`, the whole market in one file a day, with delivery %): zero BharatStock calls. The files are kept between runs with `actions/cache`, so a run downloads only new days. Split/bonus adjustment comes from NSE's corporate-actions list (the file itself is unadjusted -- Rolex Rings' 10:1 split showed as -90%). Checked against the BharatStock figures stored this morning for 714 companies: 1M/3M returns and 60-day volatility identical for 99-100%, 52-week high/low within 1 point for 90-98%, 12-month return with no systematic bias (median -0.3%). The outliers are BharatStock's own errors -- e.g. it never adjusted Taal Tech's 5:1 split (22 Sep), so it reports -77% for the month. Turnover and volume measures are now available for every company (BharatStock gave volume for 49). Two traps handled: on holidays NSE serves the previous day's file under the holiday's name (the file's own date decides), and weekend special sessions exist (Sunday 1 Feb 2026, Budget day).
- **NSE's market-wide filing lists decide who needs what**, one free request per two-week window: results filings (SEBI integrated filing list) and shareholding filings. BharatStock is asked for a company's quarterly results only after it has filed a newer quarter (retried after 3 days if BharatStock lags, at most 3 times; once for companies BharatStock holds nothing for); annual results only when a March quarter comes in; NSE shareholding only after a newer filing. Corporate actions for the whole market in one request a run, instead of one per company.
- **Insider and fund holdings** (BharatStock, no free source -- NSE's bulk insider list does not respond to scripts): at most monthly, still only for companies with profit growth or a multi-bagger score of 2+.
- **Each company's last fetched figures are kept** in `state/library_state.json` (private repo) so every run rescores every company from stored figures plus today's prices -- no re-asking. Age limits as a safety net if a filing list is missed: results 120 days, annual 400, shareholding 120, funds 30.
- **Daily budget**: at most 9,000 BharatStock requests a UTC day (`BS_DAILY_BUDGET`), the rest left for the admin stock report; every request is counted, retries included, and a "daily limit" 429 is no longer retried. When the allowance is used up the run carries on with the free work (shareholding, prices) instead of stopping.
- **Most-needed first**: never-read companies, then free shareholding work, then newly filed results, then the one-time catch-up, then age-limit refreshes -- no more alphabetical walk.
- **Standalone results used when a company files no consolidated results** (`multibagger._consolidated`), for the library and the multi-bagger score.
- **Runs daily** at 06:15 IST (after the allowance resets and NSE has published the day's files) and starts another run only while there is work it can do now; work waiting for BharatStock waits for tomorrow.
- **Tracker** in `library.json` (`tracker`) and on the admin dashboard Overview, "Data freshness": BharatStock requests used today, what is still needed per source, what the last run refreshed, price date, and whether each NSE list was read.
- **First run on the tracker** starts every company from its current figures (nothing is lost while it waits) and re-reads quarterly + annual results once: ~2 requests a company, about 6,000 in all -- one day's budget. After that a normal day costs a few hundred at most (results season), next to nothing outside it.
- Verified on this machine with the real private data and nothing published: a run with BharatStock used up spent no BharatStock requests, corrected shareholding for 241 companies in 5 minutes and read all three NSE lists (2,354 companies' results filings, 2,310 shareholding filings, 1,514 companies' corporate actions) and prices for 2,571 companies; a simulated full-allowance run made exactly one quarterly + one annual request per company (5,978 in all); a second run the same day made none for results.
- **First real run (10 Oct, 10:16-10:54 IST, run 38025240081):** BharatStock allowance already used up, so 1 request (the one that found it); shareholding re-read for 1,189 companies from NSE -- **FII is now on the corrected method for every company**; prices for 2,571 companies from NSE's file; 11 discovery alerts. Every company is queued for its one-time results read on the next run with a fresh allowance.
- **"2,575 of 2,574 listed" on the Overview**: the extra entry was CENTEXT-RE, a temporary rights-entitlement line no longer on NSE's list, carried over from an old batch. Companies that leave NSE's list are now dropped at the next run.
- Workflow change (daily 06:15 IST schedule, price-file cache, `more_work` chaining) committed by the owner through GitHub's web upload (`30a4871`): the saved git and CLI sign-ins lack GitHub's separate "workflow" permission.
- Side effect to expect: the first run rescores older entries (scored before the current rule set and without price data) on today's rules, so a one-off batch of discovery alerts (~57 in the dry run) can arrive.

### FII figures corrected: the big "FII jumps" were filing reclassifications, not trading
- Owner asked to check the extreme FII moves in What changed. Only 18 of ~1,400 companies showed a 5+ point FII change; re-reading the actual NSE filings for the six largest:
  - **ICICI Bank 34.49% -> 49.82%**: this quarter's filing put the ADR depository (16.03%) inside "Institutions (Foreign)"; real foreign portfolio holding 34.48% -> 33.79% (-0.69).
  - **CleanMax 29.80% -> 11.21%, PPL Pharma 30.18% -> 12.52%**: a strategic foreign stake (~19% / ~18%) moved from "foreign direct investment" (inside the total) to "foreign companies" (outside it); real FPI +0.59 / +0.29.
  - **Davangere 0 -> 15.88%, MIC Electronics 5.58 -> 20.35%, GA Technologies 0.35 -> 31.22%**: compared against **mid-quarter event filings** (25 Aug, 4 Sep, 17 Aug). MIC's FPI entry is real; GA Technologies' newer 30 Sep filing shows 0.24%.
- **Fixes (`hub/shareholding.py`)**: FII is now **foreign portfolio investors only (FPI Category I + II)** -- the "Institutions (Foreign)" total also carries FDI, ADR/GDR depositories and foreign VC, which companies reclassify between quarters (fallback for older filings: total less those parts). And **only quarter-end filings** are used, so a mid-quarter allotment filing is never compared as "last quarter". Re-reading the same real filings: ICICI -0.69, CleanMax +0.59, PPL +0.29, GA Technologies -0.11.
- Stored figures are corrected as the weekly batch re-reads each company; entries carry `shp_v: 2` once read the corrected way. Until then the dashboard does not show that company's FII change anywhere (What changed, report, Ownership factor score, screener, scorecard).
- Tests: FII = FPI I + II with ADR depository and FDI excluded, older-filing fallback, event filings skipped.

### Admin dashboard: analysis tools -- factor scores, screener, scatter explorer, what changed, sectors, peers
Owner: "so much data, it needs to be analytical." Built all six options the owner picked.
- **Factor rankings** (new page): every company scored 0-100 on Quality (ROE, ROCE, margins, cash conversion, interest cover, debt, profit consistency), Growth (revenue, profit, EPS, profit streak, cash-flow growth), Value (P/E, P/B, P/S -- losses not counted as cheap -- and dividend yield), Momentum (3M/12M return, return vs NIFTY, distance from 52-week high) and Ownership (promoter, FII, DII and fund moves, pledge). Each = average of the company's percentile on its inputs against all scored companies; a factor needs half its inputs, the composite needs four of the five factors (so the smallest companies with patchy data don't float to the top). ~1,300 companies get a composite. Default view Rs 1,000 cr+.
- **Screener** (new page): combine any measure or factor score with above/below/at least/at most; results table with the condition columns and medians; five starter ideas (quality at a fair price, momentum leaders, promoters and funds buying, cash-rich growers, undiscovered quality). **Saved screens are stored on the relay** (`adminScreens`/`adminSaveScreens`, script property `SAVED_SCREENS`, ~9 KB cap) so they follow the owner across devices.
- **Scatter explorer** (new page): any two measures or scores against each other, bubble size by market cap, colour by industry / screen membership / composite band, dashed median lines, outlier trimming, log X; read-out with correlation and a "sweet spot" list (better than the median on both). Click a dot to open the company.
- **What changed** (new page): companies entering or leaving Proven compounders, multibagger gate changes, promoter/FII/DII moves of 1+ point and profit growth turning, all since each company's previous scoring; plus 2+ point ownership moves in recent quarterly filings (last ~7 months) and upcoming corporate actions. Strongest first, filterable.
- **Sectors** (new page): medians by NSE industry (companies, market cap, revenue/profit growth, margin, ROE, P/E, 12M return, composite, compounder and multibagger counts) with green/red shading between industries, a median 12-month-return chart, and click-through to each industry's companies by composite score. Industries with fewer than 5 companies are faded and left out of the chart.
- **Stock report**: new **factor profile** (radar vs the industry median, plus each score) and **peers** table (same industry, closest in size; best in group in bold). Library table gains a composite column.
- **Industry data**: NSE's per-company quote API (which has every company's industry) blocks scripted access, so industries come from NSE's NIFTY Total Market constituent list: 755 companies, 22 industries; smaller companies stay unclassified, never guessed. Served live by the relay (`adminIndustries`, cached 6 h) and saved by the weekly batch as `industries`.
- **Weekly batch** now also stores `scored_on` and a compact `prev` snapshot per company (its previous key figures: the six compounder-rule inputs, P/E, returns, growth, ROE, ownership levels, rules met, multibagger score) so "What changed" can compare. Starts filling in as companies are re-scored.
- Verified on this machine against the real private data with a stand-in relay: all six pages and the report panels render with no script errors; batch helpers tested (`fetch_industries` against the live NSE list, `snapshot` only copies listed keys, rounds, never nests).

## 2026-10-09

### Stock report: shareholding in plain words, who-bought/who-sold chart, quarterly holding history
- Owner found "-0.56 pp" unclear. The shareholding panel now says it plainly -- "Promoter 51.44%, down 0.56 from 52.00% last quarter" -- for promoter, FII, DII and public & others (whatever the three named groups gave up or took), plus a line on the promoter stake a year ago and on pledging. The donut is gone.
- **Who bought, who sold**: a diverging bar chart of each group's change since last quarter (right = increased, left = decreased), the owner's choice of chart.
- **Holding by quarter** (trend line for promoter, FII, DII) appears once a company has three stored quarters. The weekly batch now saves `holding_history` per company: promoter and public % for every quarter NSE lists (already fetched, previously dropped), and FII/DII % for the filings it reads (latest, previous quarter, year ago), merged with what earlier batches stored so FII/DII fill in over time. Newest value wins per quarter; a missing value never erases a stored one; capped at 12 quarters (`hub/shareholding.py` `target_dates`, `holding_history`).
- Verified: `test_holding_history.py` (dates line up with the filings read, oldest-first, merge across batches keeps earlier FII/DII, cap, empty fetch keeps history); page previewed on real data with stand-in history for one company.

### Admin dashboard rebuilt: research-terminal design, Proven compounders screen, clickable stock report
Owner's feedback: the Matured tab looked identical to Multibagger, there was no way to see a full report on a company, and the dashboard looked unprofessional. Owner's choices: compounders as their own screen; the report to include live quarterly trends from BharatStock; a clean research-terminal look.
- **Why Matured looked identical:** it was the same multi-bagger list, same columns and detail panel, with only the default sort changed (more fund holders first). Replaced.
- **Proven compounders** (new screen, client-side over the library): established companies that pass all six rules -- profit up in 6+ of the last 8 quarters, net margin >= 8%, operating cash >= 0.8x profit, held by 30+ fund schemes, pledge <= 5% (or none recorded), market cap >= Rs 5,000 cr. Ranked by five extra quality checks (revenue growing, interest cover >= 3x, ROE >= 15%, above 200-day average, promoter stake steady) then size. 76 companies on 9 Oct data (HDFC Bank, ICICI Bank, Infosys, HAL, NTPC, Divi's, Eicher, Pidilite, Britannia, Polycab...). A "near misses" view shows companies failing exactly one rule and which.
- **Early multibaggers**: same backend screen, now with its own columns (gates, turnaround, revenue/profit growth, margin, consistency, fund schemes, market cap, promoter signal) and filters.
- **Stock report** (click any company anywhere, or search by symbol/name): header with badges (proven compounder, multibagger x/4, turnaround, undiscovered, high pledge); market cap, P/E, 1Y return, 3Y CAGR, 52-week range, dividend yield; **price chart** 6M/1Y/3Y with a rebased **vs NIFTY** view; **quarterly revenue and net profit bars with net margin** (12 quarters, consolidated); **scorecard** of every measure grouped (growth, profitability, cash flow, balance sheet, valuation, price, ownership, context) with where the company ranks among all ~1,860 in the library; **shareholding donut** and changes; **corporate actions** (upcoming first); **recent news**; multi-bagger gates; and the full parameter table.
- **Live parts** come from new `relay/Report.gs` (`adminStock`): BharatStock quarterly financials and three years of prices (fetched on click, never stored or cached -- licence), NIFTY from the private `state/prices.json`, Google News headlines. Each part fails independently with a reason. **Needs `BHARATSTOCK_API_KEY` in the relay's script properties** (entered by the owner); until then the two charts say so and everything else works. About 2 BharatStock requests per report opened.
- **Weekly batch now keeps what it already fetched and dropped**: each company's NSE corporate actions (last year + upcoming, `actions`), its `sector`, and a top-level `names` map (symbol -> company name, from NSE's EQUITY_L). They fill in as the batch revisits each company; names on the next batch.
- **Design:** sidebar navigation, global search with suggestions, overview page (KPIs, top compounders, top multibaggers, upcoming corporate actions, data coverage), sortable sticky-header tables, consistent type and colour, dark mode following the system, phone layout. Registry, bulk deals, parameters and back-tests restyled (back-tests no longer raw JSON dumps).
- **The page moved out of a template literal into `relay/AdminPage.html`** (served with `createHtmlOutputFromFile`), removing the escaping trap behind the 9 Oct broken-button bug. `relay/check.js` now parses every `.gs` file, checks they don't clash, parses every inline script in every `.html` page, and checks that every server function the page calls exists and is public.
- Verified on this machine against the real private data (library, multi-bagger, admin summary) with a stand-in relay: overview, both screens, library, search, stock report (charts drawn with stand-in live data), phone layout. `test_batch_report_fields.py` covers the corporate-actions filter (upcoming + last year, newest first, malformed dropped), company-name parsing, and that the existing dividend/buyback values are unchanged.

### Relay deploys moved to `clasp` (no Chrome needed)
- Chrome-based deploys kept failing on account mix-ups: Claude in Chrome only reaches profiles whose extension is signed in to the session's Claude account (on 9 Oct, Chrome `Default` = Google ramghatage@gmail.com was reachable; `Profile 5` = Google ramghatagedb1101@gmail.com was not), and the deploy dialog itself is sometimes blocked by the session's permission check.
- `clasp` 2.4.2 installed globally and signed in as **ramghatagedb1101@gmail.com** (credentials in `~/.clasprc.json` on the owner's laptop). Needed: the account's Apps Script API setting turned On (script.google.com/home/usersettings) and **all** permission boxes ticked at sign-in -- the first attempt granted only name/email and every call failed with "insufficient authentication scopes".
- Gotcha found and recorded: with the API setting still off, `clasp push` printed "Pushed 3 files" but nothing changed; the first version created afterwards (Version 23) held the *old* code and was not deployed. Always confirm the uploaded content before versioning -- the procedure in `relay/README.md` does.

### Sign-in now lasts 7 days (admin dashboard and phone app)
- Owner's choice (was six hours). The six hours was CacheService's hard cap on any entry, not a setting, so sessions moved to the **script properties** with their own expiry (`ADMIN_SESSION_DAYS = 7`).
- Each session is stored as `sess_<SHA-256 of the token>` = expiry time, so the token itself never appears in the project settings (both Google accounts with access to the project can see those). Expired sessions are deleted when checked and swept whenever a new one starts.
- **Sign out now ends the session on the server**, not just in the browser: new `adminLogout(token)` (dashboard) and `mode=app_logout` (phone app). Several devices can be signed in at once; signing out one leaves the others.
- One-time effect of deploying it: sessions from the old storage stop working, so each device signs in once more.
- **Deployed 22:18 IST as Version 24 on both addresses**, with `clasp` from the owner's machine (see below). Verified live on both: page script parses, `app_data` refuses an unknown session, new `app_logout` answers, quotes unaffected.
- Verified offline (`test_sessions.js`, 13 cases, Apps Script services mocked): valid at 6 days 23 hours, expired after 7 days, expired entries deleted, two devices independent, sign-out ends only that session, unknown or empty tokens refused by `adminData`/`appData_`, `app_logout` works. `node relay/check.js` passes.

### Admin login button: real cause found and fixed -- a browser-side syntax error, not authorization
- **Cause:** the new Multibagger/Matured code in `relay/Admin.gs` had `'... (the screen\'s own default ranking)'` inside the `ADMIN_HTML` template literal. In a template literal `\'` is just `'`, so the page's browser script got a bare quote in the middle of a string and **failed to parse as a whole**. No button on the page had a handler; "Email me a code" did nothing; `doGet` ran (the page loads) but `adminRequestCode` never did -- exactly what the Executions log showed. Reworded to avoid the apostrophe.
- **Why the earlier diagnosis missed it:** `node --check relay/Admin.gs` only sees the server code; the browser script is a string to node. And the deployment that "worked" (`AKfycbye12r6…`) was on Version 20, which does *not* contain the new tabs -- it was not the same code. The re-authorization theory is not needed.
- **New `relay/check.js`** (`node relay/check.js`): builds `ADMIN_HTML` the way Apps Script does and parses each `<script>` block in it, plus both server files. It fails on the broken 9 Oct code and passes on the fix. **Run it before every relay paste/deploy.**
- **Session now kept across tab closes:** the admin token moved from `sessionStorage` to `localStorage` (wrapped in try/catch). The server session is unchanged (six hours, CacheService's cap); an expired token still lands on sign-in.
- Commit `d7578a5`. Pasted into the Apps Script editor and **saved** (verified the editor matched the repo exactly first; `Code.gs` unchanged). **Deployed ~19:50 IST** as a new version on both `AKfycbwQZxgg…` (admin bookmark) and `AKfycbye12r6…` (live relay), from the ramghatagedb1101@gmail.com Chrome profile. Verified live: both serve the fixed page and its served script parses.

### Accounts and browser access: read this before acting on the owner's behalf
- **Accounts for this project:** only Google `ramghatagedb1101@gmail.com` (owns the Market_watch relay; codes and alerts go there) and GitHub `ramghatagedb1101-NSEFO`. The owner's other Google `ramghatage@gmail.com` and GitHub `ramghatage-ux` **must not be used here** (owner's instruction, 9 Oct).
- **Claude in Chrome reaches only the profiles signed in to the session's Claude account.** The owner has two Claude accounts and two Chrome profiles, each with the extension. When this session ran as Claude `ramghatage@gmail.com`, `list_connected_browsers` showed only the profile logged in to Google `ramghatage@gmail.com` (no GitHub login); the ramghatagedb1101 profile was invisible. Fix: match the extension's Claude account in the ramghatagedb1101 profile to the session's (this doesn't change its Google/GitHub logins), and close or sign out the other profile's extension. **Before any outward action in Chrome, check:** GitHub `meta[name="user-login"]` = `ramghatagedb1101-NSEFO`; Apps Script account popup = `ramghatagedb1101@gmail.com`.
- In the wrong profile, a relay deploy dialog showed "Execute as: Me (ramghatage@gmail.com)" and asked to authorise; cancelled, nothing changed. Deploying from the wrong Google account would make the relay run as that account.
- **Relay deployments:** 8 active. `AKfycbye12r6…` is the live relay (`docs/index.html` RELAY_URL, the `RELAY_URL` secret, the Kite redirect). `AKfycbwQZxgg…` is the owner's admin bookmark. Update both in place (pencil → version), never "New deployment" (changes the URL).
- **Kite resets every access token at about 6:00 AM IST.** A login after midnight but before 6 AM is stored as "today's" token and then wiped, giving "Kite: Incorrect `api_key` or `access_token`". The relay only checks the token's date. Log in after 6 AM. (Happened 9 Oct; a fresh login at 06:40 fixed it.)
- **Stock library restarted** after the quota reset: the 8 Oct chain had stopped on a 0-processed batch. Run 37869589396 (started by the owner 06:54) scored the full 70 minutes and chained; batch 2 (run 37875233387) started 08:04.

### Admin dashboard: added Multibagger and Matured tabs; redeploy left the login button broken
Owner asked for two new admin-dashboard tabs: one showing the full multi-bagger ranked list (previously
only a summary count existed, on the Status tab), and one surfacing the same data sorted toward
established, widely-held performers instead of the screen's own default bias toward fresh/undiscovered
names (more mutual-fund holders first, not fewer).

- `relay/Admin.gs`: added `adminMultibagger()` (reads `site/multibagger.json` from the private repo,
  same pattern as the existing `adminLibrary()`), two new `TABS` entries (`multibagger`, `matured`), a
  shared `draw()` branch and `loadMb()`/`drawMbTable()`/`mbGoPage()`/`showMbStock()` client functions --
  both tabs share one data load, differing only in default/selectable sort order. No new data pipeline:
  `multibagger.json`'s `ranked` list and its `mutual_funds.schemes_holding` field already carried
  everything needed.
- Verified the pasted content line-by-line against the local file in the Apps Script editor (search-based
  spot checks on every new function, not just a visual scroll) before saving, after an earlier mid-edit
  mistake: a `key` action meant to scroll the editor typed "Page_Down" as literal text into the file
  instead, corrupting one line -- caught before saving, fixed by re-pasting clean from the clipboard.
- Deployed as a new version ("Version 21") to the owner's actual bookmarked admin URL (confirmed by
  matching the Deployment ID character-for-character against the URL the owner pasted, since the project
  has eight active deployments, several with near-identical names, and the one initially opened for
  editing turned out to be the wrong one).

**Found immediately after deploying: the live "Email me a code" login button stopped working on that
URL** -- no error, no success, just silent. Confirmed via the Apps Script Executions log (authoritative):
every click since the redeploy produces a `doGet` with zero `adminRequestCode` executions, on multiple
fresh tabs, after a hard refresh, after long waits, and from the owner's own separately-opened tab. The
exact same code on a second, untouched deployment of the same project (still pinned to the old "Version
20") worked on the very first click. Ruled out: the diff touching login code (`git diff` confirms it
didn't), a JS syntax error (`node --check` on the full file is clean), and Google-side quota exhaustion
(the untouched deployment proves quota is fine). Leading theory: Apps Script's one-time re-authorization
requirement for a privileged call (`MailApp.sendEmail`) under a brand-new deployment version, normally
cleared by running the function once from the editor -- attempted but not completed before this session
had to stop (the editor's function-selector dropdown kept silently reverting to `adminPage`, so the
intended re-auth attempt never actually exercised `adminRequestCode`). **Full diagnosis and next steps
in `STATUS.md`'s HANDOVER section -- read that before touching this.** Not yet fixed as of this entry.

Also flagged by the owner, not yet implemented: the dashboard asks for a fresh six-digit code every time
the browser tab/window closes, even within the server's own 6-hour session window, because
`relay/Admin.gs` stores the login token in `sessionStorage` (cleared on tab close) rather than
`localStorage`. Diagnosed, low-risk one-line-type fix identified, not made -- blocked on the login bug
above making it impossible to verify end-to-end.

### Claude's own `git push` access broke -- wrong GitHub account, not a code problem
No code change today; a local environment problem, logged here because it blocked pushing the rest of
today's work and the next session needs to know about it immediately.

`git push` started failing with `Permission to ramghatagedb1101-NSEFO/market-hub.git denied to
ramghatage-ux` (HTTP 403). Root cause: the owner's machine has `gh auth git-credential` registered as
the credential helper for github.com (in `~/.gitconfig`, overriding the system's normal Credential
Manager), and `gh` itself is currently logged in as `ramghatage-ux` -- the account used for the owner's
*other* projects (Aiyoo.shop, HaloShoot), not the one that owns `market-hub`. Confirmed directly:
Claude-in-Chrome's browser session is signed into github.com as `ramghatage-ux` too (its own repo list
showed `ramghatage-ux/aiyoo`, `ramghatage-ux/haloshoot`, etc.) -- the owner has multiple Chrome profiles
logged into different GitHub accounts, and Claude-in-Chrome was driving the wrong one when this was set
up. Switching the Chrome profile alone will not fix it: `gh auth login`'s token is cached once and
persists independently of which browser profile is active afterward.

**Fix needed from the owner, not Claude:** run `gh auth login` fresh, choosing the browser-based flow,
and complete the GitHub authorization step in the Chrome profile actually signed in as the account that
owns `market-hub` -- not `ramghatage-ux`. This is an account-authorization action, so it's the owner's
to click, same as every other credential step in this project. Once `gh auth status` shows the right
account, a plain `git push` should work again with no further changes.

**Resolved, same day.** The owner had two Chrome profiles signed into different GitHub accounts, and
the one Claude-in-Chrome happened to be paired with kept flipping between them across reconnects --
not a changing login, just no way to tell which physical window "Browser 1" pointed to on any given
connection. Once the owner confirmed which open window was actually signed in as
`ramghatagedb1101-NSEFO`, `gh auth login`'s browser-based device flow was run against that window
(code `870D-050A`, approved by the owner -- the account-authorization click is always theirs to make).
`gh auth status` confirmed the account switch, and the 3 queued commits (`17669cc`, `07d7c3a`,
`53549dc`) pushed clean after a trivial merge with 8 unrelated automated `live quotes` commits
(`docs/data/live.json` only -- no overlap with the queued changes). `git push` is back to normal; no
lingering effect on anything else from 8 Oct, which was already pushed before this broke.

## 2026-10-08

### Stock credit-spread screen: activated the dormant position tracker, fixed a silent sector-cap bug
Asked "did the SBIN recommendation actually work out," and the honest answer was "nothing tracks
that" -- found the fix was mostly already written. `rg/tracker.py` and `rg/mtm.py` are a complete,
vendored position tracker (persist recommendations as OPEN, settle at expiry with realized P&L,
Black-Scholes mark-to-market for open positions), left dormant on purpose per `hub/stocks.py`'s own
former docstring ("no tracker writes, no positions are booked"). Also found, while wiring it in: that
same `main()` already called `tracker.open_sector_counts()`/`open_position_keys()` for **reads**, so
the sector-concentration cap (`MAX_PER_SECTOR`) could apply across runs, not just within one -- but
since `tracker.record_new()` was never called to **write** to that book, it has been permanently
empty since this screen went live. The cross-run sector cap (built specifically to prevent two runs
13 minutes apart both picking the same sector, a real 17-Aug-2026 incident) has silently been a no-op
the entire time.

- `hub/stocks.py`: added `_settle_fn()` (the underlying's live LTP, for `tracker.evaluate_closed()`)
  and `_track_record()` (an all-time summary via `tracker.summary()`, gated at 10 settled trades
  before publishing a win rate -- lower than the Desk tab's 20, since 30-66 DTE settlement is far
  slower than a daily index forecast and 20 could take many months here). Wired `evaluate_closed` →
  the existing screen → `record_new` → publish, each run. Every **qualifying** recommendation is
  tracked as if traded -- nothing in this app knows whether the owner actually took a given trade, so
  this is the screen's own measured hypothetical performance, stated explicitly in the published
  `"basis"` field, not claimed as the owner's real P&L.
- `rg/config.py`: moved `POSITIONS_FILE` out of `rg/data/` (never synced anywhere, gitignored into the
  void) to `state/stocks_positions.json`, syncing automatically via `hub/site_data.py`'s existing
  `state/*.json` glob -- same mechanism as today's other two new logs. `rg/tracker.py`'s `_save()` was
  creating `DATA_DIR`, not `POSITIONS_FILE`'s own parent; fixed, since those two now diverge.
- `hub/admin_publish.py`: added `stock_track_record` to the existing `TESTS` dict, which already feeds
  the admin dashboard's Back-tests tab generically -- surfaces with **no `Admin.gs` change at all**.
- Verified with a standalone test (`test_stock_tracker.py`, 9 cases) before wiring anything in:
  `_settle_fn` returns the live spot and fails safe (0, never a fabricated price) on a bad quote or
  exception; the win-rate gating at each of the three bands; a position settling above its short
  strike realizes as a WIN with positive P&L; an open position never contributes to realized P&L (the
  exact 17-Aug-2026 day-0-credit bug `mtm.py` warns about); and, directly reproducing the dormant bug
  this also fixes, a second run's position is now visible to `open_sector_counts()` via the same
  persisted book a prior run wrote to.
- Scope, deliberately: covers the stock screen only, not the index-level F&O suggestions
  (`hub/fno.py`, no equivalent tracker) or expiry-theta (already has its own lighter settled-session
  log from earlier today, logging a last intraday read rather than a true realized P&L).
- **Not yet done:** a live `python -m hub.stocks` run to confirm the book persists correctly through a
  real cycle -- the standalone tests cover the logic, not an end-to-end live run yet.

### Stock screen: a run-history log, found missing while answering a real question
Asked what would have happened on the SBIN spread the owner saw mid-morning, and had to answer "I
can't tell you" -- `hub/stocks.py` overwrites `docs/data/stocks.json` on every run, including manual
re-dispatches used for testing, and the daily job ran four times on 8 Oct (pre-market, a 10:55 IST
mid-morning run, and the scheduled 18:22 IST post-close run). Whatever the mid-morning run actually
recommended was gone the moment the evening run replaced it as "today's" view, and it wasn't in the
GitHub Actions log either (that step only logs a line count, never the recommendation itself) or
recoverable from the private repo's history (no access to it from here).

Added `_append_log()` to `hub/stocks.py`: every run now also appends a compact row (timestamp, mode,
symbol count, India VIX, and the full recommendations list -- strikes, credit, max loss, POP, spot at
entry) to a new `state/stocks_log.json`, capped at 1,000 entries, alongside the existing overwritten
"current" file (unchanged). Diagnostics (the ~50-name rejection breakdown) are deliberately left out of
the log to keep it lean -- only what was actually suggested is worth keeping forever. Syncs
automatically via `hub/site_data.py`'s existing `state/*.json` glob; no workflow change needed.
Verified with a standalone test (`test_stocks_log.py`, 5 cases): a run's recommendations survive
intact; two same-day runs with different numbers for the same symbol both stay retrievable, not one
overwriting the other; a zero-recommendation run still gets logged, not silently skipped; the log caps
at `LOG_MAX_ENTRIES` keeping the most recent rows; a missing or corrupt log file never breaks the
daily job.

### Acted on an outside options-trading review of the methodology doc
Prepared a methodology write-up for an outside expert (trading/quant background) to review; their
written feedback flagged two concrete, implementable changes and confirmed the existing 0.20-0.30
delta band trade-off as the right call (no change needed there). Two other recommendations --
a capital-efficiency (ROCE) gate on the multi-bagger screen, and an adaptive band-learning step size
in the core forecast engine -- need more groundwork (confirming 3-year ROCE data actually exists
cleanly in BharatStock's annual rows; backtesting the engine change before it goes live) and are not
yet started. A third (splitting "Financial Services" into Private Banks/NBFCs/PSU Banks/Insurance/AMC
sub-sectors) conflicts with a documented past decision -- neither NSE's CSV nor BharatStock expose
that breakdown, and a prior hand-built sector taxonomy disagreed with NSE's own label on 24 of 25
names -- left as is, by the owner's explicit call.

- **`rg/strategy.py`/`rg/config.py`: a slippage haircut on the credit-spread qualification gate.** The
  reviewer flagged that qualifying a spread on its unhaircut mid credit (`_gate_credit`) overstates
  what a retail limit order on a thinner NIFTY 50/100 name will actually fill at. Added
  `CREDIT_SLIPPAGE_HAIRCUT_PCT = 12.5` (centre of the reviewer's suggested 10-15% range) applied only
  inside `_gate_credit`'s pass/fail threshold -- the displayed `net_credit`, position sizing, score and
  the stop-loss/profit-target prices all still read the real, un-haircut mid from `_build_spread`, so
  the card never shows a number the trade didn't actually offer. Verified with a standalone test
  (`test_slippage_haircut.py`, 4 cases): the haircut lowers the gated credit without mutating the real
  mid; a spread that cleared the raw 15% floor but not the haircut-adjusted one is now correctly
  rejected; a spread with real margin above the floor still passes; an out-of-range config value is
  clamped rather than inverting the gate.
- **`hub/expiry_theta.py`: a settled-session log for the 0-DTE module.** The reviewer's verdict on the
  expiry-morning iron condor was explicit: keep it at 1 lot (already true) "as a live paper-trading
  exercise until you have accumulated at least 50-100 settled sessions of recorded execution data" --
  but nothing previously recorded what happened to a suggested condor after the fact; `STATE_FILE` is
  overwritten by the next session's suggestion, so last Tuesday's outcome was gone the moment this
  Tuesday's first run wrote a new one. Added `_archive_stale_session()`, called at the top of `main()`:
  when a new day's run notices `STATE_FILE` holds a prior session, it appends that session's last
  intraday read (status/verdict/cost-to-close, from whatever `OUT_FILE` last recorded that day) to a
  new `state/expiry_theta_log.json`, before this run's fresh suggestion overwrites the state file.
  Deduplicates by date, so re-running the same morning never double-logs. Explicitly labelled as "last
  intraday read, not a confirmed end-of-day settlement" in every row -- this module runs three times
  during market hours, not at the close, so a true settlement price is never actually known. Syncs
  automatically via `hub/site_data.py`'s existing `state/*.json` glob; no workflow change needed.
  Verified with a standalone test (`test_expiry_theta_log.py`, 5 cases): archives a stale session with
  its last read; never touches today's own in-progress session; two runs on the same new day log the
  stale session only once; a first-ever run with no state file is a quiet no-op; a session still gets
  logged (with nulls) if `OUT_FILE` has already moved past it.

### Stock library: found the 8 Oct quota corruption is much larger than first thought, repair tool added
- Checked the admin dashboard's Library tab for real -- **1,401 of the 1,896 published entries (74%) are bare `{"symbol", "error"}` placeholders**, not real company data: every one carries the exact "429 Client Error: Too Many Requests" error the 8 Oct quota-exhaustion incident produced before `_is_quota_exhausted()` stopped a batch cleanly on its first 429 instead of writing garbage for the rest of the universe. The corrupted range is one contiguous block (confirmed by paging the admin dashboard: real data for the first ~495 companies by rank, then 0/0/0/0% straight through to the end) -- several separate pre-fix batches' tails, accumulated over days, not one single incident.
- Normal weekly batching would eventually walk back through this range and fix it on its own, but the cursor had already moved past it by the time this was checked today -- a full ~2,570-company cycle away, weeks at the current cadence, not acceptable for data this broken.
- Added a one-off `fix_cursor_for_corrupted_entries()` to `hub/library.py` (`python -m hub.library --fix-cursor`): found every entry with an error and no `cells` (the exact corruption signature) and moved `cursor_next` back to the earliest one's position in the current universe order. Touches only the cursor, not the entries themselves -- each gets properly overwritten, not deleted, when its batch turn comes around. Verified with a standalone mocked test (`test_fix_cursor.py`, 4 cases) before running for real.
- **Ran it 8 Oct via a one-off workflow** (`fix-library-cursor.yml`, `workflow_dispatch`, with a push-trigger fallback since the `gh` CLI's token here turned out to only have read access -- `git push` uses a different, separately-configured credential). Confirmed from the run's own log: `corrupted_count: 1397, old_cursor: 1896, new_cursor: 499`. The function and the one-off workflow were both removed afterward, same lifecycle as `diag.yml` earlier today -- this was a repair, not a feature.

### Phone app: a live, reproducible outage found and fixed (not just transient)
- Live, signed-in walk of the phone page's F&O/Multi-bagger/Desk screens found the whole data layer down: "Brief not available", "feed unavailable" -- live index quotes (a separate public endpoint) kept working, so the gate itself and the quotes ticker looked fine, but every signed-in screen was empty.
- Root cause: `relayPost()` (`docs/index.html`) POSTs to the relay for every signed-in data call (`app_data`, the single call that bundles feed/brief/context/stocks/fno/multibagger) with **no retry at all**. Confirmed via the browser's network log: 4 consecutive `app_data` POSTs all returned HTTP 404, while the relay's own GET `mode=quote` endpoint answered normally the whole time -- the exact same transient Google-side 404 already found and fixed today in five GitHub Actions workflows (daily.yml, expiry-theta.yml, live.yml, indicator-test.yml, threshold-test.yml), just never carried over to the one place a real visitor actually hits it.
- Fixed with the same 3-attempt backoff pattern already used in those workflows, now in `relayPost()` itself so every `app_*` call (sign-in code, verify, and the data bundle) benefits. No change to `relay/Code.gs`/`Admin.gs` -- this is a client-side-only fix, so it needs no manual redeploy, just the next push to `docs/`.

### Admin dashboard: live tab-by-tab audit, one real UX gap fixed
- Signed in and walked all six tabs (Status/Library/Parameters/Registry/Bulk deals/Back-tests) with real data -- all render correctly, including the Library tab's 1,896-row filtered table and the Registry tab's NSE-filing-to-alias candidate matches.
- **Tapping a library row to see its parameter detail looked broken but wasn't.** `showStock()` (`relay/Admin.gs`) correctly fills `#stockdetail`, but that div sits below the full 100-row page, and nothing scrolled to it -- on a long page this reads as "nothing happened." Added `scrollIntoView({behavior:'smooth'})` after both the success and error-row paths. Needs the relay redeployed by hand before it's live (`relay/README.md`).

### Three more "claims vs. reality" bugs found in a full business-logic audit
- **`rg/strategy.py`: the concentration-limit diagnostic's own expiry date was never read.** `config.CAP_DIAGNOSTIC_UNTIL` documents that past that date the diagnostic (`cap_suppressed`, which re-simulates `_apply_caps` three times over on every run) should stop and be replaced by a prompt to decide on `MAX_PER_SECTOR` permanently -- found 8 days past its own expiry with no change in behavior, because nothing ever actually compared the date. Added `_cap_diagnostic_rows()`: past the date, skip the simulation and surface the pending decision as a `DIAGNOSTIC_EXPIRED` row instead. Confirmed no user-facing impact today (`docs/index.html` never displays this diagnostic), but the code now matches its own documented intent. Verified with a standalone test (5 checks: runs normally before/on the expiry date, skips `cap_suppressed` past it, correct sentinel row, downstream count doesn't crash).
- **`hub/context.py`: one failing news feed used to discard every headline already collected from the other four.** `_headlines()` loops over 5 RSS feeds (CNBC and Investing.com have both been flaky); an exception from any single feed propagated out of the whole function, losing headlines the other working feeds had already returned -- contradicting this module's own stated "each source fails on its own" design, just at a finer grain than the top-level sources. Fixed so each feed fails independently; only a fully-failed run (all 5 down) still raises, so the daily brief correctly shows headlines as unavailable rather than silently publishing an empty list as if nothing had failed. Verified with a standalone test (one feed failing preserves the others' headlines; all feeds failing still raises).
- **`hub/narrate.py`: the promised "Gemini fallback" didn't exist.** `daily.yml`'s step is literally named "Daily brief (NVIDIA, Gemini fallback)", but the code only ever reached Gemini when `NVIDIA_API_KEY` was unset entirely -- a live NVIDIA outage with both keys present (the actual case this repo runs in) wrote an error message instead of falling back. Extracted `_write_gemini()` as a standalone function and restructured `main()` so Gemini is tried on any NVIDIA failure, not just a missing key. Verified with a standalone test (4 scenarios: NVIDIA fails, Gemini succeeds -- falls back correctly; NVIDIA fails, no Gemini key -- honest error; NVIDIA succeeds -- Gemini never called; both fail -- combined error message).
- Closed as confirmed-working-as-designed, not bugs, during the same audit: `hub/fno.py`'s gates and expiry detection, `multibagger.py`'s constants, `hub/bulkdeals.py`'s BUY/SELL matching (checked live against NSE's real CSV), the admin relay's media-type handling for large files, `docs/index.html`'s sign-in form and `APP_FILES` contract, and the vendored-but-intentionally-dormant `rg/tracker.py`/`rg/mtm.py` position-tracking subsystem (confirmed nothing in `hub/` imports either module).
- Deleted confirmed-dead code: `.github/workflows/kite-login.yml` and `diag.yml` (nothing reads the `KITE_ACCESS_TOKEN` secret any more; diag.yml's own header said to delete it once self-dispatch permissions were proven, which they now are), plus their orphaned dependencies `hub/sources/kite_login.py` and `triggers/diag.txt`.

### Expiry-day theta harvest (`hub/expiry_theta.py`, EXPERIMENTAL, UNVALIDATED)
- New, deliberately separate module from `rg/strategy.py`: a NIFTY iron condor opened on its own weekly expiry morning, profiting from that day's rapid time decay. The stock credit-spread screen has a hard 30-DTE floor and force-closes at 21 DTE specifically to stay out of this window (severe gamma risk); this trades exactly the window that choice avoids, so it is a genuinely different risk profile, not a variant of the existing screen.
- Short strikes are placed at least 3x NIFTY's own realized daily volatility from spot (`state/prices.json`, free), not a fixed percentage -- data-driven, same convention as the rest of this file. Credit-to-width gate is stricter than the daily F&O screen's (0.15 vs 0.10), stop-loss tighter (1.5x credit vs the 30-66 DTE screen's 2.0x), fixed 1-lot sizing -- conservative on every axis given this is unvalidated.
- Runs three times on NIFTY's expiry day (10:00, 12:30, 14:45 IST) via a new `expiry-theta.yml` workflow: morning suggests a trade (same-day state persisted to `state/expiry_theta_state.json`, synced like any other state/ file); the later two runs read the same position's live cost-to-close and give a hold/exit verdict from the stop-loss/profit-target gates, instead of screening again. No order is ever placed by the script -- same as every other suggestion in this codebase, the owner trades manually.
- No backtest exists or is possible without intraday historical options data this repo doesn't have -- unlike the rest of the daily job's output, this has not even been checked against the past. Every output carries an explicit EXPERIMENTAL/UNVALIDATED disclaimer; treat it as a hypothesis, not a track record.
- Verified with a standalone test against a fabricated option chain and NIFTY price history (mocked Kite client, no live calls): no-op on a non-expiry day, a sane new suggestion on expiry morning (4 legs, positive credit, stop-loss above profit-target), and a correct hold/exit management read on a same-day re-run.

### Closed three more roadmap items: 10th-4th analytical tools, working capital, sector P/E history
- `hub/tools/more_tools.py`: the four analytical tools missing since the original "ten analytical tools" request (six were built first) -- `macd_cross` (medium-term EMA momentum), `bollinger_reversion` (20-session mean reversion, longer than `rsi_reversion`'s RSI(14)), `momentum_10d` (medium-term continuation, distinct from `short_reversal`'s 1-day reversal and `drift_252`'s full-year drift), `turn_of_month` (day-of-month seasonality, distinct from `weekday_bias`'s day-of-week seasonality). Auto-registered via the existing plugin loader; the engine already defaults an unseen tool to `DEFAULT_WEIGHT`, so nothing else needed changing.
- `working_capital_days`/`working_capital_change`: were marked "available" but never implemented. Implemented with the same defensive multi-candidate field-name guess already used for `dividend_paid` -- a wrong guess stays a gap, never a fabricated figure.
- `sector_pe_vs_history`: genuinely cannot mean anything without a persisted sector-P/E time series, which didn't exist. Started one (`state/sector_pe_history.json`, one point per batch per sector); the comparison activates only once 8 observations have accumulated. Registry status set to `collecting`, matching the existing bulk-deal parameters' convention.
- Fixed two stale `README.md` claims ("F&O picks (not connected yet)", "multi-bagger screen (not connected yet)") -- both have been live for days.

### Fixed a real multibagger-scoring bug found while investigating live batch numbers
- Two consecutive live batches (617 companies combined) reported `multibagger_batch_written: 0` -- every company failed to produce a multi-bagger score. Found and fixed an unguarded zero-price division: several of today's new price parameters (`ret_1m/3m/6m/12m`, `from_52w_high/low`, `rel_strength_vs_index`) divided by a specific historical close or window extreme without checking it was nonzero, plausible across 2,572 companies including illiquid/suspended micro-caps. Also added `batch_error_count`/`multibagger_failure_sample` diagnostics to the log output, so a future zero-written batch is diagnosable from the GitHub Actions log directly.

### Privacy: phone app sign-in, and all working data moved to the private repo
**Phone app sign-in**
- **The phone page now asks for the same six-digit email code as the admin dashboard** (ten-minute code, one per minute, six-hour session kept on the device). It posts to the relay (`mode=app_code`, `app_verify`, `app_data`; text/plain body, so no CORS preflight) because it is a separate web page and cannot use `google.script.run`. Settings has a **Sign out** button. Live index quotes in the ticker stay public and show before sign-in.
- **A wrong code five times cancels the code**, for the dashboard and the phone app alike; previously a code could be guessed without limit within its ten minutes.
- One data call (`app_data`) returns every file the page needs; the relay fetches them from the private repo in parallel (`UrlFetchApp.fetchAll`) with the existing read-only `ADMIN_READ_TOKEN`. No new secret or script property.
- Service worker cache bumped to `market-hub-v10` so phones pick up the new page.

**Data moved out of this public repo** (new `hub/site_data.py`)
- `docs/data/*.json` (feed, brief, context, stocks, fno, multibagger, back-test and test summaries, bulk deals) now live in `market-hub-private/site/`. `live.json` stays public: index quotes only, the same as the relay's public `mode=quote`.
- `state/` (`state.json`, `prices.json`, `bulk_deals.csv`) now lives in `market-hub-private/state/`. The daily job no longer commits it here; its commit step now only saves `rg/data/sector_map.json` and `index_membership.json` (public index lists).
- Every job that reads or writes these files runs `python -m hub.site_data pull` after checkout and `push` at the end (daily, library, multibagger, indicator-test, threshold-test, backtest-multibagger). `push` sends only files that differ from what `pull` brought in, in one commit, and rebuilds on the new head if `main` moved, so the daily job and a library batch running together never overwrite each other's newer file. In daily.yml the pull is now required (no `continue-on-error`): without state the forecast would restart from nothing.
- The first pull of each folder seeds from this repo's last public copy (site: `13e3a83`; state: `2e10d3f`), so history carries over. New manual `site-data.yml` does that copy without running a job. A seeded file that a job did not change is only sent if the private repo still has no copy, so a slow job that also seeded can never replace a newer file with the old public one.
- Running locally now needs `python -m hub.site_data pull` first (with `PRIVATE_REPO_TOKEN`), or jobs start from empty state.
- Not private: anything committed before today is still in this repo's git history.

**Rollout (done 8 Oct)**
- Relay redeployed as **Version 19** on the existing deployment the phone page, the daily job and the Kite redirect use (`AKfycbye12r6…`, same `/exec` URL). That deployment had been on Version 8 (7 Oct 10:13), so this also put live everything since then that had only been deployed to the separate admin-dashboard deployments, plus the 8 Oct email alerts. The other five active deployments were not changed. Checked live: quotes still served; `app_data` without a session returns `session_expired`; a wrong code is refused.
- `site-data` run seeded `site/` (commit `4f58b7b` in the private repo). GitHub Pages now returns 404 for the data files; `market-hub-4dq.pages.dev` serves the sign-in page in their place.
- A stock-library batch (run 37730982115) was mid-run on the old workflow when the change reached `main`. It finished cleanly (no multi-bagger change to commit, so nothing was re-added here) and chained to the next batch (run 37737062142), which runs on the new workflow and fetched its data from the private repo.
- Verified before rollout, offline: the sync logic against a fake GitHub API (seed, changed-file-only push for both folders, concurrent update from another job, no-change run), and the page against a mock relay (send code, wrong code, sign-in, reload keeps the session, expired session returns to sign-in and clears the screen, sign-out).

### Stock library: BharatStock quota efficiency, merged with multi-bagger, more parameters actually computed
- **library.py and multibagger.py used to each fetch the same BharatStock financials independently, a day apart (library Saturdays, multibagger Sundays).** Can't cache the raw responses to bridge them -- BharatStock's licence forbids re-serving raw financial data to disk, which is why multi-bagger's own file header already says raw figures stay in memory only. Fixed the actual duplication instead: `hub/library.py` now computes the multi-bagger gate score in the same per-company loop, from the rows it already fetched for the 124-parameter screen, and publishes `docs/data/multibagger.json` itself (same shape, so the public site needs no change). `multibagger.yml`'s weekly schedule is removed (kept as a manual escape hatch); `library.yml` now also commits `docs/data/multibagger.json` to the public repo. Trade-off accepted: multi-bagger coverage now grows with library's own batches instead of finishing in a single same-day run.
- **Several parameters were marked "available" in the registry but were never actually computed.** `price_values()` only ever computed `ret_12m`/`from_52w_high`/`above_200dma`; `ret_1m`, `ret_3m`, `from_52w_low`, `volatility_60d` were silently never built despite the registry saying otherwise. Separately, `delivery_pct_20d` and `volume_ratio_20d` always read empty placeholder lists (`price_values(px, [], [])`), so they could never produce a value either. All now computed, plus `avg_turnover_20d` and `delivery_change`, from a new `fetch_price_history()` that captures volume/delivery-percentage from the same BharatStock prices response the old fetch discarded -- no new endpoint, no new call.
- **`rel_strength_vs_index`, `beta_vs_index` added using NIFTY 50 data already stored for free** (`state/prices.json`, the daily NSE bhavcopy job) as the benchmark -- zero extra BharatStock calls. The registry's own wording said "Nifty 500"; relabelled to say Nifty 50 honestly rather than silently claim a benchmark not actually used.
- **`dividend_paid` and `dividend_policy_change` added** from the annual financials row already fetched for `cfo`/`capex`/`fcf` -- field name is a best-effort guess (several candidates tried), same defensive pattern used throughout this file for uncertain BharatStock field names; a wrong guess just leaves it a gap, never a fabricated figure.
- **`sector_ret_3m`, `peer_group_growth_median`, `rel_strength_rank_sector` added** via a new sector-aggregation pass after each batch, using only data every company in the batch already has (ret_3m, profit_yoy, ret_6m) grouped by `sector_map.json` -- no new fetches.
- **`mf_schemes_holding`'s rule direction was backwards.** It rewarded 5+ mutual fund schemes already holding the stock -- but `multibagger.py`'s own ranking has always preferred *fewer* holders as a tiebreaker ("fresher names first"), since heavy existing fund ownership means the market already found the stock. Fixed to reward thin ownership instead, and added `mf_discovery_tier` (1 = fewer than 5 schemes, 2 = 5-20) so a stock crossing from tier 1 to tier 2 between batches is still flagged as a watch item instead of silently dropping out the moment it "becomes part of the crowd."
- `working_capital_days` was also marked "available" but was never implemented (no field names confirmed); corrected to `gap` rather than leave a false label. `working_capital_change` and `sector_pe_vs_history` (needs a persisted multi-year sector-PE history that doesn't exist yet) remain explicitly `to_build`/`gap`, not faked.
- `library.yml`'s weekly cron moved from 13:00 IST to 07:00 IST Saturday (was landing early afternoon, not morning).
- Fixed a real resumable-batching bug found investigating quota usage: `fetch_existing()` read the private repo's `library.json` via the Contents API, which only inlines file content below 1 MB -- above that (true after the first ~899-company batch) it silently returned empty content, failing JSON parsing and resetting the cursor to 0, discarding every prior batch's work. Three batches this week repeated this before it was caught. Fixed with a fallback to the Git Data API's blob endpoint, which has no such limit.

### Email alerts for new "discovery" stocks (`hub/alerts.py`)
- A stock newly in `mf_discovery_tier` 1 or 2 (thin mutual-fund ownership) **and** passing at least 60% of its testable library gates (minimum 10 gates tested, so a data-starved stock can't trigger one) now sends an email via the existing Kite-login relay -- no new email service, reuses `RELAY_URL`/`RELAY_KEY` already in GitHub secrets, and sends to the same Google account the admin dashboard's sign-in code already goes to (`Session.getEffectiveUser()`).
- A symbol already alerted at its current tier doesn't re-alert every batch; a tier change (1 <-> 2) does re-alert, on purpose -- a stock's status moving is itself new information, and over-notifying was judged safer than silently going quiet on a stock that's slipping.
- Needs the relay's Apps Script redeployed by hand (`relay/README.md` has the exact steps) before it can actually send -- Apps Script isn't deployed from GitHub.
- Verified with a standalone test (fabricated stocks/tiers, no network): strong+thin-ownership stocks fire, weak-fundamentals and too-little-data stocks don't, repeat alerts at the same tier are suppressed, a tier change fires again.

### Daily job reliability
- Today's scheduled run failed in 41 seconds: the Kite-token relay call returned a generic Google "Drive: Page Not Found" page instead of a JSON response, even though a check moments earlier confirmed a valid token for the day. A transient Google-side glitch, not a real missing token or a code problem. Added a 4-try retry with backoff to that call; re-ran manually and it succeeded immediately.
- **Audited the rest of the daily pipeline for the same bug class.** `store.refresh_prices()` deliberately raises rather than write a partial price day ("no partial writes" is correct), but the underlying fetches had no retry at all, so a transient blip in either would trigger that intentional hard-stop and skip the entire rest of the day (F&O, market context, the brief, bulk deals, admin publish, the final commit — none of it). Fixed: `hub/sources/nse.py` and `hub/sources/kite.py` now retry a genuine fetch failure up to 4 times, without retrying (or swallowing) a real negative result — a 404 holiday, or Kite's "symbol not found." Verified with injected failures: recovers from a transient blip, doesn't waste retries on a real negative, still raises after a persistent failure.
- `daily.yml`: the "F&O suggestions" and "Collect today's bulk deals" steps were missing `continue-on-error`, unlike every other non-essential step in the same workflow — their failure was silently skipping bulk deals/admin-publish/commit (bulk deals' failure skipped admin-publish and the commit). Added.

### F&O stock screen: fixed two rejection-reason mislabelings, then the credit gate itself
- The Desk tab's duplicate, stale "Multi-bagger screen: Not connected yet..." stub was removed (the real tab already existed and was accurate; this one was leftover and wrong).
- Track record panel was showing 100%/0% hit rates computed from a single settled outcome. The direction-hit scoring itself checked out correct (a real sign-agreement test, not a "band trick"), but a percentage from N=1 isn't a track record — added a `MIN_N = 20` gate: a horizon with fewer settled outcomes shows "–" instead of a number, with a one-line note.
- `stockScreen()`'s rejection breakdown dumped everything that wasn't "earnings" or "IV rank" into one bucket hardcoded as "Delivery below the 40% gate," when most of those names were actually rejected for zero/low net credit. Rewrote with real per-reason categories (earnings, IV too low, IV not measurable, delivery, zero credit, credit-to-width too thin, short strike not past the OI wall, bid-ask too wide, POP too low) shown as proper symbol/value tables instead of one paragraph of prose.
- That rewrite had its own bug: it classified a stock's *whole* rejection detail string as one category by matching substrings anywhere in it, so a stock rejected on the call side for one reason and the put side for another got merged into a single (often wrong) bucket, and "low reward" (`% of width <`) collided with "zero credit" (`pays nothing`) on the same substring. Fixed by splitting each detail string at the actual leg boundary (`; call-side...`) before classifying each clause independently, verified against the real data until every category's count summed correctly and known multi-reason stocks (ADANIENT, KOTAKBANK, RELIANCE) showed under each of their genuine reasons, not a merged one.
- **The credit gate itself was silently rejecting real, tradeable spreads.** `USE_WORST_CASE_CREDIT` (a deliberate fix from 17-Aug for a real CIPLA incident where a spread priced to a negative worst-case credit) was gating *whether a trade qualifies at all* on the worst-case fill (both legs crossing the spread, i.e. a market order) — not just the reported return-on-risk headline. Three days of history showed exactly 1 qualifying trade total while India VIX sat at 13.6–13.95; several names (ADANIENT, BEL, ETERNAL and others) had a genuinely positive *mid* credit the whole time and were being discarded as "no trade." The gate now always reads the mid credit (the price a limit/combo order is meant to achieve — the same basis already used for sizing, scoring and the stop-loss/profit-target prices); the original CIPLA safety concern is preserved as an explicit `fill_risk` flag on the card ("needs a limit/combo order near mid — a market order may not fill this credit") instead of silently dropping the trade.
- The stop-loss and profit-target exit prices (`stop_loss_debit`, `profit_target_debit`) were already computed by the screening engine for every qualifying trade but never shown anywhere. Now displayed on each recommendation card, along with fixing a pre-existing display bug where the card read `r.credit`/`r.pop` — fields that never existed in the data (the real keys are `net_credit`/`pop_pct`) — so credit and POP always rendered as "–" even for a qualifying trade.

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
