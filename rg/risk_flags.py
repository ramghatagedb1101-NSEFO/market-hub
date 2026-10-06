"""
risk_flags.py — append-only observation store for macro risk flags.

Deliberately NOT stored inside data/macro_briefing.json. That file is a per-day
cache; coupling flag lifetime to it would mean a deterministic-fallback day wipes
the flags, and any later change to decay policy would need a data migration.

Design rule: STORE OBSERVATIONS, DERIVE VERDICTS.
Each record holds only what was observed — when it was first and last seen, the
severity the model assigned, the catalyst date it named. Whether the flag is
active *right now*, and how much severity has decayed, are computed at read time
by resolve() / effective_severity(). Changing the policy is therefore a function
edit, never a migration of stored `active: true` fields.

Purity split, so the policy is unit-testable against fixed dates with no I/O:
  PURE   — resolve, effective_severity, expiry_for, merge, flags_for,
           market_flags, target_key   (every one takes `today` explicitly)
  IMPURE — load, save, ingest, active_for_symbol   (thin wrappers only)

Record shape (schema 1):
  flag_key         stable id; see target_key() — keyed on the TARGET, not wording
  scope            "symbol" | "sector" | "market"
  affected_symbols validated tickers (authoritative — see macro._normalise_key_risks)
  affected_sectors validated sectors, expanded via market_data.get_sector()
  risk             the model's one-line description (for the report and matching)
  severity_raw     "HIGH" | "MEDIUM" | "LOW" | None  — as assigned, never decayed
  catalyst_date    ISO date the risk resolves on, or None if open-ended
  source_section   provenance: "key_risks", or "manual" for a config override
  first_seen       ISO date the flag was created  (never reset on re-confirmation)
  last_seen        ISO date it was last re-confirmed
  observations     how many times it has been seen
"""

import hashlib
import json
from datetime import date, timedelta

from . import config
from .macro import _sim          # reuse the theme-dedup similarity for matching

_STORE  = config.DATA_DIR / "risk_flags.json"
_SCHEMA = 1

# Ascending, so decay is a single index step down and None means "decayed away".
_SEV_ORDER = ("LOW", "MEDIUM", "HIGH")


# ── helpers ───────────────────────────────────────────────────────────
def _iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _as_date(value):
    """Tolerant ISO parse. Returns None rather than raising on junk."""
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def target_key(scope, symbols, sectors) -> str:
    """
    Stable id for what a flag POINTS AT, not how it is worded — so the same story
    re-described tomorrow re-confirms the existing flag instead of creating a new
    one with a reset first_seen (which would defeat duration tracking entirely).
    Wording drift is handled separately by the similarity check in merge().
    """
    canon = "|".join([
        str(scope or "").strip().lower(),
        ",".join(sorted({str(s).strip().upper() for s in (symbols or []) if str(s).strip()})),
        ",".join(sorted({str(s).strip().upper() for s in (sectors or []) if str(s).strip()})),
    ])
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:12]


# ── PURE: resolution order ────────────────────────────────────────────
def expiry_for(flag, today):
    """
    Resolution order, highest precedence first. Returns (expires_on, rule).

      1. catalyst_date + RISK_FLAG_CATALYST_GRACE  — the risk hangs on a dated
         event, so it dies once that event has passed and been digested;
      2. last_seen + RISK_FLAG_TTL_DAYS            — open-ended risk, ages out
         unless the model keeps re-confirming it;
      3. first_seen + RISK_FLAG_MAX_AGE_DAYS       — hard ceiling, applied to
         (2) so an endlessly re-confirmed open-ended story cannot keep a flag
         alive forever. For (1) the ceiling STRETCHES to at least
         catalyst_date + grace instead of capping it early — a dated catalyst
         is by definition informative about how long the flag should live, so
         a far-dated one (e.g. 45 days out against a 30-day default ceiling)
         must survive to see its own event, not expire days before it.

    `rule` names whichever bound actually binds, so diagnostics can explain the
    expiry rather than just asserting it. Returns (None, "malformed") when the
    record lacks the dates needed to decide — callers treat that as inactive
    rather than defaulting it open.
    """
    first = _as_date(flag.get("first_seen"))
    last  = _as_date(flag.get("last_seen")) or first
    if last is None or first is None:
        return None, "malformed"
    if last < first:                      # corrupt record; don't extend life
        last = first

    catalyst = _as_date(flag.get("catalyst_date"))
    if catalyst is not None:
        base, rule = catalyst + timedelta(days=config.RISK_FLAG_CATALYST_GRACE), "catalyst"
        # Stretch the ceiling to cover the catalyst (+ grace) rather than letting
        # the default max-age cut a far-dated catalyst off before it even fires.
        max_age_days = max(config.RISK_FLAG_MAX_AGE_DAYS,
                            (catalyst - first).days + config.RISK_FLAG_CATALYST_GRACE)
    else:
        base, rule = last + timedelta(days=config.RISK_FLAG_TTL_DAYS), "ttl"
        max_age_days = config.RISK_FLAG_MAX_AGE_DAYS

    ceiling = first + timedelta(days=max_age_days)
    if ceiling < base:
        return ceiling, "max_age"
    return base, rule


def effective_severity(flag, today):
    """
    Severity as of `today`: the raw value decayed one tier per
    RISK_FLAG_STALE_DAYS since last_seen. Derived, never stored — so re-tuning
    the decay rate needs no rewrite of existing records.

    None when the model assigned no valid severity (including schema-1 legacy
    string risks, which carry severity_raw=None) or when decay has run it past
    LOW. A None severity must never be silently read as "no risk" — it means
    "unrated", and the scoring layer is expected to treat it as a no-op.
    """
    raw = str(flag.get("severity_raw") or "").strip().upper()
    if raw not in _SEV_ORDER:
        return None
    last = _as_date(flag.get("last_seen"))
    if last is None:
        return None
    stale = max(0, (today - last).days)
    step = config.RISK_FLAG_STALE_DAYS
    tiers = stale // step if step > 0 else 0
    idx = _SEV_ORDER.index(raw) - tiers
    return _SEV_ORDER[idx] if idx >= 0 else None


def resolve(flag, today):
    """Full read-time verdict for one flag. Pure: no I/O, no implicit clock."""
    expires, rule = expiry_for(flag, today)
    first = _as_date(flag.get("first_seen"))
    last  = _as_date(flag.get("last_seen")) or first
    return {
        "flag_key":           flag.get("flag_key"),
        "active":             bool(expires is not None and today <= expires),
        "rule":               rule,
        "expires_on":         _iso(expires) if expires else None,
        "days_remaining":     (expires - today).days if expires else None,
        "age_days":           (today - first).days if first else None,
        "staleness_days":     max(0, (today - last).days) if last else None,
        "severity_raw":       flag.get("severity_raw"),
        "effective_severity": effective_severity(flag, today),
    }


def active(flags, today) -> list:
    """Flags whose resolve() says they are live as of `today`. Pure."""
    return [f for f in (flags or []) if resolve(f, today)["active"]]


# ── PURE: lookup ──────────────────────────────────────────────────────
def flags_for(flags, symbol, sector, today) -> list:
    """
    Active NAME-SPECIFIC flags hitting this symbol, by explicit ticker or by
    sector expansion. Market-scope flags are excluded on purpose: they are an
    exposure-level lever (position count / capital), not a per-name penalty —
    folding them in here would penalise every candidate equally, which is the
    same as penalising none. Use market_flags() for those.
    """
    sym = str(symbol or "").strip().upper()
    sec = str(sector or "").strip().upper()
    hits = []
    for f in active(flags, today):
        if f.get("scope") == "market":
            continue
        if sym and sym in {str(s).upper() for s in f.get("affected_symbols") or []}:
            hits.append(f)
        elif sec and sec in {str(s).upper() for s in f.get("affected_sectors") or []}:
            hits.append(f)
    return hits


def market_flags(flags, today) -> list:
    """Active market/index-wide flags. Pure."""
    return [f for f in active(flags, today) if f.get("scope") == "market"]


# ── PURE: scoring ─────────────────────────────────────────────────────
def score_multiplier(flags, today):
    """
    Score multiplier for ONE symbol, from the flags already filtered for it
    (i.e. the output of flags_for). Pure.

    Returns (multiplier, detail). `detail` itemises every contributing flag so
    the report can show WHY a name was demoted, not merely that it was — a
    silent multiplier is exactly the un-auditable behaviour this whole feature
    exists to replace.

    Two invariants enforced in code rather than left to documentation:
      - the multiplier is looked up against the DECAYED severity
        (effective_severity), never the model's raw label;
      - PENALTY-ONLY: the result is clamped to [0.0, 1.0], so a mis-edited
        table can never turn a risk flag into a score boost, and a negative
        entry can never invert the ranking.
    """
    mults, detail = [], []
    for f in flags or []:
        sev = effective_severity(f, today)
        key = str(sev).upper() if sev else None
        if key is not None and key not in config.RISK_FLAG_SCORE_MULT:
            print(f"  [FLAGS] severity {key!r} missing from RISK_FLAG_SCORE_MULT "
                  f"— treated as unrated (no penalty)")
        mult = config.RISK_FLAG_SCORE_MULT.get(key, config.RISK_FLAG_UNRATED_MULT)
        mults.append(mult)
        detail.append({
            "flag_key":           f.get("flag_key"),
            "risk":               f.get("risk"),
            "severity_raw":       f.get("severity_raw"),
            "effective_severity": sev,
            "multiplier":         mult,
        })

    if not mults:
        return 1.0, []
    if str(config.RISK_FLAG_COMBINE).lower() == "compound":
        total = 1.0
        for m in mults:
            total *= m
    else:                          # "worst" — see config.RISK_FLAG_COMBINE for why
        total = min(mults)
    return round(max(0.0, min(total, 1.0)), 4), detail


# ── PURE: ingest / merge ──────────────────────────────────────────────
def merge(flags, records, today):
    """
    Fold today's observations into the existing flag list. Pure — returns
    (new_flag_list, summary) and mutates nothing the caller passed in.

    APPEND-ONLY: nothing is ever deleted here. A flag that stops being reported
    simply ages out via expiry_for(), which keeps the audit trail intact and
    means a day the model returns [] does not erase yesterday's live flags. That
    is the fail-safe direction — an LLM outage makes the screen more cautious by
    inertia rather than silently less.

    Matching is two-stage: exact target_key (same scope + names), then a
    similarity check on the risk text so a genuinely different story about the
    same names becomes its own flag instead of hijacking the first one's
    first_seen. Re-confirmation refreshes last_seen / severity / catalyst and
    NEVER resets first_seen.
    """
    out = [dict(f) for f in (flags or [])]
    summary = {"new": 0, "reconfirmed": 0, "skipped": 0}

    for rec in records or []:
        text = str(rec.get("risk") or "").strip()
        if not text:
            summary["skipped"] += 1
            continue
        scope   = str(rec.get("scope") or "market").strip().lower()
        symbols = list(rec.get("affected_symbols") or [])
        sectors = list(rec.get("affected_sectors") or [])
        key     = target_key(scope, symbols, sectors)

        same_target = [f for f in out if str(f.get("flag_key", "")).split("#")[0] == key]
        match = None
        for cand in same_target:
            if _sim(text, cand.get("risk", "")) >= config.RISK_FLAG_MATCH_SIM:
                match = cand
                break

        if match is not None:
            match["last_seen"]     = _iso(today)
            match["risk"]          = text                 # keep the freshest wording
            match["severity_raw"]  = rec.get("severity") or match.get("severity_raw")
            match["catalyst_date"] = rec.get("catalyst_date") or match.get("catalyst_date")
            match["observations"]  = int(match.get("observations", 1)) + 1
            summary["reconfirmed"] += 1
            continue

        # Same names, different story -> suffix so both keep their own dates.
        flag_key = key if not same_target else f"{key}#{len(same_target) + 1}"
        out.append({
            "flag_key":         flag_key,
            "scope":            scope,
            "affected_symbols": sorted({str(s).upper() for s in symbols}),
            "affected_sectors": sorted({str(s).upper() for s in sectors}),
            "risk":             text,
            "severity_raw":     rec.get("severity"),
            "catalyst_date":    rec.get("catalyst_date"),
            "source_section":   rec.get("source_section") or "key_risks",
            "first_seen":       _iso(today),
            "last_seen":        _iso(today),
            "observations":     1,
        })
        summary["new"] += 1

    return out, summary


# ── IMPURE: thin I/O wrappers ─────────────────────────────────────────
def load() -> list:
    """Flag list from disk. Missing/corrupt/wrong-schema store -> []."""
    if not _STORE.exists():
        return []
    try:
        data = json.loads(_STORE.read_text())
    except Exception:
        return []
    if data.get("schema") != _SCHEMA:
        print(f"  [FLAGS] store schema {data.get('schema')} != {_SCHEMA} — ignoring")
        return []
    return data.get("flags") or []


def save(flags) -> None:
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STORE.write_text(json.dumps(
            {"schema": _SCHEMA, "flags": flags}, indent=2))
    except Exception as e:
        print(f"  [FLAGS] store write failed — {e}")


def ingest(records, today=None) -> list:
    """
    Merge today's normalised key_risks into the store and persist. Returns the
    full flag list (callers filter with flags_for / market_flags).
    """
    today = today or date.today()
    flags, summary = merge(load(), records, today)
    save(flags)
    live = len(active(flags, today))
    print(f"  [FLAGS] {summary['new']} new, {summary['reconfirmed']} re-confirmed, "
          f"{summary['skipped']} skipped | {live} active of {len(flags)} stored")
    return flags


def active_for_symbol(symbol, today=None) -> list:
    """Convenience read path for one symbol; resolves its sector itself."""
    today = today or date.today()
    from . import market_data          # local import: keeps risk_flags I/O-light
    sector = market_data.get_sector(symbol)
    return flags_for(load(), symbol, sector, today)
