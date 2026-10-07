"""
Sector-level news and regulatory-event counts, from Google News' public RSS search (free, no key).
One count per sector (17 NSE sectors in rg/data/sector_map.json), not per company -- every company in
a sector shares the same two numbers, computed once per run and cached for the rest of the batch.

This is a coarse, keyword-based signal, not a precise one: Google News RSS caps a feed at 100 items,
so a very active sector's count saturates and stops discriminating above that point -- still
informative (saturated means "very high attention"), just not exact above the cap. Counts are a
proxy for sector-level attention, not validated against any outcome; the threshold in hub/library.py
is a judgment call, written down, not backtested.
"""
import re

import requests

RSS = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
REGULATORY_KEYWORDS = '(notification OR "new rule" OR mandate OR ban OR tariff OR duty OR circular)'


def _count(query: str) -> int:
    r = requests.get(RSS, params={"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
                      headers=HEADERS, timeout=20)
    r.raise_for_status()
    return len(re.findall(r"<item>", r.text))


def sector_news_count(sector: str) -> int:
    """News items naming the sector, last 30 days."""
    return _count(f'"{sector}" India sector when:30d')


def regulatory_events(sector: str) -> int:
    """News items naming the sector alongside a regulatory/policy-change keyword, last 90 days."""
    return _count(f'"{sector}" India {REGULATORY_KEYWORDS} when:90d')


def build_cache(sectors: list[str]) -> dict:
    """{sector: {"sector_news_count": n, "regulatory_events": m}}, one pair of calls per sector --
    cheap even for all 17 (about 34 requests), computed fresh each batch rather than stored, since
    the counts are only ever a same-day snapshot anyway."""
    cache = {}
    for sector in sectors:
        entry = {}
        try:
            entry["sector_news_count"] = sector_news_count(sector)
        except Exception:
            pass
        try:
            entry["regulatory_events"] = regulatory_events(sector)
        except Exception:
            pass
        cache[sector] = entry
    return cache
