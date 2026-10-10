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
import csv
import io
import json
import os
import statistics as st
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import config
from . import alerts
from .multibagger import (universe, fetch, fetch_annual, fetch_insider, fetch_mf,
                          insider_signal, mf_counts, _consolidated, score, UA, EQUITY_LIST,
                          FIELDS, ENDPOINT_COUNTS, BS_REQUESTS)
from . import bhav
from . import nse_feeds
from . import documents as docs_mod
from . import library_compact
from . import shortlist as shortlist_mod
from . import digest as digest_mod
from . import shareholding as shp
from . import corporate_actions as ca
from . import named_holders as nh
from . import sector_news

PRIVATE_REPO = "ramghatagedb1101-NSEFO/market-hub-private"
REGISTRY_FILE = config.REPO / "hub" / "registry.json"
SECTOR_MAP_FILE = config.REPO / "rg" / "data" / "sector_map.json"
MULTIBAGGER_FILE = config.SITE_DIR / "data" / "multibagger.json"
PRIVATE_FILE = "library.json"
TIME_BUDGET_SECONDS = 70 * 60


def load_nifty_series() -> dict:
    """The free NIFTY 50 daily close history already maintained by the daily job (state/prices.json,
    NSE bhavcopy) -- used as the benchmark for beta/relative-strength so those parameters need no
    extra BharatStock call at all, and no index data re-serving question ever comes up."""
    try:
        data = json.loads(config.PRICES_FILE.read_text(encoding="utf-8"))
        return data.get("NIFTY") or {}
    except (OSError, ValueError):
        return {}

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
    "working_capital_days": ("Working capital cycle below 60 days", lambda v: v < 60),
    "working_capital_change": ("Working capital cycle not longer than a year ago", lambda v: v <= 0),
    "debt_to_equity": ("Debt to equity < 1.0", lambda v: v < 1.0),
    "debt_change_1y": ("Borrowings not higher than a year ago", lambda v: v <= 0),
    "cfo": ("Operating cash flow positive, latest year", lambda v: v > 0),
    "cfo_to_pat": ("Operating cash flow at least 0.8x net profit (annual)", lambda v: v >= 0.8),
    "cfo_margin": ("Operating cash flow at least 10% of revenue (annual)", lambda v: v >= 10),
    "cfo_growth": ("Operating cash flow higher than a year ago (annual)", lambda v: v > 0),
    "fcf": ("Free cash flow (operating cash flow less capital spending) positive (annual)", lambda v: v > 0),
    "capex_to_sales": ("Capital spending below 20% of revenue (annual)", lambda v: v < 20),
    "insider_net_shares_6m": ("Promoters net buyers over six months", lambda v: v > 0),
    # Fewer holders, not more, is the bullish read here: heavy existing fund ownership means the
    # market has already found the stock, while thin ownership alongside strong fundamentals is the
    # "undiscovered" signal worth pouncing on. Matches multibagger.py's own ranking tiebreaker, which
    # already prefers fewer mutual fund holders ("fresher names first") -- this rule used to reward
    # the opposite direction, which was a real inconsistency, not a second valid viewpoint.
    # The gate itself stays "met" across BOTH watch tiers (<20): a weekly batch can easily miss the
    # exact week a stock crosses 5 holders, so a hard cutoff there would silently drop a stock just
    # as it "becomes part of the crowd" instead of catching it at all. mf_discovery_tier (below)
    # carries the actual urgency split for the alert system: 1 = <5 (pounce), 2 = 5-20 (watch).
    "mf_schemes_holding": ("Fewer than 20 mutual fund schemes hold the stock (not yet widely discovered)", lambda v: v < 20),
    "mf_discovery_tier": ("Discovery tier 1 (<5 schemes) or 2 (5-20 schemes)", lambda v: v in (1, 2)),
    "mf_schemes_added": ("At least 1 mutual fund scheme added the stock", lambda v: v >= 1),
    "ret_1m": ("Share price up over 1 month", lambda v: v > 0),
    "ret_3m": ("Share price up over 3 months", lambda v: v > 0),
    "ret_12m": ("Share price up over 12 months", lambda v: v > 0),
    "from_52w_high": ("Within 20% of the 52-week high", lambda v: v >= -20),
    "from_52w_low": ("At least 20% above the 52-week low", lambda v: v >= 20),
    "above_200dma": ("Close above 200-day average", lambda v: v is True),
    "volatility_60d": ("Annualised volatility below 50% over 60 sessions", lambda v: v <= 50),
    "delivery_pct_20d": ("Average delivery at least 40% over 20 sessions", lambda v: v >= 40),
    "delivery_change": ("Delivery percentage not lower than the prior 60 sessions", lambda v: v >= 0),
    "volume_ratio_20d": ("Recent volume at least as high as the prior 60 sessions", lambda v: v >= 1.0),
    "avg_turnover_20d": ("Average daily turnover at least ₹1 crore over 20 sessions", lambda v: v >= 1),
    "rel_strength_vs_index": ("Six-month return at or above the Nifty 50's", lambda v: v >= 0),
    "beta_vs_index": ("Beta against the Nifty 50 below 1.5", lambda v: v <= 1.5),
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
    "dividend_paid": ("Dividends paid in the latest year (any payout)", lambda v: v > 0),
    "dividend_policy_change": ("Dividend per share raised vs the previous year", lambda v: v > 0),
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
    # Sector-level (median/rank across every company sharing a sector this batch) -- same judgment-call
    # style as the two rules above: a reasonable threshold, not derived from any outcome test.
    "sector_ret_3m": ("Sector median 3-month return positive", lambda v: v > 0),
    "peer_group_growth_median": ("Sector median profit growth positive", lambda v: v > 0),
    "rel_strength_rank_sector": ("In the top half of its sector by 6-month return", lambda v: v >= 50),
    # Needs MIN_PE_HISTORY accumulated observations before it means anything -- see
    # apply_sector_aggregates(). Stays not_testable (a gap) for every company until then.
    "sector_pe_vs_history": ("Sector median P/E not higher than its own accumulated history", lambda v: v <= 0),
}

NOT_YET = [
    "cash_flow_quarterly", "capex", "capex_change",
    "bulk_buys_20d", "bulk_sells_20d", "registry_buys_20d",
    "ev_ebitda", "ev_sales", "peg",
    "market_value_bucket", "listing_age_years",
]


def _is_quota_exhausted(exc: Exception) -> bool:
    """A BharatStock 429 mid-batch almost always means the day's whole quota is gone (seen
    2026-10-07 and again 2026-10-08: every call fails the same way for the rest of the run, it
    does not recover within minutes the way a burst rate limit would -- multibagger.py's own
    fetch() already retries a 429 a few times with backoff before giving up, so by the time this
    is raised here, that retry already happened and failed). Distinguished by HTTP status code,
    not by matching message text."""
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) == 429


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

    def wc_days(row):
        # Field names are an educated guess (same defensive pattern as dividend_paid elsewhere in
        # this file): a wrong guess just leaves working_capital_days/_change a gap, never a
        # fabricated figure. Days approximated against the quarter's own revenue (~91 days/quarter),
        # the same simplification the registry's own definition implies (receivable + inventory -
        # payable days, not a full operating-cycle model with separate COGS/purchases bases).
        rcv = row.get("trade_receivables") or row.get("receivables") or row.get("sundry_debtors")
        inv = row.get("inventories") or row.get("inventory") or row.get("stock_in_trade")
        pay = row.get("trade_payables") or row.get("payables") or row.get("sundry_creditors")
        rv = row.get("revenue")
        if not rv or rcv is None or inv is None or pay is None:
            return None
        return (rcv + inv - pay) / rv * 91
    wc_latest, wc_ya = wc_days(latest), wc_days(ya)
    if wc_latest is not None:
        out["working_capital_days"] = wc_latest
    if wc_latest is not None and wc_ya is not None:
        out["working_capital_change"] = wc_latest - wc_ya
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

    def dps(row):
        # Field name is an educated guess, same defensive pattern as elsewhere in this file: a wrong
        # guess just leaves dividend_paid/dividend_policy_change out, never a fabricated figure.
        div = (row.get("dividend_paid") or row.get("dividends_paid") or
               row.get("total_dividend_paid") or row.get("dividend_payout"))
        face, paid_up = row.get("face_value_per_share"), row.get("paid_up_equity_capital")
        if div is None or not face or not paid_up:
            return None, None
        return abs(div), abs(div) / (paid_up / face)

    div_paid, div_per_share = dps(latest)
    if div_paid is not None:
        out["dividend_paid"] = div_paid
    if len(a) > 1:
        ya = a[1]
        ya_cfo, ya_capex = ya.get("cash_flow_operating"), ya.get("capex")
        if cfo is not None and ya_cfo:
            out["cfo_growth"] = (cfo / ya_cfo - 1) * 100 if ya_cfo > 0 else None
        if capex is not None and ya_capex is not None:
            out["capex_change"] = abs(capex) - abs(ya_capex)   # sign of the raw field is unconfirmed; compare magnitudes
        _, ya_div_per_share = dps(ya)
        if div_per_share is not None and ya_div_per_share is not None:
            out["dividend_policy_change"] = div_per_share - ya_div_per_share
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
    return valuation_from_basis(valuation_basis(q), price_last)


def price_values(series: list[tuple[date, float]], delivery: list[float], volume: list[float]) -> dict:
    out = {}
    if len(series) < 30:
        return out
    closes = [c for _, c in series]
    last = closes[-1]

    def back(n):
        return closes[-n - 1] if len(closes) > n else None

    # Divides by a specific historical close or a window extreme -- guarded against zero throughout:
    # a glitched/suspended-trading zero-price record is plausible across 2,572 companies including
    # illiquid micro-caps, and should leave that one figure a gap, not crash the whole company.
    if len(closes) > 21 and closes[-22]:
        out["ret_1m"] = (last / closes[-22] - 1) * 100
    if len(closes) > 63 and closes[-64]:
        out["ret_3m"] = (last / closes[-64] - 1) * 100
    if len(closes) > 126 and closes[-127]:
        out["ret_6m"] = (last / closes[-127] - 1) * 100
    if back(252) is not None or back(200) is not None:
        out["ret_12m"] = (last / closes[-253] - 1) * 100 if len(closes) > 252 and closes[-253] else None
    if len(closes) >= 252:
        hi = max(closes[-252:])
        lo = min(closes[-252:])
        if hi:
            out["from_52w_high"] = (last / hi - 1) * 100
        if lo:
            out["from_52w_low"] = (last / lo - 1) * 100
    if len(closes) >= 200:
        ma200 = sum(closes[-200:]) / 200
        out["above_200dma"] = last > ma200
    if len(closes) >= 61:
        window = closes[-61:]
        rets = [(window[i] / window[i - 1] - 1) for i in range(1, len(window)) if window[i - 1]]
        if len(rets) >= 2:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            out["volatility_60d"] = (var ** 0.5) * (252 ** 0.5) * 100
    if delivery:
        d20 = delivery[-20:]
        out["delivery_pct_20d"] = sum(d20) / len(d20)
        if len(delivery) >= 80:
            prior = delivery[-80:-20]
            if prior:
                out["delivery_change"] = out["delivery_pct_20d"] - sum(prior) / len(prior)
    if len(volume) >= 80:
        recent = sum(volume[-20:]) / 20
        prior = sum(volume[-80:-20]) / 60
        out["volume_ratio_20d"] = recent / prior if prior else None
    if volume and len(volume) >= 20 and len(volume) == len(closes):
        turnover = [v * c for v, c in zip(volume[-20:], closes[-20:])]
        out["avg_turnover_20d"] = (sum(turnover) / len(turnover)) / 1e7   # INR crore, same unit as market_value_bucket
    return out


def index_relative_values(series: list[tuple[date, float]], nifty: dict) -> dict:
    """Relative strength and beta against the NIFTY 50 -- the only benchmark series already stored
    for free (state/prices.json, from the daily NSE bhavcopy job). The parameter registry's own
    wording says "Nifty 500"; this uses NIFTY 50 instead since that is the series actually on hand
    for free, and relabels the rule text to say so rather than silently claim a different benchmark."""
    out = {}
    if len(series) < 127 or not nifty:
        return out
    closes = [c for _, c in series]
    dates = [d for d, _ in series]
    last = closes[-1]
    aligned = [(d, c) for d, c in zip(dates, closes) if d.isoformat() in nifty]
    if len(aligned) < 127:
        return out
    n_last = nifty[aligned[-1][0].isoformat()]
    n_6m = nifty.get(aligned[-127][0].isoformat())
    stock_base = aligned[-127][1]
    if n_6m and stock_base:
        stock_ret_6m = (last / stock_base - 1) * 100
        nifty_ret_6m = (n_last / n_6m - 1) * 100
        out["rel_strength_vs_index"] = stock_ret_6m - nifty_ret_6m
    if len(aligned) >= 253:
        window = aligned[-253:]
        s_rets, n_rets = [], []
        for i in range(1, len(window)):
            d0, c0 = window[i - 1]
            d1, c1 = window[i]
            n0, n1 = nifty.get(d0.isoformat()), nifty.get(d1.isoformat())
            if c0 and n0 and n1:
                s_rets.append(c1 / c0 - 1)
                n_rets.append(n1 / n0 - 1)
        if len(n_rets) >= 30:
            n_mean = sum(n_rets) / len(n_rets)
            n_var = sum((r - n_mean) ** 2 for r in n_rets) / len(n_rets)
            if n_var:
                s_mean = sum(s_rets) / len(s_rets)
                cov = sum((s_rets[i] - s_mean) * (n_rets[i] - n_mean) for i in range(len(n_rets))) / len(n_rets)
                out["beta_vs_index"] = cov / n_var
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


def _cell_value(stock: dict, pid: str):
    c = (stock.get("cells") or {}).get(pid)
    return c.get("value") if c else None


def _apply_extra_cells(stock: dict, new_values: dict) -> None:
    """Adds or overwrites a few cells on an already-evaluated stock dict (sector-level aggregates,
    computed after the per-company loop once every company's own cells are known) and keeps
    met/not_met/not_testable/data_quality_pct consistent -- without re-running evaluate() on the raw
    per-company values, which are not available for a company carried over from a prior batch (only
    its already-evaluated cells are)."""
    cells = stock.setdefault("cells", {})
    met_delta = not_met_delta = not_testable_delta = 0
    for pid, v in new_values.items():
        if v is None:
            continue
        label, test = RULES[pid]
        prev = cells.get(pid)
        ok = bool(test(v))
        cells[pid] = {"value": round(v, 2) if isinstance(v, float) else v,
                      "status": "met" if ok else "not_met", "rule": label}
        was_testable = prev is not None and prev.get("status") != "not_testable"
        if not was_testable:
            not_testable_delta -= 1
            met_delta += 1 if ok else 0
            not_met_delta += 0 if ok else 1
        elif prev["status"] == "met" and not ok:
            met_delta -= 1
            not_met_delta += 1
        elif prev["status"] == "not_met" and ok:
            not_met_delta -= 1
            met_delta += 1
    if met_delta or not_met_delta or not_testable_delta:
        stock["met"] = max(0, stock.get("met", 0) + met_delta)
        stock["not_met"] = max(0, stock.get("not_met", 0) + not_met_delta)
        stock["not_testable"] = max(0, stock.get("not_testable", 0) + not_testable_delta)
        stock["testable"] = stock["met"] + stock["not_met"]
        stock["data_quality_pct"] = round(100 * stock["testable"] / len(RULES), 1)


SECTOR_PE_HISTORY_FILE = config.REPO / "state" / "sector_pe_history.json"
MIN_PE_HISTORY = 8   # observations (roughly weekly batches) before "vs history" means anything


def _load_sector_pe_history() -> dict:
    try:
        return json.loads(SECTOR_PE_HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply_sector_aggregates(merged_stocks: list[dict], sector_map: dict) -> None:
    """Sector-level context for every company scored so far (this batch or an earlier one): the
    sector's median 3-month return, its median profit growth, each company's percentile rank by
    6-month return within its own sector, and (sector_pe_vs_history) today's sector median P/E
    against its own accumulated history. Needs no new BharatStock call -- every input (ret_3m,
    profit_yoy, ret_6m, pe) is already sitting in each company's own cells from the per-company loop.

    sector_pe_vs_history genuinely cannot mean anything on day one: the registry's own definition
    is "vs its own five-year median," and there is no persisted sector-PE time series yet. This
    starts one today (state/sector_pe_history.json, synced like any other state/ file) and records
    one data point per batch; the comparison only activates once MIN_PE_HISTORY points exist, so it
    reads "not enough history yet" honestly instead of comparing against a history of one."""
    history = _load_sector_pe_history()
    today = datetime.now(config.IST).date().isoformat()
    groups: dict[str, list[dict]] = {}
    for s in merged_stocks:
        sector = sector_map.get(s.get("symbol"))
        if sector and "cells" in s:
            groups.setdefault(sector, []).append(s)
    for sector, members in groups.items():
        ret3 = [v for v in (_cell_value(s, "ret_3m") for s in members) if v is not None]
        growth = [v for v in (_cell_value(s, "profit_yoy") for s in members) if v is not None]
        ret6 = {s["symbol"]: _cell_value(s, "ret_6m") for s in members}
        ranked6 = sorted(v for v in ret6.values() if v is not None)
        sector_ret_3m = st.median(ret3) if ret3 else None
        peer_growth = st.median(growth) if growth else None
        n6 = len(ranked6)

        pe_values = [v for v in (_cell_value(s, "pe") for s in members) if v is not None]
        pe_vs_hist = None
        if pe_values:
            sector_pe_today = st.median(pe_values)
            series = history.setdefault(sector, {})
            series[today] = sector_pe_today   # overwrite if this sector was already seen this batch
            if len(series) >= MIN_PE_HISTORY:
                pe_vs_hist = sector_pe_today - st.median(series.values())

        for s in members:
            new_values = {"sector_ret_3m": sector_ret_3m, "peer_group_growth_median": peer_growth}
            if pe_vs_hist is not None:
                new_values["sector_pe_vs_history"] = pe_vs_hist
            v6 = ret6.get(s["symbol"])
            if v6 is not None and n6 >= 3:
                new_values["rel_strength_rank_sector"] = 100 * sum(1 for x in ranked6 if x <= v6) / n6
            _apply_extra_cells(s, new_values)
    SECTOR_PE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECTOR_PE_HISTORY_FILE.write_text(json.dumps(history, indent=1), encoding="utf-8")


def _mb_holders(r: dict):
    mf = r.get("mutual_funds") or {}
    return mf.get("schemes_holding") if mf.get("schemes_holding") is not None else 10 ** 6


def merge_and_write_multibagger(mb_stocks: list[dict], prior_mb: dict, mb_failures: dict,
                                 names: list[str], cycle_complete: bool) -> int:
    """Merges this batch's multi-bagger scores into the prior cumulative set and republishes
    docs/data/multibagger.json -- same output shape hub.multibagger._write() always produced, so the
    public site's Multi-bagger tab needs no change. Coverage now grows with library's own batches
    instead of a separate same-day weekly pass (see note below); the two pipelines used to both
    fetch the same BharatStock financials independently, once a week apiece."""
    prior_mb.update({r["symbol"]: r for r in mb_stocks})
    merged = list(prior_mb.values())
    rated = [r for r in merged if r.get("score") is not None]
    ranked = sorted(rated, key=lambda r: (r["score"], r["measures"].get("turnaround", False),
                                          -_mb_holders(r), r["measures"].get("profit_growth_yoy_pct") or -1e9),
                    reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    out = {
        "ts": datetime.now(config.IST).isoformat(timespec="minutes"),
        "partial": not cycle_complete,
        "universe": len(names),
        "processed": len(merged),
        "scored": len(merged),
        "rated": len(rated),
        "not_rated_few_quarters": len(merged) - len(rated),
        "rated_all_four_gates": sum(1 for r in ranked if r["score"] == 4),
        "turnarounds": sum(1 for r in ranked if r["measures"].get("turnaround")),
        "failures": list(mb_failures.values()),
        "endpoint_fields": FIELDS,
        "endpoint_calls": ENDPOINT_COUNTS,
        "ranked": ranked,
        "note": "Derived ratings and gates only. A gate with missing data is a gap, never a pass. "
                "Ranking: rating, then recent turnaround, then fewer mutual fund holders. "
                "Scored as part of the stock-library batch run (shares one BharatStock fetch per "
                "company with the 124-parameter screen) -- coverage grows with library's batches "
                "rather than completing in a single same-day run; partial=true until a full pass "
                "of the universe lands in one cycle.",
    }
    MULTIBAGGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    MULTIBAGGER_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(merged)


SHP_VERSION = 2
INDUSTRY_LIST = "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"

# The measures the admin dashboard compares between batches for its "What changed" feed: the six
# Proven-compounder rules, the factor-score inputs that move most, and the ownership levels.
SNAPSHOT_KEYS = ("profit_consistency_8q", "net_margin", "cfo_to_pat", "mf_schemes_holding", "pledge_pct",
                 "market_value_bucket", "promoter_holding", "fii_holding", "dii_holding", "pe", "ret_12m",
                 "profit_yoy", "rev_yoy", "roe")


def fetch_industries() -> dict:
    """Symbol -> NSE industry (22 broad industries) for the ~750 companies in the NIFTY Total Market
    index. NSE's per-company quote API (which has the industry for every company) blocks scripted
    access, so companies outside this index stay unclassified rather than guessed."""
    r = requests.get(INDUSTRY_LIST, headers=UA, timeout=30)
    r.raise_for_status()
    rows = csv.DictReader(io.StringIO(r.text))
    return {row["Symbol"].strip(): row["Industry"].strip() for row in rows
            if (row.get("Symbol") or "").strip() and (row.get("Industry") or "").strip()}


def snapshot(prior_entry: dict, prior_mb_row: dict | None) -> dict | None:
    """The key figures from a company's previous library entry, for the dashboard's change feed.
    Never nests (only the listed values are copied), so it stays small."""
    cells = prior_entry.get("cells") or {}
    vals = {}
    for k in SNAPSHOT_KEYS:
        v = (cells.get(k) or {}).get("value")
        if v is not None:
            vals[k] = round(v, 2) if isinstance(v, float) else v
    if not vals:
        return None
    out = {"scored_on": prior_entry.get("scored_on"), "shp_v": prior_entry.get("shp_v"), "met": prior_entry.get("met"),
           "testable": prior_entry.get("testable"), "values": vals}
    if prior_mb_row and prior_mb_row.get("score") is not None:
        out["mb_score"] = prior_mb_row["score"]
    return out


def fetch_company_names() -> dict:
    """Symbol -> company name, from the same NSE EQUITY_L list universe() reads."""
    r = requests.get(EQUITY_LIST, headers=UA, timeout=30)
    r.raise_for_status()
    rows = list(csv.reader(io.StringIO(r.text)))
    head = [h.strip().upper() for h in rows[0]]
    i_sym, i_name = head.index("SYMBOL"), head.index("NAME OF COMPANY")
    return {row[i_sym].strip(): row[i_name].strip() for row in rows[1:]
            if len(row) > max(i_sym, i_name) and row[i_sym].strip()}


# ---------------------------------------------------------------------------------------------------
# What each company needs, and fetching only that (10 Oct 2026).
#
# BharatStock allows 10,000 requests a day. Until now every batch re-read every company in full -- 16
# years of prices, quarterly and annual results, insider and fund data -- about 7 requests a company,
# whether or not anything had changed. Now:
#   prices                 NSE's daily price file (hub/bhav.py), free, every company, every run
#   corporate actions      NSE's market-wide list, one free request a run
#   quarterly results      BharatStock, only after NSE shows the company filed a newer quarter
#   annual results         BharatStock, only when a new financial year's results are in
#   shareholding           NSE (free), only after NSE shows a newer quarter's filing
#   insider + fund data    BharatStock, at most monthly, only for companies either screen wants it for
#   documents              NSE (free): links to annual reports, call transcripts, presentations and
#                          recordings -- one market-wide request a run for new filings, plus each
#                          company once (and its annual reports once a year)
# Each company's last fetched figures are kept in state/library_state.json (private repo), so a run
# recomputes every company's scores from stored figures plus today's prices without asking again.
# Each source also has an age limit (REFRESH_DAYS) as a safety net in case a filing list is missed.
# ---------------------------------------------------------------------------------------------------
STATE_FILE = config.REPO / "state" / "library_state.json"
BS_DAILY_BUDGET = int(os.getenv("BS_DAILY_BUDGET", "9000"))   # of 10,000: the rest is left for the admin stock report
REFRESH_DAYS = {"fin": 120, "ann": 400, "shp": 120, "fund": 30, "docs": 180}
DOCS_FILE = config.SITE_DIR / "data" / "docs.json"   # links to NSE annual reports, transcripts, presentations
RETRY_DAYS = 3              # BharatStock can lag an NSE filing by a few days
MAX_TRIES = 3               # per newly filed quarter; after that the age limit takes over
FIRST_FEED_LOOKBACK = 100   # days of filing lists read on the first run (covers the current results season)
FEED_OVERLAP = 3            # days re-read on each run, for late-listed filings
BS_STAGES = ("fin", "ann", "fund")

FIN_KEYS = ("rev_yoy", "profit_yoy", "eps_yoy", "profit_consistency_8q", "profit_run", "net_margin",
            "operating_margin", "interest_cover", "roe", "debt_to_equity", "debt_change_1y", "roce",
            "working_capital_days", "working_capital_change")
ANN_KEYS = ("cfo", "cfo_to_pat", "cfo_margin", "fcf", "capex", "capex_to_sales", "dividend_paid", "cfo_growth",
            "capex_change", "dividend_policy_change")
VAL_KEYS = ("market_value_bucket", "pe", "pb", "ps")
INST_KEYS = ("promoter_holding", "public_float", "promoter_change_qoq", "promoter_change_yoy",
             "promoter_holding_change_3q", "fii_holding", "dii_holding", "pledge_pct", "fii_change_qoq",
             "dii_change_qoq", "pledge_change", "registry_holders", "registry_new_entrants",
             "holder_count_change", "top10_holding_change")
FUND_KEYS = ("insider_net_shares_6m", "mf_schemes_holding", "mf_schemes_added", "mf_discovery_tier")
PRICE_KEYS = ("ret_1m", "ret_3m", "ret_6m", "ret_12m", "from_52w_high", "from_52w_low", "above_200dma",
              "volatility_60d", "delivery_pct_20d", "delivery_change", "volume_ratio_20d", "avg_turnover_20d",
              "rel_strength_vs_index", "beta_vs_index", "dividend_yield", "buyback_flag")


def _iso(d) -> str | None:
    return d.isoformat() if isinstance(d, date) else d


def _date(s) -> date | None:
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _cells_of(entry: dict | None, keys) -> dict:
    cells = (entry or {}).get("cells") or {}
    out = {}
    for k in keys:
        v = (cells.get(k) or {}).get("value")
        if v is not None:
            out[k] = v
    return out


def migrate(entry: dict | None) -> dict:
    """First run on the tracker: start each company from the figures its library entry already holds,
    so nothing is lost while it waits its turn. Marked migrated: quarterly and annual results are
    re-read once (to store the inputs valuation and the multi-bagger score need), shareholding only if
    it predates the 10 Oct FII correction."""
    c = {"basis": {}, "src": {}}
    if not entry or not entry.get("cells"):
        return c
    on = entry.get("scored_on") or "2026-10-01"
    fin = _cells_of(entry, FIN_KEYS)
    fin["_latest_period"] = entry.get("latest_period")
    fin["_quarters"] = entry.get("quarters", 0)
    c["basis"]["fin"] = fin
    c["basis"]["val_cells"] = _cells_of(entry, VAL_KEYS)
    c["src"]["fin"] = {"on": on, "period": entry.get("latest_period"), "migrated": True}
    c["basis"]["ann"] = _cells_of(entry, ANN_KEYS)
    c["src"]["ann"] = {"on": on, "migrated": True}
    if entry.get("shp_v", 0) >= SHP_VERSION:
        c["basis"]["inst"] = _cells_of(entry, INST_KEYS)
        hh = entry.get("holding_history") or []
        c["src"]["shp"] = {"on": on, "quarter": hh[-1]["quarter"] if hh else None, "v": entry.get("shp_v")}
    if entry.get("holding_history"):
        c["holding_history"] = entry["holding_history"]
    fund = _cells_of(entry, FUND_KEYS)
    if fund:
        c["basis"]["fund"] = fund
        c["src"]["fund"] = {"on": on}
    return c


def _wants_fund(c: dict, mb_row: dict | None) -> bool:
    py = (c["basis"].get("fin") or {}).get("profit_yoy")
    return ((py is not None and py > 0) or
            (mb_row is not None and mb_row.get("score") is not None and mb_row["score"] >= 2))


def needs(c: dict, mb_row: dict | None, today: date) -> list[str]:
    """The stages this company needs now, in the order they must run (annual before quarterly, since
    the multi-bagger score made from the quarterly rows uses the annual cash-flow ratio)."""
    src = c.get("src") or {}
    out = []

    def due(stage):
        s = src.get(stage)
        if not s:
            return True
        retry = _date(s.get("retry"))
        if retry and retry > today:
            return False
        if s.get("migrated"):
            return True
        if stage == "shp" and (s.get("v") or 0) < SHP_VERSION:
            return True
        want, have = s.get("want"), s.get("quarter" if stage == "shp" else "period")
        # A company BharatStock holds no results for gets one try per filed quarter, not three.
        if want and (not have or want > str(have)[:10]) and s.get("tries", 0) < (1 if s.get("empty") else MAX_TRIES):
            return True
        on = _date(s.get("on"))
        return on is None or (today - on).days >= REFRESH_DAYS[stage]

    if due("ann"):
        out.append("ann")
    if out or due("fin"):
        out.append("fin")
    if due("shp"):
        out.append("shp")
    d = src.get("docs")
    retry = _date((d or {}).get("retry"))
    if not (retry and retry > today) and (
            not d or due("docs") or docs_mod.annual_report_due(c.get("docs") or {}, d.get("ar_checked"), today)):
        out.append("docs")
    # Fund data is wanted only for companies with profit growth or a multi-bagger score of 2+. Fresh
    # results can change that, so after a results refresh refresh_company() checks again itself.
    s = src.get("fund")
    stale = not s or _date(s.get("on")) is None or (today - _date(s["on"])).days >= REFRESH_DAYS["fund"]
    if stale and ("fin" in out or _wants_fund(c, mb_row)):
        out.append("fund")
    return out


def _priority(stages: list[str], c: dict) -> int:
    src = c.get("src") or {}
    if "fin" in stages and not src.get("fin"):
        return 0                       # never read at all
    if all(s in ("shp", "docs") for s in stages):
        return 1                       # free: costs no BharatStock requests
    if any((src.get(s) or {}).get("want") for s in stages):
        return 2                       # a newer quarter has been filed
    if any((src.get(s) or {}).get("migrated") for s in stages):
        return 3
    return 4


def _mark_wants(companies: dict, filed: dict, stage: str, key: str) -> int:
    n = 0
    for sym, q in filed.items():
        c = companies.get(sym)
        if c is None:
            continue
        s = c["src"].setdefault(stage, {})
        qi = q.isoformat()
        have = str(s.get(key) or "")[:10]
        if (not have or qi > have) and qi > (s.get("want") or ""):
            s["want"], s["tries"] = qi, 0
            n += 1
            if stage == "fin" and q.month == 3:          # a March quarter brings the year's annual results
                a = c["src"].setdefault("ann", {})
                if qi > (a.get("want") or ""):
                    a["want"], a["tries"] = qi, 0
    return n


def _after_fetch(s: dict, have, today: date) -> None:
    """Bookkeeping after a stage ran: done if it now holds the filed quarter, else try again later."""
    s["on"] = today.isoformat()
    s.pop("migrated", None)
    s.pop("error", None)
    want = s.get("want")
    if want and (not have or str(have)[:10] < want):
        s["tries"] = s.get("tries", 0) + 1
        s["retry"] = (today + timedelta(days=RETRY_DAYS)).isoformat()
    else:
        s.pop("want", None)
        s.pop("tries", None)
        s.pop("retry", None)


def valuation_basis(q: list[dict]) -> dict:
    """The financial inputs of valuation_values(), stored so PE/PB/PS/market value can be recomputed
    from each day's price without re-reading the results."""
    if not q:
        return {}
    latest = q[0]
    face, paid_up = latest.get("face_value_per_share"), latest.get("paid_up_equity_capital")
    return {"shares": paid_up / face if face and paid_up else None,
            "ttm_eps": _sum4([x.get("eps") for x in q]),
            "equity": latest.get("total_equity") or latest.get("equity_attributable_to_owners"),
            "ttm_rev": _sum4([x.get("revenue") for x in q])}


def valuation_from_basis(vb: dict, price_last: float | None) -> dict:
    out = {}
    shares = vb.get("shares")
    if not price_last or not shares:
        return out
    market_cap = price_last * shares
    out["market_value_bucket"] = market_cap / 1e7   # INR crore
    if vb.get("ttm_eps") and vb["ttm_eps"] > 0:
        out["pe"] = price_last / vb["ttm_eps"]
    if vb.get("equity"):
        out["pb"] = market_cap / vb["equity"]
    if vb.get("ttm_rev"):
        out["ps"] = market_cap / vb["ttm_rev"]
    return out


class QuotaGone(Exception):
    pass


def _bs(call, *args):
    """A BharatStock call; QuotaGone when the day's allowance is used up (a 429 after retries)."""
    try:
        return call(*args)
    except Exception as exc:
        if _is_quota_exhausted(exc):
            raise QuotaGone() from exc
        raise


def refresh_company(sym: str, c: dict, stages: list[str], ctx: dict) -> list[str]:
    """Runs the given stages for one company, storing what it fetched in c. Returns the stages that
    completed. Raises QuotaGone the moment BharatStock refuses, after storing anything already done."""
    today, key = ctx["today"], ctx["key"]
    basis, src = c.setdefault("basis", {}), c.setdefault("src", {})
    done = []
    annual_rows = None
    for stage in stages:
        if stage in BS_STAGES and not ctx["bs_ok"]():
            continue
        try:
            if stage == "ann":
                annual_rows = _bs(fetch_annual, sym, key)
                ann = cash_flow_values(annual_rows)
                a = _consolidated(annual_rows)
                if a and a[0].get("cash_flow_operating") is not None and a[0].get("net_profit"):
                    ann["_cfo_ratio"] = a[0]["cash_flow_operating"] / a[0]["net_profit"]
                basis["ann"] = ann
                _after_fetch(src.setdefault("ann", {}), ann.get("_annual_period"), today)
                src["ann"]["period"] = ann.get("_annual_period")
                src["ann"]["empty"] = not annual_rows
            elif stage == "fin":
                rows = _bs(fetch, sym, key)
                basis["fin"] = financial_values(rows)
                basis["val"] = valuation_basis(_consolidated(rows))
                basis.pop("val_cells", None)
                period = basis["fin"].get("_latest_period")
                _after_fetch(src.setdefault("fin", {}), period, today)
                src["fin"]["period"] = period
                src["fin"]["empty"] = not rows
                try:
                    ctx["mb_new"][sym] = score(sym, rows, annual_rows,
                                               None if annual_rows is not None else (basis.get("ann") or {}).get("_cfo_ratio"))
                    ctx["mb_failures"].pop(sym, None)
                except Exception as exc:
                    ctx["mb_failures"][sym] = {"symbol": sym, "error": str(exc)[:120]}
            elif stage == "shp":
                refresh_shareholding(sym, c, ctx)
                _after_fetch(src.setdefault("shp", {}), src["shp"].get("quarter"), today)
            elif stage == "docs":
                d = src.setdefault("docs", {})
                on = _date(d.get("on"))
                if on is None or (today - on).days >= REFRESH_DAYS["docs"]:
                    fresh = docs_mod.fetch_company(ctx["nse"], sym, today)
                    store = c.setdefault("docs", {})
                    for kind, items in fresh.items():
                        docs_mod.merge(store, kind, items)
                    d["on"] = today.isoformat()
                else:                      # only the yearly annual-report check is due
                    docs_mod.merge(c.setdefault("docs", {}), "ar", docs_mod.annual_reports(ctx["nse"], sym))
                d["ar_checked"] = today.isoformat()
                d.pop("error", None)
                d.pop("retry", None)
            elif stage == "fund":
                mb_row = ctx["mb_new"].get(sym) or ctx["prior_mb"].get(sym)
                if not _wants_fund(c, mb_row):
                    continue
                try:
                    ins = insider_signal(_bs(fetch_insider, sym, key))
                except QuotaGone:
                    raise
                except Exception as exc:
                    ins = {"status": f"insider fetch failed: {str(exc)[:80]}"}
                try:
                    mf = mf_counts(_bs(fetch_mf, sym, key))
                except QuotaGone:
                    raise
                except Exception as exc:
                    mf = {"status": f"fund fetch failed: {str(exc)[:80]}"}
                fund = {"_ins": ins, "_mf": mf}
                if ins.get("net_shares") is not None:
                    fund["insider_net_shares_6m"] = ins["net_shares"]
                if mf.get("schemes_holding") is not None:
                    holding = mf["schemes_holding"]
                    fund["mf_schemes_holding"] = holding
                    fund["mf_schemes_added"] = mf.get("schemes_added", 0)
                    fund["mf_discovery_tier"] = 1 if holding < 5 else (2 if holding < 20 else 3)
                basis["fund"] = fund
                _after_fetch(src.setdefault("fund", {}), None, today)
            done.append(stage)
        except QuotaGone:
            raise
        except Exception as exc:
            s = src.setdefault(stage, {})
            s["error"] = str(exc)[:120]
            s["retry"] = (today + timedelta(days=1)).isoformat()
    return done


def refresh_shareholding(sym: str, c: dict, ctx: dict) -> None:
    """NSE shareholding (free): promoter/public history, and FII/DII/pledge plus named holders from the
    detailed filings of the latest, previous and year-ago quarters."""
    s = ctx["nse"]
    try:
        records = shp.fetch(s, sym)
    except Exception:
        ctx["nse"] = s = shp.session()     # one retry with fresh cookies
        records = shp.fetch(s, sym)
    inst_vals = shp.values(records)
    targets = shp.institutional_targets(records)
    texts = {}
    for label, url in targets.items():
        try:
            texts[label] = shp.fetch_xbrl_text(url)
        except Exception:
            pass
    inst = {label: shp.institutional_from_text(t) for label, t in texts.items()}
    try:
        q_dates = shp.target_dates(records)
        c["holding_history"] = shp.holding_history(
            records, {q_dates[lbl].isoformat(): v for lbl, v in inst.items() if lbl in q_dates},
            c.get("holding_history"))
    except Exception:
        pass
    if "latest" in inst:
        inst_vals.update(inst["latest"])
        if "prior_quarter" in inst:
            for k, prior_k in (("fii_holding", "fii_change_qoq"), ("dii_holding", "dii_change_qoq")):
                if k in inst["latest"] and k in inst["prior_quarter"]:
                    inst_vals[prior_k] = inst["latest"][k] - inst["prior_quarter"][k]
        if "year_ago" in inst and "pledge_pct" in inst["latest"] and "pledge_pct" in inst["year_ago"]:
            inst_vals["pledge_change"] = inst["latest"]["pledge_pct"] - inst["year_ago"]["pledge_pct"]
    # Named public holders matched against the investor registry. The matched names are stored and
    # counted against the registry's CURRENT statuses at scoring time, so confirming an investor
    # counts at the next run, not the next filing.
    agg_latest = agg_prior = None
    if "latest" in texts:
        try:
            holders = nh.named_holders_from_text(texts["latest"])
            matches = nh.match_registry(holders, ctx["registry"])
            if matches:
                ctx["symbol_matches"][sym] = matches
            inst_vals["_matched_latest"] = sorted({m["investor"] for m in matches})
            agg_latest = nh.aggregate(holders)
        except Exception:
            pass
    if "prior_quarter" in texts:
        try:
            holders = nh.named_holders_from_text(texts["prior_quarter"])
            inst_vals["_matched_prior"] = sorted({m["investor"] for m in nh.match_registry(holders, ctx["registry"])})
            agg_prior = nh.aggregate(holders)
        except Exception:
            pass
    if agg_latest is not None and agg_prior is not None:
        inst_vals["holder_count_change"] = agg_latest["holder_count"] - agg_prior["holder_count"]
        if agg_latest["top10_pct"] is not None and agg_prior["top10_pct"] is not None:
            inst_vals["top10_holding_change"] = agg_latest["top10_pct"] - agg_prior["top10_pct"]
    inst_vals.pop("_promoter_period", None)
    c["basis"]["inst"] = inst_vals
    src = c["src"].setdefault("shp", {})
    src["quarter"] = records[0]["date"].isoformat() if records else None
    src["v"] = SHP_VERSION


def company_values(sym: str, c: dict, ctx: dict, prior_entry: dict | None) -> tuple[dict, list | None]:
    """Every parameter for one company from its stored figures, today's prices and today's corporate
    actions -- no network calls except the per-sector news counts (cached per run)."""
    b = c.get("basis") or {}
    values = {}
    values.update(b.get("fin") or {})
    values.update({k: v for k, v in (b.get("ann") or {}).items() if not k.startswith("_")})
    px = ctx["prices"].get(sym)
    last = None
    if px and px[0]:
        series, volume, delivery = px
        values.update(price_values(series, delivery, volume))
        values.update(index_relative_values(series, ctx["nifty"]))
        last = series[-1][1]
    else:
        values.update(_cells_of(prior_entry, PRICE_KEYS))     # no price file today: keep the last figures
    if b.get("val") and last:
        values.update(valuation_from_basis(b["val"], last))
    else:
        values.update(b.get("val_cells") or _cells_of(prior_entry, VAL_KEYS))
    inst = b.get("inst") or {}
    values.update({k: v for k, v in inst.items() if not k.startswith("_")})
    if "_matched_latest" in inst:
        status = ctx["investor_status"]
        latest = {n for n in inst["_matched_latest"] if status.get(n) == "confirmed"}
        values["registry_holders"] = len(latest)
        if "_matched_prior" in inst:
            prior = {n for n in inst["_matched_prior"] if status.get(n) == "confirmed"}
            values["registry_new_entrants"] = len(latest - prior)
    values.update({k: v for k, v in (b.get("fund") or {}).items() if not k.startswith("_")})
    ca_list = None
    if ctx["ca_by_sym"] is not None:
        recs = ctx["ca_by_sym"].get(sym, [])
        ca_list = ca.recent_and_upcoming(recs, ctx["today"])
        cav = ca.values(recs, ctx["today"])
        values["buyback_flag"] = cav["buyback_flag"]
        if last and cav.get("dividend_per_share_ttm") is not None:
            values["dividend_yield"] = cav["dividend_per_share_ttm"] / last * 100
        else:
            values.pop("dividend_yield", None)
    sector = ctx["sector_map"].get(sym)
    if sector:
        cache = ctx["sector_cache"]
        if sector not in cache:
            try:
                cache[sector] = {"sector_news_count": sector_news.sector_news_count(sector)}
            except Exception:
                cache[sector] = {}
            try:
                cache[sector]["regulatory_events"] = sector_news.regulatory_events(sector)
            except Exception:
                pass
        values.update(cache[sector])
    return values, ca_list


def main() -> dict:
    """One run: read the free market-wide lists (filings, corporate actions, prices), work out what
    each company needs, fetch only that -- most-needed first, BharatStock calls within the day's
    budget -- then rescore every company from stored figures and today's prices. Reports whether
    doable work remains (more_work) so the workflow can start another run."""
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    started = time.time()
    today = datetime.now(config.IST).date()
    utc_day = datetime.now(timezone.utc).date().isoformat()
    names = universe()
    existing, sha = fetch_existing()
    state = load_state()
    company_names = dict(existing.get("names") or {})
    try:
        company_names.update(fetch_company_names())
    except Exception:
        pass   # names are a nicety for the stock report; never fail a batch over them
    industries = dict(existing.get("industries") or {})
    try:
        industries.update(fetch_industries())
    except Exception:
        pass   # same: sector analytics fall back to the last good map
    prior_stocks = {s["symbol"]: s for s in existing.get("stocks", []) if isinstance(s, dict) and s.get("symbol")}
    prior_matches = dict(existing.get("investor_matches") or {})
    already_alerted = dict(existing.get("alerted") or {})
    try:
        registry_investors = json.loads(REGISTRY_FILE.read_text(encoding="utf-8")).get("investors", [])
    except (OSError, ValueError):
        registry_investors = []
    try:
        sector_map = json.loads(SECTOR_MAP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sector_map = {}
    try:
        existing_mb = json.loads(MULTIBAGGER_FILE.read_text(encoding="utf-8")) if MULTIBAGGER_FILE.exists() else {}
    except (OSError, ValueError):
        existing_mb = {}
    prior_mb = {r["symbol"]: r for r in existing_mb.get("ranked", []) if isinstance(r, dict) and r.get("symbol")}
    mb_failures = {f["symbol"]: f for f in existing_mb.get("failures", []) if isinstance(f, dict) and f.get("symbol")}

    usage = state.get("bs_usage") or {}
    if usage.get("date") != utc_day:
        usage = {"date": utc_day, "requests": 0, "exhausted": False}
    companies = state.setdefault("companies", {})
    migrated = 0
    for sym in names:
        if sym not in companies:
            companies[sym] = migrate(prior_stocks.get(sym))
            migrated += 1

    # 1. Free market-wide lists.
    nse = shp.session()
    feeds = state.setdefault("feeds", {})
    log = {"feeds": {}}
    results_filed = {}
    for name, func, stage, key_name in (("results", nse_feeds.results_filed, "fin", "period"),
                                        ("shareholding", nse_feeds.shareholding_filed, "shp", "quarter")):
        since = _date(feeds.get(name))
        start = (since - timedelta(days=FEED_OVERLAP)) if since else today - timedelta(days=FIRST_FEED_LOOKBACK)
        try:
            filed = func(nse, start, today)
            if name == "results":
                results_filed = filed
            feeds[name] = today.isoformat()
            log["feeds"][name] = {"from": start.isoformat(), "companies_filed": len(filed),
                                  "newer_than_stored": _mark_wants(companies, filed, stage, key_name)}
        except Exception as exc:
            log["feeds"][name] = {"error": str(exc)[:120]}
    since = _date(feeds.get("documents"))
    if since:      # the first run fills each company from its own list instead
        try:
            filed = docs_mod.new_filings(nse, since - timedelta(days=FEED_OVERLAP), today)
            added = 0
            for sym, kinds in filed.items():
                if sym in companies:
                    for kind, items in kinds.items():
                        added += docs_mod.merge(companies[sym].setdefault("docs", {}), kind, items)
            log["feeds"]["documents"] = {"companies_filed": len(filed), "new_documents": added}
        except Exception as exc:
            log["feeds"]["documents"] = {"error": str(exc)[:120]}
    feeds["documents"] = today.isoformat()
    ca_by_sym = None
    try:
        ca_by_sym = ca.fetch_bulk(nse, today - timedelta(days=bhav.LOOKBACK_DAYS + 5), today + timedelta(days=120))
        state["price_factors"] = {s: [[e.isoformat(), f] for e, f in ca.price_factors(r)]
                                  for s, r in ca_by_sym.items() if ca.price_factors(r)}
        log["feeds"]["corporate_actions"] = {"companies": len(ca_by_sym)}
    except Exception as exc:
        log["feeds"]["corporate_actions"] = {"error": str(exc)[:120] + " (using the last good split/bonus list)"}
    factors = {s: [(date.fromisoformat(e), f) for e, f in ev] for s, ev in (state.get("price_factors") or {}).items()}
    prices = {}
    try:
        log["prices"] = bhav.refresh(today)
        prices = bhav.load(factors, today)
        latest_px = max((p[0][-1][0] for p in prices.values() if p[0]), default=None)
        log["prices"].update({"companies": sum(1 for s in names if s in prices), "as_of": _iso(latest_px)})
    except Exception as exc:
        log["prices"] = {"error": str(exc)[:120] + " (price figures kept from the last run)"}

    # 2. What each company needs, most-needed first.
    plan = {sym: needs(companies[sym], prior_mb.get(sym), today) for sym in names}
    work = sorted((s for s in names if plan[s]), key=lambda s: (_priority(plan[s], companies[s]), s))

    def bs_ok():
        return not usage["exhausted"] and usage["requests"] < BS_DAILY_BUDGET

    ctx = {"today": today, "key": key, "nse": nse, "bs_ok": bs_ok, "mb_new": {}, "mb_failures": mb_failures,
           "prior_mb": prior_mb, "registry": registry_investors, "symbol_matches": {}}
    refreshed, stage_counts, partial = set(), {}, False
    bs_start = BS_REQUESTS[0]
    for sym in work:
        if time.time() - started > TIME_BUDGET_SECONDS:
            partial = True
            break
        stages = [st_ for st_ in plan[sym] if st_ not in BS_STAGES or bs_ok()]
        if not stages:
            continue
        before = BS_REQUESTS[0]
        try:
            done = refresh_company(sym, companies[sym], stages, ctx)
        except QuotaGone:
            usage["exhausted"] = True
            done = []
        usage["requests"] += BS_REQUESTS[0] - before
        if done:
            refreshed.add(sym)
            for st_ in done:
                stage_counts[st_] = stage_counts.get(st_, 0) + 1
        time.sleep(0.2)

    # 3. Rescore every company from stored figures and today's prices.
    investor_status = {inv["name"]: inv.get("status") for inv in registry_investors if inv.get("name")}
    ctx.update({"prices": prices, "nifty": load_nifty_series(), "ca_by_sym": ca_by_sym, "sector_map": sector_map,
                "sector_cache": {}, "investor_status": investor_status})
    stocks = []
    for sym in names:
        c, prior = companies[sym], prior_stocks.get(sym)
        values, ca_list = company_values(sym, c, ctx, prior)
        result = evaluate({k: v for k, v in values.items() if not k.startswith("_")})
        fin = (c.get("basis") or {}).get("fin") or {}
        entry = {"symbol": sym, "latest_period": fin.get("_latest_period"), "quarters": fin.get("_quarters", 0), **result}
        if ca_list is not None:
            entry["actions"] = ca_list
        elif prior and prior.get("actions"):
            entry["actions"] = prior["actions"]
        if sector_map.get(sym):
            entry["sector"] = sector_map[sym]
        if c.get("holding_history"):
            entry["holding_history"] = c["holding_history"]
        shp_src = (c.get("src") or {}).get("shp") or {}
        if shp_src.get("v"):
            entry["shp_v"] = shp_src["v"]
        # The "What changed" feed compares with the figures from before this company's last refresh.
        if sym in refreshed or not prior:
            entry["scored_on"] = today.isoformat()
            if prior and prior.get("cells"):
                snap = snapshot(prior, prior_mb.get(sym))
                if snap:
                    entry["prev"] = snap
        else:
            entry["scored_on"] = prior.get("scored_on") or today.isoformat()
            if prior.get("prev"):
                entry["prev"] = prior["prev"]
        entry["fresh"] = {k: (c.get("src") or {}).get(k, {}).get("on") for k in ("fin", "ann", "shp", "fund", "docs")}
        stocks.append(entry)
        mb = ctx["mb_new"].get(sym)
        fund = (c.get("basis") or {}).get("fund") or {}
        if mb is not None and mb.get("score") is not None and mb["score"] >= 2 and "_ins" in fund:
            mb["promoter"], mb["mutual_funds"] = fund["_ins"], fund.get("_mf")
    # Only companies listed today. A symbol that has left NSE's list (delisted, merged, or a temporary
    # rights-entitlement line such as CENTEXT-RE) is dropped instead of carried forever -- it made the
    # dashboard read "2,575 of 2,574 listed" (10 Oct 2026).
    merged_stocks = stocks
    apply_sector_aggregates(merged_stocks, sector_map)
    prior_matches.update(ctx["symbol_matches"])

    # 4. What is still needed, for the tracker and the workflow's decision to run again.
    after = {sym: needs(companies[sym], ctx["mb_new"].get(sym) or prior_mb.get(sym), today) for sym in names}
    pending = {st_: sum(1 for s in names if st_ in after[s]) for st_ in ("fin", "ann", "shp", "fund", "docs")}
    doable = [s for s in names if any(st_ not in BS_STAGES or bs_ok() for st_ in after[s])]
    DOCS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DOCS_FILE.write_text(json.dumps({s: companies[s]["docs"] for s in names if companies[s].get("docs")},
                                    ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    more_work = bool(doable) and bool(refreshed)
    cycle_complete = not doable
    mb_total = merge_and_write_multibagger(list(ctx["mb_new"].values()), prior_mb, mb_failures, names, cycle_complete)
    # Shortlist: two lists by style, weekly record and track record (hub/shortlist.py). prior_mb now holds
    # the merged multi-bagger scores.
    try:
        shortlist_summary = shortlist_mod.publish(merged_stocks, prior_mb, industries, prices, ctx["nifty"], today,
                                                  datetime.now(config.IST).isoformat(timespec="minutes"), company_names)
    except Exception as exc:
        shortlist_summary = {"error": str(exc)[:200]}
    # The phone's "Today" digest (hub/digest.py), for the Shortlist and the watchlist.
    try:
        sl_payload = json.loads(shortlist_mod.OUT_FILE.read_text(encoding="utf-8"))
        shortlist_summary["digest"] = digest_mod.build(sl_payload, companies, merged_stocks, prices, results_filed,
                                                       company_names, today)
    except Exception as exc:
        shortlist_summary["digest"] = {"error": str(exc)[:200]}
    today_ist = today.isoformat()
    new_findings, alerted = alerts.find_new_discoveries(merged_stocks, prior_mb, already_alerted, today_ist)
    alert_result = alerts.send_alert(new_findings, os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", ""))

    tracker = {
        "bharatstock": {"day_utc": usage["date"], "requests_today": usage["requests"], "budget": BS_DAILY_BUDGET,
                        "allowance_used_up": usage["exhausted"], "requests_this_run": BS_REQUESTS[0] - bs_start},
        "refreshed_this_run": {"companies": len(refreshed), **stage_counts},
        "pending": pending,
        "pending_waiting_for_bharatstock": sum(1 for s in names if after[s] and s not in doable),
        "no_bharatstock_results": sum(1 for s in names if ((companies[s].get("src") or {}).get("fin") or {}).get("empty")),
        "never_read": sum(1 for s in names if not (companies[s].get("src") or {}).get("fin")),
        "migrated_this_run": migrated,
        **log,
    }
    state["bs_usage"] = usage
    state["tracker"] = tracker
    save_state(state)

    payload = {
        "generated": datetime.now(config.IST).isoformat(timespec="minutes"),
        "partial": partial,
        "universe": len(names),
        "processed": len(refreshed),
        "cursor_next": 0,
        "cycle_complete": cycle_complete,
        "total_stocks": len(merged_stocks),
        "tracker": tracker,
        "rules": {k: v[0] for k, v in RULES.items()},
        "not_yet_implemented": NOT_YET,
        "stocks": merged_stocks,
        # Symbol -> company name from NSE's EQUITY_L list, for the admin stock report.
        "names": company_names,
        # Symbol -> NSE industry (NIFTY Total Market constituents), for sector analytics and peers.
        "industries": industries,
        # Review list, every name-alias match regardless of registry status -- the owner confirms an
        # investor in hub/registry.json before it counts toward registry_holders/registry_new_entrants.
        "investor_matches": prior_matches,
        # Which symbol/tier combos have already triggered an email, so the same finding doesn't
        # re-alert every batch. See hub/alerts.py.
        "alerted": alerted,
    }
    publish(payload, sha)
    try:      # the admin dashboard's compact copy; library.json above is the record
        library_compact.publish(PRIVATE_REPO, "library_compact.json", payload, _private_headers())
    except Exception as exc:
        print(f"compact copy not published: {exc}")
    return {k: v for k, v in payload.items()
            if k not in ("stocks", "rules", "not_yet_implemented", "investor_matches", "alerted", "names", "industries")} | {
        "more_work": more_work, "stocks_written": len(merged_stocks), "shortlist": shortlist_summary,
        "symbols_with_matches": len(prior_matches),
        "multibagger_stocks_written": mb_total, "multibagger_batch_written": len(ctx["mb_new"]),
        "new_discovery_findings": len(new_findings), "alert_result": alert_result,
        "multibagger_failure_count": len(mb_failures),
        "multibagger_failure_sample": list(mb_failures.values())[:3]}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False, default=str))
