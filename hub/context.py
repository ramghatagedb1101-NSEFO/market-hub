"""
Market context for the daily brief: FII/DII flows, FX reference rates, and recent headlines.

Writes docs/data/context.json. Every source is free and needs no key. Each source fails on its own:
a blocked source is recorded in "errors" and the others still publish. The brief is told which
sources are missing, so it never fills a gap with invented numbers.

Not covered yet (needs a free key or a Kite quote, see STATUS.md): global index closes (S&P, Dow,
Nasdaq), gold and crude prices. Kite can give MCX gold and crude once the token is available.
"""
import json
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from . import config

CONTEXT_FILE = config.SITE_DIR / "data" / "context.json"
UA = {"User-Agent": "Mozilla/5.0 (market-hub; daily brief)"}

NEWS_FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Livemint Markets": "https://www.livemint.com/rss/markets",
    "BBC Business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "CNBC Top News": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
    "Investing.com News": "https://www.investing.com/rss/news_25.rss",
}
NEWS_MAX_AGE_DAYS = 3
NEWS_PER_FEED = 12
ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
NSE_FII = "https://www.nseindia.com/api/fiidiiTradeReact"


def _fii_dii() -> list[dict]:
    """Provisional cash-market flows in ₹ crore, from NSE. Needs a home-page visit first for cookies."""
    s = requests.Session()
    s.headers.update(UA)
    s.get("https://www.nseindia.com/", timeout=20)
    r = s.get(NSE_FII, headers={"Accept": "application/json", "Referer": "https://www.nseindia.com/"}, timeout=20)
    r.raise_for_status()
    rows = r.json()
    return [{"category": x["category"], "date": x["date"], "buy": float(x["buyValue"]),
             "sell": float(x["sellValue"]), "net": float(x["netValue"])} for x in rows]


def _fx() -> dict:
    """USD/INR from the ECB reference rates (EUR cross rates, so INR / USD). Published on working days."""
    r = requests.get(ECB_DAILY, headers=UA, timeout=20)
    r.raise_for_status()
    root = ElementTree.fromstring(r.content)
    day = None
    rate = {}
    for el in root.iter():
        if el.tag.endswith("Cube") and el.get("time"):
            day = el.get("time")
        if el.tag.endswith("Cube") and el.get("currency") in ("USD", "INR"):
            rate[el.get("currency")] = float(el.get("rate"))
    return {"date": day, "usd_inr": round(rate["INR"] / rate["USD"], 2), "source": "ECB reference rates"}


FRED_SERIES = {
    "S&P 500": "SP500",
    "Dow Jones": "DJIA",
    "Nasdaq Composite": "NASDAQCOM",
    "WTI crude (USD/bbl)": "DCOILWTICO",
}


def _fred() -> dict:
    """Latest daily closes from FRED (St. Louis Fed). Needs FRED_API_KEY. US prices lag India by a session."""
    import os
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is not set")
    out = {}
    for name, sid in FRED_SERIES.items():
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": sid, "api_key": key, "file_type": "json",
                                 "sort_order": "desc", "limit": 10}, headers=UA, timeout=20)
        r.raise_for_status()
        obs = [o for o in r.json()["observations"] if o["value"] not in (".", "")]
        if len(obs) < 2:
            continue
        last, prev = float(obs[0]["value"]), float(obs[1]["value"])
        out[name] = {"date": obs[0]["date"], "last": last, "prev": prev,
                     "change_pct": round((last / prev - 1) * 100, 2)}
    if not out:
        raise RuntimeError("FRED returned no recent observations")
    return out


def _commodities() -> dict:
    """MCX gold and crude futures from Kite. Needs KITE_API_KEY and KITE_ACCESS_TOKEN."""
    from .sources import commodities
    return commodities.main()


def _usd_inr_live() -> dict:
    """Live USD/INR from Kite's currency futures. Needs KITE_API_KEY and KITE_ACCESS_TOKEN."""
    from .sources import commodities
    return commodities.usd_inr()


def _india_vix() -> dict:
    """India VIX level and change from Kite. Needs KITE_API_KEY and KITE_ACCESS_TOKEN."""
    from .sources import kite
    q = kite.client().quote(["NSE:INDIA VIX"])["NSE:INDIA VIX"]
    last = float(q["last_price"])
    prev = float(q["ohlc"]["close"])
    return {"last": round(last, 2), "change_pct": round((last / prev - 1) * 100, 2) if prev else None}


def _wti() -> dict:
    """WTI crude in US$/bbl, daily, from Alpha Vantage (free key). Usually the previous session's close."""
    import os
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not set")
    r = requests.get("https://www.alphavantage.co/query",
                     params={"function": "WTI", "interval": "daily", "apikey": key}, headers=UA, timeout=20)
    r.raise_for_status()
    body = r.json()
    if "data" not in body:
        raise RuntimeError(body.get("Information") or body.get("Note") or "no WTI data returned")
    rows = [x for x in body["data"] if x.get("value") not in (None, ".", "")]
    if len(rows) < 2:
        raise RuntimeError("fewer than two WTI prices returned")
    last, prev = float(rows[0]["value"]), float(rows[1]["value"])
    return {"date": rows[0]["date"], "last": last, "prev": prev,
            "change_pct": round((last / prev - 1) * 100, 2), "source": "Alpha Vantage"}


def _headlines() -> list[dict]:
    """Recent headlines from each feed. Titles and links only; the brief quotes at most a few."""
    cutoff = datetime.now(config.IST) - timedelta(days=NEWS_MAX_AGE_DAYS)
    items, seen = [], set()
    for source, url in NEWS_FEEDS.items():
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            root = ElementTree.fromstring(r.content)
        except Exception:
            raise RuntimeError(f"{source} did not load") from None
        count = 0
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            pub = it.findtext("pubDate")
            when = None
            if pub:
                try:
                    when = parsedate_to_datetime(pub)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=config.IST)
                    if when < cutoff:
                        continue
                except (TypeError, ValueError):
                    when = None
            seen.add(title.lower())
            items.append({"source": source, "title": re.sub(r"\s+", " ", title),
                          "time": when.astimezone(config.IST).isoformat(timespec="minutes") if when else None})
            count += 1
            if count >= NEWS_PER_FEED:
                break
    items.sort(key=lambda x: x["time"] or "", reverse=True)
    return items


def main() -> dict:
    out = {"ts": datetime.now(config.IST).isoformat(timespec="minutes"), "errors": {}}
    for key, fn in (("fii_dii", _fii_dii), ("fx", _fx), ("global", _fred), ("commodities", _commodities),
                    ("india_vix", _india_vix), ("usd_inr_live", _usd_inr_live), ("wti", _wti), ("headlines", _headlines)):
        try:
            out[key] = fn()
        except Exception as exc:
            out[key] = None
            out["errors"][key] = str(exc)[:200]
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    res = main()
    print(json.dumps({k: (v if k != "headlines" or v is None else f"{len(v)} headlines")
                      for k, v in res.items()}, indent=2, ensure_ascii=False))
