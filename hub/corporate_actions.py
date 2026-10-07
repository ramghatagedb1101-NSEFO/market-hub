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
