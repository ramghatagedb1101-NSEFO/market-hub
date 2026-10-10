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
REVENUE = ("RevenueFromOperations", "TotalRevenueFromOperations")
# Companies, then banks (Schedule III for banks), then insurers -- each files profit under its own name.
PROFIT = ("ProfitLossForPeriod", "ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForThePeriod",
          "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
          "ProfitLossAfterTaxAndExtraordinaryItems", "ProfitLoss")
EPS = ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsLossPerShareFromContinuingOperations")
# How far apart the two sources may be before it counts as a disagreement (percentage points of growth).
TOL_REV, TOL_PROFIT = 5.0, 10.0


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
    """bs: the library's figures from BharatStock (rev_yoy, profit_yoy, eps_yoy, _latest_period).
    Returns {"status": ok | mismatch | period_differs | unavailable, ...}."""
    rows = filings(s, sym)
    if not rows:
        return {"status": "unavailable", "why": "no machine-readable results filing at NSE"}
    latest = max(r["quarter"] for r in rows)
    nature = "consolidated" if any(r["quarter"] == latest and r["nature"] == "consolidated" for r in rows) else "standalone"
    cur = _pick(rows, latest, nature)
    ago_q = min((r["quarter"] for r in rows if r["nature"] == nature and abs((latest - r["quarter"]).days - 365) <= 20), default=None,
                key=lambda q: abs((latest - q).days - 365))
    if not ago_q:
        return {"status": "unavailable", "why": "no filing for the same quarter a year earlier", "period": latest.isoformat()}
    f1, f0 = facts(cur["xbrl"]), facts(_pick(rows, ago_q, nature)["xbrl"])
    out = {"period": latest.isoformat(), "basis": nature, "nse": {"rev": f1.get("revenue"), "profit": f1.get("profit"), "eps": f1.get("eps"),
           "rev_year_ago": f0.get("revenue"), "profit_year_ago": f0.get("profit"), "eps_year_ago": f0.get("eps"),
           "shares": (f1["paid_up"] / f1["face"]) if f1.get("paid_up") and f1.get("face") else None},
           "nse_rev_yoy": _growth(f1.get("revenue"), f0.get("revenue")), "nse_profit_yoy": _growth(f1.get("profit"), f0.get("profit")),
           "nse_eps_yoy": _growth(f1.get("eps"), f0.get("eps")),
           "bs_rev_yoy": bs.get("rev_yoy"), "bs_profit_yoy": bs.get("profit_yoy"), "bs_period": str(bs.get("_latest_period") or "")[:10]}
    if out["nse_rev_yoy"] is None and out["nse_profit_yoy"] is None:
        out.update(status="unavailable", why="the filing's revenue and profit facts could not be read (bank or insurer format?)")
        return out
    if out["bs_period"] and out["bs_period"] != out["period"]:
        out.update(status="period_differs", why=f"BharatStock's latest quarter is {out['bs_period']}, NSE's is {out['period']}")
        return out
    diffs = []
    if out["nse_rev_yoy"] is not None and out["bs_rev_yoy"] is not None and abs(out["nse_rev_yoy"] - out["bs_rev_yoy"]) > TOL_REV:
        diffs.append(f"revenue growth {out['bs_rev_yoy']:+.1f}% (BharatStock) vs {out['nse_rev_yoy']:+.1f}% (NSE filing)")
    if out["nse_profit_yoy"] is not None and out["bs_profit_yoy"] is not None and abs(out["nse_profit_yoy"] - out["bs_profit_yoy"]) > TOL_PROFIT:
        diffs.append(f"profit growth {out['bs_profit_yoy']:+.1f}% (BharatStock) vs {out['nse_profit_yoy']:+.1f}% (NSE filing)")
    out.update(status="mismatch" if diffs else "ok", diffs=diffs)
    return out
