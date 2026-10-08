"""
Stock library: every listed NSE company (EQ and BE) scored on the parameters that have a confirmed
source today. Each parameter has a written rule. A stock gets, per parameter: the value, met, not met,
or not testable (data missing). Nothing is counted as met without data.

Output goes to the PRIVATE repo market-hub-private (library.json), not the public site, because it
holds per-company values derived from BharatStock data. Needs BHARATSTOCK_API_KEY and
PRIVATE_REPO_TOKEN (contents read and write on market-hub-private).

Parameters without a calculation yet are listed in NOT_YET in the output, so the gap is visible.
"""
import base64
import json
import os
import time
from datetime import date, datetime, timedelta

import requests

from . import config
from .multibagger import (universe, fetch, fetch_annual, fetch_insider, fetch_mf,
                          insider_signal, mf_counts, _consolidated)
from .backtest_multibagger import prices as fetch_prices
from . import shareholding as shp
from . import corporate_actions as ca
from . import named_holders as nh
from . import sector_news

PRIVATE_REPO = "ramghatagedb1101-NSEFO/market-hub-private"
REGISTRY_FILE = config.REPO / "hub" / "registry.json"
SECTOR_MAP_FILE = config.REPO / "rg" / "data" / "sector_map.json"
PRIVATE_FILE = "library.json"
TIME_BUDGET_SECONDS = 70 * 60

# Rule for each parameter: (label, test). test(value) -> True / False. None value = not testable.
RULES = {
    "rev_yoy": ("Revenue growth, latest quarter vs year ago > 10%", lambda v: v > 10),
    "profit_yoy": ("Profit growth, latest quarter vs year ago > 15%", lambda v: v > 15),
    "profit_consistency_8q": ("Quarters of profit growth in last 8 >= 6", lambda v: v >= 6),
    "profit_run": ("Consecutive quarters of profit above year-ago level >= 4", lambda v: v >= 4),
    "eps_yoy": ("EPS growth, latest quarter vs year ago > 15%", lambda v: v > 15),
    "net_margin": ("Net margin > 8%", lambda v: v > 8),
    "operating_margin": ("Operating margin > 12%", lambda v: v > 12),
    "interest_cover": ("Operating profit / finance cost > 3x", lambda v: v > 3),
    "roe": ("Return on equity > 15%", lambda v: v > 15),
    "roce": ("Return on capital employed > 15%", lambda v: v > 15),
    "debt_to_equity": ("Debt to equity < 1.0", lambda v: v < 1.0),
    "debt_change_1y": ("Borrowings not higher than a year ago", lambda v: v <= 0),
    "cfo": ("Operating cash flow positive, latest year", lambda v: v > 0),
    "cfo_to_pat": ("Operating cash flow at least 0.8x net profit (annual)", lambda v: v >= 0.8),
    "cfo_margin": ("Operating cash flow at least 10% of revenue (annual)", lambda v: v >= 10),
    "cfo_growth": ("Operating cash flow higher than a year ago (annual)", lambda v: v > 0),
    "fcf": ("Free cash flow (operating cash flow less capital spending) positive (annual)", lambda v: v > 0),
    "capex_to_sales": ("Capital spending below 20% of revenue (annual)", lambda v: v < 20),
    "insider_net_shares_6m": ("Promoters net buyers over six months", lambda v: v > 0),
    "mf_schemes_holding": ("At least 5 mutual fund schemes hold the stock", lambda v: v >= 5),
    "mf_schemes_added": ("At least 1 mutual fund scheme added the stock", lambda v: v >= 1),
    "ret_12m": ("Share price up over 12 months", lambda v: v > 0),
    "from_52w_high": ("Within 20% of the 52-week high", lambda v: v >= -20),
    "above_200dma": ("Close above 200-day average", lambda v: v is True),
    "delivery_pct_20d": ("Average delivery at least 40% over 20 sessions", lambda v: v >= 40),
    "volume_ratio_20d": ("Recent volume at least as high as the prior 60 sessions", lambda v: v >= 1.0),
    "pe": ("Price to earnings below 40x", lambda v: 0 < v < 40),
    "pb": ("Price to book below 6x", lambda v: 0 < v < 6),
    "ps": ("Price to sales below 5x", lambda v: 0 < v < 5),
    "market_value_bucket": ("Market value at least ₹500 crore (not a micro-cap)", lambda v: v >= 500),
    "promoter_holding": ("Promoter and promoter group holding at least 40%", lambda v: v >= 40),
    "promoter_change_qoq": ("Promoter holding not lower than the previous quarter", lambda v: v >= 0),
    "promoter_change_yoy": ("Promoter holding not lower than a year ago", lambda v: v >= 0),
    "public_float": ("Public float at least 25% (SEBI's minimum public shareholding norm)", lambda v: v >= 25),
    "fii_holding": ("Foreign institutional holding at least 5%", lambda v: v >= 5),
    "dii_holding": ("Domestic institutional holding at least 5%", lambda v: v >= 5),
    "pledge_pct": ("Promoter pledge below 10% of promoter holding", lambda v: v < 10),
    "dividend_yield": ("Dividend yield at least 1%, trailing twelve months", lambda v: v >= 1),
    "buyback_flag": ("Share buyback in the last year", lambda v: v is True),
    "promoter_holding_change_3q": ("Promoter holding not lower than three quarters ago", lambda v: v >= 0),
    "fii_change_qoq": ("Foreign institutional holding not lower than the previous quarter", lambda v: v >= 0),
    "dii_change_qoq": ("Domestic institutional holding not lower than the previous quarter", lambda v: v >= 0),
    "pledge_change": ("Promoter pledge not higher than a year ago", lambda v: v <= 0),
    "registry_holders": ("At least one confirmed registry investor holds this stock", lambda v: v > 0),
    "registry_new_entrants": ("A confirmed registry investor is new this quarter", lambda v: v > 0),
    "holder_count_change": ("More disclosed public holders than a quarter ago", lambda v: v > 0),
    "top10_holding_change": ("Top ten disclosed holders' combined stake not lower than a quarter ago", lambda v: v >= 0),
    # Sector-level (Google News RSS, keyword counts) -- a coarse attention proxy, not backtested; the
    # thresholds are a written judgment call, not derived from any outcome test.
    "sector_news_count": ("At least 20 sector-related news items in the last 30 days", lambda v: v >= 20),
    "regulatory_events": ("No more than 65 regulatory/policy-keyword mentions for the sector in the last 90 days", lambda v: v <= 65),
}

NOT_YET = [
    "cash_flow_quarterly", "capex", "capex_change",
    "bulk_buys_20d", "bulk_sells_20d", "registry_buys_20d",
    "ret_1m", "ret_3m", "ret_6m", "volatility_60d", "rel_strength_vs_index", "beta_vs_index",
    "ev_ebitda", "ev_sales", "peg", "sector_ret_3m",
    "market_value_bucket", "listing_age_years",
]


def _sum_last(values):
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def _growth(a, b):
    if a is None or b is None or b <= 0:
        return None
    return (a / b - 1) * 100


def financial_values(rows: list[dict]) -> dict:
    q = _consolidated(rows)
    out = {}
    if len(q) < 5:
        return out
    latest, ya = q[0], q[4]
    out["rev_yoy"] = _growth(latest.get("revenue"), ya.get("revenue"))
    out["profit_yoy"] = _growth(latest.get("net_profit"), ya.get("net_profit"))
    out["eps_yoy"] = _growth(latest.get("eps"), ya.get("eps"))
    yoy = []
    for i in range(min(8, len(q) - 4)):
        a, b = q[i].get("net_profit"), q[i + 4].get("net_profit")
        yoy.append(a is not None and b is not None and a > 0 and a > b)
    out["profit_consistency_8q"] = sum(1 for f in yoy if f)
    run = 0
    for f in yoy:
        if f:
            run += 1
        else:
            break
    out["profit_run"] = run
    rev, pat = latest.get("revenue"), latest.get("net_profit")
    if rev and pat is not None:
        out["net_margin"] = pat / rev * 100
    op = latest.get("operating_profit")
    if rev and op is not None:
        out["operating_margin"] = op / rev * 100
    fin = latest.get("finance_costs")
    if op is not None and fin:
        out["interest_cover"] = op / fin
    eq = latest.get("total_equity") or latest.get("equity_attributable_to_owners")
    if pat is not None and eq:
        out["roe"] = pat * 4 / eq * 100          # annualised from the latest quarter
    debt = _sum_last([latest.get("borrowings_current"), latest.get("borrowings_non_current")])
    ya_debt = _sum_last([ya.get("borrowings_current"), ya.get("borrowings_non_current")])
    if debt is not None and eq:
        out["debt_to_equity"] = debt / eq
    if debt is not None and ya_debt is not None:
        out["debt_change_1y"] = debt - ya_debt
    if op is not None and debt is not None and eq:
        ce = eq + debt
        out["roce"] = op * 4 / ce * 100 if ce else None
    out["_latest_period"] = latest.get("period_end_date")
    out["_quarters"] = len(q)
    return out


def cash_flow_values(annual_rows: list[dict]) -> dict:
    """Cash-flow parameters, from annual financials only: BharatStock fills cash_flow_operating and
    capex once a year, never on the quarterly rows, so these cannot come from financial_values()."""
    a = _consolidated(annual_rows)
    out = {}
    if not a:
        return out
    latest = a[0]
    cfo, rev, pat = latest.get("cash_flow_operating"), latest.get("revenue"), latest.get("net_profit")
    capex = latest.get("capex")
    if cfo is not None:
        out["cfo"] = cfo
        if pat:
            out["cfo_to_pat"] = cfo / pat
        if rev:
            out["cfo_margin"] = cfo / rev * 100
        if capex is not None:
            out["fcf"] = cfo - abs(capex)
    if capex is not None:
        out["capex"] = capex
        if rev:
            out["capex_to_sales"] = abs(capex) / rev * 100
    if len(a) > 1:
        ya = a[1]
        ya_cfo, ya_capex = ya.get("cash_flow_operating"), ya.get("capex")
        if cfo is not None and ya_cfo:
            out["cfo_growth"] = (cfo / ya_cfo - 1) * 100 if ya_cfo > 0 else None
        if capex is not None and ya_capex is not None:
            out["capex_change"] = abs(capex) - abs(ya_capex)   # sign of the raw field is unconfirmed; compare magnitudes
    out["_annual_period"] = latest.get("period_end_date")
    return out


def _sum4(vals: list) -> float | None:
    """Sum of exactly four values, or None if fewer than four quarters or any is missing -- a
    partial TTM figure from fewer quarters would misstate the ratio, so it is a gap instead."""
    vals = vals[:4]
    if len(vals) < 4 or any(v is None for v in vals):
        return None
    return sum(vals)


def valuation_values(q: list[dict], price_last: float | None) -> dict:
    """PE, PB, price/sales and market value, computed from confirmed financials fields (shares
    outstanding = paid-up equity capital / face value) and the latest traded price. BharatStock's
    'ratios' endpoint is not reachable on the current plan (persistent 429s), so this needs no new
    source at all -- everything here was already being fetched for financial_values()."""
    out = {}
    if not q or not price_last:
        return out
    latest = q[0]
    face, paid_up = latest.get("face_value_per_share"), latest.get("paid_up_equity_capital")
    if not face or not paid_up:
        return out
    shares = paid_up / face
    market_cap = price_last * shares
    out["market_value_bucket"] = market_cap / 1e7   # INR crore

    ttm_eps = _sum4([x.get("eps") for x in q])
    if ttm_eps and ttm_eps > 0:
        out["pe"] = price_last / ttm_eps

    eq = latest.get("total_equity") or latest.get("equity_attributable_to_owners")
    if eq:
        out["pb"] = market_cap / eq

    ttm_rev = _sum4([x.get("revenue") for x in q])
    if ttm_rev:
        out["ps"] = market_cap / ttm_rev
    return out


def price_values(series: list[tuple[date, float]], delivery: list[float], volume: list[float]) -> dict:
    out = {}
    if len(series) < 30:
        return out
    closes = [c for _, c in series]
    last = closes[-1]

    def back(n):
        return closes[-n - 1] if len(closes) > n else None

    if back(252) is not None or back(200) is not None:
        out["ret_12m"] = (last / closes[-253] - 1) * 100 if len(closes) > 252 else None
    if len(closes) >= 252:
        hi = max(closes[-252:])
        out["from_52w_high"] = (last / hi - 1) * 100
    if len(closes) >= 200:
        ma200 = sum(closes[-200:]) / 200
        out["above_200dma"] = last > ma200
    if delivery:
        out["delivery_pct_20d"] = sum(delivery[-20:]) / len(delivery[-20:])
    if len(volume) >= 80:
        recent = sum(volume[-20:]) / 20
        prior = sum(volume[-80:-20]) / 60
        out["volume_ratio_20d"] = recent / prior if prior else None
    return out


def evaluate(values: dict) -> dict:
    cells = {}
    met = not_met = not_testable = 0
    for pid, (label, test) in RULES.items():
        v = values.get(pid)
        if v is None:
            cells[pid] = {"value": None, "status": "not_testable", "rule": label}
            not_testable += 1
            continue
        ok = bool(test(v))
        cells[pid] = {"value": round(v, 2) if isinstance(v, float) else v,
                      "status": "met" if ok else "not_met", "rule": label}
        met += 1 if ok else 0
        not_met += 0 if ok else 1
    testable = met + not_met
    return {"cells": cells, "met": met, "not_met": not_met, "not_testable": not_testable,
            "testable": testable, "data_quality_pct": round(100 * testable / len(RULES), 1)}


def _private_headers() -> dict:
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def fetch_existing() -> tuple[dict, str | None]:
    """Reads the published library.json, if any, so a batch can resume from the last cursor and
    merge into the prior results instead of starting over or overwriting other batches' work.

    2026-10-08: the Contents API only inlines a file's content below 1 MB -- above that it
    returns an empty content field with no error, which used to decode to "", fail json.loads,
    and silently reset to "no prior data" (losing every earlier batch's results and restarting
    the cursor at 0). library.json passes 1 MB after the first batch (~899 companies), so this
    was hit on every batch after the first. Falls back to the Git Data API's blob endpoint
    (no practical size limit, same sha) whenever the inline content is missing.
    """
    url = f"https://api.github.com/repos/{PRIVATE_REPO}/contents/{PRIVATE_FILE}"
    got = requests.get(url, headers=_private_headers(), timeout=30)
    if got.status_code == 404:
        return {}, None
    got.raise_for_status()
    body = got.json()
    sha = body.get("sha")
    try:
        content_b64 = body.get("content")
        if not content_b64:
            blob = requests.get(f"https://api.github.com/repos/{PRIVATE_REPO}/git/blobs/{sha}",
                                 headers=_private_headers(), timeout=60)
            blob.raise_for_status()
            content_b64 = blob.json().get("content", "")
        content = base64.b64decode(content_b64).decode("utf-8")
        return json.loads(content), sha
    except (ValueError, TypeError, KeyError):
        return {}, sha


def publish(payload: dict, sha: str | None) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    url = f"https://api.github.com/repos/{PRIVATE_REPO}/contents/{PRIVATE_FILE}"
    headers = _private_headers()
    msg = {"message": f"stock library {date.today().isoformat()}",
           "content": base64.b64encode(body).decode("ascii")}
    if sha:
        msg["sha"] = sha
    requests.put(url, headers=headers, json=msg, timeout=120).raise_for_status()


def main() -> dict:
    """Runs one batch, starting where the last batch left off. A single GitHub Actions job cannot
    finish the full ~2,570-company universe once real API calls are happening (roughly 300 fit in
    the 70-minute time budget) -- so each run picks up at `cursor_next` from the previous run's
    published library.json, processes as much as its time budget allows, merges its results into
    the prior stocks (other companies' entries are left untouched), and reports whether the pass
    wrapped around (cycle_complete). The workflow uses cycle_complete to decide whether to dispatch
    another run and keep the chain going."""
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    started = time.time()
    names = universe()
    existing, sha = fetch_existing()
    start_idx = existing.get("cursor_next", 0)
    if not isinstance(start_idx, int) or not (0 <= start_idx < len(names)):
        start_idx = 0
    prior_stocks = {s["symbol"]: s for s in existing.get("stocks", []) if isinstance(s, dict) and s.get("symbol")}
    prior_matches = {k: v for k, v in (existing.get("investor_matches") or {}).items()}
    try:
        registry_investors = json.loads(REGISTRY_FILE.read_text(encoding="utf-8")).get("investors", [])
    except (OSError, ValueError):
        registry_investors = []
    investor_status = {inv["name"]: inv.get("status") for inv in registry_investors if inv.get("name")}
    symbol_matches = {}
    try:
        sector_map = json.loads(SECTOR_MAP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sector_map = {}
    sector_cache = {}   # built lazily, one pair of Google News calls per sector actually seen this batch
    nse_session = shp.session()
    stocks, partial, processed = [], False, 0
    for sym in names[start_idx:]:
        if time.time() - started > TIME_BUDGET_SECONDS:
            partial = True
            break
        processed += 1
        try:
            rows = fetch(sym, key)
            values = financial_values(rows)
            try:
                values.update(cash_flow_values(fetch_annual(sym, key)))
            except Exception:
                pass
            try:
                px = fetch_prices(sym, key)
            except Exception:
                px = []
            values.update(price_values(px, [], []))
            last = px[-1][1] if px else None
            values.update(valuation_values(_consolidated(rows), last))
            try:
                nse_records = shp.fetch(nse_session, sym)
            except Exception:
                try:
                    nse_session = shp.session()   # one retry with a fresh session/cookies
                    nse_records = shp.fetch(nse_session, sym)
                except Exception:
                    nse_records = []
            values.update(shp.values(nse_records))
            targets = shp.institutional_targets(nse_records)
            texts = {}
            for label, url in targets.items():
                try:
                    texts[label] = shp.fetch_xbrl_text(url)
                except Exception:
                    pass
            inst = {label: shp.institutional_from_text(t) for label, t in texts.items()}
            if "latest" in inst:
                values.update(inst["latest"])
                if "prior_quarter" in inst:
                    for k, prior_k in (("fii_holding", "fii_change_qoq"), ("dii_holding", "dii_change_qoq")):
                        if k in inst["latest"] and k in inst["prior_quarter"]:
                            values[prior_k] = inst["latest"][k] - inst["prior_quarter"][k]
                if "year_ago" in inst and "pledge_pct" in inst["latest"] and "pledge_pct" in inst["year_ago"]:
                    values["pledge_change"] = inst["latest"]["pledge_pct"] - inst["year_ago"]["pledge_pct"]
            # Named public holders above the 2-lakh disclosure threshold, matched against the investor
            # registry. A match is evidence to review, not an automatic confirmation: registry_holders
            # and registry_new_entrants only count investors whose registry status is already
            # "confirmed", so they stay honestly at 0 until the owner reviews and confirms a match.
            matches_latest = []
            agg_latest = agg_prior = None
            if "latest" in texts:
                try:
                    holders_latest = nh.named_holders_from_text(texts["latest"])
                    matches_latest = nh.match_registry(holders_latest, registry_investors)
                    if matches_latest:
                        symbol_matches[sym] = matches_latest
                    agg_latest = nh.aggregate(holders_latest)
                except Exception:
                    pass
            confirmed_latest = {m["investor"] for m in matches_latest
                                 if investor_status.get(m["investor"]) == "confirmed"}
            values["registry_holders"] = len(confirmed_latest)
            if "prior_quarter" in texts:
                try:
                    holders_prior = nh.named_holders_from_text(texts["prior_quarter"])
                    matches_prior = nh.match_registry(holders_prior, registry_investors)
                    confirmed_prior = {m["investor"] for m in matches_prior
                                        if investor_status.get(m["investor"]) == "confirmed"}
                    values["registry_new_entrants"] = len(confirmed_latest - confirmed_prior)
                    agg_prior = nh.aggregate(holders_prior)
                except Exception:
                    pass
            if agg_latest is not None and agg_prior is not None:
                values["holder_count_change"] = agg_latest["holder_count"] - agg_prior["holder_count"]
                if agg_latest["top10_pct"] is not None and agg_prior["top10_pct"] is not None:
                    values["top10_holding_change"] = agg_latest["top10_pct"] - agg_prior["top10_pct"]
            try:
                ca_records = ca.fetch(nse_session, sym)
                ca_values = ca.values(ca_records)
                if last and ca_values.get("dividend_per_share_ttm") is not None:
                    values["dividend_yield"] = ca_values["dividend_per_share_ttm"] / last * 100
                values["buyback_flag"] = ca_values["buyback_flag"]
            except Exception:
                pass
            sector = sector_map.get(sym)
            if sector:
                if sector not in sector_cache:
                    try:
                        sector_cache[sector] = {"sector_news_count": sector_news.sector_news_count(sector)}
                    except Exception:
                        sector_cache[sector] = {}
                    try:
                        sector_cache[sector]["regulatory_events"] = sector_news.regulatory_events(sector)
                    except Exception:
                        pass
                values.update(sector_cache[sector])
            # Insider and fund data only for companies with profit growth: keeps the run inside the daily request limit.
            if values.get("profit_yoy") is not None and values["profit_yoy"] > 0:
                ins = insider_signal(fetch_insider(sym, key))
                if ins.get("net_shares") is not None:
                    values["insider_net_shares_6m"] = ins["net_shares"]
                mf = mf_counts(fetch_mf(sym, key))
                if mf.get("schemes_holding") is not None:
                    values["mf_schemes_holding"] = mf["schemes_holding"]
                    values["mf_schemes_added"] = mf.get("schemes_added", 0)
            result = evaluate({k: v for k, v in values.items() if not k.startswith("_")})
            stocks.append({"symbol": sym, "latest_period": values.get("_latest_period"),
                           "quarters": values.get("_quarters", 0), **result})
        except Exception as exc:
            stocks.append({"symbol": sym, "error": str(exc)[:120]})
        time.sleep(0.2)

    end_idx = start_idx + processed
    cycle_complete = end_idx >= len(names)
    cursor_next = 0 if cycle_complete else end_idx
    prior_stocks.update({s["symbol"]: s for s in stocks})
    merged_stocks = list(prior_stocks.values())
    prior_matches.update(symbol_matches)

    payload = {
        "generated": datetime.now(config.IST).isoformat(timespec="minutes"),
        "partial": partial,
        "universe": len(names),
        "processed": processed,
        "batch_from": start_idx,
        "batch_to": end_idx,
        "cursor_next": cursor_next,
        "cycle_complete": cycle_complete,
        "total_stocks": len(merged_stocks),
        "rules": {k: v[0] for k, v in RULES.items()},
        "not_yet_implemented": NOT_YET,
        "stocks": merged_stocks,
        # Review list, every name-alias match regardless of registry status -- the owner confirms an
        # investor in hub/registry.json before it counts toward registry_holders/registry_new_entrants.
        "investor_matches": prior_matches,
    }
    publish(payload, sha)
    return {k: v for k, v in payload.items()
            if k not in ("stocks", "rules", "not_yet_implemented", "investor_matches")} | {
        "stocks_written": len(merged_stocks), "batch_written": len(stocks),
        "symbols_with_matches": len(prior_matches)}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
