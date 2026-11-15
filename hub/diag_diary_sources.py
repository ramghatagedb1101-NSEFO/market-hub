"""
Which free sources can fill the market diary back to 2023 (owner, 15 Nov 2026: "FII/DII flows, US market moves, gold,
crude and dollar changes, plus the morning news score can be added from 2023 onwards"). Probes each candidate and
prints what it returns for early 2023 and for last week: row counts, first / last dates, a sample. Nothing is saved.
Run on GitHub (NSE / NSDL block the owner's laptop): diag.yml -f module=diag_diary_sources
"""
import csv
import io
import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}


def show(name, fn):
    try:
        print(f"== {name}: {fn()}", flush=True)
    except Exception as e:                                       # noqa: BLE001
        print(f"== {name}: FAILED {type(e).__name__}: {str(e)[:200]}", flush=True)


def fred(series):
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2023-01-01", headers=UA, timeout=60)
    rows = [x for x in csv.reader(io.StringIO(r.text))][1:]
    rows = [x for x in rows if len(x) > 1 and x[1] not in (".", "")]
    return f"HTTP {r.status_code}, {len(rows)} rows, {rows[0] if rows else None} .. {rows[-1] if rows else None}"


def stooq(sym):
    r = requests.get(f"https://stooq.com/q/d/l/?s={sym}&i=d&d1=20230101", headers=UA, timeout=60)
    rows = list(csv.reader(io.StringIO(r.text)))
    return f"HTTP {r.status_code}, {len(rows) - 1} rows, head {rows[:2]}, last {rows[-1] if rows else None}"


def gdelt(start, end):
    q = "(nifty OR sensex OR \"indian stocks\" OR \"dalal street\")"
    r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", headers=UA, timeout=60,
                     params={"query": q, "mode": "artlist", "maxrecords": 75, "format": "json", "sort": "datedesc",
                             "startdatetime": start, "enddatetime": end})
    try:
        arts = r.json().get("articles") or []
    except ValueError:
        return f"HTTP {r.status_code}, not JSON: {r.text[:160]!r}"
    return f"HTTP {r.status_code}, {len(arts)} articles; e.g. " + " | ".join(f"{a.get('seendate')} {a.get('domain')}: {a.get('title', '')[:70]}" for a in arts[:4])


def nsdl():
    s = requests.Session()
    s.headers.update(UA)
    out = []
    for u in ("https://www.fpi.nsdl.co.in/web/Reports/ReportsListing.aspx", "https://www.fpi.nsdl.co.in/web/Reports/Latest.aspx",
              "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"):
        r = s.get(u, timeout=60)
        links = sorted(set(re.findall(r'href="([^"]*(?:Archive|Daily|Latest|Monthly)[^"]*)"', r.text, re.I)))[:12]
        tables = re.findall(r"<table.*?</table>", r.text, re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", tables[0]) if tables else ""
        out.append(f"{u.rsplit('/', 1)[1]} HTTP {r.status_code} len {len(r.text)} links {links} first table: {re.sub(r'\\s+', ' ', txt)[:300]!r}")
    return "\n   ".join(out)


def nse_fiidii():
    s = requests.Session()
    s.headers.update(UA)
    s.get("https://www.nseindia.com", timeout=30)
    out = []
    for u in ("https://www.nseindia.com/api/fiidiiTradeReact", "https://www.nseindia.com/api/fiidiiTradeNse",
              "https://nsearchives.nseindia.com/content/fo/fii_stats_02-Jan-2024.xls"):
        r = s.get(u, timeout=30)
        out.append(f"{u.rsplit('/', 1)[1]} HTTP {r.status_code} {r.headers.get('content-type')} {r.text[:200]!r}")
    return "\n   ".join(out)


def main() -> None:
    for sid in ("SP500", "NASDAQCOM", "DCOILWTICO", "DCOILBRENTEU", "DEXINUS"):
        show(f"FRED {sid}", lambda sid=sid: fred(sid))
    for sym in ("xauusd", "xauinr", "usdinr", "^spx"):
        show(f"stooq {sym}", lambda sym=sym: stooq(sym))
    show("GDELT 2023-03-01 before the open", lambda: gdelt("20230228100000", "20230301033000"))
    show("GDELT 2026-11-13 before the open", lambda: gdelt("20261112100000", "20261113033000"))
    show("NSDL FPI", nsdl)
    show("NSE FII/DII", nse_fiidii)


if __name__ == "__main__":
    main()
