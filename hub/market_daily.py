"""
Daily market history for the strategy bot and the strategy builder's market signals (14 Nov 2026, owner: step 1 of the
strategy bot -- IV percentile, India VIX, FII positions, put-call ratio, open interest). Free NSE end-of-day files only
(the same three hub/expiry_history.py reads), one entry per trading day from 3 Jan 2022, so a one-year percentile is
ready from 2023 and every back-test period (Jan 2024 on) is covered.

state/market/daily.json (private repo) = {"YYYY-MM-DD": {
    "vix": India VIX close, "vix_chg": % change on the day,
    "fii" / "client" / "dii" / "pro": {fut, call, put} net long share of all index futures / calls / puts (participant
        file; + = net long), e.g. fii.fut = -0.32: FIIs short 32% of index futures open interest,
    "NIFTY" / "BANKNIFTY": {close, expiry (the one read: the nearest with 2+ days to go), dte, atm, iv (ATM implied
        volatility, % a year, from the ATM call and put closes), straddle, pcr (put / call OI within 3% of the index,
        that expiry), pcr_all (all strikes, all expiries), oi_calls, oi_puts (all expiries), oi_chg (% change in total
        option OI on the day), max_pain, call_wall, put_wall},
    then filled in after: "NIFTY".iv_pct / "BANKNIFTY".iv_pct = share of the previous 252 sessions with a lower IV (0-100),
    vix_pct the same for VIX }, ...}
Values are each day's CLOSE: a strategy reads the previous session's entry (known before the open), never the day's own.
Holidays are kept as {"holiday": true} once a week old, so they are not asked for again.

    python -m hub.market_daily                 (BUDGET requests, default 1500 = about 500 days; START default 2022-01-03)
Run on GitHub (NSE blocks the owner's laptop): market-daily.yml (the backfill, chains itself until done) and the
daily job's step (each evening's new day).
"""
import math
import os
import sys
from datetime import date, datetime, timedelta

from . import config
from .expiry_history import (IDX, NSE_SYMS, Nse, _b76, chain_stats, load, parse_index, parse_participant, save)

PATH = "state/market/daily.json"
FLOWS = "state/market/flows.json"           # 14 Nov 2026: the market diary's figures by session (see flows())
START = date(2022, 1, 3)
LOOKBACK = 252


def parse_vix(text: str) -> tuple | None:
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if cells and cells[0].lower() == "india vix":
            try:                         # Index Name, Index Date, Open, High, Low, Close, Points Change, Change(%), ...
                return float(cells[5]), float(cells[7])
            except (ValueError, IndexError):
                return None
    return None


def implied_vol(price: float, F: float, K: float, years: float, call: bool) -> float | None:
    """Annual volatility (%) that prices this option (Black-76, no discounting), by bisection; None if unpriceable."""
    if price <= 0 or years <= 0:
        return None
    root = math.sqrt(years)
    lo, hi = 1e-4, 3.0 * root
    if _b76(F, K, hi, call) < price or _b76(F, K, lo, call) > price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _b76(F, K, mid, call) < price else (lo, mid)
    return round((lo + hi) / 2 / root * 100, 2)


def index_entry(chains: dict, d: date, spot: float) -> dict | None:
    exps = sorted(e for e in chains if e >= d.isoformat())
    near = next((e for e in exps if (date.fromisoformat(e) - d).days >= 2), None)
    if not near:
        return None
    st = chain_stats(chains[near], spot)
    if not st:
        return None
    dte = (date.fromisoformat(near) - d).days
    row = chains[near][st["atm"]]
    F, K, years = st["forward"], st["atm"], dte / 365.0
    ivs = [v for v in (implied_vol(row[0], F, K, years, True), implied_vol(row[1], F, K, years, False)) if v]
    calls = sum(v[2] for c in chains.values() for v in c.values())
    puts = sum(v[3] for c in chains.values() for v in c.values())
    return {"close": spot, "expiry": near, "dte": dte, "atm": K, "iv": round(sum(ivs) / len(ivs), 2) if ivs else None,
            "straddle": st["straddle"], "pcr": round(st["puts_oi"] / st["calls_oi"], 3) if st["calls_oi"] else None,
            "pcr_all": round(puts / calls, 3) if calls else None, "oi_calls": int(calls), "oi_puts": int(puts),
            "max_pain": st["max_pain"], "call_wall": st["call_wall"], "put_wall": st["put_wall"]}


def day(nse: Nse, d: date) -> dict | None:
    """One session's entry, or None (no F&O file: a holiday, or not published yet)."""
    fo = nse.fo_day(d)
    if not fo:
        return None
    out = {}
    raw = nse.get(f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv")
    text = raw.decode("utf-8", "replace") if raw else ""
    ix = parse_index(text) if text else {}
    v = parse_vix(text) if text else None
    if v:
        out["vix"], out["vix_chg"] = v
    po = nse.participant(d)
    for g, k in (("FII", "fii"), ("Client", "client"), ("DII", "dii"), ("Pro", "pro")):
        if po and po.get(g):
            out[k] = po[g]
    for s in NSE_SYMS:
        spot = (ix.get(s) or (None,) * 4)[3]
        if spot and fo.get(s):
            e = index_entry(fo[s], d, spot)
            if e:
                out[s] = e
    return out


def derive(hist: dict) -> None:
    """Fills iv_pct, vix_pct and oi_chg from the stored sessions (cheap; run over everything each time)."""
    days = sorted(k for k, v in hist.items() if not v.get("holiday"))
    series = {s: [] for s in NSE_SYMS}
    vix = []
    prev = None
    for k in days:
        e = hist[k]
        for s in NSE_SYMS:
            x = e.get(s)
            if not x:
                continue
            past = [v for v in series[s][-LOOKBACK:] if v is not None]
            x["iv_pct"] = round(100 * sum(1 for v in past if v < x["iv"]) / len(past), 1) if x.get("iv") and len(past) >= 120 else None
            p = (hist[prev].get(s) if prev else None) or {}
            tot, ptot = x["oi_calls"] + x["oi_puts"], (p.get("oi_calls") or 0) + (p.get("oi_puts") or 0)
            x["oi_chg"] = round((tot / ptot - 1) * 100, 2) if ptot else None
            series[s].append(x.get("iv"))
        if e.get("vix") is not None:
            past = vix[-LOOKBACK:]
            e["vix_pct"] = round(100 * sum(1 for v in past if v < e["vix"]) / len(past), 1) if len(past) >= 120 else None
            vix.append(e["vix"])
        prev = k


def _chg(x) -> float | None:
    v = (x or {}).get("change_pct") if isinstance(x, dict) else None
    return round(float(v), 2) if isinstance(v, (int, float)) else None


def flows() -> dict:
    """The daily job's market diary (hub/context.py, state/market_diary.json; kept since 14 Nov 2026) and the morning
    news score (hub/news_score.py, state/news_score_log.json) as one table by session date, for strategy signals and
    the research bot: fii_cash / dii_cash (net rupees crore, that session), sp500_chg / nasdaq_chg (the US session that
    evening), crude_chg / gold_chg / usdinr_chg (% on the day, MCX / currency futures at the daily job's time), and
    news_score (-2..+2, that MORNING's headlines up to 09:00: known before the open of its own day)."""
    out = {}
    for k, e in (load("state/market_diary.json") or {}).items():
        if not isinstance(e, dict):
            continue
        day, row = k, {}
        for f in e.get("fii_dii") or []:
            try:
                day = datetime.strptime(f.get("date", ""), "%d-%b-%Y").date().isoformat()
            except ValueError:
                pass
            if str(f.get("category", "")).startswith("FII") and isinstance(f.get("net"), (int, float)):
                row["fii_cash"] = round(f["net"], 2)
            elif f.get("category") == "DII" and isinstance(f.get("net"), (int, float)):
                row["dii_cash"] = round(f["net"], 2)
        g = e.get("global") or {}
        row["sp500_chg"], row["nasdaq_chg"] = _chg(g.get("S&P 500")), _chg(g.get("Nasdaq Composite"))
        com = e.get("commodities") or {}
        row["gold_chg"] = next((_chg(v) for n, v in com.items() if n.lower().startswith("gold")), None)
        cu = e.get("crude_usd")
        row["crude_chg"] = cu.get("change_pct") if isinstance(cu, dict) else None
        if row["crude_chg"] is None:
            row["crude_chg"] = next((_chg(v) for n, v in com.items() if n.lower().startswith("crude")), None)
        row["usdinr_chg"] = _chg(e.get("usd_inr_live"))
        out.setdefault(day, {}).update({k2: v for k2, v in row.items() if v is not None})
    for n in load("state/news_score_log.json") or []:
        if isinstance(n, dict) and n.get("date") and isinstance(n.get("score"), (int, float)):
            out.setdefault(n["date"], {})["news_score"] = n["score"]
    return out


def main() -> int:
    start = date.fromisoformat(os.getenv("START") or START.isoformat())
    budget = int(os.getenv("BUDGET") or 1500)
    today = datetime.now(config.IST).date()
    end = today if datetime.now(config.IST).hour >= 19 else today - timedelta(days=1)   # files are out by ~18:30
    hist = load(PATH) or {}
    todo, d = [], start
    while d <= end:
        if d.weekday() < 5 and d.isoformat() not in hist:
            todo.append(d)
        d += timedelta(days=1)
    print(f"market history: {len(hist)} days stored, {len(todo)} to fetch ({start} to {end}), budget {budget} requests")
    nse, got, holidays = Nse(), 0, 0
    try:
        for d in todo:
            if nse.requests + 3 > budget:
                print("budget reached; the next run carries on")
                break
            e = day(nse, d)
            if e is None:
                if (today - d).days > 7:
                    hist[d.isoformat()] = {"holiday": True}
                    holidays += 1
                continue
            hist[d.isoformat()] = e
            got += 1
            if got % 50 == 0:
                print(f"  {d}: {got} sessions so far, {nse.requests} requests", flush=True)
    except RuntimeError as exc:                      # NSE refusing: keep what was collected
        print(f"::warning::NSE stopped the run early: {str(exc)[:160]}")
    derive(hist)
    left = sum(1 for d in todo if d.isoformat() not in hist and (today - d).days > 7)
    save(PATH, hist, f"market history: {len(hist)} days")
    fl = flows()
    save(FLOWS, fl, f"market flows: {len(fl)} days")
    last = max((k for k, v in hist.items() if not v.get("holiday")), default=None)
    e = hist.get(last) or {}
    n = e.get("NIFTY") or {}
    print(f"saved: {got} new sessions, {holidays} holidays; {left} older weekdays still to fetch; {nse.requests} requests")
    if last:
        print(f"latest {last}: VIX {e.get('vix')} ({e.get('vix_pct')} pct); NIFTY IV {n.get('iv')}% ({n.get('iv_pct')} pct), "
              f"PCR {n.get('pcr')}, FII futures {((e.get('fii') or {}).get('fut'))}")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"more={'true' if left else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
