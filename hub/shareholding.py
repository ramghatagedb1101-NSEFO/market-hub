"""
Promoter shareholding, from NSE's own corporate-filings JSON API (free, no key). Confirmed reachable
from GitHub Actions on 2026-10-07 (hub/diag_nse_shp.py) -- unlike some other www.nseindia.com
endpoints, this one did not need cookie/session tricks beyond a plain homepage GET first.

NSE returns every submission for a company, including revised/duplicate filings for the same
quarter, so records are grouped by `date` (the quarter end) and only the latest-broadcast one per
quarter is kept before computing quarter-over-quarter and year-over-year change.
"""
from datetime import date, datetime, timedelta

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern",
}
HOMEPAGE = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
API = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={sym}"


def session() -> requests.Session:
    """One session, reused for every company in a run: NSE's Akamai bot-check cookies are handed
    out on the homepage GET and are valid for many subsequent API calls."""
    s = requests.Session()
    s.get(HOMEPAGE, headers=HEADERS, timeout=20)
    return s


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%d-%b-%Y").date()
    except (TypeError, ValueError):
        return None


def fetch(s: requests.Session, symbol: str) -> list[dict]:
    """One record per quarter-end, newest first. Raises on a network error or non-200/404 so the
    caller can refresh the session and retry; a 404 (company not covered) returns an empty list."""
    r = s.get(API.format(sym=symbol), headers=HEADERS, timeout=20)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, list):
        return []
    by_quarter = {}
    for row in body:
        d = _parse_date(row.get("date"))
        pr = row.get("pr_and_prgrp")
        if d is None or pr in (None, ""):
            continue
        prev = by_quarter.get(d)
        if prev is None or (row.get("broadcastDate") or "") > (prev.get("broadcastDate") or ""):
            by_quarter[d] = row
    out = [{"date": d, "promoter_pct": float(v["pr_and_prgrp"]), "public_pct": float(v["public_val"])}
           for d, v in by_quarter.items() if v.get("public_val") not in (None, "")]
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def values(records: list[dict]) -> dict:
    out = {}
    if not records:
        return out
    latest = records[0]
    out["promoter_holding"] = latest["promoter_pct"]
    out["_promoter_period"] = latest["date"].isoformat()
    if len(records) > 1:
        out["promoter_change_qoq"] = latest["promoter_pct"] - records[1]["promoter_pct"]
    target = latest["date"] - timedelta(days=365)
    best, best_diff = None, timedelta(days=46)   # within about a quarter and a half either way
    for rec in records[1:]:
        diff = abs(rec["date"] - target)
        if diff < best_diff:
            best, best_diff = rec, diff
    if best is not None:
        out["promoter_change_yoy"] = latest["promoter_pct"] - best["promoter_pct"]
    return out
