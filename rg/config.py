"""
config.py — all tunables for the RG Option Selling Tool in one place.

Philosophy: BALANCED, LOW-RISK premium selling.
  - Only sell when implied vol is elevated (rich premium).
  - Always defined-risk (a long wing caps the loss) — never naked.
  - Short strike far OTM (low delta => high probability of profit).
  - Position sized so capital-at-risk per strategy never exceeds the cap.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────
PKG_DIR       = Path(__file__).resolve().parent
# Only forecast_hub/.env, never a .env higher up the tree (the buying tool's).
load_dotenv(PKG_DIR.parent / ".env")

DATA_DIR      = PKG_DIR / "data"
POSITIONS_FILE = DATA_DIR / "positions.json"      # persistent tracker
REPORT_DIR    = PKG_DIR / "reports"

# ── Chain-snapshot cache (see market_data.get_chain_snapshot) ─────────
# WHY THIS EXISTS: nothing used to persist the option chain. get_chain_snapshot
# quoted Kite live every run and threw the result away, and the only chain-shaped
# store on disk (supplementary_data/snapshots.db) keeps OI alone — no bid, no ask.
# So a finished run could not be re-examined: asked on 17-Aug-2026 to re-run the
# screen under a new config toggle without touching Kite, the honest answer was
# that the quotes no longer existed anywhere. Everything downstream of the chain
# (every gate, every credit, every RoR) was therefore un-auditable after the fact
# and un-testable against real data.
#
# MODE — RG_CHAIN_CACHE:
#   write (default) — fetch live, write the enriched snapshot through to disk.
#                     Identical selection behaviour to before; only a side effect
#                     is added.
#   read            — REPLAY. Serve snapshots from the cache and make Kite
#                     unreachable (market_data.get_kite raises), so a replay
#                     cannot quietly become half-live. A symbol with no cached
#                     snapshot returns None, which the screen already reports as
#                     "no chain data" rather than skipping silently.
#   off             — neither read nor write; the pre-cache behaviour exactly.
# An unrecognised value falls back to `write` — the fail-safe direction, since it
# is the one mode that cannot serve a stale quote as if it were live.
CHAIN_CACHE_MODE = os.getenv("RG_CHAIN_CACHE", "write").strip().lower()
if CHAIN_CACHE_MODE not in ("write", "read", "off"):
    print(f"  [CONFIG] RG_CHAIN_CACHE={CHAIN_CACHE_MODE!r} unrecognised — using 'write'")
    CHAIN_CACHE_MODE = "write"

# Day-scoped directory, one JSON per symbol: chain_cache/2026-08-17/RELIANCE.json.
# Scoped by DAY because a chain is only meaningful for the session it was taken
# in — dating the directory makes a stale read impossible to reach by accident and
# makes a day's worth deletable in one move.
CHAIN_CACHE_DIR = DATA_DIR / "chain_cache"

# Retention. A ~400-strike enriched chain is roughly 150-200 KB of JSON, so a
# 100-name universe writes ~15-20 MB per run and several runs a day overwrite
# within the same dated folder. 3 days keeps yesterday and the day before for
# comparison without letting the folder grow without bound; run.py prunes after
# every write-mode run and prints what it removed, because a cache that quietly
# fills a disk is worse than no cache.
CHAIN_CACHE_KEEP_DAYS = 3

# Which day `read` mode replays. Default (empty) is TODAY — the coherent case,
# where the cached DTE, expiry and earnings window still agree with the clock.
# Set RG_CHAIN_REPLAY_DATE=YYYY-MM-DD to replay an earlier session, but note it
# replays the CHAIN, not the CALENDAR: the earnings-in-cycle gate, settlement and
# the tracker still use today's date, so a past-date replay is a study of the
# selection layer, not a faithful re-run of that day.
CHAIN_CACHE_REPLAY_DATE = os.getenv("RG_CHAIN_REPLAY_DATE", "").strip() or None

# ── Universe ──────────────────────────────────────────────────────────
# The selling tool scans an NSE index constituent list, fetched live from NSE's
# static archive CSV (always current, no stale hardcoded list) with a per-mode
# JSON cache as fallback. Set RG_UNIVERSE=watchlist to use the buying tool's
# .env WATCHLIST instead.
WATCHLIST = [s.strip() for s in os.getenv("WATCHLIST", "").split(",") if s.strip()]
UNIVERSE_MODE = os.getenv("RG_UNIVERSE", "nifty50").lower()  # nifty50 | nifty100 | watchlist

NIFTY50_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
]
NIFTY100_CSV_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty100list.csv",
]

# mode -> (csv urls, cache file, minimum plausible constituent count). The count
# is a sanity gate: a truncated or error-page response must not silently become
# the universe.
UNIVERSE_SPECS = {
    "nifty50":  (NIFTY50_CSV_URLS,  DATA_DIR / "nifty50.json",  40),
    "nifty100": (NIFTY100_CSV_URLS, DATA_DIR / "nifty100.json", 80),
}
if UNIVERSE_MODE not in UNIVERSE_SPECS and UNIVERSE_MODE != "watchlist":
    print(f"  [CONFIG] RG_UNIVERSE={UNIVERSE_MODE!r} unrecognised — using 'nifty50'")
    UNIVERSE_MODE = "nifty50"

# Cache of the ACTIVE mode. Other modules (macro._known_symbols) read this to
# learn the scannable universe, so it must track UNIVERSE_MODE, not be pinned.
UNIVERSE_CACHE = UNIVERSE_SPECS.get(UNIVERSE_MODE, UNIVERSE_SPECS["nifty50"])[1]

# Human label for the report header. Derived from the mode for the same reason
# UNIVERSE_CACHE is: the header previously hardcoded "NIFTY 50", so a nifty100
# run produced a report that named a universe it had not scanned — and the one
# field a reader would check to tell the two products apart was the field that
# could not distinguish them.
UNIVERSE_LABELS = {
    "nifty50":   "NIFTY 50",
    "nifty100":  "NIFTY 100 (50 + Next 50)",
    "watchlist": "Watchlist (.env)",
}
UNIVERSE_LABEL = UNIVERSE_LABELS.get(UNIVERSE_MODE, UNIVERSE_MODE.upper())

# Index membership (NIFTY50 vs NEXT50) for the nifty100 universe, derived by
# differencing the NIFTY 50 list against the NIFTY 100 list — same CSV pattern.
INDEX_MEMBERSHIP_CACHE = DATA_DIR / "index_membership.json"

# Sector map derived from the Industry column NSE already publishes in that same
# CSV — written on every successful fetch, so it stays in step with semi-annual
# index rebalances instead of being hand-maintained. SECTOR_MAP below remains a
# MANUAL OVERRIDE that wins over the cache.
SECTOR_MAP_CACHE = DATA_DIR / "sector_map.json"

# ── Capital / sizing ──────────────────────────────────────────────────
CAPITAL_PER_STRATEGY = 100_000     # ₹1 lakh cap on capital-at-risk per strategy
MAX_RECOMMENDATIONS  = 5           # top-N spreads emitted per run

# ── Position sizing basis: live SPAN margin vs the max-loss proxy ─────
# max_loss (width - credit) is the DEFINED-RISK WORST CASE, not what the
# exchange actually blocks to hold the position — SPAN + exposure margin on a
# credit spread is typically a fraction of max_loss, because SPAN prices the
# position's real one-day risk, not its terminal payoff. Sizing off max_loss
# alone therefore systematically UNDER-sizes every trade relative to what
# CAPITAL_PER_STRATEGY could actually carry.
#
# True (default): ask Kite for the real SPAN/exposure margin on 1 lot
#   (market_data.get_span_margin) and size lots against THAT figure. Falls back
#   to the max_loss proxy per-trade whenever a live reading is unavailable —
#   the feature is off, the run is a chain-cache replay (get_kite refuses
#   there), or the margin API call itself fails — so a Kite outage degrades
#   sizing to the old behaviour rather than raising.
# False: skip the margin API entirely and size every trade on max_loss, as
#   before this feature existed.
USE_SPAN_MARGIN = os.getenv("RG_USE_SPAN_MARGIN", "True").lower() == "true"

# ── Entry filters — encode the RG selling-engine blueprint ────────────
# (env-overridable so thresholds can be tuned without code edits)
MIN_IV_RANK        = float(os.getenv("RG_MIN_IV_RANK", "30"))   # sell only when premium is rich

# ── Short-strike delta band — WHY IT IS 20-30 AND NOT THE BLUEPRINT'S 10-20 ──
# For a vertical spread, credit/width is bounded by the risk-neutral probability
# of finishing beyond the short strike, which is approximately the short strike's
# own delta. So a 0.15-delta short leg can only ever collect ~15% of width at
# FAIR VALUE, and less than that after paying the bid-ask.
#
# That made the old settings mutually unsatisfiable: SHORT_DELTA_MAX 0.20 with
# MIN_CREDIT_TO_WIDTH 0.15 demanded a reward the structure cannot pay. Measured
# on the live NIFTY 50 (17-Aug-2026, 43 DTE, 10 symbols x 4 widths, mid prices):
# put verticals collected 10-15% of width and call verticals 6-11%. The ONLY
# readings above 15% came from single-strike spreads on a suspect quote — i.e.
# the gate could only ever pass on noise, and the screen returned zero
# recommendations every run as a result.
#
# Widening the band to 20-30 delta is the deliberate trade: POP falls from
# ~80-90% to ~70-80%, credit/width rises to roughly 20-30%, so MIN_CREDIT_TO_WIDTH
# 0.15 becomes reachable on real quotes. More premium per trade, more strikes
# breached. The alternative — keeping 10-20 delta and dropping
# MIN_CREDIT_TO_WIDTH to ~0.10 — buys safety at a reward the blueprint rejects.
# Both are coherent; this one was chosen. Do not tighten one of these three
# numbers without re-checking it against the other two.
SHORT_DELTA_MIN    = 0.20          # was 0.10
SHORT_DELTA_TARGET = 0.25          # centre of the 20–30 band
SHORT_DELTA_MAX    = 0.30          # ~70% POP floor at the short strike
MIN_POP_PCT        = 70.0          # was 80.0 — follows the delta band, not an independent easing
# Iron condors carry two short strikes, so POP = 100 - put_delta - call_delta.
# At the 0.25 target that is ~50%, which the previous 65 floor rejected outright:
# every condor was silently discarded and the tool fell back to a single spread.
# 45 keeps a real floor (a condor must still be better than a coin flip) while
# leaving the structure reachable. It is NOT a loosening — it is the same
# arithmetic relationship to the delta band that 65 had to the old one.
IC_MIN_POP_PCT     = 45.0          # was 65.0
MIN_DTE            = 30            # HARD FLOOR — never sell shorter than this
MAX_DTE            = 66            # hard ceiling (see below)
PREFERRED_MAX_DTE  = 45            # blueprint band is 30–45; reported, not enforced
# Stock F&O is MONTHLY ONLY — one expiry per month, 28–35 days apart. A 30–45
# window therefore has dead stretches where no expiry qualifies at all: on
# 31-Aug the Sep expiry is 29 DTE (one day under the floor) and the Oct expiry is
# 57 DTE, so nothing is eligible. MAX_DTE must span more than one inter-expiry
# gap (worst observed 35 days) or the tool goes quiet for ~2 weeks a month, which
# is what prompted this. 30 + 35 = 65, so 66 with a day of slack.
# Tenors beyond PREFERRED_MAX_DTE are flagged on the chain, not silently taken.
MIN_CREDIT_TO_WIDTH = 0.15         # credit must be >=15% of width (reward floor).
                                   # Only reachable because the delta band is 20-30
                                   # — see the note above SHORT_DELTA_MIN before
                                   # touching either.

# ── Which credit the REPORTED RoR headline is measured on ──
# Two credits exist for every spread and both are already computed (see
# strategy._leg_mid vs _short_price/_long_price):
#   net_credit       — the combo mid, the realistic fill when worked as one order
#   net_credit_worst — sell the short at the bid, pay the ask on the long
#
# False (legacy): every displayed Return on Risk reads the MID. Defensible as the
#   expected fill, but it means the headline reward number is the best of the two
#   prices the trade can get, and on a thin far-OTM chain the gap is not a
#   rounding difference. Measured on the three condors this tool actually booked
#   on 17-Aug-2026: RoR 75.4 -> 58.7 (BAJFINANCE), 79.9 -> 65.3 (TCS), 71.2 -> 40.8
#   (HDFCLIFE). HDFCLIFE loses 30 points of reward — the card said 71% and the
#   price you can be certain of paid 41%.
#
# True (current, set 17-Aug-2026): report net_credit_worst as the headline, so the
#   number in front of the reader is the one no adverse fill can take away. The
#   RoR pair (worst AND mid) is carried on every reco either way, so nothing is
#   hidden — only which of the two is the headline changes.
#
# 2026-10-08: this flag used to ALSO gate the reward check itself -- a spread
# whose worst-case credit was non-positive (the CIPLA 1350/1340 that priced to
# -0.50 on 17-Aug-2026, the incident that motivated True) was rejected outright,
# even when its mid credit was genuinely positive and tradeable as a limit order.
# Over the screen's first three days live that silently discarded real, workable
# trades (ADANIENT, BEL, ETERNAL and others) and read on the card as "no
# opportunity exists" when the honest statement was "this needs a limit order,
# not a market order." The gate (strategy._gate_credit) now always reads mid;
# the CIPLA risk this flag was built for is carried forward as an explicit
# fill_risk() stamp on the card instead of a silent rejection, so the user
# decides with the real number in front of them. This flag now controls ONLY
# which number is the RoR headline, never whether a trade qualifies.
USE_WORST_CASE_CREDIT = True
# Long wing = N strikes away from the short strike, counted by POSITION in the
# chain's sorted strike list, not by arithmetic on a step size. NSE strike
# spacing is not uniform (tighter near ATM, wider in the wings), so
# short_strike +/- step lands on a strike that does not exist — which is what
# used to surface as "no constructible spread". See strategy._adjacent_strike.
SPREAD_WIDTH_STEPS = 1

ENABLE_IRON_CONDOR = True          # combine both sides into an iron condor when both qualify

# ── Low-vol regime: prefer ONE side over a condor ─────────────────────
# An iron condor is a bet on a RANGE, and it pays for that by carrying two short
# strikes: POP = 100 - put_delta - call_delta, so at the 0.25 target it is ~50%
# where a single-sided spread at the same delta is ~75%. That is a fair trade when
# premium is rich — you are paid twice for the extra breach risk.
#
# In a LOW-VOL regime it stops being fair. Both wings are priced off the same
# compressed vol, so the second wing adds little credit while still adding a whole
# strike that can be breached, and a low VIX is also where a vol expansion is most
# likely to run one side through. So below this level the higher-POP single-sided
# spread is preferred and the condor is stood down.
#
# 12.0 sits below anything this tool has actually seen — India VIX was 15.67 on
# 17-Aug-2026 and 15.63/15.67 across the June readings in
# supplementary_data/vix_history.json — so on today's data the rule is INERT by
# construction. It is a floor for a regime we have not been in, not a re-tune of
# current behaviour; raise it only against measured evidence of what a condor
# actually collects at that level.
#
# Set to None to disable the check entirely. A MISSING or unparseable VIX also
# disables it for that run: "we could not read the VIX" is not evidence of low
# vol, and the condor branch is the long-standing default. See
# strategy._prefer_single_side.
LOW_VIX_THRESHOLD = 12.0
if LOW_VIX_THRESHOLD is not None:
    try:
        LOW_VIX_THRESHOLD = float(LOW_VIX_THRESHOLD)
    except (TypeError, ValueError):
        print(f"  [CONFIG] LOW_VIX_THRESHOLD={LOW_VIX_THRESHOLD!r} is not a number "
              f"— disabling the low-vol condor override")
        LOW_VIX_THRESHOLD = None
SETTLE_WITH_HISTORICAL = True      # settle tracker P&L on the expiry-day close (else spot proxy)
REQUIRE_WALL_PROTECTION = True     # blueprint: short strike must sit beyond the OI wall
MAX_BID_ASK_PCT    = 2.5           # blueprint: reject legs with bid-ask > 2.5% of premium
MIN_DELIVERY_5D    = 40.0          # blueprint: underlying 5d avg delivery >= 40%
BLOCK_EARNINGS_IN_CYCLE = True
# Owner decision (6 Oct 2026): an ESTIMATED results date that overlaps the expiry does not block the
# trade. It is shown as "results date not confirmed". A CONFIRMED date still blocks. Set True to block
# on estimates again.
BLOCK_ON_ESTIMATED_EARNINGS = False     # blueprint: no short premium over an earnings date

# ── Estimated earnings window (see earnings.py) ────────────────────────
# BLOCK_EARNINGS_IN_CYCLE can only block a date it can SEE, and a FORMALLY
# CONFIRMED date does not exist for a 30-66 DTE candidate: NSE publishes a
# results board meeting only once the company files the intimation, ~7 days
# ahead. Demanding one is therefore a permanent veto, not a strict gate.
#
# So the date is resolved in three tiers — confirmed / estimated / unverified —
# where `estimated` projects the company's OWN prior-year same-quarter filing
# date forward a year and widens it by a buffer. Per-company matters: measured
# 17-Aug-2026, RELIANCE files Q1 around 17-19 Jul and CUMMINSIND around 5 Aug,
# so a generic "45 days after quarter end" bound would be 19 days too coarse to
# separate them.
EARNINGS_ESTIMATE = True
EARNINGS_HISTORY_CACHE = DATA_DIR / "earnings_history.json"
EARNINGS_HISTORY_TTL_DAYS = 7      # facts move once a quarter; don't refetch per run
EARNINGS_ESTIMATE_BUFFER_TD = 5    # ± NSE sessions around the projected date
# A same-quarter anchor requires a full year on file. Thinner history does not
# get an estimate — it gets `unverified`, which is the honest answer.
EARNINGS_HISTORY_MIN_QUARTERS = 4
# Quarterly reporting means the next results date is ALWAYS within ~4 months. A
# projection landing beyond this means the anchor for the next quarter was never
# observed, not that earnings are far off — so it degrades to `unverified`
# rather than asserting a clear cycle over the exact gap in the data. This is
# what makes recent listings and demergers fall out automatically instead of
# needing a hand-maintained exclusion list.
EARNINGS_ESTIMATE_MAX_HORIZON_DAYS = 130

# ── What to do when the earnings date is UNVERIFIABLE ──────────────────
# Reached only after all three tiers above fail, which after the estimator
# landed is a much smaller set than before: previously EVERY name missed the
# gate (31 supplementary files for a ~100-name universe, zero carrying a
# non-null next_earnings_date), so REQUIRE_EARNINGS_DATA=True would have
# rejected the entire scan and False meant the blueprint's hardest rule applied
# to nothing.
#
# False: recommend anyway, but tag the reco and the diagnostics line so the
#   unverified earnings risk is stated rather than assumed away.
# True (current, set 17-Aug-2026): treat "cannot verify" as "do not sell" — the
#   fail-safe direction. Only defensible once the estimator landed: measured that
#   day on the live NIFTY 100 this rejects 3 names (M&M, PFC, POWERGRID — thin NSE
#   board-meeting feeds), where before the estimator it would have rejected all
#   100. The card banner and the diagnostics line both survive the flip, so a
#   name dropped here still names its cause.
REQUIRE_EARNINGS_DATA = True
MAX_PER_SECTOR     = 1             # blueprint: sector concentration cap

# ── Per-sector override: MAX_PER_SECTOR is a floor, not a fit for every bucket ──
# Sector labels are NSE's, not ours — granularity is whatever the exchange
# publishes (see market_data._write_sector_map). FINANCIAL SERVICES is one
# bucket of 23 names in the NIFTY 100 (banks, NBFCs, insurers, AMCs and housing
# financiers all lumped together), so a flat MAX_PER_SECTOR=1 treats HDFCBANK
# and a small NBFC as fully correlated when they are not. No finer column
# exists in NSE's own constituent CSV (Company Name / Industry / Symbol /
# Series / ISIN Code only — checked 17-Aug-2026 against ind_nifty100list.csv),
# so widening this bucket via a hand-built sub-sector taxonomy would be exactly
# the brittle, un-NSE-sourced parallel classification this project has
# deliberately avoided elsewhere (see SECTOR_MAP's own docstring below). A
# named override is the honest fix: still a hard cap, still auditable against
# NSE's own label, just sized to the one bucket that is genuinely oversized.
# See REFERENCE.md §7 ("Sector labels are NSE's, not ours").
#
# Keys are matched against market_data.get_sector()'s output (NSE's own
# vocabulary, upper-cased); any sector not listed here still gets
# MAX_PER_SECTOR. See strategy._sector_cap_for.
SECTOR_CAP_OVERRIDE = {"FINANCIAL SERVICES": 2}

# Is MAX_PER_SECTOR a PORTFOLIO limit or a per-run one?
#
# True (current): the OPEN book's per-sector tally seeds the cap, so a sector
# already holding a live position cannot take another. It was per-run, and two
# runs 13 minutes apart on 17-Aug-2026 therefore left the book holding BAJFINANCE
# (₹98,325) and HDFCLIFE (₹99,572) — ₹1,97,897 of capital-at-risk in Financial
# Services under a 1-per-sector rule. Neither run was wrong about its own
# candidates; nothing was looking at the two together. See
# strategy._apply_caps and tracker.open_sector_counts.
#
# Note the consequence, which is intended: while a name is open, its whole sector
# is closed to new recommendations — including the name itself. In short premium
# that is the point of the cap. Five names in one sector is one bet with five
# tickets that all realise together on a sector gap.
CAP_COUNTS_OPEN_POSITIONS = True

# ── Next 50 tiering (only meaningful when RG_UNIVERSE=nifty100) ───────
# The expanded universe is NOT an equal pool. A NIFTY Next 50 name is a smaller,
# thinner underlying: wider option spreads, patchier delivery, more gap risk. Two
# independent controls, because they answer different questions.
#
# (a) IS IT GOOD ENOUGH — stricter entry gates for a NEXT50-tagged candidate.
#     Without this a thin name can still win a slot on a high score, and score
#     says nothing about whether you can actually get filled at a fair price.
NEXT50_STRICTER_GATES  = True
NEXT50_MAX_BID_ASK_PCT = 1.5       # vs MAX_BID_ASK_PCT 2.5 for a NIFTY 50 name
NEXT50_MIN_DELIVERY_5D = 50.0      # vs MIN_DELIVERY_5D 40
NEXT50_MIN_IV_RANK     = 40.0      # vs MIN_IV_RANK 30 — demand richer premium
                                   # to accept the extra underlying risk
#
# (b) SHOULD IT BE PREFERRED — tiered fill. Every qualifying NIFTY 50 name is
#     ranked ahead of every Next 50 name regardless of score, so Next 50 only
#     backfills slots the core index left empty. That is the role it is actually
#     good for. A pure score multiplier would NOT guarantee this: a strong Next
#     50 name would still displace a weaker NIFTY 50 one.
NEXT50_TIERED_FILL = True

# ── Concentration-limit diagnostic (TIME-BOXED — read this) ───────────
# Shows which already-qualifying spreads the sector cap and top-N cut held back,
# so MAX_PER_SECTOR can be tuned against evidence instead of intuition. It is a
# measurement, NOT a second recommendation list: trading the blocked rows
# wholesale rebuilds exactly the concentration the cap exists to prevent, and in
# short premium five names in one sector is one bet with five tickets that all
# realise together on a sector gap.
#
# It EXPIRES on purpose. Left running indefinitely it becomes a standing
# workaround for a rule you no longer believe in, and the report ends up
# carrying two competing answers to "what should I trade". Past the date the
# section is replaced by a prompt to make the MAX_PER_SECTOR decision. Extend it
# deliberately if you need more runs — don't extend it to avoid deciding.
CAP_DIAGNOSTIC_UNTIL = os.getenv("RG_CAP_DIAGNOSTIC_UNTIL", "2026-09-30")
CAP_DIAGNOSTIC_TOP_N = 10

# ── Macro risk-flag lifetime (policy for risk_flags.py) ───────────────
# These are the DECAY POLICY, not stored state: risk_flags.json holds only
# observations (first_seen / last_seen / catalyst_date) and every verdict is
# derived at read time, so changing a number here re-dates existing flags with
# no data migration. Deliberately NOT reusing macro._RECENCY_DAYS (4) — that
# window is tuned for price-action themes, and a governance or succession story
# has a far longer half-life than a one-day move.
RISK_FLAG_TTL_DAYS       = 10      # open-ended risk: active this long after last_seen
RISK_FLAG_MAX_AGE_DAYS   = 30      # hard ceiling from first_seen, binds over everything
RISK_FLAG_CATALYST_GRACE = 1       # stay active this many days past a named catalyst date
RISK_FLAG_STALE_DAYS     = 5       # severity decays one tier per this many days unconfirmed
RISK_FLAG_MATCH_SIM      = 0.15    # risk-text Jaccard to count as the SAME flag on
                                   # re-confirmation. Measured, not guessed: reworded
                                   # versions of one story score 0.24-0.33, unrelated
                                   # risks 0.00-0.05, so 0.15 sits in the gap. Set it
                                   # too high and every reword creates a new flag with a
                                   # reset first_seen, which quietly defeats duration
                                   # tracking. Unrelated to macro's 0.8 theme dedup —
                                   # that detects near-IDENTICAL headlines, a stricter job.

# ── Macro risk-flag scoring (severity -> score multiplier) ────────────
# A FIXED TABLE, deliberately interposed between the model and the score. The
# LLM's severity is a LABEL; this file decides what that label costs. severity
# must never become a multiplier directly — that hands an unaudited model output
# direct control over position ranking, and re-tuning the penalty would mean
# re-prompting instead of editing one line.
#
# Applied to risk_flags.effective_severity() — the DECAYED value — not
# severity_raw, so an unconfirmed flag's penalty fades along with its severity.
#
# These DEMOTE, they do not veto. The multiplier scales strategy.py's score, so
# a flagged name ranks below equivalent clean ones but can still be recommended
# when the candidate list is thin. A hard veto would need its own gate in
# _symbol_reject_reason — a deliberate, separate decision.
#
# Keys are upper-case to match the severities risk_flags actually stores
# ("HIGH"/"MEDIUM"/"LOW"); lookup is case-insensitive.
RISK_FLAG_SCORE_MULT = {
    "HIGH":   0.30,
    "MEDIUM": 0.60,
    "LOW":    0.85,
}
RISK_FLAG_UNRATED_MULT = 1.0       # severity None (unrated, or decayed away) -> no-op.
                                   # Unrated means "we don't know", never "no risk".

# How several flags on one symbol combine: "worst" (lowest multiplier wins) or
# "compound" (multiply them). Default "worst" because same-day flags are NOT
# independent — one briefing names up to 3 related risks, so compounding
# double-counts correlated evidence (two HIGH flags would give 0.09, a de-facto
# veto nobody chose). Switch to "compound" only with evidence they're separable.
RISK_FLAG_COMBINE = "worst"

# Shadow vs live. Default "shadow": flags are resolved, attached to the reco,
# persisted to the tracker and printed EXACTLY as in live — only the score
# multiplier is pinned to 1.0, so nothing is demoted. The two modes share one
# code path and differ by a single value, so flipping to live does not switch on
# untested code. Unknown values fall back to shadow (fail-safe direction).
# Burn in through at least one real named-risk story before going live.
RISK_FLAG_MODE = os.getenv("RG_RISK_FLAG_MODE", "shadow").strip().lower()
if RISK_FLAG_MODE not in ("shadow", "live"):
    print(f"  [CONFIG] RG_RISK_FLAG_MODE={RISK_FLAG_MODE!r} unrecognised — using 'shadow'")
    RISK_FLAG_MODE = "shadow"

# ── Marking OPEN positions (see mtm.py) ───────────────────────────────
# True (current): reprice every leg by Black-Scholes at the current spot, the IV
#   backed out of its own live quote, and the REMAINING time to expiry. Unrealised
#   P&L is then credit received minus the debit it would cost to close today.
# False: value open positions on the EXPIRY payoff — the legacy behaviour, kept
#   only so the change can be compared against the old reports. It is not a
#   valuation of a live position: at entry the spot sits inside the profit zone by
#   construction, so the payoff reports the entire credit as day-0 profit. That is
#   how the tracker came to show +₹2,23,025 / 75.5% RoC on 17-Aug-2026 across
#   three condors booked that morning with 43 days left to run.
MARK_OPEN_WITH_BS = True

# A defined-risk vertical is worth [0, width] at any point in its life, so P&L is
# bounded by [-max_loss, +credit] throughout — clamping to that band removes quote
# noise without masking a real move. Every clamped mark is flagged in the report
# rather than silently smoothed, so a systematically clamped position is visible.
MARK_CLAMP_TO_STRUCTURE = True

# ── Trade management (blueprint: 21 DTE roll + profit/stop) ───────────
MANAGE_DTE            = 21          # force close/roll at 21 DTE (locks ~70–80% of decay)
STOP_LOSS_CREDIT_MULT = 2.0        # suggested exit if loss hits 2x credit received
PROFIT_TARGET_PCT     = 50.0       # suggested exit at 50% of max profit

# ── Risk-free rate (for greeks, matches black_scholes) ────────────────
RISK_FREE_RATE = 0.065

# ── Standard disclaimer (mirrors the naked-buying tool's wording) ─────
DISCLAIMER = (
    "IMPORTANT: This is an internal research document generated for informational purposes only. "
    "This report does not constitute investment advice, a solicitation, or a recommendation to buy or "
    "sell any financial instrument. Options trading — including the selling of premium — involves "
    "substantial risk of loss and may not be suitable for all investors; losses on a defined-risk "
    "spread are capped at the stated maximum but can still be realised in full. Past analysis and "
    "notional performance do not guarantee future results. The analysis is based on available market "
    "data and quantitative models which may contain errors or omissions. Always consult a "
    "SEBI-registered investment adviser before making trading decisions. RG Invest accepts no liability "
    "for any losses incurred from reliance on this report."
)

# ── Sector map: MANUAL OVERRIDE only ──────────────────────────────────
# Sectors now come from the Industry column of NSE's own constituent CSV, cached
# to data/sector_map.json on every successful universe fetch. This dict is
# consulted FIRST and wins where a symbol appears in both — use it to correct or
# re-group an NSE label, not to enumerate the universe. Entries for symbols
# outside the active universe are simply unused.
# Intentionally EMPTY. Sectors come from NSE's own Industry column via
# data/sector_map.json; resolve with market_data.get_sector(), never by reading
# this dict directly.
#
# The previous hand-maintained list used a parallel vocabulary (BANKING, IT,
# METAL) against NSE's (FINANCIAL SERVICES, INFORMATION TECHNOLOGY, METALS &
# MINING). Measured on the live NIFTY 100, 24 of its 25 in-index entries
# disagreed with the NSE label, which SPLIT single industries across several cap
# buckets — FINANCIAL SERVICES became three, so HDFCBANK + CHOLAFIN + PFC could
# all be recommended in one run under MAX_PER_SECTOR=1. It also carried entries
# (TATAMOTORS, OFSS) for symbols no longer in the index at all.
#
# Add an entry ONLY to correct a specific NSE label, and use NSE's own
# vocabulary when you do, or you will reintroduce the split.
SECTOR_MAP = {}
