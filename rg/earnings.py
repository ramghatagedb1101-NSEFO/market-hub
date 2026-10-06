"""
earnings.py — next-earnings resolution for the selling screen.

WHY THIS MODULE EXISTS
----------------------
`BLOCK_EARNINGS_IN_CYCLE` is the blueprint's hardest rule: never hold short
premium over a results date. It can only block a date it can SEE, and the two
things it used to see were both inadequate:

  * `supplementary_data/<SYM>.json:next_earnings_date` — written by the buying
    tool's fetcher, which is scoped to the 25-name .env WATCHLIST. Measured
    17-Aug-2026: 31 files exist for a ~100-name universe and ZERO carry a
    non-null next_earnings_date. The gate was failing open on the entire scan.
  * NSE's forward calendar — `api/event-calendar` publishes a board meeting only
    once the company has filed the intimation, which is roughly 7 days ahead.
    This tool sells 30-66 DTE. So a *formally confirmed* results date does not
    exist yet for almost any candidate at the moment of selection. Requiring one
    is not strictness, it is a permanent veto on the whole universe.

The fix is to stop treating "no filing yet" as "unknowable". Indian quarterly
results are strongly periodic per company: SEBI LODR Reg 33 caps the filing at
45 days after quarter end (60 for Q4), and within that each company keeps its
own habitual slot. Measured on the live index, that slot is stable to a few days
year-on-year but varies WIDELY between companies — RELIANCE files Q1 around
17-19 Jul while CUMMINSIND files the same quarter around 5 Aug, 19 days later.
A generic "45 days after quarter end" rule would therefore be far too coarse to
be useful; the company's OWN prior-year date for the SAME quarter is the signal.

So we resolve the next earnings date in three tiers, most authoritative first:

  confirmed  — a board meeting is on file for a future date. Exact, no buffer.
  estimated  — no filing yet, but the company's prior-year same-quarter date is
               known; project it forward a year and widen by a buffer.
  unverified — no usable periodic history (recent listing, demerger, or a gap
               in the filing record). The gate then behaves exactly as before
               and `REQUIRE_EARNINGS_DATA` decides whether that is a reject.

Source: `api/corporate-board-meetings?index=equities&symbol=X`, which returns
~20 rows (roughly 5 years of quarterly meetings) carrying `bm_date` and a
`bm_purpose` of "Financial Results" / "Financial Results/Dividend". The same
endpoint supplies BOTH tiers, so the confirmed and estimated paths cannot
disagree about their underlying facts. `api/corporates-financial-results` was
evaluated and rejected: it returns 0 rows for exactly the recent-listing names
that need the fallback most (TATACAP, TMCV, ENRIN), and its filingDate ordering
is unreliable.

DESIGN RULE, mirroring risk_flags.py: store observations, derive verdicts. The
cache holds only the fetched meeting dates. Which quarter is next, how wide the
buffer is, and whether the window collides with the contract cycle are all
computed at read time from `today`, so retuning the buffer is a config edit and
never a data migration.
"""

import json
import time
from datetime import date, datetime, timedelta

from . import config

# Reuse the buying tool's NSE holiday set so a "trading day" means the same
# thing here as in the IV backfill. Falling back to weekdays-only is acceptable
# and is the conservative direction to be wrong in only marginally: an unlisted
# holiday makes the ±N-trading-day window span slightly fewer calendar days.
try:
    from .nse_holidays import NSE_HOLIDAYS as _HOLIDAYS
except Exception:                                    # pragma: no cover
    _HOLIDAYS = set()

_SCHEMA = 1
_NSE_BASE = "https://www.nseindia.com"
_BM_URL = _NSE_BASE + "/api/corporate-board-meetings?index=equities&symbol={sym}"

# NSE serves a challenge page instead of JSON without a full browser UA.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_BASE + "/companies-listing/corporate-filings-board-meetings",
}


# ── pure date helpers (no I/O, `today` always explicit) ────────────────
def parse_nse_date(value):
    """
    NSE mixes "05-Aug-2026", "2026-08-05" and "05-08-2026", sometimes with a
    trailing time. Returns a date or None — never raises, because one malformed
    row must not lose the rest of a symbol's history.
    """
    s = str(value or "").strip().split(" ")[0]
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def is_trading_day(d) -> bool:
    return d.weekday() < 5 and str(d) not in _HOLIDAYS


def shift_trading_days(d, n: int):
    """Move `n` NSE sessions from `d` (negative moves back). n=0 returns `d`."""
    if n == 0:
        return d
    step = 1 if n > 0 else -1
    remaining, cur = abs(n), d
    while remaining:
        cur += timedelta(days=step)
        if is_trading_day(cur):
            remaining -= 1
    return cur


def results_dates(rows) -> list:
    """
    Distinct board-meeting dates whose purpose is a results approval, newest
    first.

    Deduped by date because NSE emits two rows per meeting — the company's
    "Board Meeting Intimation" and the "Financial Results" purpose line — and
    counting both would double every quarter, breaking the history-depth gate.
    """
    out = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = f"{row.get('bm_purpose') or ''} {row.get('bm_desc') or ''}".lower()
        if "financial result" not in text and "financial results" not in text:
            continue
        d = parse_nse_date(row.get("bm_date"))
        if d:
            out.add(d)
    return sorted(out, reverse=True)


def _project(anchor, today):
    """
    Anchor + one year, nudged onto a trading day.

    Uses +364 days rather than a calendar year so the projection keeps the
    anchor's DAY OF WEEK. Results meetings cluster on weekdays by habit (a board
    that meets on a Tuesday tends to keep meeting on a Tuesday), and a calendar
    +1 year drifts by one or two weekdays, which would then be silently snapped
    somewhere else. 364 is 52 whole weeks.
    """
    d = anchor + timedelta(days=364)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def next_earnings_window(history, today=None) -> dict:
    """
    Resolve the next earnings date for one symbol from its results-date history.

    `history` is the list of dates from results_dates(). Returns a dict that
    always carries `status`, `lo` and `hi` (lo/hi None when unverified), so a
    caller never has to branch on shape:

        status="confirmed"  a meeting is already on file for a future date;
                            lo == hi == that date, no buffer applied.
        status="estimated"  projected from the prior-year same-quarter date;
                            lo/hi are the date ± EARNINGS_ESTIMATE_BUFFER_TD.
        status="unverified" no usable pattern; the caller must treat the cycle
                            as UNCHECKED, never as clear.

    The horizon guard is what makes this safe on thin history, and it is the
    reason a naive "nearest projection wins" is not enough. Quarterly reporting
    means the next results date is always within ~130 days. A name with only two
    or three quarters on file can have its nearest projection land 8+ months out
    — not because earnings are far away, but because the anchor for the NEXT
    quarter was never observed. Returning that as a clear window would be worse
    than having no estimate at all: it would assert safety over the exact gap in
    the data. So an out-of-horizon projection degrades to `unverified`, which is
    how "recent listings and demergers" fall out of this automatically rather
    than needing to be named in a list that would go stale.
    """
    today = today or date.today()
    hist = sorted({d for d in (history or [])}, reverse=True)
    base = {"status": "unverified", "date": None, "lo": None, "hi": None,
            "anchor": None, "quarters": len(hist), "horizon_days": None,
            "buffer_td": config.EARNINGS_ESTIMATE_BUFFER_TD,
            "source": "nse_board_meetings"}

    # Tier 1 — already filed for a future date. Exact; a buffer here would
    # invent uncertainty the exchange has already removed.
    future = [d for d in hist if d >= today]
    if future:
        d = min(future)
        return {**base, "status": "confirmed", "date": d, "lo": d, "hi": d,
                "horizon_days": (d - today).days}

    if not config.EARNINGS_ESTIMATE:
        return base
    if len(hist) < config.EARNINGS_HISTORY_MIN_QUARTERS:
        return {**base, "reason": f"only {len(hist)} quarter(s) of filing history"}

    # Tier 2 — project every observed date forward a year and take the first
    # that has not already passed. That IS "prior-year same quarter" without
    # needing to label quarters: the projection landing next is by construction
    # the one whose anchor sits a year before it.
    cands = sorted(d for d in (_project(h, today) for h in hist) if d >= today)
    if not cands:
        return {**base, "reason": "all projections lie in the past"}

    est = cands[0]
    horizon = (est - today).days
    if horizon > config.EARNINGS_ESTIMATE_MAX_HORIZON_DAYS:
        return {**base, "horizon_days": horizon,
                "reason": (f"nearest projection {est} is {horizon}d out, beyond the "
                           f"{config.EARNINGS_ESTIMATE_MAX_HORIZON_DAYS}d quarterly "
                           f"horizon — the next quarter's anchor is missing")}

    buf = config.EARNINGS_ESTIMATE_BUFFER_TD
    return {**base, "status": "estimated", "date": est,
            "lo": shift_trading_days(est, -buf), "hi": shift_trading_days(est, buf),
            "anchor": est - timedelta(days=364), "horizon_days": horizon}


def collides(window, start, end) -> bool:
    """True when an earnings window overlaps the [start, end] contract cycle."""
    if not window or window.get("lo") is None or window.get("hi") is None:
        return False
    return window["lo"] <= end and window["hi"] >= start


def describe(window) -> str:
    """One-line human form for diagnostics and report cards."""
    if not window:
        return "no earnings data"
    st = window.get("status")
    if st == "confirmed":
        return f"{window['date']} (confirmed, filed with NSE)"
    if st == "estimated":
        return (f"{window['lo']}..{window['hi']} (estimated from "
                f"{window['anchor']}, ±{window['buffer_td']} sessions)")
    return f"unverified — {window.get('reason', 'no usable filing history')}"


# ── cache I/O ─────────────────────────────────────────────────────────
def load_cache() -> dict:
    path = config.EARNINGS_HISTORY_CACHE
    if not path.exists():
        return {"schema": _SCHEMA, "symbols": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema": _SCHEMA, "symbols": {}}
    if data.get("schema") != _SCHEMA:
        return {"schema": _SCHEMA, "symbols": {}}
    return {"schema": _SCHEMA, "symbols": data.get("symbols") or {}}


def save_cache(cache) -> None:
    path = config.EARNINGS_HISTORY_CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": _SCHEMA, "symbols": cache.get("symbols", {})},
                               indent=2, default=str), encoding="utf-8")


def _stale(entry, today) -> bool:
    fetched = parse_nse_date((entry or {}).get("fetched"))
    if not fetched:
        return True
    return (today - fetched).days >= config.EARNINGS_HISTORY_TTL_DAYS


def fetch_symbol(symbol, session):
    """Board-meeting rows for one symbol. Returns [] on any failure."""
    import requests  # local import: the pure path must not need the network stack
    try:
        resp = session.get(_BM_URL.format(sym=symbol), timeout=15)
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}"
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("data", [])
        return (data or []), None
    except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
        return [], type(e).__name__


def refresh(symbols, today=None, force=False) -> dict:
    """
    Top up the results-date cache for `symbols`, honouring the TTL.

    Refreshes weekly rather than per run because the underlying facts move at
    most once a quarter, and a per-run fetch would add ~100 NSE calls to a run
    that already doubled its Kite calls under nifty100.

    A symbol whose fetch fails KEEPS its cached history — an NSE outage must not
    silently downgrade a name from `estimated` to `unverified`, which would look
    identical to a company that genuinely has no filing record.
    """
    import requests
    today = today or date.today()
    cache = load_cache()
    syms = cache.setdefault("symbols", {})
    due = [s for s in symbols if force or _stale(syms.get(s), today)]
    if not due:
        print(f"  [EARNINGS] cache fresh for all {len(symbols)} symbol(s)")
        return cache

    session = requests.Session()
    session.headers.update(_HEADERS)
    try:
        session.get(_NSE_BASE, timeout=10)
        session.get(_NSE_BASE + "/companies-listing/corporate-filings-board-meetings",
                    timeout=10)
    except requests.RequestException as e:
        print(f"  [EARNINGS] NSE session failed ({type(e).__name__}) — "
              f"keeping {len(syms)} cached entr(ies)")
        return cache

    ok = failed = 0
    for i, sym in enumerate(due, 1):
        rows, err = fetch_symbol(sym, session)
        dates = results_dates(rows)
        if dates:
            syms[sym] = {"fetched": str(today), "results_dates": [str(d) for d in dates]}
            ok += 1
        else:
            failed += 1
            # Record the attempt so a name with genuinely no filings is not
            # re-fetched every run, but do not overwrite a good history.
            prior = syms.get(sym) or {}
            syms[sym] = {"fetched": str(today),
                         "results_dates": prior.get("results_dates", []),
                         "last_error": err or "no results rows"}
        if i % 20 == 0:
            print(f"  [EARNINGS] {i}/{len(due)} fetched...")
        time.sleep(0.35)          # be polite to NSE; ~35s for a 100-name refresh

    save_cache(cache)
    print(f"  [EARNINGS] refreshed {len(due)} symbol(s): {ok} with history, {failed} without")
    return cache


def history_for(symbol, cache=None) -> list:
    cache = cache if cache is not None else load_cache()
    entry = (cache.get("symbols") or {}).get(symbol) or {}
    return [d for d in (parse_nse_date(x) for x in entry.get("results_dates", [])) if d]


def window_for(symbol, today=None, cache=None) -> dict:
    """Cache-backed resolution for one symbol. Never touches the network."""
    return next_earnings_window(history_for(symbol, cache), today=today)


if __name__ == "__main__":
    import sys
    from . import market_data
    syms = sys.argv[1:] or market_data.get_universe()
    refresh(syms, force="--force" in sys.argv)
    cache = load_cache()
    for s in syms:
        if s.startswith("--"):
            continue
        print(f"  {s:14} {describe(window_for(s, cache=cache))}")
