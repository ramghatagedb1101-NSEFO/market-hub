"""
The trades summary for the phone and dashboard "Auto trading" screens (14 Nov 2026, owner: "a screen on the admin
dashboard and the mobile app to see the trades summary and daily/monthly profit or loss").

Built only from the journals (one JSON line per event, trader/journal.py), so it survives restarts:
  trades    every round trip, first in first out per contract: entry and exit time and price, quantity, profit after
            both sides' charges, and why it closed (stop-loss, trailing stop, the strategy, close-all, expiry)
  days      profit booked each day (trades closed that day), trades, wins, losses
  months    the same by calendar month
  open      positions still held: quantity, entry, latest price, open profit, protection (stop / trailing)
  pending   orders still working at the broker (entries not filled yet, stop-losses, trailing stops), as of the last
            profit line
  status    running or not, strategy, stopped-for-the-day reason, last heard from; autopilot's latest pick
  by_strategy   profit, trades, won, best and worst trade per strategy (owner, 14 Nov 2026: "which strategy made the
            maximum profit and which strategy contributed to the losses"), largest profit first
  by_strategy_regime   the same split by the market condition at entry (autopilot's paper record)

    python -m trader.summary JOURNAL_DIR [--out file.json] [--publish]   (publish: private repo site/algo.json)
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WHY = {"stop": "Stop-loss", "trail": "Trailing stop", "close-all": "Closed: day stopped", "settle": "Expiry",
       "target": "Target", "time-exit": "Exit time"}


def read(dirpath: str) -> list[dict]:
    rows = []
    for f in sorted(Path(dirpath).glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    rows.sort(key=lambda r: r.get("t", ""))
    return rows


def exercise_stt(qty: int, value: float) -> float:
    """STT a buyer pays when an option settles in the money (0.15% of its value; hub/rule_test.py)."""
    return value * qty * 0.0015 if qty > 0 and value > 0 else 0.0


def _expiry(key: str) -> str:
    return key.split(" ")[1]


def strategy_of(tag: str) -> str:
    """Which strategy a trade belongs to, from its order tag: s:<id> (builder), condor-* (expiry condor), else other."""
    tag = tag or ""
    if tag.startswith("s:"):
        return tag[2:]
    if tag.startswith("condor"):
        return "expiry_condor"
    return "other"


def build(rows: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now()
    lots = defaultdict(list)          # contract -> open lots [qty signed, price, time, charge per unit, tag, regime]
    trades, marks, protect, stop_of = [], {}, {}, {}
    pending, pending_at = [], None
    status = {"strategy": None, "killed": None, "last": None, "started": None, "autopilot": None}
    names = {"expiry_condor": "Expiry condor", "other": "Other trades"}
    order_regime = {}                 # order id -> market condition at entry

    def close(key, qty_signed, px, t, fee, tag):
        """Match a fill against open lots of the other side; returns the quantity left over (opens a new lot)."""
        left, fee_unit = qty_signed, fee / abs(qty_signed) if qty_signed else 0.0
        while left and lots[key] and (lots[key][0][0] > 0) != (left > 0):
            lot = lots[key][0]
            n = min(abs(left), abs(lot[0]))
            sign = 1 if lot[0] > 0 else -1          # long lot: profit = exit - entry
            pnl = sign * (px - lot[1]) * n - (lot[3] + fee_unit) * n
            sid = strategy_of(lot[4])
            trades.append({"contract": key, "dir": "long" if sign > 0 else "short", "qty": n,
                           "entry_t": lot[2], "entry": round(lot[1], 2), "exit_t": t, "exit": round(px, 2),
                           "pnl": round(pnl, 2), "why": WHY.get(tag, "Strategy exit" if tag else "Exit"),
                           "entry_tag": lot[4], "strategy_id": sid, "regime": lot[5] if len(lot) > 5 else None})
            lot[0] -= sign * n
            left += sign * n
            if lot[0] == 0:
                lots[key].pop(0)
        return left

    for r in rows:
        k, t = r.get("kind"), r.get("t")
        status["last"] = t
        if r.get("strategy_id") and r.get("strategy"):
            names[r["strategy_id"]] = r["strategy"]
        if k == "start":
            status.update(strategy=r.get("strategy"), started=t, killed=None)
        elif k == "switch":
            status["strategy"] = r.get("strategy")
        elif k == "autopilot":
            status["autopilot"] = {k2: r.get(k2) for k2 in ("t", "regime", "regime_why", "strategy", "why")}
            status["strategy"] = r.get("strategy") or "watch only"
        elif k == "kill":
            status["killed"] = r.get("reason")
        if k == "order":
            if r.get("stop"):
                stop_of[r["contract"]] = r["stop"]
            if r.get("order"):
                order_regime[r["order"]] = r.get("regime")
            tag = r.get("tag") or ""
            if tag.startswith("s:") and tag[2:] not in names and ":" in (r.get("reason") or ""):
                names[tag[2:]] = r["reason"].split(":", 1)[0]
        elif k == "trail-on":
            protect[r["contract"]] = "Trailing stop"
        elif k == "fill":
            q = r["qty"] if r["side"] == "BUY" else -r["qty"]
            left = close(r["contract"], q, r["price"], t, r.get("charges", 0.0), r.get("tag", ""))
            if left:
                lots[r["contract"]].append([left, r["price"], t, r.get("charges", 0.0) / abs(q), r.get("tag", ""),
                                            order_regime.get(r.get("order"))])
                if r["side"] == "BUY" and r["contract"] in stop_of:
                    protect[r["contract"]] = f"Stop-loss at {stop_of[r['contract']]:g}"
        elif k == "mark":
            for key, v in (r.get("positions") or {}).items():
                marks[key] = v[1]
            if r.get("orders") is not None:
                pending, pending_at = r["orders"], t
        elif k == "settle":
            for key in [c for c in lots if c.startswith(r["index"] + " " + r["expiry"])]:
                strike, right = float(key.split(" ")[2][:-1]), key[-1]
                v = max(r["index_close"] - strike, 0) if right == "C" else max(strike - r["index_close"], 0)
                q = sum(l[0] for l in lots[key])
                close(key, -q, v, t, exercise_stt(q, v), "settle")

    today = now.date().isoformat()
    # Positions of an expiry that has passed with no exit in the journal: settled by the exchange; valued at the last
    # price seen (the journal has no index close on the machine).
    for key in [c for c in lots if lots[c] and _expiry(c) < today]:
        q, v = sum(l[0] for l in lots[key]), marks.get(key, 0.0)
        close(key, -q, v, _expiry(key) + "T15:30:00", exercise_stt(q, v), "settle")

    open_ = []
    for key, ls in sorted(lots.items()):
        q = sum(l[0] for l in ls)
        if not q:
            continue
        entry = sum(l[0] * l[1] for l in ls) / q
        mark = marks.get(key)
        open_.append({"contract": key, "qty": q, "entry": round(entry, 2), "mark": mark,
                      "pnl": round((mark - entry) * q, 2) if mark is not None else None,
                      "protection": protect.get(key) if q > 0 else None})

    days = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})
    for tr in trades:
        d = days[tr["exit_t"][:10]]
        d["pnl"] += tr["pnl"]
        d["trades"] += 1
        d["wins" if tr["pnl"] > 0 else "losses"] += 1
    day_list = [{"date": d, **{k: (round(v, 2) if k == "pnl" else v) for k, v in x.items()}} for d, x in sorted(days.items())]
    months = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "days_up": 0, "days_down": 0})
    for d in day_list:
        m = months[d["date"][:7]]
        m["pnl"] += d["pnl"]
        m["trades"] += d["trades"]
        m["days_up" if d["pnl"] > 0 else "days_down"] += 1
    month_list = [{"month": m, **{k: (round(v, 2) if k == "pnl" else v) for k, v in x.items()}} for m, x in sorted(months.items())]

    for tr in trades:
        tr["strategy"] = names.get(tr["strategy_id"], tr["strategy_id"])
    by = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "best": None, "worst": None})
    by_reg = defaultdict(lambda: defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0}))
    for tr in trades:
        b = by[tr["strategy_id"]]
        b["pnl"] += tr["pnl"]
        b["trades"] += 1
        b["wins"] += tr["pnl"] > 0
        b["best"] = tr["pnl"] if b["best"] is None else max(b["best"], tr["pnl"])
        b["worst"] = tr["pnl"] if b["worst"] is None else min(b["worst"], tr["pnl"])
        if tr.get("regime"):
            g = by_reg[tr["strategy_id"]][tr["regime"]]
            g["pnl"] += tr["pnl"]
            g["trades"] += 1
            g["wins"] += tr["pnl"] > 0
    by_strategy = sorted(({"id": k, "name": names.get(k, k), "pnl": round(v["pnl"], 2), "trades": v["trades"],
                           "wins": v["wins"], "best": v["best"], "worst": v["worst"],
                           "avg": round(v["pnl"] / v["trades"], 2)} for k, v in by.items()), key=lambda x: -x["pnl"])
    by_strategy_regime = {k: {r: {"pnl": round(x["pnl"], 2), "trades": x["trades"], "wins": x["wins"]} for r, x in v.items()}
                          for k, v in by_reg.items()}

    run, peak, dd = 0.0, 0.0, 0.0
    for d in day_list:
        run += d["pnl"]
        peak = max(peak, run)
        dd = min(dd, run - peak)
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    open_pnl = sum(p["pnl"] for p in open_ if p["pnl"] is not None)
    today_row = next((d for d in day_list if d["date"] == today), None)
    month_row = next((m for m in month_list if m["month"] == today[:7]), None)
    return {
        "asof": now.isoformat(timespec="minutes"),
        "account": "IBKR paper",
        "status": status,
        "today": {"booked": today_row["pnl"] if today_row else 0.0, "open": round(open_pnl, 2),
                  "trades": today_row["trades"] if today_row else 0},
        "month": {"booked": month_row["pnl"] if month_row else 0.0, "trades": month_row["trades"] if month_row else 0},
        "totals": {"booked": round(sum(t["pnl"] for t in trades), 2), "trades": len(trades), "wins": len(wins),
                   "losses": len(losses), "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
                   "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
                   "best": max((t["pnl"] for t in trades), default=None),
                   "worst": min((t["pnl"] for t in trades), default=None), "worst_drop": round(dd, 2)},
        "open": open_,
        "pending": pending,                      # orders still working as of the last profit line
        "pending_at": pending_at,
        "days": day_list,
        "months": month_list,
        "trades": list(reversed(trades)),        # newest first; every trade, no cut-off
        "by_strategy": by_strategy,
        "by_strategy_regime": by_strategy_regime,
    }


PUBLISHED = "site/algo.json"


def publish(s: dict) -> bool:
    """Save to the private repo for the phone and dashboard, unless only the time stamps changed in the last hour."""
    from hub.expiry_history import load, save
    old = load(PUBLISHED) or {}

    def same(x):
        st = {k: v for k, v in (x.get("status") or {}).items() if k != "last"}
        return {**{k: v for k, v in x.items() if k not in ("asof", "status")}, "st": st}

    fresh = old.get("asof") and (datetime.fromisoformat(s["asof"]) - datetime.fromisoformat(old["asof"])).total_seconds() < 3600
    if old and same(old) == same(s) and fresh:
        return False
    save(PUBLISHED, s, f"Auto trading summary: {s['totals']['trades']} trades")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args()
    s = build(read(a.dir))
    if a.out:
        Path(a.out).write_text(json.dumps(s, separators=(",", ":")), encoding="utf-8")
    saved = publish(s) if a.publish else False
    print(f"summary: {s['totals']['trades']} trades, {len(s['days'])} days, {len(s['open'])} open positions"
          f"{'; published' if saved else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
