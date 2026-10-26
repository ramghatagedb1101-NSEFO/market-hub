"""All tunables for the hub. Change behaviour here, not in the engine."""
import os
from datetime import timedelta, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parent              # the hub/ package
REPO = PKG.parent                                  # repo root: forecast_hub/ (publish this only)
STATE_FILE = REPO / "state" / "state.json"        # kept in the private repo (hub/site_data.py)
SITE_DIR = REPO / "docs"                          # static phone app, served by GitHub Pages
FEED_FILE = SITE_DIR / "data" / "feed.json"       # what the phone app reads
TRADES_FILE = REPO / "state" / "trades.json"      # optional: F&O picks written by the engines

IST = timezone(timedelta(hours=5, minutes=30))    # fixed offset: no tzdata needed on Windows

PRICES_FILE = REPO / "state" / "prices.json"      # daily closes, grown incrementally

# Where each index's closes come from (hub/sources/prices.py decides the order):
#   nse_csv: index name in NSE's free bhavcopy (checked first, NIFTY and BANKNIFTY)
#   kite:    (exchange, tradingsymbol) on Kite Connect (paid, used when nse_csv is absent -- SENSEX)
INDEX_SOURCES = {
    "NIFTY":     {"kite": ("NSE", "NIFTY 50"), "nse_csv": "Nifty 50"},
    "BANKNIFTY": {"kite": ("NSE", "NIFTY BANK"), "nse_csv": "Nifty Bank"},
    "SENSEX":    {"kite": ("BSE", "SENSEX")},
}
INDICES = tuple(INDEX_SOURCES)
HISTORY_DAYS = 5 * 365                            # backfill depth on first run

# Expiry dates come from Kite's contract lists (hub/expiries.py: rule changes and holiday moves followed by
# themselves). This rule is only the fallback when the lists cannot be read: (kind, weekday 0=Mon .. 4=Fri), as of
# Oct 2026 -- NIFTY weekly Tuesday, SENSEX weekly Thursday, BANK NIFTY monthly only (last Tuesday). Before
# 14 Oct 2026 this was one weekday each, with BANK NIFTY Wednesday and SENSEX Monday (wrong) and no holiday moves.
EXPIRY_RULE = {"NIFTY": ("weekly", 1), "BANKNIFTY": ("monthly", 1), "SENSEX": ("weekly", 3)}

HORIZONS = ("day", "expiry", "month", "year")

HISTORY_YEARS = "5y"
MIN_HISTORY = 60          # sessions needed before any forecast is made
VOL_WINDOW = 20           # sessions for daily volatility

# Model parameters (learned weights/band adjust online; these are the starting values).
DRIFT_SCALE = 0.5         # max expected move, in units of horizon sigma, when all tools agree
BAND_K0 = 1.2816          # z for an 80% band (starting point)
TARGET_COVERAGE = 0.80    # the band should contain the actual close this share of the time
ETA_WEIGHT = 0.15         # multiplicative-weights learning rate for tools
ETA_BAND = 0.02           # step size for band calibration (fixed-step; still the live default)
ETA_BAND_MIN = 0.004      # floor for the adaptive step size (hub.band_step_test), a fifth of ETA_BAND --
                          # the band is never frozen solid, same principle as WEIGHT_FLOOR below
WEIGHT_FLOOR = 0.02       # no tool is ever switched fully off

# Overnight US cue for the phone's close estimate (26 Oct 2026, hub.us_cue_test): next-day index log return per unit
# of S&P 500 log return over the US sessions since the last Indian close. Least squares over the last 2 years; the
# 5-year direction hit rate is 56-59% on all three (the ten tools above: 41-48%, no next-day skill).
US_BETA = {"NIFTY": 0.24, "BANKNIFTY": 0.22, "SENSEX": 0.22}
CLOSE_MIN_US_MOVE = 0.5   # % S&P move below which there is no lean (past direction about 50/50 there)
CLOSE_RANGE_A, CLOSE_RANGE_C = 0.656, 0.245   # live 80% half-width = daily vol x (A x sqrt(session left) + C)
# GIFT Nifty cue (26 Oct 2026, hub/diag_gift.py, 724 sessions Nov 2023 - Oct 2026): x = log(GIFT now / GIFT at 15:30 IST
# on the last Indian session). Before 09:15 it replaces the S&P cue when the relay has a GIFT quote. Beta, direction hit %
# at 09:00, and the range factor sqrt(1 - corr^2) (what the cue leaves unexplained) per index.
GIFT_BETA = {"NIFTY": 0.90, "BANKNIFTY": 0.97, "SENSEX": 0.90}
GIFT_HIT = {"NIFTY": 69, "BANKNIFTY": 64, "SENSEX": 68}
GIFT_RANGE = {"NIFTY": 0.80, "BANKNIFTY": 0.85, "SENSEX": 0.81}
# The phone (docs/index.html closeEstimate) uses these numbers through the feed, and the range constants above
# directly: change both together.
