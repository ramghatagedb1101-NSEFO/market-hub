"""
The phone's "Today" digest (11 Oct 2026), written by the daily library run as site/digest.json. For the
companies that matter to the owner -- the Shortlist's two lists and the watchlist (read from the relay,
behind RELAY_KEY) -- it lists what changed since the previous day:

  shortlist   joined / left a list, newly "core"
  filing      results filed at NSE; earnings-call transcript, investor presentation or annual report filed
              (with whether an AI summary exists)
  move        a daily price move of 4% or more
  upcoming    a dividend, split, bonus or buyback with its ex-date in the next 14 days

Everything comes from data the run already holds; nothing new is fetched except the watchlist.
"""
import json
import os
from datetime import date, timedelta

import requests

from . import config

OUT_FILE = config.SITE_DIR / "data" / "digest.json"
STATE_FILE = config.REPO / "state" / "digest_state.json"
SUMMARIES_FILE = config.SITE_DIR / "data" / "summaries.json"
MOVE_PCT = 4.0
FILING_DAYS = 3
UPCOMING_DAYS = 14
KIND = {"tr": "Earnings-call transcript filed", "pr": "Investor presentation filed", "ar": "Annual report filed"}


def watchlist() -> list[str]:
    url, key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    if not url or not key:
        return []
    try:
        r = requests.get(url, params={"mode": "watchlist", "key": key}, timeout=30)
        return [s for s in (r.json().get("symbols") or []) if isinstance(s, str)]
    except Exception:
        return []


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def build(shortlist: dict, companies: dict, stocks: list[dict], prices: dict, results_filed: dict,
          names: dict, today: date) -> dict:
    lists = {st: [x["symbol"] for x in L.get("top", [])] for st, L in (shortlist.get("lists") or {}).items()}
    core = sorted({x["symbol"] for L in (shortlist.get("lists") or {}).values() for x in L.get("top", []) if x.get("core")})
    watch = watchlist()
    scope = {}
    for st, syms in lists.items():
        for s in syms:
            scope[s] = "Compounders" if st == "compounders" else "Emerging"
    for s in watch:
        scope.setdefault(s, "Watchlist")

    # what changed in the lists since the previous day
    state = _load(STATE_FILE, {})
    first_today = state.get("last_date") != today.isoformat()
    if first_today:
        state["base_date"], state["base_lists"], state["base_core"] = state.get("last_date"), state.get("last_lists"), state.get("last_core")
    state["last_date"], state["last_lists"], state["last_core"] = today.isoformat(), lists, core
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")

    items = []

    def add(kind, sym, title, detail="", when=None, url=None, where=None, **extra):
        items.append({"type": kind, "symbol": sym, "name": names.get(sym, ""), "scope": where or scope.get(sym, ""),
                      "title": title, "detail": detail, "date": when, "url": url, **extra})

    base = state.get("base_lists")
    if base is not None:
        label = {"compounders": "Compounders", "emerging": "Emerging"}
        for st, syms in lists.items():
            before = set(base.get(st) or [])
            for s in syms:
                if s not in before:
                    item = next((x for x in shortlist["lists"][st]["top"] if x["symbol"] == s), {})
                    add("shortlist", s, f"Joined the {label[st]} list", (item.get("why") or [""])[0].split(" - better")[0])
            for s in before - set(syms):
                add("shortlist", s, f"Left the {label[st]} list", "", where=label[st])
        for s in sorted(set(core) - set(state.get("base_core") or [])):
            add("shortlist", s, "Now core: on the list 3 weeks running", "")

    summaries = _load(SUMMARIES_FILE, {})
    since = (today - timedelta(days=FILING_DAYS)).isoformat()
    by_sym = {s["symbol"]: s for s in stocks if s.get("symbol")}
    for sym in scope:
        q = results_filed.get(sym)
        if q:
            add("filing", sym, "Results filed", f"Quarter ending {q.strftime('%d %b %Y')}")
        docs = (companies.get(sym) or {}).get("docs") or {}
        for kind in ("tr", "pr", "ar"):
            for d in docs.get(kind) or []:
                if (d.get("date") or "") >= since:
                    has = (summaries.get(sym, {}).get(kind) or {}).get("url") == d.get("url")
                    add("filing", sym, KIND[kind], "AI summary ready" if has else "", d.get("date"), d.get("url"), summary=has)
        px = prices.get(sym)
        if px and len(px[0]) >= 2 and px[0][-2][1]:
            (d1, c1), c0 = px[0][-1], px[0][-2][1]
            chg = (c1 / c0 - 1) * 100
            if abs(chg) >= MOVE_PCT:
                add("move", sym, f"{'Up' if chg > 0 else 'Down'} {abs(chg):.1f}% on {d1.strftime('%a %d %b')}", f"Close Rs {c1:,.2f}", d1.isoformat(), change=round(chg, 2))
        for a in (by_sym.get(sym) or {}).get("actions") or []:
            ex = a.get("ex_date") or ""
            if a.get("upcoming") and ex <= (today + timedelta(days=UPCOMING_DAYS)).isoformat():
                add("upcoming", sym, a.get("subject", "Corporate action"), f"Ex-date {date.fromisoformat(ex).strftime('%a %d %b')}", ex)
    order = {"shortlist": 0, "filing": 1, "move": 2, "upcoming": 3}
    items.sort(key=lambda x: (order[x["type"]], x["date"] or "", x["symbol"]))
    payload = {"generated": shortlist.get("generated"), "date": today.isoformat(), "since": state.get("base_date"),
               "watchlist": watch, "scope": len(scope), "items": items}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    sent = notify(payload) if first_today else None
    return {"items": len(items), "scope": len(scope), "watchlist": len(watch), "email": sent}


def notify(payload: dict):
    """The first run of the day hands the digest to the relay, which emails it once a day (relay
    Alerts.gs, sendDigest_; switchable on the dashboard)."""
    url, key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    if not url or not key:
        return None
    body = {"date": payload["date"], "items": [{k: x.get(k) for k in ("type", "symbol", "title", "detail")} for x in payload["items"]]}
    try:
        r = requests.post(url, params={"mode": "digest", "key": key}, data=json.dumps(body), timeout=30,
                          headers={"Content-Type": "text/plain"})
        return r.json()
    except Exception as exc:
        return {"error": str(exc)[:200]}
