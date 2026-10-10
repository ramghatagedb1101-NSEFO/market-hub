"""
Promoter shareholding, from NSE's own corporate-filings JSON API (free, no key). Confirmed reachable
from GitHub Actions on 2026-10-07 (hub/diag_nse_shp.py) -- unlike some other www.nseindia.com
endpoints, this one did not need cookie/session tricks beyond a plain homepage GET first.

NSE returns every submission for a company, including revised/duplicate filings for the same
quarter, so records are grouped by `date` (the quarter end) and only the latest-broadcast one per
quarter is kept before computing quarter-over-quarter and year-over-year change.
"""
import re
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


QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}


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
        # Quarter-end filings only. NSE also lists event filings (after an allotment, say) dated mid-
        # quarter -- 17 Aug, 4 Sep -- and comparing one of those with the previous filing was being
        # reported as a "quarter-on-quarter" change (found 10 Oct 2026: GATECH, MICEL, DAVANGERE).
        if (d.month, d.day) not in QUARTER_ENDS:
            continue
        prev = by_quarter.get(d)
        if prev is None or (row.get("broadcastDate") or "") > (prev.get("broadcastDate") or ""):
            by_quarter[d] = row
    out = [{"date": d, "promoter_pct": float(v["pr_and_prgrp"]), "public_pct": float(v["public_val"]),
            "xbrl": v.get("xbrl")}
           for d, v in by_quarter.items() if v.get("public_val") not in (None, "")]
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def _xbrl_fact(text: str, tag: str, context: str) -> str | None:
    m = re.search(r'<in-bse-shp:' + tag + r'[^>]*contextRef="' + context + r'"[^>]*>([^<]*)</in-bse-shp:' + tag + r'>', text)
    return m.group(1).strip() if m else None


def fetch_xbrl_text(xbrl_url: str) -> str:
    """The raw filing, fetched once and shared by every reader of it (institutional facts, named
    holders) so a filing already downloaded for one is never downloaded again for the other."""
    r = requests.get(xbrl_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def institutional_from_text(text: str) -> dict:
    """FII %, DII % and promoter pledge %, from the detailed XBRL shareholding filing -- the summary
    JSON used for promoter_holding/public_float does not carry these. Percentages in the XBRL are
    decimal fractions (0.172 = 17.2%). Confirmed field names against real filings on 2026-10-07:
    Reliance (no pledge) and a company with an active pledge, both parsed correctly.

    Pledge is reported only when it exists: SEBI filings omit the percentage fact entirely for a
    company with no pledge, rather than stating an explicit 0. The boolean
    "...EncumberedUnderPledgedForPromoterAndPromoterGroup" flag disambiguates a genuine zero from a
    fact that is simply missing, so pledge_pct is 0.0 (not "not testable") when that flag says false."""
    out = {}
    tag = "ShareholdingAsAPercentageOfTotalNumberOfShares"

    def pct(context):
        v = _xbrl_fact(text, tag, context)
        return None if v in (None, "") else float(v) * 100

    # FII means foreign portfolio investors: FPI Category I + II. The filing's "Institutions (Foreign)"
    # total also holds foreign direct investment, overseas depositories (ADR/GDR shares) and foreign
    # VC funds -- strategic or custodial holdings that companies move in and out of that heading
    # between quarters. Using the total produced false 15-30 point "FII" jumps (found 10 Oct 2026:
    # ICICI Bank's ADR depository counted one quarter and not the previous; CleanMax and PPL Pharma's
    # strategic foreign stakes reclassified from FDI to "foreign companies").
    fpi = [pct("InstitutionsForeignPortfolioInvestorCategoryOne_ContextI"),
           pct("InstitutionsForeignPortfolioInvestorCategoryTwo_ContextI")]
    if any(x is not None for x in fpi):
        out["fii_holding"] = sum(x for x in fpi if x is not None)
    else:
        # Older filings without the FPI split: the total less the non-portfolio parts it carries.
        total = pct("InstitutionsForeign_ContextI")
        if total is not None:
            parts = [pct(c) for c in ("ForeignDirectInvestment_ContextI", "OverseasDepositories_ContextI",
                                      "ForeignVentureCapitalInvestors_ContextI")]
            out["fii_holding"] = max(0.0, total - sum(x for x in parts if x is not None))
    dii = pct("InstitutionsDomestic_ContextI")
    if dii is not None:
        out["dii_holding"] = dii
    pledged_flag = _xbrl_fact(text, "WhetherAnySharesHeldByPromotersAreEncumberedUnderPledgedForPromoterAndPromoterGroup", "MainI")
    if pledged_flag is not None:
        if pledged_flag.lower() == "false":
            out["pledge_pct"] = 0.0
        else:
            pledge = _xbrl_fact(text, "EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares",
                                 "ShareholdingOfPromoterAndPromoterGroup_ContextI")
            if pledge not in (None, ""):
                out["pledge_pct"] = float(pledge) * 100
    return out


def fetch_institutional(xbrl_url: str) -> dict:
    """Convenience wrapper: fetches the filing and reads the institutional facts from it. Prefer
    fetch_xbrl_text() + institutional_from_text() when the same filing is also read for named
    holders, so it is downloaded only once."""
    if not xbrl_url:
        return {}
    return institutional_from_text(fetch_xbrl_text(xbrl_url))


def _nearest(records: list[dict], target: date, tolerance_days: int = 46) -> dict | None:
    """The record closest to `target`, within about a quarter and a half either way -- quarterly
    filings drift (not every company reports on the same day), so an exact date match is too strict."""
    best, best_diff = None, timedelta(days=tolerance_days)
    for rec in records:
        diff = abs(rec["date"] - target)
        if diff < best_diff:
            best, best_diff = rec, diff
    return best


def values(records: list[dict]) -> dict:
    out = {}
    if not records:
        return out
    latest = records[0]
    out["promoter_holding"] = latest["promoter_pct"]
    out["public_float"] = latest["public_pct"]
    out["_promoter_period"] = latest["date"].isoformat()
    if len(records) > 1:
        out["promoter_change_qoq"] = latest["promoter_pct"] - records[1]["promoter_pct"]
    yoy = _nearest(records[1:], latest["date"] - timedelta(days=365))
    if yoy is not None:
        out["promoter_change_yoy"] = latest["promoter_pct"] - yoy["promoter_pct"]
    q3 = _nearest(records[1:], latest["date"] - timedelta(days=273))   # three quarters back
    if q3 is not None:
        out["promoter_holding_change_3q"] = latest["promoter_pct"] - q3["promoter_pct"]
    return out


def target_dates(records: list[dict]) -> dict:
    """The quarter-end date behind each institutional_targets() label, so the FII/DII figures read
    from those filings can be filed under the right quarter in holding_history()."""
    out = {}
    if not records:
        return out
    out["latest"] = records[0]["date"]
    if len(records) > 1:
        out["prior_quarter"] = records[1]["date"]
    yoy = _nearest(records[1:], records[0]["date"] - timedelta(days=365))
    if yoy is not None:
        out["year_ago"] = yoy["date"]
    return out


def holding_history(records: list[dict], inst_by_quarter: dict | None = None,
                    prior: list[dict] | None = None, limit: int = 12) -> list[dict]:
    """Quarterly shareholding for the admin stock report's trend chart, oldest first:
    [{quarter, promoter, public, fii, dii}]. Promoter and public % come for every quarter NSE lists
    (records); FII/DII % only for the quarters whose detailed filing was read this batch
    (inst_by_quarter, keyed by ISO quarter-end) -- so `prior` (this company's history from earlier
    batches) is merged in and FII/DII fill in over time instead of being re-fetched for every quarter.
    A newer value for the same quarter wins; a missing one never erases a stored one."""
    by_q = {}
    for row in prior or []:
        q = row.get("quarter")
        if q:
            by_q[q] = dict(row)
    for rec in records:
        q = rec["date"].isoformat()
        row = by_q.setdefault(q, {"quarter": q})
        row["promoter"] = round(rec["promoter_pct"], 2)
        row["public"] = round(rec["public_pct"], 2)
    for q, inst in (inst_by_quarter or {}).items():
        row = by_q.setdefault(q, {"quarter": q})
        for src, dst in (("fii_holding", "fii"), ("dii_holding", "dii")):
            if inst.get(src) is not None:
                row[dst] = round(inst[src], 2)
    rows = sorted(by_q.values(), key=lambda r: r["quarter"])
    return rows[-limit:]


def institutional_targets(records: list[dict]) -> dict:
    """Which filings to fetch XBRL for, to get FII/DII/pledge change as well as the latest level:
    the latest quarter (always), the previous quarter (for the QoQ change) and the filing closest to
    a year ago (for the YoY pledge change). Returns {label: xbrl_url}, skipping a label when no
    record is close enough or the record has no xbrl link."""
    out = {}
    if not records:
        return out
    latest = records[0]
    if latest.get("xbrl"):
        out["latest"] = latest["xbrl"]
    if len(records) > 1 and records[1].get("xbrl"):
        out["prior_quarter"] = records[1]["xbrl"]
    yoy = _nearest(records[1:], latest["date"] - timedelta(days=365))
    if yoy is not None and yoy.get("xbrl"):
        out["year_ago"] = yoy["xbrl"]
    return out
