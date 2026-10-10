"""
Company documents from NSE (free, no key): annual reports, earnings-call transcripts, investor
presentations and call recordings -- links to NSE's own PDFs, never the PDFs themselves (11 Oct 2026).

  fetch_company(s, sym)   one company: its last ~13 months of announcements plus its annual reports.
                          Used once per company to fill in, then only as a safety refresh.
  new_filings(s, a, b)    the whole market's announcements for a date window in one request, so new
                          transcripts and presentations are picked up daily without asking per company.

Classification is by NSE's own subject line ("Investor Presentation") and attachment text
("...informed the Exchange about Earnings Call Transcripts"). Confirmed 10 Oct 2026 on Titan: Q1
transcript (11 Aug), presentation (7 Aug), recording link (7 Aug), FY2026 annual report (3 Jul).
"""
from datetime import date, datetime, timedelta

from . import shareholding as shp

ANN_SYM = "https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={sym}&from_date={a}&to_date={b}"
ANN_ALL = "https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={a}&to_date={b}"
ANNUAL = "https://www.nseindia.com/api/annual-reports?index=equities&symbol={sym}"
KEEP = {"ar": 5, "tr": 4, "pr": 4, "rec": 2}     # how many of each kind to keep per company
LOOKBACK_DAYS = 400
CHUNK_DAYS = 7                                     # ~3,000 filings per week of the whole market


def _get(s, url):
    r = s.get(url, headers={**shp.HEADERS, "Accept": "application/json"}, timeout=90)
    r.raise_for_status()
    return r.json()


def _when(row) -> str | None:
    for k in ("an_dt", "sort_date", "exchdisstime"):
        v = row.get(k)
        if v:
            for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(str(v).strip()[:20], fmt).date().isoformat()
                except ValueError:
                    pass
    return None


def classify(row) -> str | None:
    """'tr' transcript, 'rec' call recording, 'pr' investor presentation, or None."""
    desc = (row.get("desc") or "").lower()
    text = (row.get("attchmntText") or "").lower()
    if not row.get("attchmntFile"):
        return None
    if "transcript" in text or "transcript" in desc:
        return "tr"
    if desc == "investor presentation" or "investor presentation" in text or "earnings presentation" in text:
        return "pr"
    if "recording" in text and ("call" in text or "meet" in text or "analyst" in text or "audio" in text):
        return "rec"
    return None


def _item(row) -> dict:
    return {"date": _when(row), "url": row.get("attchmntFile"),
            "title": (row.get("attchmntText") or row.get("desc") or "").strip()[:160]}


def merge(docs: dict, kind: str, items: list[dict]) -> bool:
    """Adds items to docs[kind] (newest first, de-duplicated by URL, capped). True if anything new."""
    have = docs.setdefault(kind, [])
    urls = {x["url"] for x in have}
    added = [x for x in items if x.get("url") and x["url"] not in urls]
    if not added:
        return False
    have.extend(added)
    have.sort(key=lambda x: x.get("date") or "", reverse=True)
    del have[KEEP[kind]:]
    return True


def annual_reports(s, sym: str) -> list[dict]:
    body = _get(s, ANNUAL.format(sym=sym))
    rows = body.get("data") if isinstance(body, dict) else body
    out = []
    for r in rows or []:
        if not r.get("fileName"):
            continue
        fy = f"{r.get('fromYr')}-{str(r.get('toYr') or '')[-2:]}" if r.get("fromYr") else None
        when = None
        try:
            when = datetime.strptime(str(r.get("broadcast_dttm") or "")[:11], "%d-%b-%Y").date().isoformat()
        except ValueError:
            pass
        out.append({"date": when, "url": r["fileName"], "fy": fy, "size": r.get("attFileSize")})
    return out


def fetch_company(s, sym: str, today: date) -> dict:
    """{'ar': [...], 'tr': [...], 'pr': [...], 'rec': [...]} for one company."""
    docs = {}
    a = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%m-%Y")
    rows = _get(s, ANN_SYM.format(sym=sym, a=a, b=today.strftime("%d-%m-%Y")))
    by_kind = {}
    for row in rows if isinstance(rows, list) else []:
        k = classify(row)
        if k:
            by_kind.setdefault(k, []).append(_item(row))
    for k, items in by_kind.items():
        merge(docs, k, items)
    merge(docs, "ar", annual_reports(s, sym))
    return docs


def new_filings(s, start: date, end: date) -> dict:
    """{symbol: {kind: [items]}} for transcripts, presentations and recordings filed in [start, end]."""
    out = {}
    a = start
    while a <= end:
        b = min(end, a + timedelta(days=CHUNK_DAYS - 1))
        rows = _get(s, ANN_ALL.format(a=a.strftime("%d-%m-%Y"), b=b.strftime("%d-%m-%Y")))
        for row in rows if isinstance(rows, list) else []:
            k = classify(row)
            sym = (row.get("symbol") or "").strip()
            if k and sym:
                out.setdefault(sym, {}).setdefault(k, []).append(_item(row))
        a = b + timedelta(days=1)
    return out


def annual_report_due(docs: dict, last_ar_check: str | None, today: date) -> bool:
    """Annual reports come out once a year, mostly June-September for a March year-end. Ask again only
    when the latest one on file is for an older financial year than the one just ended and the last
    check was over a month ago."""
    fy_end = today.year if today.month >= 7 else today.year - 1     # the year whose March report is due
    latest = (docs.get("ar") or [{}])[0]
    have = int(str(latest.get("fy") or "0-0").split("-")[0] or 0) + 1 if latest.get("fy") else 0
    if have >= fy_end:
        return False
    try:
        return (today - date.fromisoformat(last_ar_check)).days >= 30
    except (TypeError, ValueError):
        return True
