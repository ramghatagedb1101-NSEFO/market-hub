"""
Dividends and buybacks, from NSE's own corporate-actions API (free, no key, same Akamai session as
hub.shareholding -- confirmed working with that session's cookies on 2026-10-07).

The feed is free text ("Dividend - Rs 6 Per Share", "Bonus 1:1", "Buyback of Equity Shares"), not a
structured amount field, so the rupee figure is parsed out of the subject line with a regex. A
subject that does not match the expected "Rs <amount> Per Share" pattern is skipped, never guessed.
"""
import re
from datetime import date, datetime, timedelta

API = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={sym}"

_DIV_RE = re.compile(r"Rs\.?\s*([\d.]+)\s*Per\s*Share", re.I)


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%d-%b-%Y").date()
    except (TypeError, ValueError):
        return None


def fetch(s, symbol: str) -> list[dict]:
    """Raises on a network error or non-200/404 so the caller can retry with a fresh session; a 404
    (no actions on record) returns an empty list."""
    r = s.get(API.format(sym=symbol), headers={**_headers(), "Accept": "application/json"}, timeout=20)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    body = r.json()
    return body if isinstance(body, list) else []


def _headers() -> dict:
    from . import shareholding as shp
    return shp.HEADERS


def recent_and_upcoming(records: list[dict], as_of: date | None = None, past_days: int = 365,
                        limit: int = 12) -> list[dict]:
    """The actions worth showing on a stock report: anything with an ex-date in the future, plus the
    last year. NSE's own wording is kept as-is (subject), dates normalised to ISO. Newest first.
    This is public NSE data, so unlike BharatStock figures it can be stored in library.json."""
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=past_days)
    out = []
    for row in records:
        ex = _parse_date(row.get("exDate"))
        if ex is None or ex < cutoff:
            continue
        rec = _parse_date(row.get("recDate") or row.get("recordDate"))
        out.append({"subject": (row.get("subject") or "").strip(), "ex_date": ex.isoformat(),
                    "record_date": rec.isoformat() if rec else None, "upcoming": ex >= as_of})
    out.sort(key=lambda x: x["ex_date"], reverse=True)
    return out[:limit]


def values(records: list[dict], as_of: date | None = None) -> dict:
    """dividend_yield needs the price separately (library.py combines it); this returns the trailing
    12-month per-share dividend total and the buyback flag, both from the ex-date window only."""
    out = {}
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=365)
    div_total = 0.0
    div_seen = False
    buyback = False
    for row in records:
        subject = row.get("subject") or ""
        ex = _parse_date(row.get("exDate"))
        if ex is None or ex < cutoff or ex > as_of:
            continue
        if re.search(r"buy\s*back", subject, re.I):
            buyback = True
        if re.search(r"dividend", subject, re.I):
            m = _DIV_RE.search(subject)
            if m:
                div_total += float(m.group(1))
                div_seen = True
    if div_seen:
        out["dividend_per_share_ttm"] = div_total
    out["buyback_flag"] = buyback
    return out


BULK_API = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={a}&to_date={b}"
_SPLIT_RE = re.compile(r"From\s+R[se]\.?\s*([\d.]+).*?To\s+R[se]\.?\s*([\d.]+)", re.I)
_BONUS_RE = re.compile(r"^\s*Bonus\s+(\d+)\s*:\s*(\d+)", re.I)


def fetch_bulk(s, start: date, end: date) -> dict:
    """Every company's corporate actions with an ex-date in [start, end], in ONE request, grouped by
    symbol: {symbol: [record]}. Records have the same shape as fetch()'s, so recent_and_upcoming()
    and values() take them unchanged. Replaces one fetch() per company per batch (10 Oct 2026)."""
    r = s.get(BULK_API.format(a=start.strftime("%d-%m-%Y"), b=end.strftime("%d-%m-%Y")),
              headers={**_headers(), "Accept": "application/json"}, timeout=90)
    r.raise_for_status()
    body = r.json()
    out = {}
    for row in body if isinstance(body, list) else []:
        sym = (row.get("symbol") or "").strip()
        if sym:
            out.setdefault(sym, []).append(row)
    return out


def price_factors(records: list[dict]) -> list[tuple[date, float]]:
    """(ex_date, factor) for each face-value split/consolidation and bonus: earlier prices times the
    factor are comparable with prices from the ex-date on. Split "From Rs 10/- To Re 1/-" -> 0.1;
    "Bonus 1:1" -> 0.5. Rights issues and preference-share bonuses ("Scheme Of Arrangement - Bonus
    NCRPS") are left out: they do not change the equity share count the way these do."""
    out = []
    for row in records:
        ex = _parse_date(row.get("exDate"))
        subj = row.get("subject") or ""
        if ex is None:
            continue
        fac = None
        m = _SPLIT_RE.search(subj)
        if m and re.search(r"split|sub-?division|consolidat", subj, re.I):
            a, b = float(m.group(1)), float(m.group(2))
            if a > 0 and b > 0:
                fac = b / a
        else:
            m = _BONUS_RE.match(subj)
            if m:
                new, held = int(m.group(1)), int(m.group(2))
                if new > 0 and held > 0:
                    fac = held / (new + held)
        if fac and fac != 1:
            out.append((ex, fac))
    return out
