# Changelog

Newest first. Dates are IST. "Login" covers how the Kite access token gets from your morning login into the daily job.

## 2026-10-11

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
