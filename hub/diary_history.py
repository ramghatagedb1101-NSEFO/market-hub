"""
The market diary's figures from 2023 on (owner, 15 Nov 2026: "FII/DII flows, US market moves, gold, crude and dollar
changes, plus the morning news score can be added from 2023 onwards"), each from ONE source used for the history and
for every day after, so a strategy reads the same thing in a back-test and live:

  fii_cash     FPI net equity buying on the stock exchanges, rupees crore, NSDL's confirmed daily figure by reporting
               date (fpi.nsdl.co.in Archive: one request a month lists every reporting date); a reporting date carries
               the previous session's confirmed trades, published that evening -> a strategy sees it the session after.
  usdinr, usdinr_chg   NSDL's conversion rate for that reporting date, and its % change.
  sp500_chg, nasdaq_chg   FRED (SP500, NASDAQCOM), % change on the US session of that date (after India's close).

  gold_chg, crude_chg   MCX's official daily bhavcopy (mcxindia.com, futures only, one request a day): the most-held
               GOLD / CRUDEOIL futures contract that day (largest open interest) and ITS OWN close against its own previous
               close -- never across two contracts, so a contract roll cannot show as a move. MCX trades to 23:30: a
               strategy sees the change the next Indian morning.
Not here: DII flows (no official history; the diary keeps NSE's figure from 14 Nov 2026); no news (owner: official
data only).

state/market/diary_history.json (private) = {"YYYY-MM-DD": {...}}; hub/market_daily.py flows() merges it.
    python -m hub.diary_history        (FRED_API_KEY, PRIVATE_REPO_TOKEN; GitHub: diary-history.yml and the daily job)
"""
import html
import os
import re
import sys
import time
from datetime import date, datetime, timedelta

import requests

from . import config
from .expiry_history import load, save

PATH = "state/market/diary_history.json"
START = date(2023, 1, 1)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
NSDL = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
FRED = {"sp500_chg": "SP500", "nasdaq_chg": "NASDAQCOM"}


def _num(s: str) -> float | None:
    s = s.replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    try:
        v = float(s.strip("()").replace("Rs.", ""))
    except ValueError:
        return None
    return -v if neg else v


def nsdl_month(s: requests.Session, upto: date) -> dict:
    """Every reporting date of upto's month up to upto: {date: {"fii_cash", "usdinr"}}."""
    r = s.get(NSDL, timeout=60)
    form = {k: html.unescape(v) for k, v in re.findall(r'<input[^>]+name="(__[A-Z]+)"[^>]+value="([^"]*)"', r.text)}
    form.update({"__EVENTTARGET": "btnSubmit1", "__EVENTARGUMENT": "", "hdnDate": upto.strftime("%d-%b-%Y"),
                 "hdnFlag": "", "HdnValexceldata": ""})
    r = s.post(NSDL, data=form, timeout=60)
    out = {}
    for row in re.findall(r"<tr.*?</tr>", r.text, re.S | re.I):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<t[dh].*?</t[dh]>", row, re.S | re.I)]
        # the first row of each reporting date: date, Equity, Stock Exchange, purchases, sales, net, net $, rate
        if len(cells) >= 8 and re.match(r"\d\d-[A-Za-z]{3}-\d{4}$", cells[0]) and cells[1] == "Equity" \
                and cells[2] == "Stock Exchange":
            d = datetime.strptime(cells[0], "%d-%b-%Y").date().isoformat()
            out[d] = {k: v for k, v in (("fii_cash", _num(cells[5])), ("usdinr", _num(cells[7]))) if v is not None}
    return out


MCX = "https://www.mcxindia.com/market-data/bhavcopy"


def mcx_session():
    from curl_cffi import requests as creq                 # MCX refuses plain requests (as BSE does)
    s = creq.Session(impersonate="chrome")
    s.get(MCX, timeout=30)
    return s


def mcx_day(s, d: date) -> dict | None:
    """{gold_chg, gold, crude_chg, crude} for one MCX session, or None (no session that day)."""
    r = s.get(MCX + "/GetDateWiseBhavCopy", params={"InstrumentName": "FUTCOM", "fromDate": d.strftime("%d/%m/%Y")},
              headers={"Referer": MCX, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}, timeout=40)
    rows = (r.json() or {}).get("Data") or []
    out = {}
    for sym, key in (("GOLD", "gold"), ("CRUDEOIL", "crude")):
        fut = [x for x in rows if str(x.get("Symbol", "")).strip() == sym and x.get("InstrumentName") == "FUTCOM"
               and (x.get("Volume") or 0) > 0 and (x.get("PreviousClose") or 0) > 0]
        if not fut:
            continue
        top = max(fut, key=lambda x: x.get("OpenInterest") or 0)
        out[key] = top["Close"]
        out[key + "_chg"] = round((top["Close"] / top["PreviousClose"] - 1) * 100, 2)
    return out or None


def fred_changes(key: str, series: str, start: date) -> dict:
    r = requests.get("https://api.stlouisfed.org/fred/series/observations", headers=UA, timeout=60,
                     params={"series_id": series, "api_key": key, "file_type": "json",
                             "observation_start": (start - timedelta(days=10)).isoformat()})
    r.raise_for_status()
    obs = [(o["date"], float(o["value"])) for o in r.json()["observations"] if o["value"] not in (".", "")]
    return {d: round((v / p - 1) * 100, 2) for (_, p), (d, v) in zip(obs, obs[1:]) if p and d >= start.isoformat()}


def main() -> int:
    hist = load(PATH) or {}
    today = datetime.now(config.IST).date()
    have = {k for k, v in hist.items() if "fii_cash" in v}
    # months to read: every month with no NSDL figure yet, and always the current and previous month (late filings)
    months, m = [], date(START.year, START.month, 1)
    while m <= today:
        end = min(date(m.year + (m.month == 12), m.month % 12 + 1, 1) - timedelta(days=1), today)
        if not any(k[:7] == m.isoformat()[:7] for k in have) or (today - end).days < 40:
            months.append(end)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    s = requests.Session()
    s.headers.update(UA)
    got = 0
    for end in months:
        try:
            rows = nsdl_month(s, end)
        except requests.RequestException as e:
            print(f"::warning::NSDL {end:%b %Y}: {type(e).__name__}")
            continue
        for d, v in rows.items():
            hist.setdefault(d, {}).update(v)
        got += len(rows)
        print(f"NSDL {end:%b %Y}: {len(rows)} reporting dates", flush=True)
        time.sleep(1.5)
    # dollar-rupee change from one reporting date to the next
    prev = None
    for d in sorted(hist):
        u = hist[d].get("usdinr")
        if u and prev:
            hist[d]["usdinr_chg"] = round((u / prev - 1) * 100, 3)
        prev = u or prev
    # MCX gold and crude: every weekday since START without them (a bounded number a run; the next run carries on)
    todo, d = [], START
    while d < today:
        if d.weekday() < 5 and not (hist.get(d.isoformat()) or {}).get("mcx_checked"):
            todo.append(d)
        d += timedelta(days=1)
    limit = int(os.getenv("MCX_MAX") or 1200)
    if todo:
        try:
            ms = mcx_session()
            n = 0
            for d in todo[:limit]:
                try:
                    v = mcx_day(ms, d)
                except Exception as e:                       # noqa: BLE001 -- that day is tried again next run
                    print(f"::warning::MCX {d}: {type(e).__name__}")
                    continue
                row = hist.setdefault(d.isoformat(), {})
                row.update(v or {})
                if v is not None or (today - d).days > 7:   # a holiday is not asked again once a week old
                    row["mcx_checked"] = True
                n += 1
                time.sleep(0.4)
            print(f"MCX: {n} days read ({len(todo) - min(len(todo), limit)} left)", flush=True)
        except Exception as e:                               # noqa: BLE001
            print(f"::warning::MCX unavailable: {type(e).__name__}: {str(e)[:120]}")
    key = os.getenv("FRED_API_KEY")
    if key:
        for field, sid in FRED.items():
            try:
                ch = fred_changes(key, sid, START)
            except requests.RequestException as e:
                print(f"::warning::FRED {sid}: {type(e).__name__}")
                continue
            for d, v in ch.items():
                hist.setdefault(d, {})[field] = v
            print(f"FRED {sid}: {len(ch)} sessions", flush=True)
    else:
        print("::warning::FRED_API_KEY is not set: US markets not updated")
    save(PATH, dict(sorted(hist.items())), f"diary history: {len(hist)} days")
    fii = sorted(k for k, v in hist.items() if "fii_cash" in v)
    print(f"saved: {len(hist)} days; NSDL {len(fii)} reporting dates ({fii[0] if fii else '-'} .. {fii[-1] if fii else '-'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
