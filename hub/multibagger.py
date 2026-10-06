"""
Multi-bagger screen for NSE Midcap 150 and Smallcap 250 names, on BharatStock quarterly financials.

Writes docs/data/multibagger.json with derived scores, ranks and gate results only.
Raw financial figures are used in memory and never written to disk or to the public repository,
because BharatStock's terms do not allow re-serving raw data without a separate licence.

Needs BHARATSTOCK_API_KEY (GitHub secret). Starter plan (3,000 requests a day) covers the universe
in one run; the free plan (25 a day) does not.
"""
import csv
import io
import json
import os
import time
from datetime import datetime

import requests

from . import config

OUT_FILE = config.SITE_DIR / "data" / "multibagger.json"
API = "https://bharatstockapi.com/v1/stocks/{t}/financials"
UNIVERSE_URLS = [
    "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
]
EXCLUDED = {"ACC"}   # large cap, present in the NSE file by mistake; never scored
UA = {"User-Agent": "Mozilla/5.0 (market-hub; multibagger)"}


def universe() -> list[str]:
    syms = set()
    for url in UNIVERSE_URLS:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        for row in csv.DictReader(io.StringIO(r.text)):
            s = (row.get("Symbol") or "").strip()
            if s:
                syms.add(s)
    return sorted(syms - EXCLUDED)


def fetch(symbol: str, key: str) -> list[dict]:
    r = requests.get(API.format(t=symbol), params={"period_type": "quarterly"},
                     headers={"X-API-Key": key}, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    body = r.json()
    return body.get("data", body if isinstance(body, list) else [])


INSIDER = "https://bharatstockapi.com/v1/stocks/{t}/insider-trades"


def fetch_insider(symbol: str, key: str) -> list[dict]:
    r = requests.get(INSIDER.format(t=symbol), params={"promoters_only": "true"},
                     headers={"X-API-Key": key}, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    body = r.json()
    return body.get("data", body if isinstance(body, list) else [])


def insider_signal(rows: list[dict], months: int = 6) -> dict:
    """Derived promoter signal over the last months: net shares bought or sold, and a flag.
    Field names are read defensively; a missing field is a gap, never a guess."""
    from datetime import date, timedelta
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


def _consolidated(rows: list[dict]) -> list[dict]:
    rows = [x for x in rows if (x.get("consolidation_type") or "consolidated") == "consolidated"]
    return sorted(rows, key=lambda x: x["period_end_date"], reverse=True)


def score(symbol: str, rows: list[dict]) -> dict:
    """Derived measures only. Returns gates, measures and a score; no raw figures."""
    q = _consolidated(rows)
    out = {"symbol": symbol, "quarters": len(q), "gates": {}, "measures": {}, "gaps": []}
    if len(q) < 5:
        out["gaps"].append("fewer than five consolidated quarters")
        out["score"] = None
        return out
    latest, year_ago = q[0], q[4]
    def growth(a, b):
        if a is None or b in (None, 0):
            return None
        return (a / b - 1) * 100
    rev_g = growth(latest.get("revenue"), year_ago.get("revenue"))
    pat_g = growth(latest.get("net_profit"), year_ago.get("net_profit"))
    eps_g = growth(latest.get("eps"), year_ago.get("eps"))
    yoy_profit_quarters = 0
    for i in range(min(8, len(q) - 4)):
        g = growth(q[i].get("net_profit"), q[i + 4].get("net_profit"))
        if g is not None and g > 0:
            yoy_profit_quarters += 1
    margin = None
    if latest.get("revenue") and latest.get("net_profit") is not None:
        margin = latest["net_profit"] / latest["revenue"] * 100
    cfo_ratio = None
    if latest.get("cash_flow_operating") is not None and latest.get("net_profit"):
        cfo_ratio = latest["cash_flow_operating"] / latest["net_profit"]
    out["measures"] = {
        "revenue_growth_yoy_pct": _r(rev_g),
        "profit_growth_yoy_pct": _r(pat_g),
        "eps_growth_yoy_pct": _r(eps_g),
        "profit_growth_quarters_of_last_8": yoy_profit_quarters,
        "net_margin_pct": _r(margin),
        "operating_cash_to_profit": _r(cfo_ratio, 2),
    }
    # Gates: a gate that cannot be tested is a gap, never a pass.
    m = out["measures"]
    out["gates"] = {
        "revenue_growing": None if rev_g is None else rev_g > 10,
        "profit_growing": None if pat_g is None else pat_g > 15,
        "profit_consistent": yoy_profit_quarters >= 6,
        "cash_backed": None if cfo_ratio is None else cfo_ratio >= 0.8,
    }
    for k, v in out["gates"].items():
        if v is None:
            out["gaps"].append(k)
    passed = sum(1 for v in out["gates"].values() if v)
    failed = sum(1 for v in out["gates"].values() if v is False)
    out["score"] = None if failed else passed
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
            try:
                ins = fetch_insider(sym, key)
                if ins and not getattr(main, "_logged", False):
                    print("insider fields (names only):", sorted(ins[0].keys()), flush=True)
                    main._logged = True
                res["promoter"] = insider_signal(ins)
            except Exception as exc:
                res["promoter"] = {"status": f"insider fetch failed: {str(exc)[:80]}"}
            results.append(res)
        except Exception as exc:
            failures.append({"symbol": sym, "error": str(exc)[:120]})
        time.sleep(0.2)
    ranked = sorted([r for r in results if r.get("score") is not None],
                    key=lambda r: (r["score"], r["measures"].get("profit_growth_yoy_pct") or -1e9), reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    out = {
        "ts": datetime.now(config.IST).isoformat(timespec="minutes"),
        "universe": len(names),
        "scored": len(results),
        "passing_all_gates_tested": sum(1 for r in ranked if r["score"] == 4),
        "failures": failures,
        "ranked": ranked,
        "note": "Derived scores and gates only. Gates with missing data are listed as gaps, never passed.",
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in out.items() if k != "ranked"}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
