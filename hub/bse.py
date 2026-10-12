"""
BSE as a third results source (12 Oct 2026), for companies that file no machine-readable results at NSE
(about 280, e.g. Abbott India). Free and public, like NSE.

BSE's firewall refuses ordinary programs (plain requests and curl get "Access Denied", from GitHub's
servers and from home alike) but answers a connection that looks like Chrome, so this uses curl_cffi's
browser impersonation. Two calls:
  ListofScripData   every active BSE equity with its ISIN, matched to NSE symbols through NSE's own
                    equity list (one request a run, only when a company needs BSE)
  TabResults_PAR    a company's results snapshot: latest quarter, previous quarter and the last full
                    year -- revenue, net profit, EPS, operating and net margin (Rs crore)
The snapshot has no year-ago quarter, so BSE supports the level check (net margin) and supplies figures
where BharatStock has none; it cannot rebuild year-on-year growth.
"""
import csv
import io
from datetime import date

from curl_cffi import requests as cr

API = "https://api.bseindia.com/BseIndiaAPI/api"
H = {"Accept": "application/json, text/plain, */*", "Origin": "https://www.bseindia.com", "Referer": "https://www.bseindia.com/"}
NSE_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
MON = {m: i + 1 for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_codes = None


def _get(url, **kw):
    return cr.get(url, headers=H, impersonate="chrome", timeout=60, **kw)


def codes() -> dict:
    """{NSE symbol: BSE scrip code}, built once per run."""
    global _codes
    if _codes is None:
        nse = cr.get(NSE_LIST, impersonate="chrome", timeout=60).text
        rows = list(csv.reader(io.StringIO(nse)))
        head = [h.strip().upper() for h in rows[0]]
        i_sym, i_isin = head.index("SYMBOL"), head.index("ISIN NUMBER")
        isin = {r[i_isin].strip(): r[i_sym].strip() for r in rows[1:] if len(r) > i_isin}
        bse = _get(f"{API}/ListofScripData/w", params={"scripcode": "", "Group": "", "industry": "", "segment": "Equity", "status": "Active"}).json()
        _codes = {isin[x["ISIN_NUMBER"].strip()]: str(x["SCRIP_CD"]) for x in bse
                  if x.get("ISIN_NUMBER") and x["ISIN_NUMBER"].strip() in isin}
    return _codes


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _quarter_end(label: str):
    """'Jun-26' -> 2026-06-30."""
    try:
        m, y = label.split("-")
        y, mo = 2000 + int(y), MON[m[:3]]
        nxt = date(y + (mo == 12), mo % 12 + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)
    except (ValueError, KeyError, AttributeError):
        return None


def results(sym: str) -> dict | None:
    """The latest quarter from BSE's results snapshot, or None when BSE has no code or no results."""
    code = codes().get(sym)
    if not code:
        return None
    r = _get(f"{API}/TabResults_PAR/w", params={"scripcode": code, "tabtype": "RESULTS"})
    if r.status_code != 200 or not r.text.strip():
        return None
    body = r.json()
    if isinstance(body, str):            # BSE returns the JSON as a JSON string
        import json
        body = json.loads(body)
    rows = {x.get("title"): x for x in body.get("resultinCr") or []}
    q = _quarter_end(body.get("col2") or "")
    if not q or "Revenue" not in rows:
        return None
    pick = lambda t, k: _num((rows.get(t) or {}).get(k))
    return {"code": code, "period": q.isoformat(), "revenue_cr": pick("Revenue", "v1"), "profit_cr": pick("Net Profit", "v1"),
            "eps": pick("EPS", "v1"), "npm": pick("NPM %", "v1"), "opm": pick("OPM %", "v1"),
            "prev_period": (_quarter_end(body.get("col3") or "") or date.min).isoformat(),
            "prev_revenue_cr": pick("Revenue", "v2"), "prev_profit_cr": pick("Net Profit", "v2")}
