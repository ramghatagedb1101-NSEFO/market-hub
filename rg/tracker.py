"""
tracker.py — persistent recommendation log, admission control, and P&L scoring.

On every run the orchestrator calls:
  1. evaluate_closed(settle_fn)   — settle any recommendation whose expiry has
     passed, computing realised P&L from the credit-spread payoff at expiry.
  2. open_sector_counts(...)      — what the OPEN book already holds per sector,
     so the concentration cap can be enforced across runs, not just within one.
  3. record_new(recommendations)  — append this run's picks as OPEN.
  4. month_to_date_report(mark_fn)— MTD P&L: realised for settled positions,
     live mark-to-market for open ones.

Two valuations, never interchangeable (both live in mtm.py):
  settled  -> mtm.settlement_pnl_per_share, the payoff at expiry, a function of
              the underlying alone. Realised, final.
  open     -> mtm.mark_position, every leg repriced by Black-Scholes at the
              current spot, its own live IV, and the REMAINING time to expiry.

Open positions used to be marked with the settlement payoff too, which reports
the whole credit as profit on day 0 — the spot is inside the profit zone at entry
by construction. See mtm's module docstring for the 17-Aug-2026 numbers.

ADMISSION CONTROL: record_new only accepts candidates carrying
`recommended is True`, the stamp strategy.generate_recommendations applies to the
post-cap list and to nothing else. The selection layer also builds several
COUNTERFACTUAL lists per run (the concentration diagnostic simulates lifting each
limit, and drop attribution re-ranks on pre-flag scores); every one of those is a
list of the same candidate dicts, so passing the wrong one would persist trades
the screen had explicitly rejected — with capital-at-risk attached and
indistinguishable from a real pick thereafter.
"""

import json
from datetime import date, datetime

from . import config, mtm


def _load() -> dict:
    if config.POSITIONS_FILE.exists():
        try:
            return json.loads(config.POSITIONS_FILE.read_text())
        except Exception:
            pass
    return {"positions": [], "last_run": None}


def _save(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.POSITIONS_FILE.write_text(json.dumps(data, indent=2))


def _pos_id(rec: dict, stamp: str) -> str:
    """
    Position id keyed on the FULL leg set. It used to read
    f"{short_strike}-{long_strike}", which on a condor is the put wing only — so
    a four-leg condor and a two-leg bull put spread on the same symbol and expiry
    produced the same id.
    """
    return (f"{rec['symbol']}|{rec['expiry']}|{rec['strategy']}|"
            f"{mtm.leg_signature(rec)}|{stamp[:10]}")


def open_positions() -> list:
    return [p for p in _load()["positions"] if p.get("status") == "OPEN"]


def open_position_keys() -> set:
    """
    {(symbol, expiry)} for the live book — the same identity `admission_reason`
    dedupes on at persistence time, surfaced here so the SELECTION layer can
    also see it. Without this, a symbol that is already OPEN but re-clears
    every gate this run still shows up as a "new" recommended card (record_new
    will correctly refuse to book it a second time, but the report card reads
    as a fresh trade, and — since strategy._apply_caps has no way to know it
    is redundant — it also occupies a sector-cap slot a genuinely new
    candidate could have used instead).
    """
    return {(p["symbol"], str(p["expiry"])) for p in open_positions()}


def open_sector_counts(sector_of) -> dict:
    """
    {sector: number of OPEN positions} for the live book.

    Fed to strategy._apply_caps so MAX_PER_SECTOR is a PORTFOLIO limit rather
    than a per-run one. Without it the cap only ever saw the current run's
    candidates, and consecutive runs quietly stacked one sector:

      17-Aug 11:00  BAJFINANCE (Financial Services) recommended, score 0.4756;
                    HDFCLIFE dropped — "sector cap: FINANCIAL SERVICES already at 1".
      17-Aug 11:13  re-run. BAJFINANCE now priced as a bull put spread, score
                    0.2551; HDFCLIFE as a condor, 0.2573. HDFCLIFE wins the slot
                    and is recorded — while BAJFINANCE is still OPEN from 11:00.

    Both runs applied the cap correctly to their own candidates. The book ended
    up holding ₹1,97,897 of capital-at-risk in one sector under a 1-per-sector
    rule, because neither run could see the other's position.
    """
    counts = {}
    for p in open_positions():
        sec = sector_of(p["symbol"])
        counts[sec] = counts.get(sec, 0) + 1
    return counts


def evaluate_closed(settle_fn) -> list:
    """
    Settle every OPEN position whose expiry has passed. settle_fn(position)
    returns (settlement_price, note) — the caller decides whether that is the
    exact expiry-day close or an evaluation-date spot proxy.
    Returns the list of positions settled on this run.
    """
    data = _load()
    today = date.today()
    just_settled = []
    for p in data["positions"]:
        if p.get("status") != "OPEN":
            continue
        try:
            exp = datetime.strptime(p["expiry"], "%Y-%m-%d").date()
        except Exception:
            continue
        if exp >= today:
            continue  # still live
        try:
            settle, note = settle_fn(p)
        except Exception:
            settle, note = 0, "settlement lookup failed"
        if not settle:
            continue
        pnl_share = mtm.settlement_pnl_per_share(p, settle)
        pnl_total = round(pnl_share * p["lot_size"] * p["lots"], 2)
        p["status"] = "WIN" if pnl_total >= 0 else "LOSS"
        p["settlement_spot"] = round(settle, 2)
        p["realized_pnl"] = pnl_total
        p["closed_on"] = str(today)
        p["eval_note"] = note
        just_settled.append(p)
    if just_settled:
        _save(data)
    return just_settled


def admission_reason(rec: dict, open_keys: set) -> str | None:
    """
    Why this candidate must NOT be persisted, or None to admit it. Pure — the
    whole gate in one testable function.

    Three independent checks, each closing a fault that has actually occurred:

      recommended    the candidate carries the post-cap stamp. Blocks every
                     counterfactual list the selection layer builds (see the
                     module docstring).
      structure      the legs decompose. A structure that cannot be decomposed
                     renders as the wrong trade for the rest of its life.
      duplicate      one live structure per (symbol, expiry). The key used to
                     include strategy and strikes, so the SAME name re-priced
                     into a different structure on a re-run — BAJFINANCE going
                     from iron condor to bull put spread between 11:00 and 11:13
                     on 17-Aug-2026 — would be admitted a second time, putting
                     two lots of capital-at-risk on one underlying.
    """
    if rec.get("recommended") is not True:
        return ("not stamped as recommended — refusing a candidate that did not "
                "come from the post-cap recommendation list")
    reason = mtm.structure_reason(rec)
    if reason:
        return f"unserialisable structure: {reason}"
    if (rec.get("symbol"), str(rec.get("expiry"))) in open_keys:
        return "already OPEN on this symbol/expiry"
    return None


def record_new(recommendations: list) -> dict:
    """
    Append this run's recommendations as OPEN, subject to admission_reason().

    Returns {"added", "skipped", "rejected", "notes"} — a dict, not a bare count,
    because a silent rejection here is exactly the failure mode the gate exists
    to surface. The caller is expected to print `notes`.
    """
    data = _load()
    stamp = datetime.now().isoformat()
    open_keys = {(p["symbol"], str(p["expiry"]))
                 for p in data["positions"] if p.get("status") == "OPEN"}
    result = {"added": 0, "skipped": 0, "rejected": 0, "notes": []}

    for rec in recommendations or []:
        reason = admission_reason(rec, open_keys)
        if reason:
            duplicate = reason.startswith("already OPEN")
            result["skipped" if duplicate else "rejected"] += 1
            result["notes"].append(f"{rec.get('symbol', '?')}: {reason}")
            continue
        entry = dict(rec)
        entry["id"] = _pos_id(rec, stamp)
        entry["recommended_on"] = stamp
        entry["status"] = "OPEN"
        entry["leg_signature"] = mtm.leg_signature(rec)
        data["positions"].append(entry)
        open_keys.add((rec["symbol"], str(rec["expiry"])))
        result["added"] += 1

    data["last_run"] = stamp
    _save(data)
    return result


def _mark_open(p: dict, mark_fn, cache: dict) -> dict:
    """Mark one open position, memoised per position id so a symbol held twice
    is not quoted twice."""
    key = p.get("id") or f"{p['symbol']}|{p['expiry']}|{mtm.leg_signature(p)}"
    if key not in cache:
        try:
            cache[key] = mark_fn(p)
        except Exception as e:
            cache[key] = {"ok": False, "mark_type": "mtm", "legs": [],
                          "mark_spot": None, "unrealised_total": None,
                          "clamped": False, "note": f"mark failed: {e}"}
    return cache[key] or {"ok": False, "note": "mark returned nothing"}


def month_to_date_report(mark_fn) -> dict:
    """
    Month-to-date performance: every strategy recommended in the current calendar
    month, valued at what it is worth NOW.

      settled trades -> realised P&L         (mark_type "realised")
      open trades    -> live mark-to-market  (mark_type "mtm"), i.e. credit
                        received minus the debit it would cost to close today

    mark_fn(position) -> the dict mtm.mark_position returns. Injected so this
    function stays testable without a Kite session.

    Return-on-capital is computed on the capital actually at risk across the
    month's positions, from REALISED + UNREALISED P&L. It previously divided the
    settlement-payoff mark by the same denominator, which on day 0 reported the
    full credit as return: 75.5% on 17-Aug-2026, on three positions opened that
    morning with 43 days to run.
    """
    data = _load()
    today = date.today()
    month_key = f"{today.year:04d}-{today.month:02d}"

    rows, cache, warnings = [], {}, []
    for p in data["positions"]:
        if str(p.get("recommended_on", ""))[:7] != month_key:
            continue
        row = dict(p)
        if p.get("status") in ("WIN", "LOSS"):
            row.update(pnl=p.get("realized_pnl", 0) or 0, mark_type="realised",
                       ref_spot=p.get("settlement_spot"), mark_ok=True,
                       debit_total=None, days_left=0, mark_note=p.get("eval_note", ""),
                       basis="payoff", clamped=False, pct_of_credit=None,
                       net_delta=None, net_theta=None)
        else:
            m = _mark_open(p, mark_fn, cache)
            row.update(pnl=(m.get("unrealised_total") or 0) if m.get("ok") else 0,
                       mark_type=m.get("mark_type", "mtm"),
                       ref_spot=m.get("mark_spot"),
                       mark_ok=bool(m.get("ok")),
                       debit_total=m.get("debit_total"),
                       days_left=m.get("days_left"),
                       mark_note=m.get("note", ""),
                       basis=m.get("basis"),
                       clamped=bool(m.get("clamped")),
                       pct_of_credit=m.get("pct_of_credit_captured"),
                       net_delta=m.get("net_delta"), net_theta=m.get("net_theta"),
                       legs_marked=m.get("legs", []))
            if not m.get("ok"):
                warnings.append(f"{p['symbol']}: {m.get('note') or 'mark unavailable'}")
            elif m.get("basis") != "market" or m.get("clamped"):
                warnings.append(f"{p['symbol']}: {m.get('note') or 'mark clamped to structure bounds'}")
        rows.append(row)

    rows.sort(key=lambda r: r.get("recommended_on", ""))
    closed = [r for r in rows if r["mark_type"] == "realised"]
    open_ = [r for r in rows if r["mark_type"] != "realised"]
    wins = [r for r in closed if (r.get("realized_pnl", 0) or 0) >= 0]
    realised = round(sum(r["pnl"] for r in closed), 2)
    unrealised = round(sum(r["pnl"] for r in open_), 2)
    total = round(realised + unrealised, 2)
    total_capital = round(sum(r.get("capital_at_risk", 0) or 0 for r in rows), 2)
    open_capital = round(sum(r.get("capital_at_risk", 0) or 0 for r in open_), 2)
    return {
        "month": month_key,
        "rows": rows,
        "count": len(rows),
        "closed": len(closed),
        "open": len(open_),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "realised_pnl": realised,
        "unrealised_pnl": unrealised,
        "total_pnl": total,
        "total_capital": total_capital,
        "open_capital": open_capital,
        "roc_pct": round(total / total_capital * 100, 1) if total_capital else 0.0,
        "unrealised_roc_pct": (round(unrealised / open_capital * 100, 1)
                               if open_capital else 0.0),
        "marks_failed": sum(1 for r in open_ if not r["mark_ok"]),
        "warnings": warnings,
    }


def summary() -> dict:
    """Aggregate performance across all settled recommendations."""
    data = _load()
    closed = [p for p in data["positions"] if p.get("status") in ("WIN", "LOSS")]
    open_ = [p for p in data["positions"] if p.get("status") == "OPEN"]
    wins = [p for p in closed if p["status"] == "WIN"]
    losses = [p for p in closed if p["status"] == "LOSS"]
    realized = round(sum(p.get("realized_pnl", 0) for p in closed), 2)
    deployed = round(sum(p.get("capital_at_risk", 0) for p in closed), 2)
    return {
        "total_recommended": len(data["positions"]),
        "open": len(open_),
        "closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        "realized_pnl": realized,
        "capital_deployed": deployed,
        "roi_pct": round(realized / deployed * 100, 1) if deployed else 0.0,
        "open_capital_at_risk": round(sum(p.get("capital_at_risk", 0) for p in open_), 2),
        "open_positions": open_,
        "closed_positions": sorted(closed, key=lambda p: p.get("closed_on", ""), reverse=True),
    }
