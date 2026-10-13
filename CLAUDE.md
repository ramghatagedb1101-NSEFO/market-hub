# Market Hub: guide for Claude sessions

A private research terminal for one Indian investor: every NSE company scored on 130+ measures, a
Shortlist with a weekly record against NIFTY, a research dashboard, a phone app, email alerts, plus NIFTY
forecasts and F&O screens. It runs every day without a PC. Read `STATUS.md` (where things stand) and the
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

Key workflows: `library.yml` (stock library, daily 06:15 IST, chains itself), `daily.yml` (forecasts),
`live.yml` (live quotes every 5 min in market hours), `summaries.yml` (AI summaries), `diag.yml`
(run a `hub/diag_*` module on GitHub's servers).

Secret names (values are the owner's): BHARATSTOCK_API_KEY, KITE_API_KEY, GEMINI_API_KEY,
PRIVATE_REPO_TOKEN, RELAY_URL, RELAY_KEY (GitHub); relay script properties hold the Kite token,
ADMIN_READ_TOKEN, GH_PAT, BHARATSTOCK_API_KEY.

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
- **AI summaries**: Google Gemini free tier (`hub/summaries.py`), not Anthropic, unless the owner says so.

## Making changes
- Push with the owner's GitHub CLI login:
  `git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push origin main`
  (pull with rebase first; the batch commits too).
- Update `CHANGELOG.md` (newest first, IST dates, the why) and `STATUS.md` for every change.
- Relay: run `node relay/check.js` and check its exit code (never pipe it through tail/grep). Deploy only
  with `bash relay/tools/deploy_relay.sh <repo> <folder holding relay-live> <last deployed commit> "<label>"`.
  `relay-live` is a clasp folder: `.clasp.json` = `{"scriptId":"13rGqOxSSC3aQzZGYjpDWT4NnNXUO_kjCQKeA4oo2pZ8MD22KEilKWR7s","rootDir":"."}`
  plus `clasp pull`. Both deployments are updated in place (`clasp deploy -i <id>`, never a new deployment):
  `AKfycbwQZxgg…` (admin bookmark) and `AKfycbye12r6…` (live relay, phone, Kite redirect); full IDs in the
  script. Deploys need `clasp` signed in as ramghatagedb1101@gmail.com.
- Relay deploys from GitHub (since 13 Oct 2026): pushing a change to `relay/*.gs` or `relay/AdminPage.html`
  starts `relay-deploy.yml`, which waits for the owner's approval (environment `relay`), then runs the strict
  script above, checks the live relay and writes the deployed commit to `.github/relay-deployed`. A cloud
  session can therefore change, push and (after approval) deploy the relay. The laptop route still works;
  after a laptop deploy, put its commit in `.github/relay-deployed` or the next GitHub deploy stops at step 1.
- Phone app (`docs/index.html`): bump the cache name in `docs/sw.js` on every change, or phones keep the
  old page. Test at phone width (375 px) before publishing.
- Verify on real data where possible (private repo files via `gh api`), not only on samples.

## How the owner wants things
- Analyse like a seasoned analyst, not a yes-man: say when something is wrong, including your own work.
- Plain language, short; reasons with every change. The owner reads on the phone.
- Dates always with the year ("Thu 17 Sep 2026"). Time labels on the phone: "Live · HH:MM IST",
  "Last quote · HH:MM IST · Day d Mon yyyy", "As of HH:MM IST · …", "Close · Day d Mon yyyy".
- Alerts go by email (Gmail on the phone). The owner does not use Telegram.
- Landing pages stay short; detail goes behind taps (sections that open, "See all").
- Scarce or paid resources are budgeted from day one.
