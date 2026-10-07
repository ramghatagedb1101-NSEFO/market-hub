"""
Multi-bagger screen over every NSE equity (series EQ and BE), on BharatStock quarterly financials.

Every company with at least five consolidated quarters gets a rating: the number of the four gates it
passes (0 to 4). Failed gates are kept, not dropped, so microcaps are rated too. Ranking is by rating,
then by a recent turnaround in profit, then by fewer mutual fund holders (fresher names first).

Writes docs/data/multibagger.json with derived scores, ranks and gate results only.
Raw financial figures are used in memory and never written to disk or to the public repository,
because BharatStock's terms do not allow re-serving raw data without a separate licence.

Needs BHARATSTOCK_API_KEY (GitHub secret). Starter plan (3,000 requests a day) and above.
"""
import csv
import io
import json
import os
import time
from datetime import date, datetime, timedelta

import requests

from . import config

OUT_FILE = config.SITE_DIR / "data" / "multibagger.json"
EQUITY_LIST = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SERIES = {"EQ", "BE"}
EXCLUDED = {"ACC"}   # large cap, never scored
UA = {"User-Agent": "Mozilla/5.0 (market-hub; multibagger)"}
API = "https://bharatstockapi.com/v1/stocks/{t}/financials"
INSIDER = "https://bharatstockapi.com/v1/stocks/{t}/insider-trades"
MFH = "https://bharatstockapi.com/v1/stocks/{t}/mf-holdings"
MAX_PAGES = 20
# Field names only (never values), recorded so a missing input can be traced in the published file.
FIELDS = {"financials": [], "insider": [], "mf": []}
ENDPOINT_COUNTS = {"financials": 0, "insider": 0, "mf": 0}


def universe() -> list[str]:
    r = requests.get(EQUITY_LIST, headers=UA, timeout=30)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.text)))
    head = [h.strip().upper() for h in rows[0]]
    i_sym, i_ser = head.index("SYMBOL"), head.index("SERIES")
    syms = set()
    for row in rows[1:]:
        if len(row) > max(i_sym, i_ser) and row[i_ser].strip() in SERIES:
            s = row[i_sym].strip()
            if s:
                syms.add(s)
    return sorted(syms - EXCLUDED)


def _pages(url: str, key: str, params: dict | None = None) -> list[dict]:
    """Reads every page the API reports. A 404 means no data for that company."""
    out, page = [], 1
    while True:
        p = dict(params or {})
        if page > 1:
            p["page"] = page
        r = requests.get(url, params=p, headers={"X-API-Key": key}, timeout=30)
        if r.status_code == 404:
            return out
        r.raise_for_status()
        body = r.json()
        if isinstance(body, dict):
            rows = body.get("data", [])
            pag = body.get("pagination") or {}
        else:
            rows, pag = body, {}
        out.extend(rows)
        more = pag.get("has_next", page < (pag.get("total_pages") or 1))
        if not rows or not more or page >= MAX_PAGES:
            return out
        page += 1


def fetch(symbol: str, key: str) -> list[dict]:
    rows = _pages(API.format(t=symbol), key, {"period_type": "quarterly"})
    ENDPOINT_COUNTS["financials"] += 1
    if rows and not FIELDS["financials"]:
        FIELDS["financials"] = sorted(rows[0].keys())
    return rows


def fetch_insider(symbol: str, key: str) -> list[dict]:
    rows = _pages(INSIDER.format(t=symbol), key, {"promoters_only": "true"})
    ENDPOINT_COUNTS["insider"] += 1
    if rows and not FIELDS["insider"]:
        FIELDS["insider"] = sorted(rows[0].keys())
    return rows


def insider_signal(rows: list[dict], months: int = 6) -> dict:
    """Derived promoter signal over the last months: net shares bought or sold, and a flag.
    Field names are read defensively; a missing field is a gap, never a guess."""
    cutoff = date.today() - timedelta(days=30 * months)
    buys = sells = 0
    usable = 0
    for x in rows:
        d = x.get("transaction_date") or x.get("date") or x.get("trade_date")
        try:
            when = date.fromisoformat(str(d)[:10])
        except (TypeError, ValueError):
            continue
        if when < cutoff:
            continue
        qty = x.get("quantity") or x.get("qty") or x.get("shares")
        kind = str(x.get("transaction_type") or x.get("type") or x.get("mode") or "").lower()
        if qty is None or not kind:
            continue
        usable += 1
        if "acq" in kind or "buy" in kind:
            buys += float(qty)
        elif "disp" in kind or "sell" in kind:
            sells += float(qty)
    if usable == 0:
        return {"status": "no usable promoter trades in window", "net_shares": None, "flag": None}
    net = buys - sells
    return {"status": "ok", "trades": usable, "bought_shares": buys, "sold_shares": sells,
            "net_shares": net, "flag": "promoter buying" if net > 0 and buys > sells else
                                       ("promoter selling" if sells > buys else "neutral")}


def fetch_mf(symbol: str, key: str) -> list[dict]:
    rows = _pages(MFH.format(t=symbol), key)
    ENDPOINT_COUNTS["mf"] += 1
    if rows and not FIELDS["mf"]:
        FIELDS["mf"] = sorted(rows[0].keys())
    return rows


def mf_counts(rows: list[dict]) -> dict:
    """Counts only, published. Named schemes are used in memory and never written out."""
    held = set()
    added = reduced = 0
    net = 0.0
    usable = 0
    for x in rows:
        name = x.get("scheme_name") or x.get("scheme") or x.get("scheme_code")
        chg = x.get("quantity_change")
        if name is None:
            continue
        held.add(name)
        if chg is None:
            continue
        usable += 1
        chg = float(chg)
        net += chg
        if chg > 0: added += 1
        elif chg < 0: reduced += 1
    if not held:
        return {"status": "no mutual fund holdings returned"}
    return {"status": "ok" if usable else "holdings found, no month-on-month change field",
            "schemes_holding": len(held), "schemes_added": added, "schemes_reduced": reduced,
            "net_quantity_change": net if usable else None}


def _consolidated(rows: list[dict]) -> list[dict]:
    rows = [x for x in rows if (x.get("consolidation_type") or "consolidated") == "consolidated"]
    return sorted(rows, key=lambda x: x["period_end_date"], reverse=True)


def score(symbol: str, rows: list[dict]) -> dict:
    """Derived measures only. The rating is the number of gates passed (0 to 4); failed gates are
    listed, not dropped. Fewer than five quarters means no rating at all."""
    q = _consolidated(rows)
    out = {"symbol": symbol, "quarters": len(q), "gates": {}, "measures": {}, "gaps": [], "score": None}
    if len(q) < 5:
        out["gaps"].append("fewer than five consolidated quarters")
        return out
    latest, year_ago = q[0], q[4]

    def growth(a, b):
        # A percentage needs a positive base. From a loss, the change is a gap, not a fail.
        if a is None or b is None or b <= 0:
            return None
        return (a / b - 1) * 100

    def better_than_last_year(i):
        """Profit is positive and above the same quarter a year earlier. Unlike a percentage, this
        reads correctly when last year's profit was a loss."""
        a = q[i].get("net_profit")
        b = q[i + 4].get("net_profit")
        if a is None or b is None:
            return None
        return a > 0 and a > b

    rev_g = growth(latest.get("revenue"), year_ago.get("revenue"))
    pat_g = growth(latest.get("net_profit"), year_ago.get("net_profit"))
    eps_g = growth(latest.get("eps"), year_ago.get("eps"))
    yoy_profit_quarters = 0
    flags = []
    for i in range(min(8, len(q) - 4)):
        g = growth(q[i].get("net_profit"), q[i + 4].get("net_profit"))
        if g is not None and g > 0:
            yoy_profit_quarters += 1
        flags.append(better_than_last_year(i))
    run = 0
    for f in flags:
        if f:
            run += 1
        else:
            break
    turned = 1 <= run <= 4 and any(f is False for f in flags[run:])
    cfo_ratio = None
    if latest.get("cash_flow_operating") is not None and latest.get("net_profit"):
        cfo_ratio = latest["cash_flow_operating"] / latest["net_profit"]
    margin = None
    if latest.get("revenue") and latest.get("net_profit") is not None:
        margin = latest["net_profit"] / latest["revenue"] * 100
    out["measures"] = {
        "revenue_growth_yoy_pct": _r(rev_g),
        "profit_growth_yoy_pct": _r(pat_g),
        "eps_growth_yoy_pct": _r(eps_g),
        "profit_growth_quarters_of_last_8": yoy_profit_quarters,
        "profit_growth_run_quarters": run,
        "turnaround": turned,
        "net_margin_pct": _r(margin),
        "operating_cash_to_profit": _r(cfo_ratio, 2),
    }
    # Gates: a gate that cannot be tested is a gap, never a pass.
    out["gates"] = {
        "revenue_growing": None if rev_g is None else rev_g > 10,
        "profit_growing": None if pat_g is None else pat_g > 15,
        "profit_consistent": yoy_profit_quarters >= 6,
        "cash_backed": None if cfo_ratio is None else cfo_ratio >= 0.8,
    }
    out["gaps"] = [k for k, v in out["gates"].items() if v is None]
    out["failed_gates"] = [k for k, v in out["gates"].items() if v is False]
    out["score"] = sum(1 for v in out["gates"].values() if v)
    return out


def _r(x, d=1):
    return None if x is None else round(x, d)


def main() -> dict:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    names = universe()
    results, failures = [], []
    for sym in names:
        try:
            rows = fetch(sym, key)
            res = score(sym, rows)
            # Fund and promoter data only for companies rated 2 or more: it saves about two thirds of the calls.
            if res.get("score") is not None and res["score"] >= 2:
                try:
                    ins = fetch_insider(sym, key)
                    res["promoter"] = insider_signal(ins)
                except Exception as exc:
                    res["promoter"] = {"status": f"insider fetch failed: {str(exc)[:80]}"}
                try:
                    res["mutual_funds"] = mf_counts(fetch_mf(sym, key))
                except Exception as exc:
                    res["mutual_funds"] = {"status": f"fund fetch failed: {str(exc)[:80]}"}
            results.append(res)
        except Exception as exc:
            failures.append({"symbol": sym, "error": str(exc)[:120]})
        time.sleep(0.2)

    def holders(r):
        mf = r.get("mutual_funds") or {}
        return mf.get("schemes_holding") if mf.get("schemes_holding") is not None else 10 ** 6

    rated = [r for r in results if r.get("score") is not None]
    ranked = sorted(rated, key=lambda r: (r["score"],
                                          r["measures"].get("turnaround", False),
                                          -holders(r),
                                          r["measures"].get("profit_growth_yoy_pct") or -1e9),
                    reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    out = {
        "ts": datetime.now(config.IST).isoformat(timespec="minutes"),
        "universe": len(names),
        "scored": len(results),
        "rated": len(rated),
        "not_rated_few_quarters": len(results) - len(rated),
        "rated_all_four_gates": sum(1 for r in ranked if r["score"] == 4),
        "turnarounds": sum(1 for r in ranked if r["measures"].get("turnaround")),
        "failures": failures,
        "endpoint_fields": FIELDS,
        "endpoint_calls": ENDPOINT_COUNTS,
        "ranked": ranked,
        "note": "Derived ratings and gates only. A gate with missing data is a gap, never a pass. "
                "Ranking: rating, then recent turnaround, then fewer mutual fund holders.",
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {k: v for k, v in out.items() if k != "ranked"}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
