"""
Daily news score, recorded to be tested (26 Oct 2026, owner: "add the Gemini news score recording"). There is no free
history of news to test a news signal against, so this builds one: each weekday before the open, Gemini (free tier,
one request a day) reads the headlines published between 15:30 IST on the last Indian session and 09:00 IST today and
scores their likely effect on NIFTY's close from -2 to +2. It is NOT used in any estimate. The daily job scores it
(summary(), feed.json news_score_record): direction against NIFTY's close-to-close move, and against what is left after
the GIFT Nifty lean (the close-estimate log), so after a few months it shows whether news adds anything beyond GIFT.

Headlines: the brief's RSS feeds (hub/context.py NEWS_FEEDS) plus Google News' India-markets search. Only items with a
publish time inside the window are used, so a run GitHub starts late never sees news from after 09:00. Titles only.
python -m hub.news_score record (close-estimate.yml, after the estimate) appends to the private repo's
state/news_score_log.json; only this job writes it. Needs GEMINI_API_KEY and PRIVATE_REPO_TOKEN.
"""
import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from . import config
from .close_estimate import PRIVATE, _gh, session_block
from .context import NEWS_FEEDS, UA

LOG_PATH = "state/news_score_log.json"
LOCAL_LOG = config.REPO / "state" / "news_score_log.json"
GOOGLE = "https://news.google.com/rss/search"
GOOGLE_QUERIES = ["Sensex OR Nifty", "India economy OR RBI OR rupee", "stock market Asia OR Wall Street"]
MAX_HEADLINES = 150                                      # newest first; a weekend can hold more
SCHEMA = {"type": "object", "properties": {
    "score": {"type": "integer", "minimum": -2, "maximum": 2},
    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    "reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 3}},
    "required": ["score", "confidence", "reasons"]}
PROMPT = """You are an experienced Indian equity strategist. Below are news headlines published between {start} and
{end} (Indian time), before the NSE opens at 09:15 IST on {day}. Judge their combined likely effect on the NIFTY 50's
close today versus its last close: -2 clearly negative, -1 mildly negative, 0 no clear effect or mixed, +1 mildly
positive, +2 clearly positive. Weigh only news that markets would not already have priced in at the last close. Most
days are 0. Give up to three short reasons in plain English. Headlines:
{lines}"""


def _items(start: datetime, end: datetime) -> list[dict]:
    feeds = list(NEWS_FEEDS.items()) + [("Google News", (GOOGLE, {"q": q, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}))
                                         for q in GOOGLE_QUERIES]
    out, seen = [], set()
    for source, url in feeds:
        try:
            u, params = url if isinstance(url, tuple) else (url, None)
            r = requests.get(u, params=params, headers=UA, timeout=20)
            r.raise_for_status()
            root = ElementTree.fromstring(r.content)
        except Exception:                               # noqa: BLE001 -- one feed down must not stop the rest
            continue
        for it in root.iter("item"):
            title = re.sub(r"\s+", " ", (it.findtext("title") or "")).strip()
            try:
                when = parsedate_to_datetime(it.findtext("pubDate") or "")
            except (TypeError, ValueError):
                continue                                # no publish time: cannot prove it is before 09:00
            if when.tzinfo is None:
                when = when.replace(tzinfo=config.IST)
            when = when.astimezone(config.IST)
            if not title or title.lower() in seen or not (start <= when <= end):
                continue
            seen.add(title.lower())
            out.append({"when": when, "t": when.strftime("%a %H:%M"), "src": source, "title": title})
    out.sort(key=lambda x: x["when"])                   # the newest MAX_HEADLINES, in time order
    return [{k: v for k, v in x.items() if k != "when"} for x in out[-MAX_HEADLINES:]]


def _ask(text: str) -> tuple[dict, str]:
    from .summaries import GEMINI_FALLBACK_MODEL, GEMINI_MODEL, _transient, make_client
    client, last = make_client(), None
    fmt = {"type": "text", "mime_type": "application/json", "schema": SCHEMA}
    for model, wait in ((GEMINI_MODEL, 0), (GEMINI_MODEL, 20), (GEMINI_FALLBACK_MODEL, 0)):
        time.sleep(wait)
        try:
            r = client.interactions.create(model=model, input=[{"type": "text", "text": text}], response_format=fmt)
            return json.loads(r.output_text), model
        except Exception as exc:                        # noqa: BLE001
            if not _transient(exc):
                raise
            last = exc
    raise last


def record() -> dict | None:
    now = datetime.now(config.IST)
    today = now.date().isoformat()
    r = _gh("GET", LOG_PATH)
    sha, log = (r.json()["sha"], json.loads(base64.b64decode(r.json()["content"]))) if r.status_code == 200 else (None, [])
    if any(e["date"] == today for e in log):
        return None                                     # one score a day
    feed = requests.get(PRIVATE + "site/feed.json", timeout=30, headers={
        "Authorization": "Bearer " + os.environ["PRIVATE_REPO_TOKEN"], "Accept": "application/vnd.github.raw"}).json()
    t = session_block(feed["indices"]["NIFTY"], today)
    if t is None:
        if now.weekday() < 5:                           # outside review 27 Oct 2026: never succeed with nothing
            raise SystemExit(f"no open session for {today} in the feed ({feed.get('generated_at')})")
        return None
    start = datetime.fromisoformat(t["asof"] + "T15:30:00+05:30")
    end = datetime.fromisoformat(today + "T09:00:00+05:30")
    items = _items(start, end)
    if not items:
        raise SystemExit("no headlines in the window")
    lines = "\n".join(f"- [{x['t']}] {x['title']}" for x in items)
    ans, model = _ask(PROMPT.format(start=start.strftime("%a %d %b %Y %H:%M"), end=end.strftime("%a %d %b %Y %H:%M"),
                                    day=now.strftime("%a %d %b %Y"), lines=lines))
    entry = {"date": today, "asof": t["asof"], "at": now.strftime("%H:%M"), "model": model, "headlines": len(items),
             "score": int(ans["score"]), "confidence": ans["confidence"], "reasons": ans["reasons"][:3]}
    body = {"message": f"news score {today}", "content": base64.b64encode(
        json.dumps(log + [entry], ensure_ascii=False, separators=(",", ":")).encode()).decode()}
    if sha:
        body["sha"] = sha
    if _gh("PUT", LOG_PATH, json=body).status_code not in (200, 201):
        raise SystemExit("could not write the news-score log (changed meanwhile); the next run tries again")
    return entry


def summary(prices: dict) -> dict:
    """NIFTY: days scored, and on days with a non-zero score how often its sign matched the close-to-close move and
    the move left after the recorded GIFT/S&P lean (close-estimate log)."""
    try:
        log = json.loads(LOCAL_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    from .close_estimate import LOCAL_LOG as EST_LOG
    try:
        pre = {e["date"]: e for e in json.loads(EST_LOG.read_text(encoding="utf-8")) if e["index"] == "NIFTY" and e["kind"] == "pre"}
    except (OSError, ValueError):
        pre = {}
    dates, closes = prices.get("NIFTY", ([], []))
    close = {d.isoformat(): float(c) for d, c in zip(dates, closes)}
    done = [(e, close[e["date"]], close.get(e["asof"])) for e in log if e["date"] in close and e["asof"] in close]
    called = [(e, a, b) for e, a, b in done if e["score"]]
    out = {"n": len(done), "called_n": len(called)}
    if called:
        out["called_hit_pct"] = round(100 * sum((a - b) * e["score"] > 0 for e, a, b in called) / len(called), 1)
        res = [(e, a / pre[e["date"]]["pred"] - 1) for e, a, b in called if e["date"] in pre]
        if res:
            out["beyond_estimate_n"] = len(res)
            out["beyond_estimate_hit_pct"] = round(100 * sum(r * e["score"] > 0 for e, r in res) / len(res), 1)
    return {"NIFTY": out}


if __name__ == "__main__":
    if (sys.argv[1:] or [""])[0] == "record":
        print(json.dumps(record(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
