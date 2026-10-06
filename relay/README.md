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
