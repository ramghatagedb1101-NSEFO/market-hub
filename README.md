# Market Hub

Hosted, free-to-run index forecasts (NIFTY, SENSEX) for four horizons, with a public track record
that scores every forecast against what actually happened and a naive baseline.

Runs with no PC: a scheduled GitHub Action does the daily work, GitHub Pages serves the phone app.

## What runs where

| Piece | Where | Cost |
|---|---|---|
| Daily job (prices → settle → forecast → feed) | GitHub Actions, weekdays 15:45 IST | free (public repo) |
| State (`state/`: forecasts, prices, bulk deals) | private repo `market-hub-private` (`state/`), synced by `hub/site_data.py` | free |
| Phone app (`docs/`) | GitHub Pages; signs in with the admin dashboard's email code | free (public repo) |
| Phone app data | private repo `market-hub-private` (`site/`), read through the relay after sign-in (`hub/site_data.py`) | free |
| Index prices | Yahoo Finance public chart endpoint | free, no key |

## One-time setup (about 10 minutes)

1. Create a **public** GitHub repository (Pages on private repos needs a paid plan).
2. Push this folder to it:
   ```bash
   git init -b main
   git add .
   git commit -m "Initial hub"
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
3. Repo **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*,
   Branch = `main`, Folder = `/docs`.
4. Repo **Actions** tab: open `daily-forecast` and press **Run workflow** once to check it.
5. Open `https://<you>.github.io/<repo>/` on your phone and choose **Add to Home Screen**.

After that it runs by itself every weekday after the close.

## Running locally

```bash
pip install -r requirements.txt
python -m hub.site_data pull  # first: state/ and docs/data/ from the private repo (needs PRIVATE_REPO_TOKEN)
python -m hub                 # daily job: refresh, settle, forecast, write docs/data/feed.json
python -m hub.backtest        # honest scorecard vs naive baseline, 5 years
python -m hub.backtest --seed # also save learned weights into state.json
```

## Reading the numbers

- **Direction hit %**: how often the predicted up/down matched the actual move. 50% is a coin toss.
- **Band coverage %**: share of actual closes inside the forecast range. Target is 80%.
- **MAE model vs MAE naive**: average error of the forecast vs "tomorrow = today".
  The app only calls a model useful when the model's error is lower than the naive error.

The current backtest says the model does **not** beat the naive baseline on any horizon yet.
The bands are well calibrated, the point forecasts are not. That is the honest state.

## Adding an analytical tool

Drop a file in `hub/tools/` with a function decorated by `@register("name")` that returns a
score in [-1, 1] (or `None` to abstain). It is loaded automatically. The engine learns how much
to trust each tool from its settled record, so a weak tool loses weight rather than polluting the forecast.

## F&O picks (live)

`hub/fno.py` (index iron condors/spreads) and `hub/stocks.py` (the Nifty 50 credit-spread screen,
`rg/strategy.py`) run daily, using Kite Connect (~₹500/month, already approved) for the option
chain. The credit gate reads the mid price a limit/combo order is meant to achieve; a `fill_risk`
flag and stop-loss/profit-target prices show on each qualifying card.

## Multi-bagger and stock-library screens (live)

`hub/library.py` scores every NSE EQ/BE equity (2,572 names) on 124 parameters from BharatStock
financials, batched weekly (Saturdays, chaining automatically across however many ~70-minute runs
the universe needs). The same loop computes a four-gate multi-bagger score from the same
already-fetched rows (`hub/multibagger.py`'s `score()`), so the two screens share one BharatStock
fetch per company instead of two independent weekly pulls. Output goes to the private repo
(`market-hub-private`), read by the phone app after sign-in.

## Limits to know

- Yahoo's chart endpoint is unofficial. If it changes or blocks GitHub's runners, the job fails
  loudly and writes nothing, so the last good feed stays up.
- The scheduled run can be delayed by a few minutes at GitHub's discretion.
- Exchange holidays are not modelled in the horizon calendar. Settlement absorbs them
  (the first close on or after the target), but the horizon length can be a day off around holidays.
- Expiry weekdays in `hub/config.py` mirror the parent project's `expiry_config.py`. Verify
  them against current NSE/BSE circulars.
