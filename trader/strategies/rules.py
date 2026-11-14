"""
A strategy from the dashboard's strategy builder (14 Nov 2026): a plain dictionary, checked here by clean() (the same
rules as the builder page), then run by Rules.

    {"id", "name", "index": "NIFTY"|"BANKNIFTY", "side": "BUY"|"SELL", "right": "C"|"P",
     "strike": {"mode": "atm", "steps": 0}  (steps out of the money; negative = in the money)
             | {"mode": "premium", "near": 100}  (the strike whose price is nearest),
     "expiry": "nearest"|"next"|"monthly", "lots": 1,
     "window": {"from": "09:30", "until": "14:30"},
     "groups": [{"match": "all"|"any", "signals": [ ... trader/indicators.py ... ]}, ...],
     "groups_match": "any"|"all",      (enter when any / all of the groups are true: "(A and B) or (C and D)")
     (older strategies: "match" + "signals" = one group)
     "exits": {"sl_type": "pct"|"points", "sl", "target_type", "target", "trail_after_type", "trail_after",
               "trail_type", "trail", "exit_by": "HH:MM"|None, "validity": "DAY"|"GTC"},
     "style": "intraday"|"carry", "max_trades_day": 2, "max_loss_day": 5000, "reentry_gap": 15}

Intraday = day-only stop and an exit-by time; carry = good-till-cancelled stop, held overnight.
One position at a time per strategy; a new entry only once that is closed, the re-entry gap has passed, and the day's
trade and loss limits allow it.
"""
from datetime import date, datetime

from ..indicators import COMPARE_OPS, OPERANDS, check, completed
from ..model import LOT, Contract, OrderRequest
from ..regime import REGIMES, classify

SIGNALS = {"price_ma", "ma_cross", "rsi", "orb", "change", "dte", "weekday", "compare"}
MAX_GROUPS, MAX_SIGNALS = 5, 8


def _num(x, lo, hi, default):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi)


def _hhmm(x, default):
    x = str(x or "")
    return x if len(x) == 5 and x[2] == ":" and x[:2].isdigit() and x[3:].isdigit() and "09:15" <= x <= "15:30" else default


def clean(d: dict) -> dict:
    """The strategy as the program will run it: unknown fields dropped, numbers kept inside sensible bounds."""
    st = d.get("strike") or {}
    ex = d.get("exits") or {}
    style = "carry" if d.get("style") == "carry" else "intraday"
    groups = d.get("groups")
    if not isinstance(groups, list) or not groups:
        groups = [{"match": d.get("match"), "signals": d.get("signals") or []}]
    groups = [{"match": "any" if (g or {}).get("match") == "any" else "all",
               "signals": [x for x in (_signal(y) for y in (g or {}).get("signals") or []) if x][:MAX_SIGNALS]}
              for g in groups[:MAX_GROUPS]]
    groups = [g for g in groups if g["signals"]]
    return {
        "id": str(d.get("id") or "")[:40], "name": str(d.get("name") or "Unnamed")[:80],
        "index": d.get("index") if d.get("index") in ("NIFTY", "BANKNIFTY") else "NIFTY",
        "side": "SELL" if d.get("side") == "SELL" else "BUY", "right": "P" if d.get("right") == "P" else "C",
        "strike": ({"mode": "premium", "near": _num(st.get("near"), 1, 5000, 100)} if st.get("mode") == "premium"
                   else {"mode": "atm", "steps": int(_num(st.get("steps"), -10, 20, 0))}),
        "expiry": d.get("expiry") if d.get("expiry") in ("nearest", "next", "monthly") else "nearest",
        "lots": int(_num(d.get("lots"), 1, 50, 1)),
        "window": {"from": _hhmm((d.get("window") or {}).get("from"), "09:30"),
                   "until": _hhmm((d.get("window") or {}).get("until"), "14:30")},
        "groups": groups, "groups_match": "all" if d.get("groups_match") == "all" else "any",
        "conditions": [c for c in (d.get("conditions") or []) if c in REGIMES],     # autopilot: "Suited to"
        "exits": {"sl_type": "points" if ex.get("sl_type") == "points" else "pct", "sl": _num(ex.get("sl"), 0, 1000, 25),
                  "target_type": "points" if ex.get("target_type") == "points" else "pct",
                  "target": _num(ex.get("target"), 0, 5000, 0),
                  "trail_after_type": "points" if ex.get("trail_after_type") == "points" else "pct",
                  "trail_after": _num(ex.get("trail_after"), 0, 5000, 20),
                  "trail_type": "points" if ex.get("trail_type") == "points" else "pct",
                  "trail": _num(ex.get("trail"), 0, 1000, 10),
                  "exit_by": _hhmm(ex.get("exit_by"), "15:15") if style == "intraday" else None,
                  "validity": "DAY" if style == "intraday" else "GTC"},
        "style": style,
        "max_trades_day": int(_num(d.get("max_trades_day"), 1, 50, 2)),
        "max_loss_day": _num(d.get("max_loss_day"), 0, 1e7, 5000),
        "reentry_gap": int(_num(d.get("reentry_gap"), 0, 375, 15)),
    }


def _operand(o) -> dict | None:
    if not isinstance(o, dict) or o.get("src") not in OPERANDS:
        return None
    out = {"src": o["src"]}
    if o["src"] == "value":
        out["value"] = _num(o.get("value"), -1e9, 1e9, 0)
    if o["src"] in ("ema", "sma", "rsi", "atr", "adx", "orb_high", "orb_low"):
        out["n"] = int(_num(o.get("n"), 1, 500, 15 if o["src"].startswith("orb") else 14))
    return out


def _signal(x) -> dict | None:
    if not isinstance(x, dict) or x.get("type") not in SIGNALS:
        return None
    if x["type"] == "compare":
        left, right = _operand(x.get("left")), _operand(x.get("right"))
        op = x.get("op") if x.get("op") in COMPARE_OPS else ">"
        if not left or not right:
            return None
        if op.startswith("crosses") and "opt_price" in (left["src"], right["src"]):
            op = ">" if op == "crosses_above" else "<"      # the option price has no history to cross on
        tf = int(x.get("tf")) if str(x.get("tf")) in ("1", "3", "5", "15") else 5
        return {"type": "compare", "left": left, "op": op, "right": right, "tf": tf}
    return {k: v for k, v in x.items() if isinstance(v, (str, int, float, list))}


def pick_expiry(expiries: list[str], today: date, which: str) -> str | None:
    ahead = sorted(e for e in expiries if e >= today.isoformat())
    if not ahead:
        return None
    if which == "next":
        return ahead[1] if len(ahead) > 1 else None
    if which == "monthly":
        month = ahead[0][:7]
        same = [e for e in ahead if e[:7] == month]
        return same[-1]
    return ahead[0]


class Rules:
    def __init__(self, d: dict):
        self.d = clean(d)
        self.id, self.name = self.d["id"], self.d["name"]
        self.day, self.trades, self.last_entry = None, 0, None
        self.mine: set[Contract] = set()
        self.idx = self.d["index"]

    def _new_day(self, now: datetime):
        if self.day != now.date():
            self.day, self.trades, self.last_entry = now.date(), 0, None

    def _spot(self, view) -> float | None:
        bars = view.feed.index_bars(self.idx)
        return bars[-1][4] if bars else None

    def _expiry(self, view) -> str | None:
        return pick_expiry(view.feed.expiries(self.idx), view.now.date(), self.d["expiry"])

    def _ladder(self, view, e: str):
        ks = view.feed.strikes(self.idx, e)
        spot = self._spot(view)
        if not ks or spot is None:
            return [], None, None
        i = min(range(len(ks)), key=lambda i: abs(ks[i] - spot))
        return ks, i, spot

    def wants(self, view) -> set[Contract]:
        e = self._expiry(view)
        if not e:
            return set()
        ks, i, _ = self._ladder(view, e)
        if i is None:
            return set()
        if self.d["strike"]["mode"] == "atm":
            n = self.d["strike"]["steps"]
            j = i + n if self.d["right"] == "C" else i - n
            pick = range(max(0, j - 2), min(len(ks), j + 3))
        else:
            pick = range(max(0, i - 12), min(len(ks), i + 13))
        return {Contract(self.idx, e, ks[j], self.d["right"]) for j in pick}

    def _contract(self, view, e: str) -> Contract | None:
        ks, i, _ = self._ladder(view, e)
        if i is None:
            return None
        if self.d["strike"]["mode"] == "atm":
            n = self.d["strike"]["steps"]
            j = i + n if self.d["right"] == "C" else i - n
            if not 0 <= j < len(ks):
                return None
            return Contract(self.idx, e, ks[j], self.d["right"])
        target = self.d["strike"]["near"]
        have = [(c, q.mid) for c, q in view.quotes.items()
                if c.index == self.idx and c.expiry == e and c.right == self.d["right"] and q.mid]
        return min(have, key=lambda x: abs(x[1] - target))[0] if have else None

    def step(self, view) -> list[OrderRequest]:
        now, d = view.now, self.d
        self._new_day(now)
        hhmm = now.strftime("%H:%M")
        if not (d["window"]["from"] <= hhmm <= d["window"]["until"]):
            return []
        if any(view.book.qty.get(c) for c in self.mine):
            return []                                       # one position at a time
        if self.trades >= d["max_trades_day"]:
            return []
        if d["max_loss_day"] and view.book.pnl() <= -d["max_loss_day"]:
            return []
        if self.last_entry and (now - self.last_entry).total_seconds() < 60 * d["reentry_gap"]:
            return []
        e = self._expiry(view)
        if not e or not d["groups"]:
            return []                                       # no signals: never enters on its own
        c = self._contract(view, e)
        q = view.quotes.get(c) if c else None
        if not c or not q or not q.mid:
            return []
        bars = completed(view.feed.index_bars(self.idx), now)
        ctx, pc = {"opt_price": q.mid}, view.feed.prev_close(self.idx)
        met, words = [], []
        for g in d["groups"]:
            res = [check(sg, bars, now, pc, e, ctx) for sg in g["signals"]]
            ok = all(r for r, _ in res) if g["match"] == "all" else any(r for r, _ in res)
            met.append(ok)
            if ok:
                words.append(" & ".join(w for r, w in res if r or g["match"] == "all"))
        if not (all(met) if d["groups_match"] == "all" else any(met)):
            return []
        self.trades += 1
        self.last_entry = now
        self.mine.add(c)
        why = f"{self.name}: " + " | ".join(words)
        reg, _ = classify(bars, now, e)
        return [OrderRequest(c, d["side"], d["lots"], None, why[:300], tag=f"s:{self.id}", exits=d["exits"], regime=reg)]
