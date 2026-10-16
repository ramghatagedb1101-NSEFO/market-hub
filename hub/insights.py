"""
Insights (16 Oct 2026): the free features from the owner's "borrow from the world's best apps" list, built after
the morning library run (library.yml step) into ONE file, docs/data/insights.json -> the private repo's site/
(hub/site_data.py), read by the dashboard and the phone through the relay after sign-in.

  risk        ASM (long/short term) and GSM surveillance stages, F&O ban list            NSE, free
  pledge      promoter shares pledged, latest disclosure and whether it rose             NSE pledge disclosures
  calendar    board meetings in the next 45 days (results dates)                          NSE
  filings     announcements of the last 3 days                                            NSE
  insider     promoter / director market buys and sells over 180 days, per followed company   NSE insider (PIT)
  positions   FII, DII, Pro and Client index futures and options positions, last 60 days  NSE participant-wise OI
  spikes      volume 3x its 20-day average with high delivery                             NSE daily price file
  heatmap     NIFTY Total Market stocks: industry, size, day / 1-month / from 52-week high   library + price file
  grades      A+ to F per factor within the company's industry                            library (same factors as the dashboard)
  valuation   P/E against its industry's quartiles and its own stored history             library
  superstars  registry investors' holdings by investor                                    library's filing matches
  iv          index option prices (day-before ATM straddle) over 3 years, and today's rank   private expiry history
  alerts      52-week highs/lows, 200-day crossings, results filed, insider buys/sells, saved-screen
              entries and exits, new surveillance flags -- for followed companies; new ones pushed to the phone

Nothing here is a BharatStock call or BharatStock raw data: only NSE files and figures the library already derived.
"""
import csv
import io
import json
import math
import os
import time
from datetime import date, datetime, timedelta

import requests

from . import bhav, config, library
from . import shareholding as shp

OUT_FILE = config.SITE_DIR / "data" / "insights.json"
STATE_FILE = config.REPO / "state" / "insights_state.json"
MB_FILE = config.SITE_DIR / "data" / "multibagger.json"
SL_FILE = config.SITE_DIR / "data" / "shortlist.json"
PHONE_URL = "https://ramghatagedb1101-nsefo.github.io/market-hub/"
NSE = "https://www.nseindia.com/api/"
ARCH = "https://nsearchives.nseindia.com/content/"
INSIDER_DAYS = 180
POSITION_DAYS = 60
FOLLOW_CAP = 450


def _d(x: date) -> str:
    return x.strftime("%d-%m-%Y")


def _day(s):
    s = str(s or "").strip()
    for fmt, n in (("%d-%b-%Y", 11), ("%d-%m-%Y", 10), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            pass
    return None


def _num(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


class Nse:
    def __init__(self):
        self.s = shp.session()
        self.calls = 0

    def json(self, url):
        for attempt in range(3):
            try:
                self.calls += 1
                r = self.s.get(url, headers={**shp.HEADERS, "Accept": "application/json"}, timeout=60)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (401, 403):
                    self.s = shp.session()
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2 * (attempt + 1))
        return None

    def text(self, url):
        try:
            self.calls += 1
            r = self.s.get(url, headers=shp.HEADERS, timeout=60)
            return r.content.decode("utf-8", "replace") if r.status_code == 200 else None
        except requests.RequestException:
            return None


# ------------------------------------------------------------------ market-wide NSE lists
def risk_lists(n: Nse) -> dict:
    out = {}
    asm = n.json(NSE + "reportASM") or {}
    for term, word in (("longterm", "ASM long-term"), ("shortterm", "ASM short-term")):
        block = asm.get(term) or {}
        rows = block.get("data") if isinstance(block, dict) else block
        for r in rows or []:
            sym = (r.get("symbol") or "").strip()
            if sym:
                stage = (r.get("asmSurvIndicator") or "").strip()
                out.setdefault(sym, []).append(word + (f" ({stage})" if stage else ""))
    for r in n.json(NSE + "reportGSM") or []:
        sym = (r.get("symbol") or "").strip()
        if sym:
            out.setdefault(sym, []).append("GSM stage " + str(r.get("gsmStage") or "").strip())
    ban = n.text(ARCH + "fo/fo_secban.csv") or ""
    for line in ban.splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1]:
            out.setdefault(parts[1], []).append("F&O ban")
    return out


def _norm(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    s = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp)\b", " ", s)
    return " ".join(s.split())


def pledges(n: Nse, today: date, names: dict, prior: dict) -> dict:
    body = n.json(NSE + f"corporate-pledgedata?index=equities&from_date={_d(today - timedelta(days=45))}&to_date={_d(today)}") or {}
    by_name = {_norm(v): k for k, v in (names or {}).items()}
    latest = {}
    for r in body.get("data") or []:
        sym = by_name.get(_norm(r.get("comName") or ""))
        pct = _num(r.get("percPromoterShares"))
        when = _day(r.get("broadcastDt") or r.get("disclosureToDate"))
        if sym and pct is not None and when and (sym not in latest or when > latest[sym][0]):
            latest[sym] = (when, pct)
    out = dict(prior)
    for sym, (when, pct) in latest.items():
        old = prior.get(sym) or {}
        prev = old.get("pct") if old.get("on") and old.get("on") < when.isoformat() else old.get("prev")
        out[sym] = {"pct": round(pct, 2), "on": when.isoformat(), "prev": prev,
                    "rising": prev is not None and pct > prev + 0.99}
    return out


def calendar(n: Nse, today: date) -> list:
    rows = n.json(NSE + f"corporate-board-meetings?index=equities&from_date={_d(today)}&to_date={_d(today + timedelta(days=45))}") or []
    by = {}                                     # one row per company and day: NSE lists the intimation and the results separately
    for r in rows if isinstance(rows, list) else []:
        d = _day(r.get("bm_date"))
        sym = (r.get("bm_symbol") or "").strip()
        p = (r.get("bm_purpose") or "").strip()
        if sym and d:
            ps = by.setdefault((d.isoformat(), sym), [])
            if p and "intimation" not in p.lower() and p not in ps:
                ps.append(p)
    out = [{"s": s, "d": d, "p": (", ".join(ps) or "Board meeting")[:80]} for (d, s), ps in by.items()]
    out.sort(key=lambda x: (x["d"], x["s"]))
    return out


def filings(n: Nse, today: date) -> list:
    rows = n.json(NSE + f"corporate-announcements?index=equities&from_date={_d(today - timedelta(days=3))}&to_date={_d(today)}") or []
    out = []
    for r in rows if isinstance(rows, list) else []:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        t = str(r.get("an_dt") or r.get("sort_date") or "")
        out.append({"s": sym, "t": t[:20], "h": (r.get("desc") or "").strip()[:90],
                    "x": " ".join(str(r.get("attchmntText") or "").split())[:180], "u": r.get("attchmntFile") or ""})
    return out


def insider(n: Nse, syms: list, today: date, prior: dict) -> dict:
    """{sym: {buy, sell, promoter_net (rupees, market trades only), rows:[latest 6]}} over INSIDER_DAYS."""
    cut = (today - timedelta(days=INSIDER_DAYS)).isoformat()
    out = {}
    for sym in syms:
        body = n.json(NSE + f"corporates-pit?index=equities&symbol={requests.utils.quote(sym)}")
        time.sleep(0.35)
        if body is None:
            if sym in prior:
                out[sym] = prior[sym]
            continue
        rows = []
        for r in body.get("data") or []:
            mode = str(r.get("acqMode") or "")
            if "market" not in mode.lower():
                continue                       # pledges, ESOPs, gifts, inter-se transfers: not a trade
            d = _day(r.get("acqfromDt") or r.get("date"))
            if not d or d.isoformat() < cut:
                continue
            before, after = _num(r.get("befAcqSharesNo")), _num(r.get("afterAcqSharesNo"))
            kind = str(r.get("tdpTransactionType") or "").title() or ("Buy" if (after or 0) >= (before or 0) else "Sell")
            rows.append({"d": d.isoformat(), "who": str(r.get("acqName") or "")[:60], "cat": str(r.get("personCategory") or "")[:30],
                         "k": "Buy" if kind.startswith("Buy") else "Sell", "v": _num(r.get("secVal")) or 0.0,
                         "id": str(r.get("did") or r.get("pid") or "") + d.isoformat() + str(r.get("acqName") or "")[:20]})
        rows.sort(key=lambda x: x["d"], reverse=True)
        buy = sum(x["v"] for x in rows if x["k"] == "Buy")
        sell = sum(x["v"] for x in rows if x["k"] == "Sell")
        prom = sum((x["v"] if x["k"] == "Buy" else -x["v"]) for x in rows if "promoter" in x["cat"].lower())
        if rows:
            out[sym] = {"buy": round(buy), "sell": round(sell), "promoter_net": round(prom), "n": len(rows), "rows": rows[:6]}
    return out


def _participant(text: str) -> dict | None:
    lines = [l for l in csv.reader(io.StringIO(text)) if l]
    if len(lines) < 3:
        return None
    head = [h.strip().strip('"').strip().lower() for h in lines[1]]

    def col(name):
        return head.index(name) if name in head else None
    want = {"fil": "future index long", "fis": "future index short", "cl": "option index call long",
            "pl": "option index put long", "cs": "option index call short", "ps": "option index put short"}
    out = {}
    for row in lines[2:]:
        who = row[0].strip().strip('"')
        if who.upper() == "TOTAL" or not who:
            continue
        out[who] = {k: _num(row[col(v)]) for k, v in want.items() if col(v) is not None and col(v) < len(row)}
    return out or None


def positions(n: Nse, today: date, prior: dict) -> dict:
    hist = dict(prior)
    d, tried, start = today, 0, n.calls          # its own allowance: the insider step has used ~450 calls by now
    while tried < 90 and len([k for k in hist if k >= (today - timedelta(days=POSITION_DAYS * 1.6)).isoformat()]) < POSITION_DAYS:
        d -= timedelta(days=1)
        tried += 1
        if d.weekday() >= 5 or d.isoformat() in hist:
            continue
        txt = n.text(ARCH + f"nsccl/fao_participant_oi_{d:%d%m%Y}.csv")
        rec = _participant(txt) if txt else None
        if rec:
            hist[d.isoformat()] = rec
        if n.calls - start > 90:
            break
    keep = sorted(hist)[-POSITION_DAYS:]
    return {k: hist[k] for k in keep}


# ------------------------------------------------------------------ figures from the library
FACTORS = [
    ("quality", [("roe", 1), ("roce", 1), ("net_margin", 1), ("operating_margin", 1), ("cfo_to_pat", 1), ("interest_cover", 1),
                 ("debt_to_equity", -1), ("profit_consistency_8q", 1), ("roe_avg_5y", 1), ("roe_min_5y", 1),
                 ("profitable_share_10y", 1), ("cfo_to_pat_5y", 1)], 8),
    ("growth", [("rev_yoy", 1), ("profit_yoy", 1), ("eps_yoy", 1), ("profit_run", 1), ("cfo_growth", 1), ("rev_cagr_5y", 1),
                ("profit_cagr_5y", 1), ("eps_cagr_5y", 1)], 5),
    ("value", [("pe", -1), ("pb", -1), ("ps", -1), ("dividend_yield", 1)], None),
    ("momentum", [("ret_3m", 1), ("ret_12m", 1), ("rel_strength_vs_index", 1), ("from_52w_high", 1)], None),
    ("ownership", [("promoter_change_yoy", 1), ("fii_change_qoq", 1), ("dii_change_qoq", 1), ("mf_schemes_added", 1),
                   ("pledge_pct", -1)], None),
]
POSITIVE_ONLY = {"pe", "pb", "ps"}


def _val(s, k):
    c = (s.get("cells") or {}).get(k)
    v = c.get("value") if isinstance(c, dict) else None
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return v if isinstance(v, (int, float)) and math.isfinite(v) else None


def _fii_ok(s):
    return (s.get("shp_v") or 0) >= 2


def _midrank(sorted_vals, v):
    import bisect
    lo, hi = bisect.bisect_left(sorted_vals, v), bisect.bisect_right(sorted_vals, v)
    return round((lo + (hi - lo) / 2) / len(sorted_vals) * 100) if sorted_vals else None


def factors(stocks: list) -> dict:
    """The dashboard's factor scores (relay/AdminPage.html computeFactors), same inputs and rules."""
    dist = {}
    for _, inputs, _ in FACTORS:
        for k, _d2 in inputs:
            if k not in dist:
                xs = [_val(s, k) for s in stocks if s.get("cells")]
                xs = [x for x in xs if x is not None and (k not in POSITIVE_ONLY or x > 0)]
                dist[k] = sorted(xs)
    out = {}
    for s in stocks:
        if not s.get("cells"):
            continue
        f = {}
        for key, inputs, base in FACTORS:
            xs = []
            for k, d in inputs:
                v = _val(s, k)
                if v is None or (k == "fii_change_qoq" and not _fii_ok(s)) or (k in POSITIVE_ONLY and v <= 0):
                    continue
                p = _midrank(dist[k], v)
                if p is not None:
                    xs.append(p if d > 0 else 100 - p)
            need = max(2, math.ceil((base or len(inputs)) / 2))
            f[key] = round(sum(xs) / len(xs)) if len(xs) >= need else None
        got = [f[k] for k, _, _ in FACTORS if f[k] is not None]
        f["composite"] = round(sum(got) / len(got)) if len(got) >= 4 else None
        out[s["symbol"]] = f
    return out


def _grade(p):
    for cut, g in ((90, "A+"), (80, "A"), (70, "A-"), (60, "B+"), (50, "B"), (40, "B-"), (30, "C+"), (20, "C"), (10, "D")):
        if p >= cut:
            return g
    return "F"


def grades(fac: dict, industries: dict) -> dict:
    """A+ to F per factor, ranked within the company's industry (5+ scored members), else within all companies."""
    keys = [k for k, _, _ in FACTORS] + ["composite"]
    groups = {}
    for sym in fac:
        groups.setdefault(industries.get(sym) or "", []).append(sym)
    out = {}
    allv = {k: sorted(v[k] for v in fac.values() if v.get(k) is not None) for k in keys}
    for ind, syms in groups.items():
        for k in keys:
            vals = sorted(fac[s][k] for s in syms if fac[s].get(k) is not None)
            pool = vals if ind and len(vals) >= 5 else allv[k]
            for s in syms:
                v = fac[s].get(k)
                if v is not None:
                    out.setdefault(s, {})[k[0] if k != "composite" else "c"] = _grade(_midrank(pool, v))
    return out


def valuation(stocks: list, industries: dict, today: date, hist: dict) -> tuple[dict, dict]:
    pes = {s["symbol"]: _val(s, "pe") for s in stocks}
    pes = {k: v for k, v in pes.items() if v is not None and 0 < v < 400}
    by_ind = {}
    for sym, pe in pes.items():
        by_ind.setdefault(industries.get(sym) or "", []).append(pe)

    def q(xs, f):
        xs = sorted(xs)
        i = (len(xs) - 1) * f
        lo = int(i)
        return round(xs[lo] + (xs[min(lo + 1, len(xs) - 1)] - xs[lo]) * (i - lo), 1)
    out, new_hist = {}, dict(hist)
    for sym, pe in pes.items():
        h = list(new_hist.get(sym) or [])
        if not h or (today - date.fromisoformat(h[-1][0])).days >= 7:
            h.append([today.isoformat(), round(pe, 1)])
        new_hist[sym] = h[-160:]                       # about 3 years of weekly points
        row = {"pe": round(pe, 1)}
        ind = industries.get(sym)
        peers = by_ind.get(ind or "", [])
        if ind and len(peers) >= 5:
            row["ind"] = [q(peers, .25), q(peers, .5), q(peers, .75)]
        own = [p for _, p in h]
        if len(own) >= 8:
            row["own"] = [min(own), q(own, .5), max(own), len(own)]
        out[sym] = row
    return out, new_hist


def heatmap(stocks: list, industries: dict, prices: dict) -> list:
    out = []
    for s in stocks:
        sym = s["symbol"]
        ind = industries.get(sym)
        mcap = _val(s, "market_value_bucket")
        if not ind or not mcap:
            continue
        ser = (prices.get(sym) or ([], [], []))[0]
        d1 = round((ser[-1][1] / ser[-2][1] - 1) * 100, 2) if len(ser) >= 2 and ser[-2][1] else None
        out.append({"s": sym, "i": ind, "m": round(mcap), "d1": d1, "m1": _val(s, "ret_1m"), "dd": _val(s, "from_52w_high")})
    return out


def spikes(prices: dict, universe: set) -> list:
    out = []
    for sym, (ser, vol, deliv) in prices.items():
        if sym not in universe or len(ser) < 25 or len(vol) < 25:
            continue
        avg = sum(vol[-21:-1]) / 20
        if avg <= 0:
            continue
        x = vol[-1] / avg
        dl = deliv[-1] if deliv else None
        turnover = ser[-1][1] * vol[-1] / 1e7          # rupees crore
        if x >= 3 and (dl or 0) >= 50 and turnover >= 2:
            out.append({"s": sym, "x": round(x, 1), "dl": round(dl, 1), "d1": round((ser[-1][1] / ser[-2][1] - 1) * 100, 2),
                        "cr": round(turnover, 1)})
    out.sort(key=lambda r: -r["x"])
    return out[:40]


def superstars(lib: dict) -> list:
    by = {}
    for sym, ms in (lib.get("investor_matches") or {}).items():
        for m in ms if isinstance(ms, list) else []:
            inv = m.get("investor") or m.get("name")
            if inv:
                by.setdefault(inv, []).append({"s": sym, "pct": m.get("pct") or m.get("holding_pct"), "as": m.get("holder_name") or m.get("alias_matched"),
                                               "q": m.get("quarter")})
    status = {}
    try:
        status = {i["name"]: i.get("status") for i in json.loads(library.REGISTRY_FILE.read_text(encoding="utf-8")).get("investors", [])}
    except (OSError, ValueError):
        pass
    return sorted(({"name": k, "status": status.get(k, "unconfirmed"), "holdings": sorted(v, key=lambda x: -(x["pct"] or 0))}
                   for k, v in by.items()), key=lambda x: -len(x["holdings"]))


def iv_history() -> dict:
    """Day-before ATM straddle as % of the forward per index expiry (3 years, private expiry history) and the rank of the latest."""
    url = f"https://api.github.com/repos/{library.PRIVATE_REPO}/contents/state/expiry_history/records.json"
    try:
        r = requests.get(url, headers={**library._private_headers(), "Accept": "application/vnd.github.raw"}, timeout=60)
        recs = r.json() if r.status_code == 200 else {}
    except (requests.RequestException, ValueError):
        recs = {}
    out = {}
    for r in recs.values():
        if r.get("straddle") and r.get("forward"):
            out.setdefault(r["symbol"], []).append([r["expiry"], round(r["straddle"] / r["forward"] * 100, 3)])
    res = {}
    for idx, rows in out.items():
        rows.sort()
        vals = sorted(v for _, v in rows)
        last = rows[-1][1]
        res[idx] = {"rows": rows[-160:], "last": rows[-1], "rank": _midrank(vals, last)}
    return res


# ------------------------------------------------------------------ alerts
def _field(sym, k, s, fac, mb):
    if k == "composite" or k in [f for f, _, _ in FACTORS]:
        return (fac.get(sym) or {}).get(k)
    if k == "mb_score":
        r = mb.get(sym)
        return r.get("score") if r else None
    if k == "fii_change_qoq" and not _fii_ok(s):
        return None
    return _val(s, k)


def screen_members(screen: dict, stocks: list, fac: dict, mb: dict) -> set:
    conds = [c for c in screen.get("conditions") or [] if c.get("field") and c.get("op") in (">", "<", ">=", "<=") and _num(c.get("value")) is not None]
    if not conds:
        return set()
    ops = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
    out = set()
    for s in stocks:
        if not s.get("cells"):
            continue
        ok = True
        for c in conds:
            v = _field(s["symbol"], c["field"], s, fac, mb)
            if v is None or not ops[c["op"]](v, _num(c["value"])):
                ok = False
                break
        if ok:
            out.add(s["symbol"])
    return out


def price_events(prices: dict, syms: set) -> list:
    ev = []
    for sym in syms:
        ser = (prices.get(sym) or ([], [], []))[0]
        if len(ser) < 210:
            continue
        closes = [c for _, c in ser]
        last, prev = closes[-1], closes[-2]
        yr = closes[-253:-1]
        if last > max(yr):
            ev.append((sym, "high", "new 52-week high"))
        elif last < min(yr):
            ev.append((sym, "low", "new 52-week low"))
        sma_now, sma_prev = sum(closes[-200:]) / 200, sum(closes[-201:-1]) / 200
        if prev <= sma_prev and last > sma_now:
            ev.append((sym, "dma_up", "crossed above its 200-day average"))
        elif prev >= sma_prev and last < sma_now:
            ev.append((sym, "dma_down", "fell below its 200-day average"))
    return ev


def relay_context() -> dict:
    url, key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    if not url or not key:
        return {}
    try:
        r = requests.get(url, params={"mode": "batch_context", "key": key}, timeout=60)
        body = r.json()
        return body if isinstance(body, dict) and not body.get("error") else {}
    except (requests.RequestException, ValueError):
        return {}


def send_push(alerts: list) -> dict:
    """One notification for the new alerts (hub/push.py's keys and subscriptions)."""
    from . import push as P
    url, key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    if not alerts or not url or not key:
        return {"sent": 0}
    st = P.push_state(url, key)
    if "error" in st:
        return {"sent": 0, "reason": "push_state"}
    P._mask(st.get("vapid_private_key") or "")
    priv, _keys, st = P.resolve_keys(url, key, st)
    P._mask(priv)
    subs = st.get("subscriptions") or []
    if not priv or not subs:
        return {"sent": 0, "reason": "no key or no device"}
    body = "; ".join(f"{a['s']} {a['t']}" for a in alerts[:3]) + (f"; +{len(alerts) - 3} more" if len(alerts) > 3 else "")
    payload = {"title": f"Market Hub: {len(alerts)} alert" + ("s" if len(alerts) > 1 else ""), "body": body[:180], "url": PHONE_URL + "#alerts"}
    sent, gone = 0, []
    for sub in subs:
        res = P.send_to(sub, payload, priv)
        sent += res == "sent"
        if res == "gone":
            gone.append(sub["endpoint"])
    P.drop_endpoints(url, key, gone)
    return {"sent": sent, "devices": len(subs)}


# ------------------------------------------------------------------ main
def main() -> dict:
    t0 = time.time()
    today = datetime.now(config.IST).date()
    lib, _sha = library.fetch_existing()
    stocks = [s for s in lib.get("stocks", []) if isinstance(s, dict) and s.get("symbol")]
    by_sym = {s["symbol"]: s for s in stocks}
    industries = dict(lib.get("industries") or {})
    names = dict(lib.get("names") or {})
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    try:
        mb = {r["symbol"]: r for r in json.loads(MB_FILE.read_text(encoding="utf-8")).get("ranked", []) if r.get("symbol")}
    except (OSError, ValueError):
        mb = {}
    try:
        sl = json.loads(SL_FILE.read_text(encoding="utf-8"))
        shortlist = {x["symbol"] for L in (sl.get("lists") or {}).values() for x in (L.get("top") or []) + (L.get("next") or [])}
    except (OSError, ValueError, KeyError, TypeError):
        shortlist = set()
    ctx = relay_context()
    watch = set(ctx.get("watchlist") or [])
    holdings = {h.get("s") for h in ctx.get("holdings") or [] if h.get("s")}
    screens = ctx.get("screens") or []
    registry_syms = set((lib.get("investor_matches") or {}).keys())
    mb4 = {s for s, r in mb.items() if r.get("score") == 4}
    big = {s["symbol"] for s in sorted(stocks, key=lambda s: -(_val(s, "market_value_bucket") or 0))[:150]}
    followed = list(dict.fromkeys(sorted(holdings) + sorted(watch) + sorted(shortlist) + sorted(mb4) + sorted(registry_syms) + sorted(big)))
    followed = [s for s in followed if s in by_sym][:FOLLOW_CAP]
    personal = holdings | watch | shortlist

    n = Nse()
    log = {}

    def step(name, fn, default):
        try:
            v = fn()
            log[name] = "ok"
            return v
        except Exception as e:                       # one source failing never stops the others
            log[name] = "failed: " + str(e)[:100]
            return default
    risk = step("risk", lambda: risk_lists(n), st.get("risk") or {})
    pledge = step("pledge", lambda: pledges(n, today, names, st.get("pledge") or {}), st.get("pledge") or {})
    cal = step("calendar", lambda: calendar(n, today), [])
    fil = step("filings", lambda: filings(n, today), [])
    ins = step("insider", lambda: insider(n, followed, today, st.get("insider") or {}), st.get("insider") or {})
    pos = step("positions", lambda: positions(n, today, st.get("positions") or {}), st.get("positions") or {})

    factors_ = {}
    prices = {}
    try:
        pf = json.loads((config.REPO / "state" / "library_state.json").read_text(encoding="utf-8")).get("price_factors") or {}
        prices = bhav.load({s: [(date.fromisoformat(e), f) for e, f in ev] for s, ev in pf.items()}, today)
        log["prices"] = f"{len(prices)} companies"
    except Exception as e:
        log["prices"] = "failed: " + str(e)[:100]
    fac = step("factors", lambda: factors(stocks), {})
    grd = step("grades", lambda: grades(fac, industries), {})
    val, pe_hist = step("valuation", lambda: valuation(stocks, industries, today, st.get("pe_hist") or {}), ({}, st.get("pe_hist") or {}))
    heat = step("heatmap", lambda: heatmap(stocks, industries, prices), [])
    spk = step("spikes", lambda: spikes(prices, set(by_sym)), [])
    stars = step("superstars", lambda: superstars(lib), [])
    iv = step("iv", iv_history, {})

    # Alerts for followed companies. Each has a stable key, so it is pushed once.
    alerts = []

    def add(sym, kind, text, key=None):
        alerts.append({"s": sym, "k": kind, "t": text, "id": key or f"{today.isoformat()}:{sym}:{kind}", "mine": sym in personal})
    for sym, kind, text in price_events(prices, set(followed)):
        add(sym, kind, text)
    results_words = ("financial result", "outcome of board meeting")
    for f in fil:
        if f["s"] in personal and any(w in f["h"].lower() for w in results_words):
            add(f["s"], "results", "filed: " + f["h"][:60], f"res:{f['s']}:{f['t'][:10]}")
    for sym, r in ins.items():
        for row in r.get("rows") or []:
            if "promoter" in row["cat"].lower() and row["d"] >= (today - timedelta(days=7)).isoformat():
                add(sym, "insider_" + row["k"].lower(), f"promoter {'bought' if row['k'] == 'Buy' else 'sold'} ₹{row['v'] / 1e7:.2f} cr", "ins:" + row["id"])
    prior_risk = st.get("risk") or {}
    for sym in followed:
        new = [x for x in risk.get(sym) or [] if x not in (prior_risk.get(sym) or [])]
        if new and prior_risk:
            add(sym, "risk", "now under " + ", ".join(new))
        p = pledge.get(sym) or {}
        if p.get("rising"):
            add(sym, "pledge", f"promoter pledge up to {p['pct']}%", f"pledge:{sym}:{p.get('on')}")
    members = {}
    prior_members = st.get("screens") or {}
    for sc in screens:
        name = str(sc.get("name") or "")[:60]
        cur = screen_members(sc, stocks, fac, mb)
        members[name] = sorted(cur)
        if name in prior_members:
            was = set(prior_members[name])
            for sym in sorted(cur - was)[:10]:
                add(sym, "screen_in", f"entered your screen \"{name}\"")
            for sym in sorted(was - cur)[:10]:
                add(sym, "screen_out", f"left your screen \"{name}\"")
    seen = set(st.get("alerted") or [])
    fresh = [a for a in alerts if a["id"] not in seen]
    push_result = step("push", lambda: send_push([a for a in fresh if a["mine"] or a["k"].startswith("screen")]), {"sent": 0})

    payload = {
        "generated": datetime.now(config.IST).isoformat(timespec="minutes"),
        "risk": risk, "pledge": {k: v for k, v in pledge.items() if v.get("pct", 0) > 0},
        "calendar": cal, "filings": fil, "insider": ins, "positions": pos,
        "spikes": spk, "heatmap": heat, "grades": grd, "valuation": val, "superstars": stars, "iv": iv,
        "factors": {k: v for k, v in fac.items() if v.get("composite") is not None},
        "alerts": alerts, "screens": {k: len(v) for k, v in members.items()},
        "industries": {s: i for s, i in industries.items() if s in by_sym},
        "followed": len(followed),
        "log": log,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    st.update({"risk": risk, "pledge": pledge, "insider": ins, "positions": pos, "pe_hist": pe_hist, "screens": members,
               "alerted": sorted(seen | {a["id"] for a in alerts})[-3000:]})
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, separators=(",", ":")), encoding="utf-8")
    return {"seconds": round(time.time() - t0), "nse_calls": n.calls, "followed": len(followed), "alerts": len(alerts),
            "new_alerts": len(fresh), "push": push_result, "log": log, "bytes": OUT_FILE.stat().st_size}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=str))
