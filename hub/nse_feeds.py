"""
Market-wide NSE filing lists (free, no key), one request per date window instead of one per company.
They tell the stock library WHICH companies have filed something new, so it fetches only those
(10 Oct 2026 -- before this every company was re-read every batch whether or not anything changed).

  results_filed()      quarterly/annual results, from SEBI's integrated filing (financials) list
  shareholding_filed() shareholding patterns

Both return {symbol: latest quarter-end date filed in the window}. Reached with the same Akamai
session as hub.shareholding (homepage GET first). Confirmed from a laptop on 10 Oct 2026; the
library falls back to its age-based refresh rules if either list cannot be read from GitHub Actions.
"""
from datetime import date, datetime, timedelta

from . import shareholding as shp

RESULTS = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&from_date={a}&to_date={b}"
           "&period_ended=all&type=Integrated%20Filing-%20Financials&page={p}&size=100")
SHP_LIST = "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&from_date={a}&to_date={b}"
CHUNK_DAYS = 14        # windows small enough that no list is ever cut short
MAX_PAGES = 60


def _day(s):
    try:
        return datetime.strptime(str(s).strip()[:11], "%d-%b-%Y").date()
    except (TypeError, ValueError):
        return None


def _get(s, url):
    r = s.get(url, headers={**shp.HEADERS, "Accept": "application/json"}, timeout=90)
    r.raise_for_status()
    return r.json()


def _windows(start: date, end: date):
    a = start
    while a <= end:
        b = min(end, a + timedelta(days=CHUNK_DAYS - 1))
        yield a.strftime("%d-%m-%Y"), b.strftime("%d-%m-%Y")
        a = b + timedelta(days=1)


def _keep_latest(out: dict, sym: str, q: date | None):
    if sym and q and (sym not in out or q > out[sym]):
        out[sym] = q


def results_filed(s, start: date, end: date) -> dict:
    out = {}
    for a, b in _windows(start, end):
        seen, total = 0, None
        for p in range(1, MAX_PAGES + 1):
            body = _get(s, RESULTS.format(a=a, b=b, p=p))
            rows = body.get("data") or [] if isinstance(body, dict) else []
            total = body.get("totalCount") if isinstance(body, dict) else 0
            for row in rows:
                _keep_latest(out, (row.get("symbol") or "").strip(), _day(row.get("qe_Date")))
            seen += len(rows)
            if not rows or (total is not None and seen >= total):
                break
    return out


def shareholding_filed(s, start: date, end: date) -> dict:
    out = {}
    for a, b in _windows(start, end):
        body = _get(s, SHP_LIST.format(a=a, b=b))
        for row in body if isinstance(body, list) else []:
            q = _day(row.get("date"))
            if q and (q.month, q.day) in shp.QUARTER_ENDS:     # event filings mid-quarter are not a new quarter
                _keep_latest(out, (row.get("symbol") or "").strip(), q)
    return out
