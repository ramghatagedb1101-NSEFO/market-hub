"""
The morning news score, from 2023 on and every trading morning after (owner, 15 Nov 2026), built ONE way for history
and live so a strategy reads the same thing in a back-test and in the market:
  headlines: GDELT's free news archive (api.gdeltproject.org, artlist), seen between the previous session's close
             (15:30 IST) and 09:00 IST on the day -- Indian market news, and world markets news;
  score:     Gemini (through the relay, ?mode=bot_ask, so the key stays there) with hub/news_score.py's question:
             the headlines' likely effect on NIFTY's close today, -2..+2, most days 0.
The diary's RSS-based score (hub/news_score.py) carries on for the daily brief; strategies read this one.

state/market/news_history.json (private) = {"YYYY-MM-DD": {"score", "confidence", "reasons", "headlines", "model", "at"}}
On a weekday morning (`--today`, news-today.timer at 09:05 IST) it scores today and also writes
/opt/trader/news_today.json, which the trading program reads (trader/market.py) before the 09:15 open.
    python -m trader.news_history [--max 200] [--minutes 90] [--today]
GDELT allows one request every 5 seconds an address: this runs on market-hub-trader, ~15 s a day.
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

from hub.expiry_history import load, save
from hub.holidays import is_session
from hub.news_score import PROMPT

IST = timezone(timedelta(hours=5, minutes=30))
PATH = "state/market/news_history.json"
START = date(2023, 1, 2)
LOCAL_TODAY = os.getenv("NEWS_TODAY_FILE") or "/opt/trader/news_today.json"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
# Short queries (GDELT refuses long ones), then only real business outlets are kept (15 Nov 2026: a broad search
# brought regional general news -- festivals, local politics -- into the morning's headlines).
QUERIES = ['(sensex OR nifty OR "dalal street") sourcelang:english',
           '("wall street" OR "asian markets" OR "global markets") sourcelang:english']
DOMAINS = {"economictimes.indiatimes.com", "livemint.com", "business-standard.com", "moneycontrol.com",
           "financialexpress.com", "thehindubusinessline.com", "ndtvprofit.com", "cnbctv18.com", "zeebiz.com",
           "businesstoday.in", "thehindu.com", "hindustantimes.com", "indianexpress.com", "timesofindia.indiatimes.com",
           "reuters.com", "cnbc.com", "apnews.com", "bloomberg.com", "marketwatch.com", "ft.com", "wsj.com",
           "investing.com", "fxstreet.com", "nasdaq.com", "finance.yahoo.com", "barrons.com"}
UA = {"User-Agent": "Mozilla/5.0 (market-hub research)"}
SYSTEM = "You score market news for an Indian equity strategist. Answer with JSON only: " \
         '{"score": -2|-1|0|1|2, "confidence": "low"|"medium"|"high", "reasons": [up to 3 short strings]}'
_last = [0.0]


def _gdelt(q: str, start: datetime, end: datetime) -> list[dict]:
    for attempt in range(3):
        wait = 6.0 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get(GDELT, headers=UA, timeout=60, params={
            "query": q, "mode": "artlist", "maxrecords": 75, "format": "json", "sort": "datedesc",
            "startdatetime": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "enddatetime": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")})
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        try:
            return r.json().get("articles") or []
        except ValueError:
            return []                                    # GDELT answers plain text when nothing matches
    return []


def prev_session(d: date) -> date:
    p = d - timedelta(days=1)
    while not is_session(p):
        p -= timedelta(days=1)
    return p


def headlines(d: date) -> tuple[list[str], datetime, datetime]:
    start = datetime.combine(prev_session(d), datetime.min.time(), IST).replace(hour=15, minute=30)
    end = datetime.combine(d, datetime.min.time(), IST).replace(hour=9)
    seen, out = set(), []
    for q in QUERIES:
        for a in _gdelt(q, start, end):
            t = " ".join((a.get("title") or "").split())
            dom = (a.get("domain") or "").lower().removeprefix("www.")
            if dom not in DOMAINS and not any(dom.endswith("." + x) for x in DOMAINS):
                continue
            if not t or t.lower() in seen:
                continue
            seen.add(t.lower())
            try:
                when = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(IST)
            except (KeyError, ValueError):
                continue
            if start <= when <= end:                     # never a headline after 09:00
                out.append((when, f"{when:%a %H:%M} {a.get('domain', '')}: {t}"))
    out.sort()
    return [x for _, x in out[-150:]], start, end


def score(d: date) -> dict | None:
    lines, start, end = headlines(d)
    if not lines:
        return {"score": 0, "confidence": "low", "reasons": ["no headlines found"], "headlines": 0}
    prompt = PROMPT.format(start=f"{start:%a %d %b %Y %H:%M}", end=f"{end:%a %d %b %Y %H:%M}",
                           day=f"{d:%a %d %b %Y}", lines="\n".join(lines))
    try:
        r = requests.post(os.environ["RELAY_URL"], params={"mode": "bot_ask", "key": os.environ["RELAY_KEY"]}, timeout=330,
                          data=json.dumps({"system": SYSTEM, "prompt": prompt, "temperature": 0}))
        j = r.json()
        ans = json.loads(j["text"])
        s = int(ans["score"])
    except Exception:                                    # noqa: BLE001 -- not scored this run; tried again next run
        return None
    return {"score": max(-2, min(2, s)), "confidence": str(ans.get("confidence") or "")[:10],
            "reasons": [str(x)[:200] for x in (ans.get("reasons") or [])[:3]], "headlines": len(lines),
            "model": j.get("model"), "at": datetime.now(IST).isoformat(timespec="minutes")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--minutes", type=float, default=90)
    ap.add_argument("--today", action="store_true", help="score this morning (before the open) and hand it to the program")
    ap.add_argument("--probe", action="store_true", help="headline counts for a few mornings; no scoring, nothing saved")
    a = ap.parse_args()
    if a.probe:
        for d in (date(2023, 3, 1), date(2024, 6, 4), date(2025, 9, 15), date(2026, 11, 13)):
            lines, st, en = headlines(d)
            print(f"{d}: {len(lines)} headlines ({st:%a %H:%M} -> {en:%a %H:%M}); e.g. {lines[:3]} ... {lines[-2:]}", flush=True)
        return 0
    deadline = time.time() + a.minutes * 60
    hist = load(PATH) or {}
    now = datetime.now(IST)
    if a.today:
        d = now.date()
        if not is_session(d) or now.strftime("%H:%M") < "09:00":
            print("not a trading morning after 09:00: nothing to score")
            return 0
        rec = score(d)
        if not rec:
            print("today: Gemini did not answer")
            return 1
        hist[d.isoformat()] = rec
        save(PATH, dict(sorted(hist.items())), f"news score {d}")
        try:
            with open(LOCAL_TODAY + ".tmp", "w", encoding="utf-8") as f:
                json.dump({d.isoformat(): rec["score"]}, f)
            os.replace(LOCAL_TODAY + ".tmp", LOCAL_TODAY)
        except OSError:
            pass
        print(f"today {d}: score {rec['score']} ({rec['confidence']}) from {rec['headlines']} headlines")
        return 0
    todo, d = [], START
    while d < now.date():
        if is_session(d) and d.isoformat() not in hist:
            todo.append(d)
        d += timedelta(days=1)
    print(f"news history: {len(hist)} mornings scored, {len(todo)} to go; up to {a.max} this run", flush=True)
    done = 0
    for d in todo[:a.max]:
        if time.time() > deadline or ("09:00" <= datetime.now(IST).strftime("%H:%M") <= "15:50"
                                      and datetime.now(IST).weekday() < 5):
            break
        rec = score(d)
        if rec is None:
            continue
        hist[d.isoformat()] = rec
        done += 1
        if done % 20 == 0:
            save(PATH, dict(sorted(hist.items())), f"news history: {len(hist)} mornings")
            print(f"  {d}: {done} scored this run", flush=True)
    save(PATH, dict(sorted(hist.items())), f"news history: {len(hist)} mornings")
    print(f"news history: {done} scored this run, {len(hist)} in all", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
