# Market Hub: guide for Claude sessions

A private research terminal for one Indian investor: every NSE company scored on 130+ measures, a
Shortlist with a weekly record against NIFTY, a research dashboard, a phone app, email alerts, plus NIFTY
forecasts and F&O screens, and (since 14 Nov 2026) an automatic index-options trading program on an IBKR paper
account with a strategy builder, back-tests and autopilot. It runs every day without a PC. Read `STATUS.md` (where things stand) and the
top of `CHANGELOG.md` (what changed recently and why) before changing anything.

## Accounts (non-negotiable)
- Act only as Google **ramghatagedb1101@gmail.com** and GitHub **ramghatagedb1101-NSEFO**.
- Never use ramghatage@gmail.com or GitHub ramghatage-ux, even if a browser or CLI is signed in to them.
  Check `gh auth status` and the Google account before acting.
- Never type or paste API keys, tokens or passwords anywhere. The owner adds secrets themselves.

## Where things live
| Piece | Where |
|---|---|
| Code, workflows, phone app (`docs/`, GitHub Pages) | this repo (public) |
| Data: library, Shortlist, digest, summaries, state | `ramghatagedb1101-NSEFO/market-hub-private` (`library.json`, `library_compact.json`, `site/`, `state/`) |
| Relay: Kite login, phone/dashboard API, emails, research dashboard page | Google Apps Script, source in `relay/` |
| Daily batch | GitHub Actions (`.github/workflows/`) |
| Trading program (paper) | `trader/` (this repo), running on the Oracle machine `market-hub-trader` as `trader.service`; set-up files `infra/trader/` |
| ICICI fixed-address hop | Oracle machine `market-hub-ip` (130.210.31.37), used by `breeze.yml` over SSH |

Key workflows: `library.yml` (stock library, daily 06:15 IST, chains itself), `daily.yml` (forecasts),
`breeze.yml` (ICICI minute history, 16:00 / 21:00 IST, needs the day's ICICI sign-in), `algo-sync.yml` (strategies to the
trading machine, its journals back, `site/algo.json`; every 10 min in market hours and on every switch from the
dashboard), `strategy-backtest.yml` (a builder strategy's back-test, started from the dashboard), `oci-launch.yml`
(switched off; makes / sizes the Oracle machine, never above the Always Free 2 cores / 12 GB),
`live.yml` (live quotes every 5 min in market hours), `expiry-tape.yml` (expiry days: relay called every minute,
the day's option-sellers record saved to the private repo's `state/expiry/`), `summaries.yml` (AI summaries), `diag.yml`
(run a `hub/diag_*` module on GitHub's servers).

Secret names (values are the owner's): BHARATSTOCK_API_KEY, KITE_API_KEY, GEMINI_API_KEY,
PRIVATE_REPO_TOKEN, RELAY_URL, RELAY_KEY, BREEZE_API_KEY, BREEZE_API_SECRET, ORACLE_SSH_KEY, OCI_API_KEY, OCI_TENANCY,
OCI_USER, OCI_FINGERPRINT, OCI_SSH_PUBKEY (GitHub); relay script properties hold the Kite token, ADMIN_READ_TOKEN, GH_PAT,
BHARATSTOCK_API_KEY, BREEZE_API_KEY, and the strategy builder's STRAT_* (strategies, active one, mode, fallback,
limits). The trading machine also holds `/opt/trader/secrets/bt.env` (PRIVATE_REPO_TOKEN, RELAY_URL, RELAY_KEY) for the
back-test worker (owner-approved 14 Nov 2026). The IBKR paper login lives only on the trading machine (`/opt/trader/.env`, `secrets/`), typed by the owner
through `set-login.sh`.

## Data sources and budgets
- **BharatStock** (paid, the only paid data source): 9,000 requests a day. Budget it: fetch only when
  a company has filed something new (`needs()` in `hub/library.py`), never per company per run. Its
  raw data must not be stored or re-served (licence): only derived figures; the relay shows raw figures
  live and never caches them.
- **NSE** (free): daily price file, filings lists, results XBRL, shareholding, announcements, annual
  reports. NSE blocks requests from the owner's laptop; test NSE code on GitHub with `diag.yml`.
- **BSE** (free): results snapshot and scrip codes (`hub/bse.py`). Needs `curl_cffi` (Chrome
  impersonation); plain requests get "Access Denied". BSE results are standalone only.
- **Kite Connect** (owner's plan): live quotes, candles, option chains. One login per day, through the
  relay's login link (the owner uses the Kite mobile-app route). Any other login with the same app cancels
  the relay's token; the relay detects that and emails (`relay/KiteWatch.gs`).
- **ICICI Breeze** (free, owner's ICICI account, 13 Nov 2026): minute F&O history for back-tests. The API key works only
  from the fixed address 130.210.31.37 (owner's Oracle Always Free server `market-hub-ip`, Mumbai); `breeze.yml` reaches
  ICICI through it over SSH. One ICICI sign-in a day (phone Settings button). Prices to the private repo only.
  The owner's own ICICI files (laptop `D:\ICICI data historic\NSEData`: NIFTY and BANK NIFTY options, every session
  1 Jan 2024 - 30 Oct 2026, each session under its nearest expiry) were imported on 14 Nov 2026 by
  `hub/icici_files.py` into `state/breeze/expiry_weeks/` (identical to the download wherever both exist); the download
  skips those expiries.
- **IBKR paper account** (owner's IBKR India account, 14 Nov 2026): live NSE prices and paper orders for the trading
  program, through the IB gateway on `market-hub-trader` (API on the machine only). NSE shares and F&O data are
  "Fee Waived"; no BSE (no SENSEX options). The program refuses any account not starting "DU". The paper username and
  account number stay out of this public repo. IBKR allows one session: no IBKR web / app login in market hours.
- **AI summaries**: Google Gemini free tier (`hub/summaries.py`), not Anthropic, unless the owner says so.

## Making changes
- GitHub: the owner's `gh` keyring holds two logins and the *active* one can flip to ramghatage-ux. Never rely on it
  or switch it globally; name the account in every command:
  `export GH_TOKEN=$(gh auth token -u ramghatagedb1101-NSEFO)` (check `gh api user --jq .login`), and push with
  `git -c credential.helper= -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$(gh auth token -u ramghatagedb1101-NSEFO)"; }; f' push origin main`
  (pull with rebase the same way first; the batch commits too).
- Market days: no push to `relay/*` between 09:15 and 15:30 IST (it deploys at once).
- Update `CHANGELOG.md` (newest first, IST dates, the why) and `STATUS.md` for every change.
- `METHOD.md` (the full method) lives in the PRIVATE repo `market-hub-private`, not here (owner, 15 Oct 2026: this
  repo is public). No local clone needed (dropped 27 Oct 2026 -- the sparse-clone setup was its own source of
  friction and one false guard failure): `hub/method_check.py` reads and writes it straight over the GitHub API,
  with `PRIVATE_REPO_TOKEN` (the same fine-grained token `hub/site_data.py` already uses).
  `python -m hub.method_check --pull` saves the live copy to `extras/METHOD.md` for editing;
  `python -m hub.method_check --push extras/METHOD.md "what changed"` commits it back. Never copy it into this repo
  or quote it in public files (CHANGELOG/STATUS here are public too). Update it with any change to a
  prediction-engine file (its source map lists them): push METHOD.md to the private repo FIRST, then the code here;
  run `python -m hub.method_check --base origin/main` before pushing (owner-approved, 15 Oct 2026). A change that
  does not alter the method says `[method: no change]` in its commit message.
- One working folder: `C:\nse_fo_analyser\forecast_hub` (15 Oct 2026). Extras that must stay out of this public
  repo (showcase PDF, dashboard/phone preview with private sample data, test tools) are in
  `C:\nse_fo_analyser\extras\`.
- Relay: run `node relay/check.js` and check its exit code (never pipe it through tail/grep). Deploy only
  with `bash relay/tools/deploy_relay.sh <repo> <folder holding relay-live> <last deployed commit> "<label>"`.
  `relay-live` is a clasp folder: `.clasp.json` = `{"scriptId":"13rGqOxSSC3aQzZGYjpDWT4NnNXUO_kjCQKeA4oo2pZ8MD22KEilKWR7s","rootDir":"."}`
  plus `clasp pull`. Both deployments are updated in place (`clasp deploy -i <id>`, never a new deployment):
  `AKfycbwQZxgg…` (admin bookmark) and `AKfycbye12r6…` (live relay, phone, Kite redirect); full IDs in the
  script. Deploys need `clasp` signed in as ramghatagedb1101@gmail.com.
- Relay deploys from GitHub (since 13 Oct 2026): pushing a change to `relay/*.gs` or `relay/AdminPage.html`
  starts `relay-deploy.yml` (environment `Relay`, `main` only, no approval step: owner's choice), which runs
  the strict script above, checks the live relay and writes the deployed commit to `.github/relay-deployed`. A cloud
  session can therefore change, push and deploy the relay: run `node relay/check.js` before every relay push. The laptop route still works:
  `deploy_relay.sh` writes the deployed commit to `.github/relay-deployed`; commit and push that file with the
  CHANGELOG entry, or the next GitHub deploy stops (safely) at step 1. Switching between a cloud session and
  the laptop: everything is in GitHub; `git pull` on the laptop and read STATUS.md / CHANGELOG.md.
- Phone app (`docs/index.html`): bump the cache name in `docs/sw.js` on every change, or phones keep the
  old page. Test at phone width (375 px) before publishing.
- Trading program (`trader/`): run `python -m trader.selftest` before every push. To update the machine: `git pull` in
  `/opt/trader/app`, then `sudo systemctl restart trader.service`, outside market hours (09:15-15:30 IST) unless the
  owner says otherwise; check its journal line "start" afterwards. Never place a test order on the live account; the
  paper-only guard in `trader/ibkr.py` stays.
- Previews of the dashboard and phone with sample data: `C:\nse_fo_analyser\extras\dash_preview` (launch config
  `dash-preview`, port 8765); rebuild its `index.html` / `phone/index.html` from the repo files after changes.
- Verify on real data where possible (private repo files via `gh api`), not only on samples.

## Audits: check sense, not just that it loads (owner, 13 Nov 2026)
Two bugs passed every earlier audit because the checks asked "does it render?" (peers were a same-size list from any
business; the chart's range buttons did nothing before the Kite login). Every audit of a screen now also:
- tests its fallback states: before the morning Kite login, with a source down or a key refused, on a holiday;
- sense-checks the content against reality: peers in the same business, a chart's span matching its button, dates and
  "as of" labels current, figures plausible for that company, every control actually changing what it should;
- covers every screen of the dashboard and the phone, and says what was covered.
- tests a fix in BOTH states, before and after the morning Kite login (13 Nov 2026: a chart-range fix tested only before
  the login broke 1D / 5D / 1M after it), and checks the same figure agrees wherever it is shown (Titan's 1-year return
  differed between the page header and its Peers table; the Screens list kept figures the company page had corrected).

## How the owner wants things
- Analyse like a seasoned analyst, not a yes-man: say when something is wrong, including your own work.
- Plain language, short; reasons with every change. The owner reads on the phone.
- Dates always with the year ("Thu 17 Sep 2026"). Time labels on the phone: "Live · HH:MM IST",
  "Last quote · HH:MM IST · Day d Mon yyyy", "As of HH:MM IST · …", "Close · Day d Mon yyyy".
- Alerts go by email (Gmail on the phone). The owner does not use Telegram.
- Landing pages stay short; detail goes behind taps (sections that open, "See all").
- Scarce or paid resources are budgeted from day one.
