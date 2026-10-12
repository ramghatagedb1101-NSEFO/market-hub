"""
A second source for the results figures (11 Oct 2026): each company's own quarterly filing at NSE, in
its machine-readable form (the XBRL attached to SEBI's integrated filing), read for free.

BharatStock is the library's only paid source and has shown real errors (OFSS +68.7% revenue growth on
10 Oct). verify() rebuilds the latest quarter's year-on-year revenue, profit and EPS growth from the
company's own filings -- the latest quarter and the same quarter a year earlier, consolidated when the
company files consolidated results -- and compares them with the growth the library computed from
BharatStock. A disagreement is recorded, the NSE figures are used instead (they are the company's own
numbers), and the company is flagged so nothing is ranked on the doubtful figure.

Confirmed on Titan's Q1 FY27 filing: revenue from operations Rs 18,101 cr, profit Rs 1,699 cr, EPS 19.15.
Banks, NBFCs and insurers file profit under their own names (handled); "revenue" means different things
for lenders, so for them only profit growth is compared. When neither fact can be read the check says
"unavailable", never "mismatch".
"""
import re
from datetime import date, datetime

import requests

from . import shareholding as shp

LIST = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={sym}"
        "&period_ended=all&type=Integrated%20Filing-%20Financials&page=1&size=30")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
# Small companies often file total "Income" only; it is read when revenue from operations is not filed.
REVENUE = ("RevenueFromOperations", "TotalRevenueFromOperations", "Income")
# Companies, then banks (Schedule III for banks), then insurers -- each files profit under its own name.
PROFIT = ("ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForThePeriod",
          "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
          "ProfitLossAfterTaxAndExtraordinaryItems", "ProfitLoss")
EPS = ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations")
# How far apart the two sources may be before it counts as a disagreement (percentage points of growth).
TOL_REV, TOL_PROFIT = 5.0, 10.0
TOL_MARGIN = 2.0         # net-margin points, for the level check
VERIFY_VERSION = 4       # 12 Oct 2026: level check, NSE-only figures, BSE fallback (standalone basis); non-matches re-checked once


def _day(s):
    try:
        return datetime.strptime(str(s).strip()[:11], "%d-%b-%Y").date()
    except (TypeError, ValueError):
        return None


def filings(s, sym: str) -> list[dict]:
    r = s.get(LIST.format(sym=sym), headers={**shp.HEADERS, "Accept": "application/json"}, timeout=60)
    r.raise_for_status()
    body = r.json()
    out = []
    for row in (body.get("data") if isinstance(body, dict) else body) or []:
        q = _day(row.get("qe_Date"))
        if q and row.get("xbrl", "").endswith(".xml"):
            out.append({"quarter": q, "nature": (row.get("consolidated") or "").lower(), "xbrl": row["xbrl"],
                        "revised": (row.get("type_Sub") or "").lower() != "original",
                        "broadcast": row.get("broadcast_Date") or ""})
    return out


def _fact(text: str, names, ctx: str):
    for n in names:
        m = re.search(r'<in-capmkt:' + n + r'\b[^>]*contextRef="' + re.escape(ctx) + r'"[^>]*>([^<]*)<', text)
        if m and m.group(1).strip() not in ("", "NA"):
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def facts(url: str) -> dict:
    t = requests.get(url, headers=UA, timeout=60).text
    m = re.search(r'<in-capmkt:DateOfEndOfReportingPeriod\b[^>]*contextRef="([^"]+)"[^>]*>([^<]*)<', t)
    if not m:
        return {}
    ctx = m.group(1)
    return {"period": m.group(2).strip()[:10], "revenue": _fact(t, REVENUE, ctx), "profit": _fact(t, PROFIT, ctx),
            "eps": _fact(t, EPS, ctx),
            "paid_up": _fact(t, ("PaidUpValueOfEquityShareCapital",), ctx),
            "face": _fact(t, ("FaceValueOfEquityShareCapital",), ctx)}


def _growth(a, b):
    return None if a is None or b is None or b <= 0 else (a / b - 1) * 100


def _pick(rows, quarter: date, nature: str):
    same = [r for r in rows if r["quarter"] == quarter and r["nature"] == nature]
    return sorted(same, key=lambda r: r["broadcast"])[-1] if same else None


def verify(s, sym: str, bs: dict) -> dict:
    """bs: the library's figures from BharatStock (rev_yoy, profit_yoy, eps_yoy, net_margin, _latest_period).
    Returns {"status": ok | mismatch | period_differs | nse_only | unavailable, "method": growth | margin, ...}.

    12 Oct 2026: a quarter's XBRL carries only that quarter and the year to date, so growth needs the
    year-ago filing, which many companies do not have in the integrated format. Without it -- or when
    growth means nothing (a loss or zero a year ago) -- the quarter itself is checked: net margin from the
    filing against BharatStock's. With no BharatStock results at all, the filing's figures are the
    company's figures ("nse_only")."""
    rows = filings(s, sym)
    if not rows:
        return verify_bse(sym, bs)
    latest = max(r["quarter"] for r in rows)
    nature = "consolidated" if any(r["quarter"] == latest and r["nature"] == "consolidated" for r in rows) else "standalone"
    cur = _pick(rows, latest, nature)
    ago_q = min((r["quarter"] for r in rows if r["nature"] == nature and abs((latest - r["quarter"]).days - 365) <= 20), default=None,
                key=lambda q: abs((latest - q).days - 365))
    f1 = facts(cur["xbrl"])
    f0 = facts(_pick(rows, ago_q, nature)["xbrl"]) if ago_q else {}
    out = {"period": latest.isoformat(), "basis": nature, "nse": {"rev": f1.get("revenue"), "profit": f1.get("profit"), "eps": f1.get("eps"),
           "rev_year_ago": f0.get("revenue"), "profit_year_ago": f0.get("profit"), "eps_year_ago": f0.get("eps"),
           "shares": (f1["paid_up"] / f1["face"]) if f1.get("paid_up") and f1.get("face") else None},
           "nse_rev_yoy": _growth(f1.get("revenue"), f0.get("revenue")), "nse_profit_yoy": _growth(f1.get("profit"), f0.get("profit")),
           "nse_eps_yoy": _growth(f1.get("eps"), f0.get("eps")),
           "bs_rev_yoy": bs.get("rev_yoy"), "bs_profit_yoy": bs.get("profit_yoy"), "bs_period": str(bs.get("_latest_period") or "")[:10]}
    rev, profit = f1.get("revenue"), f1.get("profit")
    out["nse_margin"] = profit / rev * 100 if rev and rev > 0 and profit is not None else None
    out["bs_margin"] = bs.get("net_margin")
    if rev is None and profit is None:
        out.update(status="unavailable", why="the filing's revenue and profit could not be read")
        return out
    if not out["bs_period"]:
        out.update(status="nse_only", method="nse", why="BharatStock has no results for this company; figures from its NSE filing")
        return out
    if out["bs_period"] != out["period"]:
        out.update(status="period_differs", why=f"BharatStock's latest quarter is {out['bs_period']}, NSE's is {out['period']}")
        return out
    growth_ok = (out["nse_rev_yoy"] is not None and out["bs_rev_yoy"] is not None) or \
                (out["nse_profit_yoy"] is not None and out["bs_profit_yoy"] is not None)
    if not growth_ok:
        # the level check: this quarter's net margin from both sources
        if out["nse_margin"] is None or out["bs_margin"] is None:
            out.update(status="unavailable", why=("the company had no revenue this quarter" if not rev else
                                                  "no year-ago filing at NSE and no margin to compare"))
            return out
        gap = out["nse_margin"] - out["bs_margin"]
        out.update(method="margin", diffs=[] if abs(gap) <= TOL_MARGIN else
                   [f"net margin {out['bs_margin']:.1f}% (BharatStock) vs {out['nse_margin']:.1f}% (NSE filing)"])
        out["status"] = "mismatch" if out["diffs"] else "ok"
        return out
    out["method"] = "growth"
    diffs = []
    if out["nse_rev_yoy"] is not None and out["bs_rev_yoy"] is not None and abs(out["nse_rev_yoy"] - out["bs_rev_yoy"]) > TOL_REV:
        diffs.append(f"revenue growth {out['bs_rev_yoy']:+.1f}% (BharatStock) vs {out['nse_rev_yoy']:+.1f}% (NSE filing)")
    if out["nse_profit_yoy"] is not None and out["bs_profit_yoy"] is not None and abs(out["nse_profit_yoy"] - out["bs_profit_yoy"]) > TOL_PROFIT:
        diffs.append(f"profit growth {out['bs_profit_yoy']:+.1f}% (BharatStock) vs {out['nse_profit_yoy']:+.1f}% (NSE filing)")
    out.update(status="mismatch" if diffs else "ok", diffs=diffs)
    return out


def verify_bse(sym: str, bs: dict) -> dict:
    """Companies with no results XBRL at NSE (12 Oct 2026): the latest quarter from BSE's results snapshot
    (hub/bse.py). BSE gives no year-ago quarter, so this is the level check -- net margin -- or, without
    BharatStock results, the company's figures ("bse_only"). Fields named nse_* hold the exchange's figures
    whichever exchange supplied them; "source" says which."""
    from . import bse
    try:
        b = bse.results(sym)
    except Exception as exc:
        return {"status": "unavailable", "why": f"no results XBRL at NSE, and BSE could not be read ({str(exc)[:80]})"}
    if not b:
        return {"status": "unavailable", "why": "no results at NSE or BSE"}
    rev, profit = b.get("revenue_cr"), b.get("profit_cr")
    margin = b.get("npm") if b.get("npm") is not None else (profit / rev * 100 if rev and rev > 0 and profit is not None else None)
    out = {"source": "bse", "period": b["period"], "basis": "as reported to BSE",
           "nse": {"rev": rev * 1e7 if rev is not None else None, "profit": profit * 1e7 if profit is not None else None, "eps": b.get("eps")},
           "nse_margin": margin, "bs_margin": bs.get("net_margin"), "bs_period": str(bs.get("_latest_period") or "")[:10],
           "nse_rev_yoy": None, "nse_profit_yoy": None, "nse_eps_yoy": None}
    if not out["bs_period"]:
        out.update(status="bse_only", method="bse", why="BharatStock has no results for this company; figures from its BSE results")
        return out
    if out["bs_period"] != out["period"]:
        out.update(status="period_differs", why=f"BharatStock's latest quarter is {out['bs_period']}, BSE's is {out['period']}")
        return out
    if margin is None or out["bs_margin"] is None:
        out.update(status="unavailable", why="the company had no revenue this quarter" if not rev else "no margin to compare")
        return out
    gap = margin - out["bs_margin"]
    out["method"] = "margin"
    if abs(gap) <= TOL_MARGIN:
        out.update(status="ok", diffs=[])
        return out
    # BSE's snapshot is standalone; BharatStock uses consolidated results whenever a company files them
    # (Titan: Rs 18,101 cr standalone at BSE vs Rs 21,356 cr consolidated). A gap is a disagreement only
    # when both are standalone; otherwise the two figures measure different things (12 Oct 2026: 88
    # "disagreements" on the first BSE run, median gap 11 points, in both directions).
    if bs.get("_basis") == "standalone":
        out.update(status="mismatch", diffs=[f"net margin {out['bs_margin']:.1f}% (BharatStock) vs {margin:.1f}% (BSE results)"])
    else:
        out.update(status="basis_differs", diffs=[],
                   why=f"BSE shows standalone results (net margin {margin:.1f}%); BharatStock's {out['bs_margin']:.1f}% "
                       f"is {'consolidated' if bs.get('_basis') else 'probably consolidated'}, so they are not comparable")
    return out
