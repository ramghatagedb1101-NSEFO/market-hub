# Kite daily login relay (one-time setup)

After this, each morning is: tap your Kite bookmark → log in with your password and 2FA → tap **Authorize**. The relay does the rest and starts the day's run.

## 1. Create the Apps Script project (Google account, free)
1. Go to https://script.google.com → **New project**.
2. Delete the sample code and paste the whole of `relay/Code.gs`.
3. Click **Deploy → New deployment → Web app**.
   - Execute as: **Me**
   - Who has access: **Anyone**
   - Click **Deploy**, approve the permissions, and copy the **Web app URL** (ends in `/exec`).

## 2. Add the script properties (Project Settings → Script properties)
Enter these yourself:
| Name | Value |
|---|---|
| `KITE_API_KEY` | the **Active** app's API key |
| `KITE_API_SECRET` | the **Active** app's API secret |
| `GH_PAT` | the GitHub fine-grained token for `market-hub` (updated in step 3) |
| `RELAY_KEY` | a long random string you make up (30+ characters) |
| `GH_REPO` | `ramghatagedb1101-NSEFO/market-hub` |

## 3. GitHub token for starting the run
Edit the `GH_PAT` token you already made: add **Actions: Read and write** (keep Secrets: Read and write too).

## 4. Point Kite at the relay
In the Kite developer console, set the Active app's **Redirect URL** to the Web app URL from step 1.

## 5. Add two GitHub secrets
Repo → Settings → Secrets and variables → Actions:
- `RELAY_URL`: the Web app URL from step 1.
- `RELAY_KEY`: the same string you put in script properties.

You can now delete the old `KITE_ACCESS_TOKEN` secret, since the daily run no longer uses it.

## Daily routine (phone)
1. Tap your Kite login bookmark (the link with the Active app's key).
2. Log in with your password and 2FA.
3. Tap **Authorize**.
4. You see "Logged in … daily run has started." Done.

## Troubleshooting
- "user is not enabled for the app": the app's Zerodha Client ID must be the account you log in with.
- "Token saved, but the daily run did not start": the `GH_PAT` lacks Actions write.
- The daily run says "No Kite token for today": log in with Kite first that day.

## Updating the deployed script (8 Oct 2026: email alerts, and phone app sign-in)
Apps Script isn't deployed from GitHub -- a code change here needs re-pasting by hand:
1. Open the Apps Script project (script.google.com → this project).
2. Replace the contents of `Code.gs` and `Admin.gs` with the current versions from this repo.
3. **Deploy → Manage deployments → the existing Web app deployment → Edit (pencil) → Version: New version → Deploy.**
   Do not create a brand-new deployment -- that would change the `/exec` URL, breaking `RELAY_URL`
   everywhere it's used (GitHub secrets, the Kite login bookmark).
4. No new script property or GitHub secret needed: `mode=alert` reuses the existing `RELAY_KEY`, and
   the email goes to the same Google account that owns the script (`Session.getEffectiveUser()`),
   same as the admin dashboard's sign-in code.
5. Phone app sign-in (`mode=app_code`, `app_verify`, `app_data`) also needs nothing new: it uses the same
   email code and session as the dashboard, and reads `site/` in `market-hub-private` with the existing
   `ADMIN_READ_TOKEN` (Contents: Read on that repo).
6. After deploying, run the **site-data** workflow once (Actions tab → site-data → Run workflow), so the
   private repo has the data before the next job runs.
7. The project has several active Web app deployments. The one to update is the one whose URL is in
   `docs/index.html` (`RELAY_URL`), the `RELAY_URL` GitHub secret and the Kite redirect:
   `AKfycbye12r6…`. Done 8 Oct 2026 as Version 19 (it had been on Version 8). The other deployments
   (admin dashboard experiments, 7 Oct) were left as they were.

## Deploying with clasp (preferred since 9 Oct 2026)
No Chrome, no account mix-ups. Runs on the owner's laptop, where `clasp` is signed in as
`ramghatagedb1101@gmail.com` (check: `node -e` with the token in `~/.clasprc.json` against the userinfo
endpoint, or `clasp login` again and choose that account, ticking every permission box).

```bash
node relay/check.js                                   # must pass: parses the admin page's browser script too
mkdir -p /tmp/relay && cd /tmp/relay
echo '{"scriptId":"13rGqOxSSC3aQzZGYjpDWT4NnNXUO_kjCQKeA4oo2pZ8MD22KEilKWR7s","rootDir":"."}' > .clasp.json
clasp deployments                                     # also renews clasp's sign-in token -- run it first, or a script
                                                      # reading ~/.clasprc.json directly gets "invalid credentials" (9 Oct)
clasp pull                                            # gets appsscript.json; compare every file with the last deployed commit
                                                      # and STOP if it differs -- don't let a failed check fall through
cp <repo>/relay/Code.gs Code.js && cp <repo>/relay/Admin.gs Admin.js && cp <repo>/relay/Report.gs Report.js && cp <repo>/relay/Research.gs Research.js && cp <repo>/relay/Phone.gs Phone.js && cp <repo>/relay/AdminPage.html AdminPage.html
clasp push -f
# confirm the saved project now matches the repo (projects.getContent) BEFORE versioning -- a push with the
# API setting off once reported success and changed nothing
clasp version "<what changed> (<commit>)"             # prints the new version number N
clasp deploy -i AKfycbwQZxgg5yCekhRX7O88GyLCMt_MHRkTSLyjA1HF7Zk6nNL14wjoDydD73IabaTyOiFV -V N -d "<desc>"   # admin bookmark
clasp deploy -i AKfycbye12r6sWmdKQhSA6cpFnKnSUFjBhKDUm9BF5mGXsFmqeWer8-F0uVOoZ6NVPXF4SZ1ww -V N -d "<desc>"   # live relay
clasp deployments                                     # both should show @N
```
`appsscript.json` has `executeAs: USER_DEPLOYING`, so the relay runs as whoever deploys -- deploy only as
ramghatagedb1101@gmail.com. Never `clasp deploy` without `-i` (that creates a new deployment and URL).

**Strict deploy (10 Oct 2026):** `bash relay/tools/deploy_relay.sh <repo> <folder holding relay-live> <last deployed commit> "<label>"` runs every step above and stops at the first failure (pre-check, `check.js`, push, content check, version check, both deploys). Never pipe a check through `tail`/`grep`: on 10 Oct that hid a rejected push and an unchanged version was deployed.

## Files in the Apps Script project (since 9 Oct 2026)
- `Code.gs` -- Kite login relay, quotes, routing (doGet/doPost).
- `Admin.gs` -- sign-in (email code, 7-day sessions), admin data readers, phone app API.
- `Report.gs` -- `adminStock`: live parts of the stock report (BharatStock quarterly and annual results, up to 10 years; Google News).
- `Research.gs` -- `adminChart` (Kite historical candles, BharatStock daily prices as fallback), `adminDocs` (NSE document links and AI summaries from the private repo), `adminSummarise` (starts the ai-summaries workflow through `GH_PAT`).
- `Phone.gs` -- phone app additions: the stock sheet (`app_stock`), the watchlist shared with the dashboard (`app_watch`, `app_watch_toggle`, `adminWatch`, `adminWatchToggle`; script property `WATCHLIST`), and `?mode=watchlist&key=RELAY_KEY` for the daily digest.
- `Alerts.gs` -- daily digest email (`mode=digest`, from the library run) and watchlist-move emails (`mode=watch_check`, from the live-quotes job); switches `ALERT_DIGEST` / `ALERT_MOVES`.
- `KiteWatch.gs` -- Kite login alarm: records and emails a refused (replaced) login once, shown on the phone and dashboard until the next relay login.
- `AdminPage.html` -- the admin dashboard page (served by `adminPage()`).

Script property for the stock report: **`BHARATSTOCK_API_KEY`** (the same key as the GitHub secret), entered by the owner in Project Settings -> Script properties. Without it the report's two charts show a notice; everything else works.

