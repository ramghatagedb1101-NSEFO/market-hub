"""
macro.py — institutional daily macro-environment briefing.

Pipeline (the ONE place a deterministic tool can't produce the value):
  Sonnet + web-search runs targeted searches across 6 domains, then returns a
  STRICT-JSON desk note: a house regime call, six themed developments (each with
  a figure, date, source and an explicit premium-selling implication), a forward
  event radar, key risks to short-premium positions, and sources.

Freshness discipline (fixes "same old news every day"):
  - every item must carry a date; anything older than RECENCY_DAYS is dropped;
  - the prompt targets PRICE ACTION / NEW catalysts, not evergreen facts;
  - day-over-day de-dup vs yesterday's cache marks unchanged themes as such.

Cost discipline: one call/day, cached to data/macro_briefing.json, meant to be
generated once centrally and shared. Token usage is logged each run. Set
RG_MACRO_LLM=0 to force the deterministic fallback.

key_risks is a MACHINE-CONSUMED contract, not prose (schema 2):
  - 0-3 entries, never padded — an empty list is a valid, expected answer;
  - each carries severity / scope / affected_symbols / affected_sectors /
    catalyst_date, so a downstream filter can act on a named danger without
    parsing English;
  - the model is never trusted: _normalise_key_risks validates severity and
    scope against fixed vocabularies and tickers against _known_symbols(),
    preserving (and logging) anything unresolvable rather than dropping it.
Bump _SCHEMA whenever that contract changes — the cache read is version-gated,
so an older-shaped briefing is discarded instead of silently mis-read.
"""

import os
import re
import json
from pathlib import Path
from datetime import date, datetime, timedelta

from . import config

_CACHE = config.DATA_DIR / "macro_briefing.json"
_CRUDE_HIST = config.DATA_DIR / "crude_history.json"
_MODEL = "claude-sonnet-4-6"
_RECENCY_DAYS = 4
_THEMES = ["Rates", "Flows", "Currency", "Commodities", "Global", "India"]

# Bump _SCHEMA whenever the key_risks contract changes. get_macro_briefing()
# version-gates the cache read on it, so an older-shaped cached briefing is
# discarded rather than handed to a consumer expecting the new shape.
_SCHEMA     = 2
_SEVERITIES = ("HIGH", "MEDIUM", "LOW")
_SCOPES     = ("symbol", "sector", "market")

_PROMPT = (
    "You are the macro strategist for RG Invest, writing the market-environment page of an "
    "institutional NSE F&O desk note for option PREMIUM SELLERS. Today is {today}.\n\n"
    "Run web searches to gather the LATEST developments (last 24–48 hours) across:\n"
    "1) overnight US & Asian equity closes, 2) crude oil & gold moves, 3) USD/INR, "
    "4) the most recent session's FII/DII cash-market flows in India, 5) India policy / "
    "regulatory / sector / results headlines, 6) geopolitics / tariffs / conflicts.\n\n"
    "FRESHNESS RULES (critical):\n"
    "- Include ONLY developments dated within the last 3 days. Every item MUST carry an "
    "explicit date. Omit anything older or undated.\n"
    "- Prioritise PRICE ACTION and NEW catalysts — things that differ from a week ago. Do NOT "
    "restate evergreen structural facts (e.g. a rate decision from weeks ago) unless there is a "
    "genuinely NEW development.\n"
    "- If a theme has no fresh development, set its headline to 'No material change' with today's date.\n\n"
    "KEY-RISK RULES (these feed an automated position filter — read carefully):\n"
    "- Return BETWEEN 0 AND 3 key risks. Return an EMPTY LIST when no material, NAMEABLE "
    "danger to short-premium positions exists today. Do NOT pad to three. A quiet tape is a "
    "real and common answer; inventing a risk to fill a slot is worse than returning none.\n"
    "- severity: HIGH only when the risk could gap a stock or the index clean through a "
    "10-15% OTM short strike within ~10 sessions. MEDIUM for a credible vol-expansion risk "
    "short of that. LOW for a watch-item with no price impact yet.\n"
    "- scope: 'symbol' when specific names are exposed, 'sector' when a whole sector is, "
    "'market' for index-wide or systemic risk.\n"
    "- affected_symbols: EXACT tickers from this list ONLY — {universe}\n"
    "  Use [] for market-scope risks. NEVER invent or abbreviate a ticker; if a name you want "
    "to flag is not on that list, omit the ticker and describe it in the risk text instead.\n"
    "- affected_sectors: only from — {sectors}\n"
    "- catalyst_date: the dated event that RESOLVES the risk (DD-Mon-YYYY), else null. This "
    "drives how long the flag stays active, so supply it whenever the risk hangs on a "
    "scheduled event, and leave it null for open-ended situations.\n\n"
    "CALIBRATION EXAMPLES (match this bar for severity):\n"
    '- Group chairman resigns, no named successor, holdings already selling off -> '
    '{{"severity":"HIGH","scope":"symbol",'
    '"affected_symbols":["TCS","TATAMOTORS","TATASTEEL","TATAPOWER"],"catalyst_date":null}} '
    "— governance cascade across several listed names, no scheduled resolution.\n"
    '- FOMC decision 4 sessions out with a hike priced near 40% -> '
    '{{"severity":"MEDIUM","scope":"market","affected_symbols":[],'
    '"catalyst_date":"16-Sep-2026"}} — index-wide vol event on a known date.\n'
    '- Monsoon-deficit chatter, no price impact yet -> {{"severity":"LOW","scope":"sector",'
    '"affected_sectors":["FMCG"],"affected_symbols":["ITC"],"catalyst_date":null}} '
    "— watch-item only.\n\n"
    "Return STRICT JSON ONLY (no prose, no markdown fences), exactly this shape:\n"
    '{{"regime_call":"<=25 words, house view for a premium seller based on the freshest tape",'
    '"themes":[{{"theme":"Rates","headline":"fresh development","figure":"level or % move",'
    '"date":"DD-Mon-YYYY","source":"publisher","seller_implication":"one line: what it means for selling premium"}}],'
    '"event_radar":[{{"date":"DD-Mon","event":"...","vol_impact":"High|Medium|Low"}}],'
    '"key_risks":[{{"risk":"one sentence: what breaks, and how it hurts a short-premium book",'
    '"severity":"HIGH|MEDIUM|LOW","scope":"symbol|sector|market",'
    '"affected_symbols":["EXACT_TICKER"],"affected_sectors":["SECTOR"],'
    '"catalyst_date":"DD-Mon-YYYY or null"}}],'
    '"sources":["publisher, DD-Mon"]}}\n'
    "Provide exactly one themes entry for each of: Rates, Flows, Currency, Commodities, Global, India. "
    "event_radar: up to 6 items in the next ~10 trading sessions. "
    "key_risks: 0 to 3 per the rules above — an empty list is valid."
)


# ── helpers ───────────────────────────────────────────────────────────
def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _regime_line(context) -> str:
    vix = (context or {}).get("india_vix")
    try:
        v = float(vix)
        band = ("a low-volatility regime — index option premium is compressed" if v < 16
                else "a moderate-volatility regime" if v < 22
                else "an elevated-volatility regime — premium is rich")
        return f"India VIX at {v:.2f} signals {band}."
    except (TypeError, ValueError):
        return "Volatility regime unavailable."


def _parse_date(s):
    s = str(s).strip()[:12]
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d-%b", "%d %b"):
        try:
            d = datetime.strptime(s, fmt)
            return d.replace(year=date.today().year).date() if d.year == 1900 else d.date()
        except ValueError:
            continue
    return None


def _fresh(item) -> bool:
    """Keep 'No material change' notes; else require a date within the window."""
    hl = (item.get("headline") or "").lower()
    if "no material change" in hl or "no change" in hl:
        return True
    d = _parse_date(item.get("date"))
    if d is None:
        return False
    return (date.today() - d).days <= _RECENCY_DAYS


def _norm(s):
    return set(re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split())


def _sim(a, b):
    A, B = _norm(a), _norm(b)
    return len(A & B) / len(A | B) if A and B else 0.0


def _dedup_vs_prior(themes):
    """Mark themes unchanged vs yesterday's cache so the note shows what CHANGED."""
    prior = {}
    if _CACHE.exists():
        try:
            c = json.loads(_CACHE.read_text())
            if c.get("date") != str(date.today()):     # genuinely a prior day
                for t in c.get("themes", []):
                    prior[t.get("theme")] = t.get("headline", "")
        except Exception:
            pass
    for t in themes:
        p = prior.get(t.get("theme"))
        if p and _sim(t.get("headline", ""), p) > 0.8:
            t["headline"] = "No material change since yesterday"
            t["figure"] = ""
            t["carried"] = True
    return themes


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _known_symbols() -> list:
    """
    Tickers the flag layer can actually resolve, so the prompt advertises the
    same set the validator enforces. Union of two DIFFERENT reference sets:
      - config.SECTOR_MAP keys — manual sector overrides, normally empty;
      - the scannable universe (nifty50 cache, else WATCHLIST) — what a
        symbol-scope flag has to match, since strategy.py sees chain["symbol"]
        from get_universe(), and get_sector() tolerates a miss as "OTHER".
    Resolved at call time rather than hardcoded, so it tracks the live universe.
    """
    syms = {str(s).strip().upper() for s in config.SECTOR_MAP}
    try:
        if config.UNIVERSE_CACHE.exists():
            syms |= {str(s).strip().upper()
                     for s in json.loads(config.UNIVERSE_CACHE.read_text())}
    except Exception:
        pass
    syms |= {s.strip().upper() for s in config.WATCHLIST}
    return sorted(s for s in syms if s)


def _known_sectors() -> list:
    """
    Valid sector labels for the prompt. Delegates to market_data.known_sectors()
    because config.SECTOR_MAP is now an empty override dict — reading its values
    here would advertise NO valid sectors to the model and then drop every sector
    it returned.
    """
    from . import market_data          # local import: avoids a package-load cycle
    return market_data.known_sectors()


def _fuzzy_symbol(token, known):
    """
    Conservative ticker recovery for a near-miss (e.g. 'TATA STEEL' -> TATASTEEL).
    Returns None rather than guessing whenever the token could plausibly be more
    than one name — 'TATA' prefixes three tickers, so it resolves to nothing.
    """
    if not token:
        return None
    cands = [k for k in known if k.startswith(token) or token.startswith(k)]
    if len(cands) == 1:
        return cands[0]
    import difflib
    close = difflib.get_close_matches(token, sorted(known), n=2, cutoff=0.86)
    return close[0] if len(close) == 1 else None


def _normalise_key_risks(raw) -> list:
    """
    Coerce the model's key_risks into the flag layer's contract (schema 2).

    The LLM is never trusted: severity and scope are validated against fixed
    vocabularies, tickers against _known_symbols() (exact, then one conservative
    fuzzy pass), sectors against the sector map's values. Anything unresolvable
    is PRESERVED under 'unmatched_symbols' and logged — never silently dropped,
    because a dropped ticker looks identical to "no risk on that name".

    Also accepts the schema-1 shape (a bare string) so an older cached briefing
    still renders. Those carry severity=None and structured=False, so the flag
    layer can skip them instead of inventing a severity they never had.
    """
    known, sectors_ok = set(_known_symbols()), set(_known_sectors())
    out = []
    for item in (raw or [])[:3]:
        if isinstance(item, str):                      # schema-1 cached briefing
            text = item.strip()
            if text:
                out.append({"risk": text, "severity": None, "scope": "market",
                            "affected_symbols": [], "affected_sectors": [],
                            "unmatched_symbols": [], "catalyst_date": None,
                            "source_section": "key_risks", "structured": False})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("risk") or item.get("headline") or "").strip()
        if not text:
            continue

        sev = str(item.get("severity") or "").strip().upper()
        if sev and sev not in _SEVERITIES:
            print(f"  [MACRO] key_risk severity {sev!r} not in {_SEVERITIES} — dropped")
        sev = sev if sev in _SEVERITIES else None

        matched, unmatched = [], []
        for s in item.get("affected_symbols") or []:
            token = re.sub(r"[^A-Z0-9&]", "", str(s).upper())
            if token in known:
                matched.append(token)
                continue
            hit = _fuzzy_symbol(token, known)
            if hit:
                print(f"  [MACRO] key_risk ticker {s!r} -> {hit} (fuzzy match)")
                matched.append(hit)
            else:
                print(f"  [MACRO] key_risk ticker {s!r} not in universe — kept unmatched")
                unmatched.append(str(s).strip().upper())

        secs = []
        for x in item.get("affected_sectors") or []:
            sector = str(x).strip().upper()
            if sector in sectors_ok:
                secs.append(sector)
            elif sector:
                print(f"  [MACRO] key_risk sector {sector!r} not a known sector — dropped")

        cd = _parse_date(item.get("catalyst_date")) if item.get("catalyst_date") else None

        scope = str(item.get("scope") or "").strip().lower()
        if scope not in _SCOPES:
            scope = "symbol" if matched else ("sector" if secs else "market")

        out.append({"risk": text, "severity": sev, "scope": scope,
                    "affected_symbols": sorted(set(matched)),
                    "affected_sectors": sorted(set(secs)),
                    "unmatched_symbols": sorted(set(unmatched)),
                    "catalyst_date": str(cd) if cd else None,
                    "source_section": "key_risks", "structured": True})
    return out


def _may_write_cache(out) -> bool:
    """
    False only when `out` is a deterministic fallback and the cache already holds
    a same-day LLM briefing. See the guarded write in get_macro_briefing().
    """
    if out.get("source") != "deterministic":
        return True
    if not _CACHE.exists():
        return True
    try:
        prior = json.loads(_CACHE.read_text())
    except Exception:
        return True
    if prior.get("date") != out.get("date"):
        return True                      # a prior day's note — safe to replace
    if prior.get("source") and prior["source"] != "deterministic":
        print("  [MACRO] today's LLM briefing kept; deterministic fallback NOT cached")
        return False
    return True


def _series(context):
    """Short trend series for the sparkline charts. Degrades to {} gracefully."""
    out = {}
    try:
        from oi_snapshot_store import get_connection
        with get_connection() as conn:
            vix = conn.execute(
                "SELECT atm_iv FROM iv_snapshots WHERE symbol LIKE '%VIX%' "
                "ORDER BY snapshot_date DESC LIMIT 20").fetchall()
            out["vix"] = [r[0] for r in reversed(vix)] if vix else []
            fii = conn.execute(
                "SELECT net_contracts FROM fii_snapshots ORDER BY snapshot_date DESC LIMIT 12").fetchall()
            out["fii"] = [r[0] for r in reversed(fii)] if fii else []
    except Exception:
        out.setdefault("vix", [])
        out.setdefault("fii", [])
    # crude: maintain our own daily history (no external series available)
    try:
        hist = json.loads(_CRUDE_HIST.read_text()) if _CRUDE_HIST.exists() else {}
        brent = (context or {}).get("brent_crude_price")
        if isinstance(brent, (int, float)):
            hist[str(date.today())] = brent
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CRUDE_HIST.write_text(json.dumps(hist, indent=2))
        out["crude"] = [hist[k] for k in sorted(hist)[-20:]]
    except Exception:
        out["crude"] = []
    return out


def _deterministic(context):
    """Fallback desk note from the quantitative snapshot when the API is off."""
    c = context or {}
    themes = []
    vix = c.get("india_vix")
    if vix is not None:
        themes.append({"theme": "Rates", "headline": "Volatility regime read",
                       "figure": f"India VIX {vix}", "date": str(date.today()), "source": "RG data",
                       "seller_implication": ("compressed premium — poor selling edge"
                                              if _f(vix) < 16 else "premium building — selectively sell")})
    fii = c.get("fii_index_futures_net_contracts")
    if isinstance(fii, (int, float)):
        themes.append({"theme": "Flows", "headline": "FII index-futures positioning",
                       "figure": f"net {fii:,} ({c.get('fii_index_futures_position','?')})",
                       "date": str(date.today()), "source": "RG data",
                       "seller_implication": "positioning skew — mind gap risk on the crowded side"})
    brent = c.get("brent_crude_price")
    if brent is not None:
        themes.append({"theme": "Commodities", "headline": "Crude level",
                       "figure": f"Brent ${brent} ({c.get('brent_crude_change_pct','?')}%)",
                       "date": str(date.today()), "source": "RG data",
                       "seller_implication": "watch energy/paint names for imported-inflation vol"})
    return {"regime_call": _regime_line(context),
            "themes": themes, "event_radar": [], "key_risks": [],
            "sources": ["RG quantitative snapshot"]}


def _fetch_llm(context):
    import anthropic
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # forecast_hub/.env only
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=_MODEL, max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": _PROMPT.format(
            today=date.today().strftime("%d %b %Y"),
            universe=", ".join(_known_symbols()),
            sectors=", ".join(_known_sectors()),
        )}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    # cost / usage telemetry
    try:
        u = resp.usage
        searches = getattr(getattr(u, "server_tool_use", None), "web_search_requests", 0) or 0
        est = u.input_tokens / 1e6 * 3 + u.output_tokens / 1e6 * 15 + searches / 1000 * 10
        print(f"  [MACRO] Sonnet: in={u.input_tokens} out={u.output_tokens} "
              f"searches={searches}  est ${est:.3f}")
    except Exception:
        pass
    data = _extract_json(text)
    if not data:
        raise RuntimeError("model did not return parseable JSON")
    return data


# ── public entry ──────────────────────────────────────────────────────
def get_macro_briefing(context) -> dict:
    """Return the structured daily desk note. Cached per calendar day."""
    today = str(date.today())
    if _CACHE.exists():
        try:
            cached = json.loads(_CACHE.read_text())
            if (cached.get("date") == today and cached.get("themes")
                    and cached.get("schema") == _SCHEMA):
                return cached
        except Exception:
            pass

    source = "deterministic"
    data = None
    if os.getenv("RG_MACRO_LLM", "1") != "0":
        try:
            data = _fetch_llm(context)
            source = "news (Sonnet multi-search)"
        except Exception as e:
            print(f"  [MACRO] LLM briefing unavailable ({str(e)[:70]}) — deterministic fallback")
    if not data:
        data = _deterministic(context)

    # freshness filter + day-over-day dedup on the themes
    themes = [t for t in data.get("themes", []) if _fresh(t)]
    themes = _dedup_vs_prior(themes)
    # keep event-radar items dated today or later
    radar = []
    for e in data.get("event_radar", []):
        d = _parse_date(e.get("date"))
        if d is None or d >= date.today():
            radar.append(e)

    out = {
        "schema": _SCHEMA,
        "date": today,
        "as_of": datetime.now().isoformat(timespec="minutes"),
        "regime": _regime_line(context),
        "regime_call": data.get("regime_call", ""),
        "themes": themes,
        "event_radar": radar[:6],
        "key_risks": _normalise_key_risks(data.get("key_risks")),
        "sources": data.get("sources", []),
        "series": _series(context),
        "source": source,
    }
    # GUARDED WRITE — a deterministic fallback must never overwrite a same-day
    # LLM briefing. It carries key_risks: [], and because the read above only
    # requires non-empty `themes` (which _deterministic does populate from
    # VIX/FII/crude), the flag-less copy would then be served for the rest of the
    # calendar day and the LLM never retried. _may_write_cache() vetoes that one
    # case; every other write proceeds as before.
    if _may_write_cache(out):
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CACHE.write_text(json.dumps(out, indent=2))
        except Exception:
            pass
    return out
