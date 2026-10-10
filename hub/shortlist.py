"""
Shortlist (11 Oct 2026): the strongest companies of the two screens, as two lists by style, recorded
weekly so the engine's own track record can be measured. Computed in the daily library run and
published as site/shortlist.json (the dashboard only displays it); weekly records and every stint on a
list are kept in state/shortlist_history.json.

  Compounders  passes all six Proven-compounder rules. Ranked for quality at a sensible price.
  Emerging     passes all four Early-multibagger gates and is not a compounder. Ranked for growth that
               the market is starting to recognise.

Why two lists: the screens answer different questions (steady, widely held vs early, under-owned); one
league table with a bonus for being in both tilted the list to the large and steady.

Common filters: enough data (35+ testable measures), tradable (Rs 2 cr+ average daily turnover, or Rs
1,000 cr+ market value when turnover is missing), operating cash at least 0.6x profit, pledge at most 5%.
At most 2 companies per industry in each list, so one sector's good quarter cannot fill it. Industry is
NSE's (NIFTY Total Market list) or the sector map; smaller companies often have neither, and the cap
cannot apply to them.

Momentum, in the spirit of NSE's Nifty200 Momentum 30 (6- and 12-month price returns relative to
volatility), with the latest month skipped as in the academic literature -- the last month tends to
reverse, so it is shown only as a "stretched" warning, never as a reason to rank higher:
    mom = average of (6-month return to a month ago, 12-month return to a month ago) / 1-year volatility
then expressed as a percentile across the library.

Track record: one record a week (the first run of each ISO week). A stint starts when a company enters a
list's top N and ends when it leaves; its return from the entry close is compared with NIFTY 50 over the
same dates. "Core" means on the list in 3+ consecutive weekly records.

A ranked screen of the owner's own rules, not a recommendation.
"""
import json
import math
from datetime import date

from . import config

LIST_SIZE = 8
PER_INDUSTRY = 2
CORE_WEEKS = 3
HISTORY_FILE = config.REPO / "state" / "shortlist_history.json"
OUT_FILE = config.SITE_DIR / "data" / "shortlist.json"

COMPOUNDER_RULES = (
    ("Profit grew in 6+ of last 8 quarters", lambda v: v("profit_consistency_8q") is not None and v("profit_consistency_8q") >= 6),
    ("Net margin >= 8%", lambda v: v("net_margin") is not None and v("net_margin") >= 8),
    ("Operating cash >= 0.8x profit", lambda v: v("cfo_to_pat") is not None and v("cfo_to_pat") >= 0.8),
    ("Held by 30+ fund schemes", lambda v: v("mf_schemes_holding") is not None and v("mf_schemes_holding") >= 30),
    ("Promoter pledge <= 5%", lambda v: v("pledge_pct") is None or v("pledge_pct") <= 5),
    ("Market cap >= Rs 5,000 cr", lambda v: v("market_value_bucket") is not None and v("market_value_bucket") >= 5000),
)
# Same factor definitions as the dashboard's factor rankings, except momentum (see the module note).
FACTORS = {
    "quality": [("roe", 1), ("roce", 1), ("net_margin", 1), ("operating_margin", 1), ("cfo_to_pat", 1),
                ("interest_cover", 1), ("debt_to_equity", -1), ("profit_consistency_8q", 1)],
    "growth": [("rev_yoy", 1), ("profit_yoy", 1), ("eps_yoy", 1), ("profit_run", 1), ("cfo_growth", 1)],
    "value": [("pe", -1), ("pb", -1), ("ps", -1), ("dividend_yield", 1)],
    "ownership": [("promoter_change_yoy", 1), ("fii_change_qoq", 1), ("dii_change_qoq", 1),
                  ("mf_schemes_added", 1), ("pledge_pct", -1)],
}
POSITIVE_ONLY = {"pe", "pb", "ps"}
WEIGHTS = {
    "compounders": {"quality": .35, "value": .25, "growth": .15, "momentum": .15, "ownership": .10},
    "emerging": {"growth": .35, "momentum": .25, "quality": .20, "value": .10, "ownership": .10},
}
WHY = (
    ("roe", "ROE", lambda v: f"{v:.1f}%", 1), ("roce", "ROCE", lambda v: f"{v:.1f}%", 1),
    ("net_margin", "Net margin", lambda v: f"{v:.1f}%", 1),
    ("profit_consistency_8q", "Profit up in", lambda v: f"{v:.0f} of the last 8 quarters", 1),
    ("profit_yoy", "Profit growth", lambda v: f"{v:+.1f}%", 1), ("rev_yoy", "Revenue growth", lambda v: f"{v:+.1f}%", 1),
    ("cfo_to_pat", "Operating cash", lambda v: f"{v:.2f}x profit", 1), ("debt_to_equity", "Debt/equity", lambda v: f"{v:.2f}", -1),
    ("interest_cover", "Interest cover", lambda v: "over 50x (practically debt-free)" if v > 50 else f"{v:.1f}x", 1),
    ("mf_schemes_added", "Fund schemes added", lambda v: f"+{v:.0f}", 1),
    ("dii_change_qoq", "Domestic institutions", lambda v: f"+{v:.2f} pts", 1),
)


def _rnd(x):
    return int(math.floor(x + 0.5))


class Dist:
    """Percentile (mid-rank for ties) of a measure across the library, as the dashboard computes it."""
    def __init__(self, stocks, value):
        self.value, self.stocks, self.cache = value, stocks, {}

    def _arr(self, k):
        if k not in self.cache:
            vals = [self.value(s, k) for s in self.stocks]
            arr = sorted(x for x in vals if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                         and (k not in POSITIVE_ONLY or x > 0))
            self.cache[k] = arr
        return self.cache[k]

    def pct(self, k, v):
        import bisect
        a = self._arr(k)
        if not a or not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        below, upto = bisect.bisect_left(a, v), bisect.bisect_right(a, v)
        return _rnd((below + (upto - below) / 2) / len(a) * 100)


def momentum_measures(series) -> dict:
    """mom raw score, 1-month return, distance from 52-week high, and DMA trend, from adjusted closes."""
    closes = [c for _, c in series]
    out = {}
    if len(closes) < 130:
        return out
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(max(1, len(closes) - 252), len(closes))
            if closes[i] and closes[i - 1]]
    vol = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * math.sqrt(252) if len(rets) > 30 else None
    skip = closes[-22]
    parts = []
    if len(closes) > 147 and closes[-148]:
        parts.append(skip / closes[-148] - 1)          # 6 months to a month ago
    if len(closes) > 273 and closes[-274]:
        parts.append(skip / closes[-274] - 1)          # 12 months to a month ago
    if parts and vol:
        out["mom"] = sum(parts) / len(parts) / vol
    out["ret_1m"] = (closes[-1] / closes[-22] - 1) * 100 if closes[-22] else None
    if len(closes) >= 200:
        out["above_50"] = closes[-1] > sum(closes[-50:]) / 50
        out["above_200"] = closes[-1] > sum(closes[-200:]) / 200
    hi = max(closes[-252:])
    out["off_high"] = (closes[-1] / hi - 1) * 100 if hi else None
    out["last"] = closes[-1]
    return out


FIGURES = ("roe", "net_margin", "rev_yoy", "profit_yoy", "profit_consistency_8q", "promoter_holding",
           "fii_holding", "dii_holding", "pledge_pct", "mf_schemes_holding", "debt_to_equity")


def build(stocks: list[dict], mb_by_sym: dict, industries: dict, prices: dict, nifty: dict,
          today: date, names: dict | None = None) -> dict:
    by_sym = {s["symbol"]: s for s in stocks if s.get("cells")}

    def value(s, k):
        c = (s.get("cells") or {}).get(k)
        return c.get("value") if c else None

    def fii_ok(s):
        return (s.get("shp_v") or 0) >= 2

    dist = Dist(list(by_sym.values()), value)
    moms = {sym: momentum_measures(prices[sym][0]) for sym in by_sym if sym in prices and prices[sym][0]}
    mom_sorted = sorted(m["mom"] for m in moms.values() if m.get("mom") is not None)

    def mom_pct(x):
        import bisect
        if x is None or not mom_sorted:
            return None
        lo, hi = bisect.bisect_left(mom_sorted, x), bisect.bisect_right(mom_sorted, x)
        return _rnd((lo + (hi - lo) / 2) / len(mom_sorted) * 100)

    def factor(s, key):
        if key == "momentum":
            return mom_pct(moms.get(s["symbol"], {}).get("mom"))
        xs = []
        for k, d in FACTORS[key]:
            v = value(s, k)
            if v is None or (k == "fii_change_qoq" and not fii_ok(s)) or (k in POSITIVE_ONLY and v <= 0):
                continue
            p = dist.pct(k, v)
            if p is not None:
                xs.append(p if d > 0 else 100 - p)
        need = max(2, math.ceil(len(FACTORS[key]) / 2))
        return _rnd(sum(xs) / len(xs)) if len(xs) >= need else None

    # industry P/E medians
    groups = {}
    for sym, s in by_sym.items():
        pe, ind = value(s, "pe"), industries.get(sym) or s.get("sector")
        if ind and isinstance(pe, (int, float)) and pe > 0:
            groups.setdefault(ind, []).append(pe)
    ind_pe = {k: sorted(v)[len(v) // 2] for k, v in groups.items() if len(v) >= 5}
    vol_pct = lambda s: dist.pct("volatility_60d", value(s, "volatility_60d"))

    pools = {"compounders": [], "emerging": []}
    left_out = {"compounders": [], "emerging": []}
    for sym, s in by_sym.items():
        v = lambda k, s=s: value(s, k)
        comp = all(rule(v) for _, rule in COMPOUNDER_RULES)
        mb = mb_by_sym.get(sym) or {}
        style = "compounders" if comp else ("emerging" if mb.get("score") == 4 else None)
        if not style:
            continue
        turnover, mcap = v("avg_turnover_20d"), v("market_value_bucket")
        drop = ("too little data" if (s.get("testable") or 0) < 35 else
                "hard to trade (under Rs 2 cr a day)" if (turnover < 2 if turnover is not None else not (mcap or 0) >= 1000) else
                "promoter pledge over 5%" if (v("pledge_pct") or 0) > 5 else
                "operating cash under 0.6x profit" if v("cfo_to_pat") is not None and v("cfo_to_pat") < 0.6 else None)
        if drop:
            left_out[style].append({"symbol": sym, "reason": drop})
            continue
        f = {k: factor(s, k) for k in ("quality", "growth", "value", "momentum", "ownership")}
        m = moms.get(sym, {})
        ind = industries.get(sym) or s.get("sector") or ""
        pe, ipe = v("pe"), ind_pe.get(ind)
        why, watch = [], []
        # Sanity: growth far beyond what a company of this size normally reports is usually a one-off or a
        # data problem (OFSS +68.7% revenue, 10 Oct); a profit jump over 200% is usually a low base. Such
        # growth is not rewarded: the growth score is held at neutral and the company flagged.
        rg, pg = v("rev_yoy"), v("profit_yoy")
        suspect = False
        chk = s.get("check") or {}
        if chk.get("status") == "mismatch":
            suspect = True
            watch.append("BharatStock disagreed with the company's NSE filing (" + "; ".join(chk.get("diffs") or []) + "); the NSE figures are used")
        elif chk.get("status") != "ok" and mcap and mcap >= 20000 and ((rg or 0) > 40 or (pg or 0) > 80):
            # Not yet confirmed against the filing: unusually fast growth for the size is held at neutral.
            suspect = True
            watch.append("Growth this fast is unusual for a company this size and not yet confirmed against its NSE filing")
        if pg is not None and pg > 200:
            suspect = True
            watch.append(f"Profit up {pg:.0f}% on a year ago: likely a low base or one-off")
        severe = [f["text"] for f in s.get("flags") or [] if f.get("level") == "severe"]
        if severe:
            suspect = True
            score_penalty = 4
            watch.extend(severe)
        else:
            score_penalty = 0
        if suspect and f["growth"] is not None:
            f["growth"] = min(f["growth"], 50)
        financial = "financial" in ind.lower() or "bank" in ind.lower()
        if financial:
            watch.append("Bank / financial: operating cash flow and net margin are not comparable with other companies; judge on asset quality and returns")
        w = WEIGHTS[style]
        score = sum(w[k] * (f[k] if f[k] is not None else 50) for k in w) - score_penalty
        if pe and pe > 0 and ipe and pe > 1.5 * ipe:
            score -= 6
            watch.append(f"P/E {pe:.1f}x against an industry median of {ipe:.1f}x")
        if (vol_pct(s) or 0) >= 90:
            score -= 4
            watch.append(f"Volatile: 60-day volatility {v('volatility_60d'):.0f}%")
        if m.get("off_high") is not None and m["off_high"] < -35:
            score -= 4
            watch.append(f"{-m['off_high']:.0f}% below its 52-week high")
        if (v("promoter_change_yoy") or 0) < -2:
            score -= 4
            watch.append(f"Promoters sold {-v('promoter_change_yoy'):.2f} pts in a year")
        if fii_ok(s) and (v("fii_change_qoq") or 0) <= -1:
            watch.append(f"Foreign investors cut {-v('fii_change_qoq'):.2f} pts last quarter")
        if m.get("ret_1m") is not None and m["ret_1m"] > 20:
            watch.append(f"Up {m['ret_1m']:.0f}% in a month: stretched. Recent spikes tend to cool; momentum here is measured over 6-12 months")
        if m.get("above_200") is False:
            watch.append("Below its 200-day average")
        cands = []
        for k, label, fmt, b in WHY:
            x = v(k)
            if x is None or (k in ("dii_change_qoq", "mf_schemes_added") and x <= 0) or (k == "profit_yoy" and x > 200):
                continue
            if (suspect and k in ("rev_yoy", "profit_yoy")) or (financial and k in ("cfo_to_pat", "net_margin", "interest_cover")):
                continue
            p = dist.pct(k, x)
            if p is None:
                continue
            r = p if b > 0 else 100 - p
            if r >= 80:
                cands.append((r, f"{label} {fmt(x)} - better than {r}% of the library"))
        why = [t for _, t in sorted(cands, reverse=True)[:4]]
        if f["momentum"] is not None and f["momentum"] >= 80:
            why.append(f"Sustained momentum: 6-12 month trend, adjusted for volatility, better than {f['momentum']}% of the library")
        if m.get("above_50") and m.get("above_200") and m.get("off_high") is not None and m["off_high"] > -10:
            why.append(f"Trend intact: above its 50- and 200-day averages, within {-m['off_high']:.0f}% of its 52-week high")
        if pe and pe > 0 and ipe and pe < 0.8 * ipe:
            why.append(f"Valued below its industry: P/E {pe:.1f}x against a median of {ipe:.1f}x")
        if chk.get("status") == "ok":
            why.append(f"Results confirmed against the company's NSE filing (quarter to {chk.get('period')})")
        figs = {k: v(k) for k in FIGURES if v(k) is not None and (k != "fii_holding" or fii_ok(s))}
        check_note = ("Results match the company's NSE filing." if chk.get("status") == "ok" else
                      "BharatStock disagreed with the NSE filing; NSE figures used." if chk.get("status") == "mismatch" else
                      "BharatStock is behind; growth and margin from the latest NSE filing." if chk.get("status") == "period_differs" else "")
        pools[style].append({"symbol": sym, "name": (names or {}).get(sym, ""), "figures": figs, "check_note": check_note,
                             "industry": ind, "score": _rnd(score), "factors": f, "why": why,
                             "watch": watch, "ret_1m": m.get("ret_1m"), "last": m.get("last"),
                             "mcap": mcap, "pe": pe, "ret_12m": v("ret_12m")})

    lists = {}
    for style, items in pools.items():
        items.sort(key=lambda x: -x["score"])
        per, chosen, held_back = {}, [], []
        for x in items:
            key = x["industry"] or x["symbol"]
            if per.get(key, 0) >= PER_INDUSTRY:
                held_back.append(x)
                continue
            per[key] = per.get(key, 0) + 1
            chosen.append(x)
        for i, x in enumerate(chosen, 1):
            x["rank"] = i
        lists[style] = {"top": chosen[:LIST_SIZE], "ranked": len(items), "next": chosen[LIST_SIZE:LIST_SIZE + 12],
                        "industry_cap_held_back": [x["symbol"] for x in held_back[:20]],
                        "left_out": left_out[style]}
    return lists


def _week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def track(lists: dict, prices: dict, nifty: dict, today: date) -> dict:
    """Updates state/shortlist_history.json and returns the track record. A weekly record is taken on the
    first run of each ISO week; stints open when a company enters a list's top N in a weekly record and
    close when it is absent from the next one."""
    try:
        hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hist = {"weeks": [], "stints": []}
    last_close = lambda sym: prices[sym][0][-1][1] if sym in prices and prices[sym][0] else None
    n_days = sorted(nifty)
    n_now = nifty[n_days[-1]] if n_days else None

    def nifty_on(day):
        prior = [d for d in n_days if d <= day]
        return nifty[prior[-1]] if prior else None

    week = _week(today)
    if not hist["weeks"] or hist["weeks"][-1]["week"] != week:
        rec = {"week": week, "date": today.isoformat(), "lists": {}}
        for style, L in lists.items():
            rec["lists"][style] = [x["symbol"] for x in L["top"]]
        hist["weeks"].append(rec)
        open_ = {(st["style"], st["symbol"]): st for st in hist["stints"] if not st.get("exit_date")}
        for style, syms in rec["lists"].items():
            for sym in syms:
                if (style, sym) not in open_ and last_close(sym):
                    hist["stints"].append({"style": style, "symbol": sym, "entry_date": today.isoformat(),
                                           "entry_price": last_close(sym), "entry_nifty": n_now})
            for (st_style, sym), st in open_.items():
                if st_style == style and sym not in syms:
                    st["exit_date"], st["exit_price"], st["exit_nifty"] = today.isoformat(), last_close(sym), n_now
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(hist, separators=(",", ":")), encoding="utf-8")

    def perf(st):
        end_p = st.get("exit_price") if st.get("exit_date") else last_close(st["symbol"])
        end_n = st.get("exit_nifty") if st.get("exit_date") else n_now
        if not end_p or not st.get("entry_price") or not end_n or not st.get("entry_nifty"):
            return None
        r, n = (end_p / st["entry_price"] - 1) * 100, (end_n / st["entry_nifty"] - 1) * 100
        return {"ret": round(r, 2), "nifty": round(n, 2), "excess": round(r - n, 2)}

    def weeks_on(style, sym):
        n = 0
        for rec in reversed(hist["weeks"]):
            if sym in rec["lists"].get(style, []):
                n += 1
            else:
                break
        return n

    for style, L in lists.items():
        for x in L["top"]:
            st = next((s for s in hist["stints"] if s["style"] == style and s["symbol"] == x["symbol"]
                       and not s.get("exit_date")), None)
            x["weeks_on"] = weeks_on(style, x["symbol"])
            x["core"] = x["weeks_on"] >= CORE_WEEKS
            if st:
                x["entry_date"] = st["entry_date"]
                x["since_entry"] = perf(st)
    out = {"first_week": hist["weeks"][0]["date"] if hist["weeks"] else None, "weekly_records": len(hist["weeks"]), "styles": {}}
    for style in lists:
        ps = [(st, perf(st)) for st in hist["stints"] if st["style"] == style]
        ps = [(st, p) for st, p in ps if p]
        closed = [p for st, p in ps if st.get("exit_date")]
        allp = [p for _, p in ps]
        out["styles"][style] = {
            "stints": len(ps), "open": len(ps) - len(closed), "closed": len(closed),
            "avg_excess": round(sum(p["excess"] for p in allp) / len(allp), 2) if allp else None,
            "beat_nifty": sum(1 for p in allp if p["excess"] > 0),
            "closed_detail": [{"symbol": st["symbol"], "entry": st["entry_date"], "exit": st.get("exit_date"), **p}
                              for st, p in ps if st.get("exit_date")][-20:],
        }
    return out


def publish(stocks, mb_by_sym, industries, prices, nifty, today, generated, names=None) -> dict:
    lists = build(stocks, mb_by_sym, industries, prices, nifty, today, names)
    record = track(lists, prices, nifty, today)
    payload = {"generated": generated, "list_size": LIST_SIZE, "per_industry": PER_INDUSTRY, "core_weeks": CORE_WEEKS,
               "weights": WEIGHTS, "lists": lists, "track_record": record}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {k: {"ranked": v["ranked"], "top": [x["symbol"] for x in v["top"]]} for k, v in lists.items()}
