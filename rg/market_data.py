"""
market_data.py — one-time option-chain snapshot via Kite REST.

Deliberately does NOT use the WebSocket feed: this is a one-shot report tool,
so a REST snapshot (instruments + quote) is lighter and self-contained. Reuses
the parent project's black_scholes (greeks/IV) and calculators (IV rank / HV).

A snapshot dict looks like:
  {
    "symbol", "spot", "prev_close", "expiry" (date), "dte", "lot_size",
    "atm_iv", "iv_rank", "iv_quality", "as_of" (ISO string — live fetch time in
    `write`/`off` mode, the cache's own capture time in `read` mode; carried
    through to recommendations by strategy.py so report.py can state how fresh
    the chain behind the PDF is without re-fetching),
    "strikes": { strike(float): {
        call_ltp, put_ltp, call_bid, call_ask, put_bid, put_ask,
        call_oi, put_oi, call_delta, put_delta, call_iv, put_iv, ...} }
  }

Every snapshot is WRITTEN THROUGH to data/chain_cache/<day>/<SYMBOL>.json on the way
out (config.CHAIN_CACHE_MODE), so a finished run can be replayed offline with
RG_CHAIN_CACHE=read — which also makes get_kite() refuse, so a replay cannot
half-silently mix cached quotes with live ones. See the cache section near the
bottom of this file.
"""

import json
import math
from pathlib import Path
from datetime import date, datetime, timedelta

# forecast_hub/ root (this file lives in forecast_hub/rg/). Holds supplementary_data/
# and the optional kite_token.json fallback. Previously the parent of the old tool.
_PARENT = Path(__file__).resolve().parent.parent

from .black_scholes import enrich_strikes_with_greeks
from .calculators import calculate_iv_rank, calculate_hv_30d
from . import config
from . import earnings

_KITE = None
_NFO = None   # cached instrument dump
_EARN_CACHE = None   # results-date cache, read once per process


def _earnings_cache():
    """
    Read the results-date cache once, not once per symbol.

    get_chain_snapshot runs in a ~100-iteration loop, so re-reading and
    re-parsing the JSON per call would be 100 disk reads for a file that cannot
    change mid-run.
    """
    global _EARN_CACHE
    if _EARN_CACHE is None:
        _EARN_CACHE = earnings.load_cache()
    return _EARN_CACHE


def get_kite():
    """
    Build a KiteConnect client from kite_token.json (daily login token).

    REFUSES in replay mode. Every live-quote path in this module funnels through
    here, so one guard makes `RG_CHAIN_CACHE=read` mean what it says instead of
    meaning "cached chains, live everything else". The callers that CAN degrade
    already do — get_market_context falls back to the cached macro snapshot,
    get_expiry_close returns None so the tracker settles on a spot proxy, mtm
    reports a mark as failed rather than as flat — so a replay reads as a replay
    everywhere rather than mixing two sessions' prices in one report.
    """
    global _KITE
    if _KITE is not None:
        return _KITE
    if config.CHAIN_CACHE_MODE == "read":
        raise RuntimeError(
            "RG_CHAIN_CACHE=read (replay mode) — Kite is deliberately unreachable. "
            "Unset it for a live run, or use market_data.read_cached_chain().")
    import os
    from kiteconnect import KiteConnect
    # Hub: credentials come from the environment only (GitHub secrets / the daily
    # workflow's relay step). The old kite_token.json file fallback is dropped so no
    # token file is ever read from the hub folder.
    k = KiteConnect(api_key=os.getenv("KITE_API_KEY", ""))
    token = os.getenv("KITE_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("No Kite access token (KITE_ACCESS_TOKEN not set).")
    k.set_access_token(token)
    _KITE = k
    return k


def _nfo_instruments():
    global _NFO
    if _NFO is None:
        _NFO = get_kite().instruments("NFO")
    return _NFO


# ══════════════════════════════════════════════════════════════════════
# SPAN MARGIN  (live sizing basis — see config.USE_SPAN_MARGIN)
# ══════════════════════════════════════════════════════════════════════
# max_loss (width - credit) is a defined-risk WORST CASE, not what the exchange
# actually blocks to hold a credit spread — SPAN + exposure margin prices the
# position's real one-day risk and is typically a fraction of max_loss. Sizing
# on max_loss alone therefore systematically under-uses CAPITAL_PER_STRATEGY.
# get_span_margin asks Kite for the real figure on 1 lot so strategy.py can
# size against it; every caller still falls back to the max_loss proxy when
# this returns None (see strategy._build_spread / _build_iron_condor).
_SPAN_MARGIN_CACHE: dict = {}


def _span_margin_key(legs):
    """
    Stable per-run cache key for one leg set: each leg's tradingsymbol (which
    already encodes underlying, expiry and strike) paired with its transaction
    side, sorted so the SAME structure quoted leg-order-reversed still hits the
    cache. Equivalent to keying on (symbol, sorted strikes, expiry, sides)
    without re-deriving those components from the tradingsymbol string.
    """
    return tuple(sorted((leg.get("tradingsymbol", ""), leg.get("transaction_type", ""))
                        for leg in legs))


def get_span_margin(legs) -> float | None:
    """
    Total SPAN + exposure margin Kite would block for `legs` (quantities already
    sized for 1 base lot each). Returns the float total, or None when a live
    reading is not available or not wanted — NEVER raises.

    `legs` is a list of Kite basket-margin order dicts: tradingsymbol, exchange
    ("NFO" — the segment NSE F&O options actually trade on, matching the
    "NFO:{tradingsymbol}" keys get_chain_snapshot already quotes against),
    transaction_type ("BUY"/"SELL"), quantity, order_type ("MARKET"), product
    ("NRML").

    Skipped entirely, with no API call:
      - config.USE_SPAN_MARGIN is False (the feature is switched off), or
      - config.CHAIN_CACHE_MODE == "read" — a replay's tradingsymbols are only
        ever as live as its cached quotes, and get_kite() already refuses to
        connect in this mode; asking it for a margin would either raise past
        this function's error handling or, worse, block against a live account
        for a trade the run has no intention of placing.

    PER-RUN CACHED (see _span_margin_key) so two call sites pricing the same
    leg set — e.g. an iron condor built from the same wings a caller already
    priced as a vertical — cost one Kite call, not two. The cache is a plain
    module dict, not lru_cache: legs are unhashable dicts, so the key has to be
    derived explicitly regardless of cache mechanism.

    Any failure — no Kite session, a malformed leg, a network error, an
    unrecognised tradingsymbol, a response Kite could not price — is caught and
    printed, and this returns None so the caller degrades to the max_loss proxy
    rather than losing the run.
    """
    if not config.USE_SPAN_MARGIN or config.CHAIN_CACHE_MODE == "read":
        return None
    if not legs:
        return None
    key = _span_margin_key(legs)
    if key in _SPAN_MARGIN_CACHE:
        return _SPAN_MARGIN_CACHE[key]

    result = None
    try:
        kite = get_kite()
        params = [{
            "exchange":         leg.get("exchange", "NFO"),
            "tradingsymbol":    leg["tradingsymbol"],
            "transaction_type": leg["transaction_type"],
            "variety":          "regular",
            "product":          leg.get("product", "NRML"),
            "order_type":       leg.get("order_type", "MARKET"),
            "quantity":         leg["quantity"],
        } for leg in legs]
        margins = kite.basket_order_margins(params)
        total = float((margins.get("final") or {}).get("total") or 0)
        if total > 0:
            result = total
    except Exception as e:
        print(f"  [SPAN] margin lookup failed for {[l.get('tradingsymbol') for l in legs]} "
              f"— {e}")
        result = None

    _SPAN_MARGIN_CACHE[key] = result
    return result


def _pick_expiry(option_instruments) -> date:
    """
    Nearest expiry with MIN_DTE <= DTE <= MAX_DTE. Returns None if none
    qualifies — standing aside beats selling the wrong tenor.

    MIN_DTE IS A FLOOR, NOT A PREFERENCE. The previous version fell back to
    "nearest expiry at least MIN_DTE away", and then to "nearest of all" — which
    on 28-Sep would have picked a **1-DTE** expiry, because no expiry was 30+ days
    out (Sep 29 = 1 day, Oct 27 = 29 days). Selling short premium one day from
    expiry is maximal gamma risk, and every downstream gate would have waved it
    through while sizing it like a normal 35-day spread.

    Stock F&O is monthly-only — the live ladder is one expiry per month, ~28-35
    days apart — so MAX_DTE has to span more than one gap or there are dead
    stretches with no eligible expiry at all. MAX_DTE is set accordingly; the
    tighter 30-45 blueprint band is reported as PREFERRED_MAX_DTE rather than
    enforced, so an out-of-band tenor is visible instead of silent.
    """
    today = date.today()
    exps = sorted({i["expiry"] for i in option_instruments})
    exps = [e if isinstance(e, date) else datetime.strptime(e, "%Y-%m-%d").date()
            for e in exps]
    eligible = [e for e in exps
                if config.MIN_DTE <= (e - today).days <= config.MAX_DTE]
    return eligible[0] if eligible else None


def get_cached_supplementary(symbol: str) -> dict:
    """
    Read the buying tool's cached per-symbol JSON (no new network call) for the
    delivery filter and earnings blocker. Returns {} if absent.
    """
    p = _PARENT / "supplementary_data" / f"{symbol}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return {}
    return {}


def _write_sector_map(rows) -> int:
    """
    Persist the Industry column NSE already ships in the constituent CSV to
    data/sector_map.json. Previously discarded; capturing it removes the need for
    a hand-maintained sector list that silently rots at every index rebalance.

    Labels are upper-cased and whitespace-collapsed only — NSE's own vocabulary
    is kept verbatim otherwise, so the file is auditable against the source CSV.
    MERGES rather than replaces, so switching between nifty50 and nifty100 does
    not drop the sectors of symbols outside the current mode.
    """
    fresh = {}
    for row in rows:
        sym = (row.get("Symbol") or "").strip().upper()
        ind = " ".join((row.get("Industry") or "").split()).upper()
        if sym and ind:
            fresh[sym] = ind
    if not fresh:
        print("  [UNIVERSE] CSV carried no Industry column — sector map not updated")
        return 0
    merged = {}
    if config.SECTOR_MAP_CACHE.exists():
        try:
            merged = json.loads(config.SECTOR_MAP_CACHE.read_text())
        except Exception:
            merged = {}
    merged.update(fresh)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.SECTOR_MAP_CACHE.write_text(json.dumps(dict(sorted(merged.items())), indent=2))
    print(f"  [UNIVERSE] sector map: {len(fresh)} from this CSV, {len(merged)} cached total")
    return len(fresh)


def _fetch_csv_rows(urls):
    """Shared CSV fetch used by the universe and membership paths. [] on failure."""
    import csv
    import io
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200 and "Symbol" in r.text:
                return list(csv.DictReader(io.StringIO(r.text)))
        except Exception as e:
            print(f"  [UNIVERSE] fetch failed ({url.split('//')[1][:25]}...): {e}")
    return []


def _write_index_membership(universe_syms) -> dict:
    """
    Tag every symbol in the active universe NIFTY50 or NEXT50 by differencing the
    NIFTY 50 constituent list against it. Cached to data/index_membership.json.

    Fail-safe direction: if the NIFTY 50 list cannot be fetched and no cache
    exists, everything is tagged NEXT50 — the STRICTER treatment. Guessing
    "NIFTY50" would quietly relax the liquidity gates on names we could not
    verify, which is the wrong way to be wrong.
    """
    core = {(r.get("Symbol") or "").strip().upper()
            for r in _fetch_csv_rows(config.NIFTY50_CSV_URLS)}
    core.discard("")
    if len(core) < 40:
        if config.INDEX_MEMBERSHIP_CACHE.exists():
            try:
                cached = json.loads(config.INDEX_MEMBERSHIP_CACHE.read_text())
                print(f"  [UNIVERSE] membership: using cached tags ({len(cached)})")
                return cached
            except Exception:
                pass
        print("  [UNIVERSE] membership: NIFTY 50 list unavailable and no cache — "
              "tagging all NEXT50 (stricter gates, conservative)")
        return {s.upper(): "NEXT50" for s in universe_syms}

    tags = {s.upper(): ("NIFTY50" if s.upper() in core else "NEXT50")
            for s in universe_syms}
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.INDEX_MEMBERSHIP_CACHE.write_text(json.dumps(dict(sorted(tags.items())), indent=2))
    n50 = sum(1 for v in tags.values() if v == "NIFTY50")
    print(f"  [UNIVERSE] membership: {n50} NIFTY50, {len(tags) - n50} NEXT50")
    return tags


def get_index_membership(symbol: str) -> str:
    """
    "NIFTY50" or "NEXT50" for one symbol. In nifty50/watchlist mode everything is
    core by definition. Unknown symbols resolve to NEXT50 — the stricter tier.
    """
    if config.UNIVERSE_MODE != "nifty100":
        return "NIFTY50"
    sym = str(symbol or "").strip().upper()
    return _read_json_memo(config.INDEX_MEMBERSHIP_CACHE).get(sym, "NEXT50")


_JSON_MEMO: dict = {}


def _read_json_memo(path) -> dict:
    """
    Read a small JSON lookup once per process, keyed by path+mtime so a rewrite
    during the run is picked up. Without this, get_sector()/get_index_membership()
    hit the disk on EVERY symbol lookup — and the cap diagnostic calls them a few
    hundred times per run.
    """
    try:
        stamp = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}
    if stamp not in _JSON_MEMO:
        try:
            _JSON_MEMO[stamp] = json.loads(path.read_text())
        except Exception:
            _JSON_MEMO[stamp] = {}
    return _JSON_MEMO[stamp]


def _sector_cache() -> dict:
    return _read_json_memo(config.SECTOR_MAP_CACHE)


def get_sector(symbol: str) -> str:
    """
    THE sector resolver — manual override first, then the NSE Industry cache,
    then "OTHER". Every caller must come through here rather than reading
    config.SECTOR_MAP, which is now empty by design.
    """
    sym = str(symbol or "").strip().upper()
    if sym in config.SECTOR_MAP:
        return config.SECTOR_MAP[sym]
    return _sector_cache().get(sym, "OTHER")


def known_sectors() -> list:
    """
    Every sector label the resolver can produce — overrides plus the NSE cache.
    Used by macro.py to tell the model which sector names are valid; reading
    config.SECTOR_MAP.values() for this would now return nothing.
    """
    labels = {str(v).strip().upper() for v in config.SECTOR_MAP.values() if v}
    labels |= {str(v).strip().upper() for v in _sector_cache().values() if v}
    return sorted(labels)


def get_universe() -> list:
    """
    Return the symbol universe to scan, per config.UNIVERSE_MODE:
      nifty50 / nifty100 — live NSE constituent CSV, cached per mode
      watchlist          — the buying tool's .env WATCHLIST

    Same fetch-with-cache-fallback path for every index mode; only the URL list,
    cache file and sanity threshold vary. Each successful fetch also refreshes
    the Industry-derived sector map (see _write_sector_map).
    """
    if config.UNIVERSE_MODE == "watchlist":
        return config.WATCHLIST

    urls, cache, min_count = config.UNIVERSE_SPECS.get(
        config.UNIVERSE_MODE, config.UNIVERSE_SPECS["nifty50"])
    label = config.UNIVERSE_MODE.upper()

    import csv
    import io
    import requests
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200 and "Symbol" in r.text:
                rows = list(csv.DictReader(io.StringIO(r.text)))
                syms = sorted({row["Symbol"].strip() for row in rows if row.get("Symbol")})
                if len(syms) >= min_count:
                    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(syms, indent=2))
                    print(f"  [UNIVERSE] {label} fetched live: {len(syms)} symbols")
                    _write_sector_map(rows)
                    if config.UNIVERSE_MODE == "nifty100":
                        _write_index_membership(syms)
                    return syms
                print(f"  [UNIVERSE] {label} CSV had only {len(syms)} symbols "
                      f"(< {min_count}) — rejected as truncated")
        except Exception as e:
            print(f"  [UNIVERSE] fetch failed ({url.split('//')[1][:25]}...): {e}")

    if cache.exists():
        try:
            syms = json.loads(cache.read_text())
            print(f"  [UNIVERSE] using cached {label}: {len(syms)} symbols")
            return syms
        except Exception:
            pass
    print(f"  [UNIVERSE] {label} unavailable — falling back to .env WATCHLIST")
    return config.WATCHLIST


def get_market_context() -> dict:
    """
    Read the buying tool's cached macro snapshot (FII, crude, breadth, VIX,
    events, geopolitical stress test) and refresh the India VIX level live.
    No new fetchers — reuses supplementary_data/market_context.json.
    """
    ctx = {}
    p = _PARENT / "supplementary_data" / "market_context.json"
    if p.exists():
        try:
            ctx = json.loads(p.read_text())
        except Exception:
            ctx = {}
    vix = ctx.get("vix_prev_close")
    try:
        q = get_kite().quote(["NSE:INDIA VIX", "NSE:NIFTY 50", "NSE:NIFTY BANK"])
        v = q.get("NSE:INDIA VIX", {})
        if v.get("last_price"):
            vix = v["last_price"]
        for key, dst in (("NSE:NIFTY 50", "nifty50"), ("NSE:NIFTY BANK", "banknifty")):
            d = q.get(key, {})
            lp = d.get("last_price")
            pc = (d.get("ohlc", {}) or {}).get("close")
            if lp:
                ctx[dst] = round(lp, 1)
                if pc:
                    ctx[dst + "_chg"] = round((lp - pc) / pc * 100, 2)
    except Exception:
        pass
    ctx["india_vix"] = vix
    return ctx


def get_expiry_close(symbol: str, expiry_str: str):
    """
    Exact underlying close on the expiry date via Kite historical data — used to
    settle tracker P&L precisely. Returns a float, or None if unavailable
    (e.g. historical API not subscribed), so the caller can fall back to spot.
    """
    from datetime import datetime as _dt, timedelta as _td
    try:
        kite = get_kite()
        q = kite.ltp([f"NSE:{symbol}"]).get(f"NSE:{symbol}", {})
        tok = q.get("instrument_token")
        if not tok:
            return None
        d = _dt.strptime(str(expiry_str)[:10], "%Y-%m-%d").date()
        candles = kite.historical_data(tok, d - _td(days=5), d + _td(days=1), "day")
        for row in reversed(candles or []):
            rd = row["date"].date() if hasattr(row["date"], "date") else row["date"]
            if rd <= d:
                return float(row["close"])
    except Exception:
        return None
    return None


def get_equity_spot(symbol: str) -> dict:
    """Return {'last': float, 'prev_close': float} for the underlying."""
    q = get_kite().quote([f"NSE:{symbol}"]).get(f"NSE:{symbol}", {})
    ohlc = q.get("ohlc", {}) or {}
    return {"last": q.get("last_price", 0) or 0,
            "prev_close": ohlc.get("close", 0) or 0}


def get_leg_snapshot(symbol: str, expiry, wanted) -> dict | None:
    """
    Live quotes for a SPECIFIC set of option contracts — the legs of a position
    already on the book. Returns None when the underlying spot or none of the
    contracts can be resolved.

        wanted: iterable of (strike, "CE" | "PE")
        ->  {"symbol", "spot", "expiry", "days_left", "lot_size", "hv_30d",
             "strikes": {strike: {call_bid, call_ask, call_ltp, put_*...}},
             "missing": [(strike, type), ...]}

    Deliberately NOT get_chain_snapshot(): that resolves its own expiry via
    _pick_expiry (30-66 DTE), so a position with 20 days left would be marked
    against a DIFFERENT, later expiry than the one it actually holds — and it
    quotes the whole chain (300-600 contracts) when a mark needs two or four.

    `missing` is returned rather than dropped so mtm.mark_position can say a leg
    was priced off a model instead of the market.
    """
    kite = get_kite()
    exp = (expiry if isinstance(expiry, date)
           else datetime.strptime(str(expiry)[:10], "%Y-%m-%d").date())
    want = {(float(k), str(t).upper()) for k, t in wanted}

    def _exp(i):
        return (i["expiry"] if isinstance(i["expiry"], date)
                else datetime.strptime(i["expiry"], "%Y-%m-%d").date())

    legs = [i for i in _nfo_instruments()
            if i.get("name") == symbol
            and i.get("instrument_type") in ("CE", "PE")
            and (float(i["strike"]), i["instrument_type"]) in want
            and _exp(i) == exp]

    spot_info = get_equity_spot(symbol)
    spot = spot_info["last"]
    if not spot:
        return None

    quotes = {}
    if legs:
        keys = [f"NFO:{i['tradingsymbol']}" for i in legs]
        for j in range(0, len(keys), 300):
            quotes.update(kite.quote(keys[j:j + 300]))

    strikes: dict = {}
    found = set()
    for i in legs:
        k = float(i["strike"])
        q = quotes.get(f"NFO:{i['tradingsymbol']}", {}) or {}
        depth = q.get("depth", {}) or {}
        bid = (depth.get("buy") or [{}])[0].get("price", 0) or 0
        ask = (depth.get("sell") or [{}])[0].get("price", 0) or 0
        row = strikes.setdefault(k, {})
        p = "call" if i["instrument_type"] == "CE" else "put"
        row[f"{p}_ltp"] = q.get("last_price", 0) or 0
        row[f"{p}_oi"] = q.get("oi", 0) or 0
        row[f"{p}_bid"] = bid
        row[f"{p}_ask"] = ask
        found.add((k, i["instrument_type"]))

    return {
        "symbol": symbol,
        "spot": round(spot, 2),
        "prev_close": round(spot_info["prev_close"], 2),
        "expiry": exp,
        "days_left": (exp - date.today()).days,
        "lot_size": (legs[0].get("lot_size", 0) or 0) if legs else 0,
        "hv_30d": calculate_hv_30d(symbol),
        "strikes": strikes,
        "missing": sorted(want - found),
    }


# ══════════════════════════════════════════════════════════════════════
# CHAIN-SNAPSHOT CACHE  (write-through; see config.CHAIN_CACHE_MODE)
# ══════════════════════════════════════════════════════════════════════
_CHAIN_SCHEMA = 1
_DATE_TAG = "__date__"


def _encode(obj):
    """
    JSON-safe copy of a snapshot, TAGGING dates rather than stringifying them.

    Field-agnostic on purpose. The alternative — enumerating the fields that need
    converting — is the rebuild-drops-fields pattern that has bitten this project
    twice already (phase_filters._build_candidate, and the field contract on
    strategy._build_iron_condor): the next date-valued field added to a snapshot
    would round-trip as a STRING, and earnings.collides evaluates
    `window["lo"] <= expiry`, so a string there raises at the gate rather than
    showing up as a data problem here. `earnings_window` alone carries four dates.

    Non-finite floats are DROPPED, not written as null. A solved IV or delta can
    come back NaN, and the selection layer reads those as `row.get("put_delta", 0)`
    — NaN falls outside the 0.20-0.30 delta band and so does the 0 default, so
    dropping the key reproduces live behaviour exactly, whereas `null` would reach
    abs(None) and raise on the replay only.
    """
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, (datetime, date)):          # datetime first: it subclasses date
        return {_DATE_TAG: obj.isoformat()}
    if isinstance(obj, dict):
        return {str(k): _encode(v) for k, v in obj.items()
                if not (isinstance(v, float) and not math.isfinite(v))}
    if isinstance(obj, (list, tuple, set)):
        return [_encode(v) for v in obj
                if not (isinstance(v, float) and not math.isfinite(v))]
    return str(obj)      # last resort — an unexpected type must not break the write


def _decode(obj):
    """Inverse of _encode: turn tagged values back into real date/datetime objects."""
    if isinstance(obj, dict):
        if len(obj) == 1 and _DATE_TAG in obj:
            s = str(obj[_DATE_TAG])
            return (datetime.fromisoformat(s) if "T" in s
                    else datetime.strptime(s[:10], "%Y-%m-%d").date())
        return {k: _decode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode(v) for v in obj]
    return obj


def replay_day() -> date:
    """The day `read` mode serves — config.CHAIN_CACHE_REPLAY_DATE, else today."""
    s = config.CHAIN_CACHE_REPLAY_DATE
    if not s:
        return date.today()
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        print(f"  [CHAIN-CACHE] RG_CHAIN_REPLAY_DATE={s!r} unparseable — using today")
        return date.today()


def _chain_cache_dir(day=None) -> Path:
    return config.CHAIN_CACHE_DIR / str(day or date.today())


def _chain_cache_path(symbol: str, day=None) -> Path:
    return _chain_cache_dir(day) / f"{str(symbol).strip().upper()}.json"


def write_chain_cache(chain: dict, day=None):
    """
    Persist one enriched snapshot. Returns the path written, or None.

    NEVER raises: the cache is a side effect and the run's job is the report, so a
    full disk or a permission error must degrade to a printed warning rather than
    losing a live scan that has already paid for its quotes. Written to a temp file
    and renamed, so an interrupted run cannot leave a half-written snapshot that
    would later decode into a partial chain.

    json.dumps runs with allow_nan=False deliberately — _encode is supposed to have
    removed every non-finite value, and if one gets through, this raises into the
    warning below instead of writing `NaN`, which is not valid JSON and which any
    other reader would choke on.
    """
    if not chain or not chain.get("symbol"):
        return None
    path = _chain_cache_path(chain["symbol"], day)
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": _CHAIN_SCHEMA,
                   "symbol": str(chain["symbol"]).upper(),
                   "captured_at": datetime.now().isoformat(timespec="seconds"),
                   "cache_day": str(day or date.today()),
                   "chain": _encode(chain)}
        tmp.write_text(json.dumps(payload, allow_nan=False))
        tmp.replace(path)
        return path
    except (OSError, TypeError, ValueError) as e:
        print(f"  [CHAIN-CACHE] {chain.get('symbol')}: write failed — {e}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def read_cached_chain(symbol: str, day=None) -> dict | None:
    """
    One cached snapshot, restored to the exact shape get_chain_snapshot returns —
    float strike keys, `date` expiry, `earnings_window` dates intact.

    Returns None (never a partial chain) when the file is absent, unreadable, of a
    different schema, for a different symbol, or missing its expiry or strikes. A
    half-decoded chain would surface downstream as "no constructible spread" — a
    sentence that blames the market for a cache fault — so every failure is printed
    and the symbol is reported as having no chain data instead.
    """
    day = day or replay_day()
    path = _chain_cache_path(symbol, day)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [CHAIN-CACHE] {symbol}: unreadable ({e}) — treated as no chain data")
        return None
    if payload.get("schema") != _CHAIN_SCHEMA:
        print(f"  [CHAIN-CACHE] {symbol}: schema {payload.get('schema')} != "
              f"{_CHAIN_SCHEMA} — refusing to replay it")
        return None
    if str(payload.get("symbol", "")).upper() != str(symbol).strip().upper():
        print(f"  [CHAIN-CACHE] {symbol}: file holds {payload.get('symbol')!r} — refused")
        return None

    chain = _decode(payload.get("chain") or {})
    # The ONE key type JSON cannot carry: strike keys are floats everywhere
    # downstream (_adjacent_strike does sorted(...).index(short_k)), and JSON object
    # keys are always strings.
    chain["strikes"] = {float(k): v for k, v in (chain.get("strikes") or {}).items()}
    if not chain.get("strikes") or not isinstance(chain.get("expiry"), date):
        print(f"  [CHAIN-CACHE] {symbol}: cached snapshot incomplete "
              f"({len(chain.get('strikes') or {})} strikes, expiry "
              f"{chain.get('expiry')!r}) — refused")
        return None
    chain["snapshot_source"] = "cache"
    chain["snapshot_captured_at"] = payload.get("captured_at")
    return chain


def cached_chain_symbols(day=None) -> list:
    """
    Every symbol with a snapshot for `day`, sorted.

    This is the universe a replay should scan: it is exactly what was captured, so
    the replay cannot quietly cover a different set of names than the run it is
    replaying — and resolving it needs no NSE constituent fetch.
    """
    d = _chain_cache_dir(day or replay_day())
    if not d.exists():
        return []
    return sorted(p.stem.upper() for p in d.glob("*.json"))


def prune_chain_cache(keep_days=None) -> list:
    """
    Delete dated snapshot folders older than the retention window. Returns the day
    names removed.

    Only ever removes directories whose name PARSES as a date, so an unrelated file
    or folder that finds its way in here is left alone rather than deleted by a
    glob. A ~100-name run writes 15-20 MB, so unpruned this is the one part of the
    tool that would grow without bound; run.py calls it after a write-mode run and
    prints what went.
    """
    import shutil
    keep = config.CHAIN_CACHE_KEEP_DAYS if keep_days is None else keep_days
    root = config.CHAIN_CACHE_DIR
    if not root.exists() or keep is None:
        return []
    cutoff = date.today() - timedelta(days=int(keep))
    removed = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            d = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            try:
                shutil.rmtree(child)
                removed.append(child.name)
            except OSError as e:
                print(f"  [CHAIN-CACHE] could not remove {child.name} — {e}")
    return removed


def chain_cache_size_mb(day=None) -> float:
    """Disk used by one day's snapshots, so a run can state what it wrote."""
    d = _chain_cache_dir(day or date.today())
    if not d.exists():
        return 0.0
    return round(sum(p.stat().st_size for p in d.glob("*.json")) / 1_048_576, 1)


def get_chain_snapshot(symbol: str) -> dict | None:
    """
    Fetch and enrich a one-time option-chain snapshot for `symbol`.

    WRITE-THROUGH CACHE: in the default `write` mode the enriched snapshot is
    persisted (config.CHAIN_CACHE_MODE) before being returned, so a finished run can
    be re-examined later without Kite. Selection is untouched — the cache is a pure
    side effect of the same live fetch. In `read` mode this serves the cache instead
    and makes no network call at all.
    """
    if config.CHAIN_CACHE_MODE == "read":
        chain = read_cached_chain(symbol)
        if chain is not None:
            # The cache's own capture time, not "now" — a replay's chain is only
            # ever as fresh as the snapshot it was written from.
            chain["as_of"] = chain.get("snapshot_captured_at")
        return chain
    kite = get_kite()
    opts = [i for i in _nfo_instruments()
            if i.get("name") == symbol and i.get("instrument_type") in ("CE", "PE")]
    if not opts:
        return None

    expiry = _pick_expiry(opts)
    if expiry is None:
        return None
    exp_opts = [i for i in opts
                if (i["expiry"] if isinstance(i["expiry"], date)
                    else datetime.strptime(i["expiry"], "%Y-%m-%d").date()) == expiry]
    if not exp_opts:
        return None

    lot_size = exp_opts[0].get("lot_size", 0) or 0
    dte = (expiry - date.today()).days

    spot_info = get_equity_spot(symbol)
    spot = spot_info["last"]
    if not spot:
        return None

    # Batch-quote every option leg (Kite limit 500 per call).
    keys = [f"NFO:{i['tradingsymbol']}" for i in exp_opts]
    quotes = {}
    for j in range(0, len(keys), 300):
        quotes.update(kite.quote(keys[j:j + 300]))

    strikes: dict = {}
    for i in exp_opts:
        k = float(i["strike"])
        q = quotes.get(f"NFO:{i['tradingsymbol']}", {}) or {}
        depth = q.get("depth", {}) or {}
        bid = (depth.get("buy") or [{}])[0].get("price", 0) or 0
        ask = (depth.get("sell") or [{}])[0].get("price", 0) or 0
        row = strikes.setdefault(k, {})
        if i["instrument_type"] == "CE":
            row["call_ltp"] = q.get("last_price", 0) or 0
            row["call_oi"]  = q.get("oi", 0) or 0
            row["call_bid"] = bid
            row["call_ask"] = ask
            # Kite's own tradingsymbol, not reconstructed from strike/expiry
            # arithmetic — rides along so strategy.py can build SPAN-margin leg
            # requests (get_span_margin) without a second instrument lookup.
            row["call_tradingsymbol"] = i["tradingsymbol"]
        else:
            row["put_ltp"] = q.get("last_price", 0) or 0
            row["put_oi"]  = q.get("oi", 0) or 0
            row["put_bid"] = bid
            row["put_ask"] = ask
            row["put_tradingsymbol"] = i["tradingsymbol"]

    # Greeks / IV from LTP (reuses the buying tool's engine).
    #
    # T_days IS RESCALED, DELIBERATELY. black_scholes.compute_greeks converts with
    # T = T_days / 252, i.e. it expects TRADING days — but `dte` here is CALENDAR
    # days. Passing dte raw makes 43 real days behave like 62 (T 0.1706 vs a true
    # 43/365 = 0.1178), which understates every solved IV by ~14%: a genuine 20%
    # ATM vol reads 17.2%.
    #
    # That matters because IV RANK compares this reading against
    # iv_history/, whose samples are computed on a correct
    # (trading-days / 252) basis. Same tenor, two conventions — so the live
    # reading always looked ~3 IV points cheaper than its own history and the rank
    # came out systematically low, right into a MIN_IV_RANK gate. Multiplying by
    # 252/365 converts calendar days to the trading-day basis the engine wants,
    # putting both sides of the comparison on one footing.
    #
    # Done HERE rather than in black_scholes.compute_greeks on purpose: that
    # function is shared with the buying tool, and changing its T convention would
    # move every greek and IV that tool reports. This confines the correction to
    # the selling tool. The underlying calendar-vs-trading-day bug in
    # compute_greeks is still there and still worth fixing properly.
    hv = calculate_hv_30d(symbol)
    t_days_252 = max(dte * 252.0 / 365.0, 1)
    enrich_strikes_with_greeks(strikes, spot=spot, T_days=t_days_252, hv_30d=hv)

    # ATM IV -> IV rank.
    atm_strike = min(strikes.keys(), key=lambda s: abs(s - spot))
    atm = strikes[atm_strike]
    atm_iv = round((atm.get("call_iv", 0) + atm.get("put_iv", 0)) / 2, 2) or atm.get("call_iv", 0)
    ivr = calculate_iv_rank(symbol, atm_iv)

    supp = get_cached_supplementary(symbol)
    delivery_5d = supp.get("delivery_volume_pct_5d_avg")
    if not isinstance(delivery_5d, (int, float)):
        delivery_5d = None

    chain = {
        "symbol":        symbol,
        "spot":          round(spot, 2),
        "prev_close":    round(spot_info["prev_close"], 2),
        "expiry":        expiry,
        "dte":           dte,
        "lot_size":      lot_size,
        "atm_iv":        atm_iv,
        "iv_rank":       ivr["iv_rank"],
        "iv_quality":    ivr["iv_rank_data_quality"],
        # Sample counts ride along so a thin or heavily-filtered history is
        # visible in the report rather than hiding behind a plausible rank.
        "iv_samples":         ivr.get("iv_rank_samples", 0),
        "iv_samples_dropped": ivr.get("iv_rank_samples_dropped", 0),
        "delivery_5d":   delivery_5d,
        "next_earnings": supp.get("next_earnings_date"),
        # Three-tier earnings resolution (confirmed / estimated / unverified),
        # read from the cache earnings.refresh() fills once a week in run.py —
        # this is a dict lookup, not a fetch, so it adds nothing to the per-
        # symbol snapshot cost.
        "earnings_window": earnings.window_for(symbol, cache=_earnings_cache()),
        "index_membership": get_index_membership(symbol),
        # False when the only eligible expiry sits beyond the 30-45 blueprint
        # band — allowed (monthly-only ladder leaves no alternative) but surfaced.
        "dte_preferred": dte <= config.PREFERRED_MAX_DTE,
        "strikes":       strikes,
    }

    # Write BEFORE stamping the provenance, so the file on disk does not claim to be
    # a live reading — read_cached_chain stamps "cache" on the way back out. Anything
    # a future field adds to the snapshot is carried automatically (see _encode).
    if config.CHAIN_CACHE_MODE == "write":
        write_chain_cache(chain)
    chain["snapshot_source"] = "live"
    chain["as_of"] = datetime.now().isoformat(timespec="seconds")
    return chain
