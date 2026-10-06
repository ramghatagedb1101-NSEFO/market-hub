"""All tunables for the hub. Change behaviour here, not in the engine."""
import os
from datetime import timedelta, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parent              # the hub/ package
REPO = PKG.parent                                  # repo root: forecast_hub/ (publish this only)
STATE_FILE = REPO / "state" / "state.json"        # committed daily by the scheduled job
SITE_DIR = REPO / "docs"                          # static phone app, served by GitHub Pages
FEED_FILE = SITE_DIR / "data" / "feed.json"       # what the phone app reads
TRADES_FILE = REPO / "state" / "trades.json"      # optional: F&O picks written by the engines

IST = timezone(timedelta(hours=5, minutes=30))    # fixed offset: no tzdata needed on Windows

PRICES_FILE = REPO / "state" / "prices.json"      # daily closes, grown incrementally

# Where each index's closes come from.
#   kite:    (exchange, tradingsymbol) on Kite Connect (paid, primary)
#   nse_csv: index name in NSE's free bhavcopy (fallback, NIFTY only)
INDEX_SOURCES = {
    "NIFTY":  {"kite": ("NSE", "NIFTY 50"), "nse_csv": "Nifty 50"},
    "SENSEX": {"kite": ("BSE", "SENSEX")},
}
INDICES = tuple(INDEX_SOURCES)
HISTORY_DAYS = 5 * 365                            # backfill depth on first run

# Weekly expiry weekday per index (0=Mon .. 4=Fri). Mirrors expiry_config.py.
# Verify against current NSE / BSE circulars before relying on expiry targets.
EXPIRY_WEEKDAY = {"NIFTY": 1, "SENSEX": 0}

HORIZONS = ("day", "expiry", "month", "year")

HISTORY_YEARS = "5y"
MIN_HISTORY = 60          # sessions needed before any forecast is made
VOL_WINDOW = 20           # sessions for daily volatility

# Model parameters (learned weights/band adjust online; these are the starting values).
DRIFT_SCALE = 0.5         # max expected move, in units of horizon sigma, when all tools agree
BAND_K0 = 1.2816          # z for an 80% band (starting point)
TARGET_COVERAGE = 0.80    # the band should contain the actual close this share of the time
ETA_WEIGHT = 0.15         # multiplicative-weights learning rate for tools
ETA_BAND = 0.02           # step size for band calibration
WEIGHT_FLOOR = 0.02       # no tool is ever switched fully off
