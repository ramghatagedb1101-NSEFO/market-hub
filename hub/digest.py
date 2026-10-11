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
import statistics
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


def _pct(x):
    return f"{x:+.1f}%"


def move_reason(sym: str, prices: dict, industries: dict, announcements: dict, nifty: dict) -> str:
    """Why a stock moved, from what the run already holds: NIFTY and its industry that day (median move
    of the industry's stocks that traded), volume against its 20-day average, and any announcement."""
    series, volume, _ = prices[sym]
    d1 = series[-1][0]
    chg = (series[-1][1] / series[-2][1] - 1) * 100

    def day_move(s):
        px = prices.get(s)
        if not px or len(px[0]) < 2 or px[0][-1][0] != d1 or not px[0][-2][1]:
            return None
        return (px[0][-1][1] / px[0][-2][1] - 1) * 100

    ind = industries.get(sym)
    peers = [m for s, i in industries.items() if ind and i == ind and s != sym for m in [day_move(s)] if m is not None]
    ind_move = statistics.median(peers) if len(peers) >= 4 else None
    prev = [k for k in nifty if k < d1.isoformat()]
    n1, n0 = nifty.get(d1.isoformat()), (nifty[max(prev)] if prev else None)
    mkt = (n1 / n0 - 1) * 100 if n1 and n0 else None
    with_industry = ind_move is not None and abs(chg - ind_move) < max(1.5, abs(chg) / 3)
    if with_industry:
        parts = [f"Moved with its industry ({ind} {_pct(ind_move)})"]
    else:
        ctx = ", ".join(x for x in ((f"NIFTY {_pct(mkt)}" if mkt is not None else ""),
                                    (f"{ind} {_pct(ind_move)}" if ind_move is not None else "")) if x)
        parts = ["Stock-specific" + (f" ({ctx})" if ctx else "")]
    base = [v for v in volume[-21:-1] if v] if len(volume) >= 21 else []
    if base and volume[-1]:
        r = volume[-1] / (sum(base) / len(base))
        if r >= 1.5:
            parts.append(f"volume {r:.1f}x normal")
        elif r <= 0.7:
            parts.append("on light volume")
    lo = (d1 - timedelta(days=1)).isoformat()
    anns = [a for a in announcements.get(sym, []) if a[0] and lo <= a[0] <= d1.isoformat()]
    if anns:
        parts.append("filed: " + anns[-1][1])
    elif not with_industry:
        parts.append("no company announcement")
    return "; ".join(parts)


def left_reason(sym: str, style: str, shortlist: dict, by_sym: dict, joined: list) -> str:
    """Why a company left a list, from the Shortlist's own output and rules."""
    from . import shortlist as sl
    L = (shortlist.get("lists") or {}).get(style) or {}
    out = next((o for o in L.get("left_out") or [] if o.get("symbol") == sym), None)
    if out:
        return "Excluded: " + out["reason"]
    nxt = next((x for x in L.get("next") or [] if x.get("symbol") == sym), None)
    if nxt:
        return f"Still qualifies but now ranks #{nxt.get('rank')}" + (f"; overtaken by {', '.join(joined[:3])}" if joined else "")
    if sym in (L.get("industry_cap_held_back") or []):
        return "Still qualifies; two companies from its industry rank higher"
    s = by_sym.get(sym)
    if style == "compounders" and s and s.get("cells") and ((s["cells"].get("profitable_share_10y") or {}).get("value")) is None:
        return "Not judged until its 10-year record loads (compounders need years of results, not 8 quarters)"
    if style == "compounders" and s and s.get("cells"):
        v = lambda k: ((s.get("cells") or {}).get(k) or {}).get("value")
        failed = [name for name, rule in sl.compounder_rules(v) if not rule(v)]
        if failed:
            return "Fails: " + "; ".join(failed[:2])
    return "No longer passes the compounder rules" if style == "compounders" else "Multi-bagger score fell below 4 of 4"


def build(shortlist: dict, companies: dict, stocks: list[dict], prices: dict, results_filed: dict,
          names: dict, today: date, industries: dict | None = None, announcements: dict | None = None,
          nifty: dict | None = None) -> dict:
    industries, announcements, nifty = industries or {}, announcements or {}, nifty or {}
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
        by_sym = {x["symbol"]: x for x in stocks if x.get("symbol")}
        joined = {st: [s for s in syms if s not in set(base.get(st) or [])] for st, syms in lists.items()}
        left = {st: sorted(set(base.get(st) or []) - set(syms)) for st, syms in lists.items()}

        def first_why(st, s):
            item = next((x for x in shortlist["lists"][st]["top"] if x["symbol"] == s), {})
            return (item.get("why") or [""])[0].split(" - better")[0]
        for st in lists:
            other = "emerging" if st == "compounders" else "compounders"
            for s in joined[st]:
                if s in left.get(other, []):          # one line for a move between the two lists
                    add("shortlist", s, f"Moved from {label[other]} to {label[st]}", "",
                        why=left_reason(s, other, shortlist, by_sym, joined[other]) + ". " + first_why(st, s))
                else:
                    add("shortlist", s, f"Joined the {label[st]} list", "", why=first_why(st, s))
            for s in left[st]:
                if s in joined.get(other, []):
                    continue
                add("shortlist", s, f"Left the {label[st]} list", "", where=label[st],
                    why=left_reason(s, st, shortlist, by_sym, joined[st]))
        for s in sorted(set(core) - set(state.get("base_core") or [])):
            add("shortlist", s, "Now core: on the list 3 weeks running", "", why="In three weekly snapshots in a row")

    summaries = _load(SUMMARIES_FILE, {})
    since = (today - timedelta(days=FILING_DAYS)).isoformat()
    by_sym = {s["symbol"]: s for s in stocks if s.get("symbol")}
    for sym in scope:
        q = results_filed.get(sym)
        if q:
            chk = (companies.get(sym) or {}).get("check") or {}
            g = [f"{lab} {_pct(chk[k])}" for k, lab in (("nse_rev_yoy", "Revenue"), ("nse_profit_yoy", "profit"))
                 if chk.get("period") == q.isoformat() and chk.get(k) is not None]
            add("filing", sym, "Results filed", f"Quarter ending {q.strftime('%d %b %Y')}",
                why=(", ".join(g) + " on a year ago") if g else f"Quarter to {q.strftime('%d %b %Y')}; growth shows once the filing is read")
        docs = (companies.get(sym) or {}).get("docs") or {}
        for kind in ("tr", "pr", "ar"):
            for d in docs.get(kind) or []:
                if (d.get("date") or "") >= since:
                    sm = summaries.get(sym, {}).get(kind) or {}
                    has = sm.get("url") == d.get("url")
                    head = ((sm.get("summary") or {}).get("headline") or "") if has else ""
                    add("filing", sym, KIND[kind], "AI summary ready" if has else "", d.get("date"), d.get("url"), summary=has,
                        why=("AI summary: " + head) if head else ("AI summary ready" if has else "Open the company to read the PDF"))
        px = prices.get(sym)
        if px and len(px[0]) >= 2 and px[0][-2][1]:
            (d1, c1), c0 = px[0][-1], px[0][-2][1]
            chg = (c1 / c0 - 1) * 100
            if abs(chg) >= MOVE_PCT:
                try:
                    why = move_reason(sym, prices, industries, announcements, nifty)
                except Exception:
                    why = ""
                add("move", sym, f"{'Up' if chg > 0 else 'Down'} {abs(chg):.1f}% on {d1.strftime('%a %d %b')}", f"Close Rs {c1:,.2f}",
                    d1.isoformat(), change=round(chg, 2), why=why)
        for a in (by_sym.get(sym) or {}).get("actions") or []:
            ex = a.get("ex_date") or ""
            if a.get("upcoming") and ex <= (today + timedelta(days=UPCOMING_DAYS)).isoformat():
                exd = date.fromisoformat(ex).strftime("%a %d %b")
                add("upcoming", sym, a.get("subject", "Corporate action"), f"Ex-date {exd}", ex,
                    why=f"Ex-date {exd}: shares bought on or after that day don't qualify")
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
