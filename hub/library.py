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
from datetime import date, datetime, timedelta

import requests

from . import config
from . import alerts
from .multibagger import (universe, fetch, fetch_annual, fetch_insider, fetch_mf,
                          insider_signal, mf_counts, _consolidated, score, UA, MAX_PAGES, EQUITY_LIST,
                          FIELDS, ENDPOINT_COUNTS)
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
PRICES_URL = "https://bharatstockapi.com/v1/stocks/{t}/prices"


def fetch_price_history(symbol: str, key: str) -> tuple[list[tuple[date, float]], list[float], list[float]]:
    """Same prices endpoint as backtest_multibagger.prices(), kept separate so a volume/delivery
    field-name guess here can never affect that tool's own (working) close-price-only fetch.

    Volume and delivery-percentage field names are read defensively (several candidate keys), the
    same pattern already used throughout this file for uncertain BharatStock/NSE field names: a
    wrong guess just leaves the value out (not_testable), never a fabricated figure."""
    closes, volume, delivery = [], [], []
    page = 1
    while page <= MAX_PAGES:
        params = {"from": "2010-01-01", "page_size": 1000}
        if page > 1:
            params["page"] = page
        r = requests.get(PRICES_URL.format(t=symbol), params=params, headers={"X-API-Key": key, **UA}, timeout=30)
        if r.status_code == 404:
            break
        r.raise_for_status()
        body = r.json()
        rows = body.get("data", [])
        for x in rows:
            c = x.get("adjusted_close") or x.get("close")
            if c is None or not x.get("trade_date"):
                continue
            closes.append((date.fromisoformat(str(x["trade_date"])[:10]), float(c)))
            v = x.get("volume") or x.get("total_traded_qty") or x.get("traded_volume") or x.get("total_volume")
            volume.append(float(v) if v is not None else None)
            d = (x.get("delivery_percentage") or x.get("delivery_pct") or
                 x.get("pct_deliverable") or x.get("deliverable_pct"))
            delivery.append(float(d) if d is not None else None)
        pag = body.get("pagination") or {}
        if not rows or not pag.get("has_next", page < (pag.get("total_pages") or 1)):
            break
        page += 1
    closes.sort(key=lambda x: x[0])
    # volume/delivery were appended in fetch order, matching closes before the sort -- only trust
    # them if every row actually had a value, otherwise a reordered/partial list would misalign.
    vol_clean = volume if volume and all(v is not None for v in volume) else []
    del_clean = delivery if delivery and all(d is not None for d in delivery) else []
    return closes, vol_clean, del_clean


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
    scored_on = datetime.now(config.IST).date().isoformat()
    start_idx = existing.get("cursor_next", 0)
    if not isinstance(start_idx, int) or not (0 <= start_idx < len(names)):
        start_idx = 0
    prior_stocks = {s["symbol"]: s for s in existing.get("stocks", []) if isinstance(s, dict) and s.get("symbol")}
    prior_matches = {k: v for k, v in (existing.get("investor_matches") or {}).items()}
    already_alerted = dict(existing.get("alerted") or {})
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
    nifty_series = load_nifty_series()
    try:
        existing_mb = json.loads(MULTIBAGGER_FILE.read_text(encoding="utf-8")) if MULTIBAGGER_FILE.exists() else {}
    except (OSError, ValueError):
        existing_mb = {}
    prior_mb = {r["symbol"]: r for r in existing_mb.get("ranked", []) if isinstance(r, dict) and r.get("symbol")}
    mb_failures = {f["symbol"]: f for f in existing_mb.get("failures", []) if isinstance(f, dict) and f.get("symbol")}
    stocks, mb_stocks, partial, processed = [], [], False, 0
    for sym in names[start_idx:]:
        if time.time() - started > TIME_BUDGET_SECONDS:
            partial = True
            break
        processed += 1
        try:
            rows = fetch(sym, key)
            values = financial_values(rows)
            annual_rows = []
            try:
                annual_rows = fetch_annual(sym, key)
                values.update(cash_flow_values(annual_rows))
            except Exception as exc:
                if _is_quota_exhausted(exc):
                    raise
            try:
                px, px_volume, px_delivery = fetch_price_history(sym, key)
            except Exception as exc:
                if _is_quota_exhausted(exc):
                    raise
                px, px_volume, px_delivery = [], [], []
            values.update(price_values(px, px_delivery, px_volume))
            values.update(index_relative_values(px, nifty_series))
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
            # Quarterly holding history for the admin report's trend chart (9 Oct 2026): every quarter
            # NSE lists for promoter/public, plus FII/DII for the filings read above, merged with what
            # earlier batches stored so FII/DII build up over time.
            try:
                q_dates = shp.target_dates(nse_records)
                holding_hist = shp.holding_history(
                    nse_records, {q_dates[lbl].isoformat(): v for lbl, v in inst.items() if lbl in q_dates},
                    (prior_stocks.get(sym) or {}).get("holding_history"))
            except Exception:
                holding_hist = (prior_stocks.get(sym) or {}).get("holding_history")
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
            ca_list = None
            try:
                ca_records = ca.fetch(nse_session, sym)
                ca_list = ca.recent_and_upcoming(ca_records)
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
            # Multi-bagger score from the SAME rows/annual_rows already fetched above for the
            # 124-parameter screen -- this is the whole point of merging the two pipelines: one
            # BharatStock fetch per company serves both screens instead of two separate weekly runs
            # each pulling the same financials. Computed here (before the insider/fund fetch below)
            # so its own ">= 2" gate and the library screen's "profit growing" gate can share a
            # single insider/fund fetch when both happen to fire for the same company, instead of
            # fetching the same two endpoints twice.
            mb_res = None
            try:
                mb_res = score(sym, rows, annual_rows)
            except Exception as exc:
                mb_failures[sym] = {"symbol": sym, "error": str(exc)[:120]}
            # Insider and fund data only for companies with profit growth, or a multi-bagger score of
            # 2+: keeps the run inside the daily request limit while still covering either screen's
            # reason to want it.
            wants_fund_data = ((values.get("profit_yoy") is not None and values["profit_yoy"] > 0) or
                                (mb_res is not None and mb_res.get("score") is not None and mb_res["score"] >= 2))
            if wants_fund_data:
                try:
                    ins = insider_signal(fetch_insider(sym, key))
                except Exception as exc:
                    if _is_quota_exhausted(exc):
                        raise
                    ins = {"status": f"insider fetch failed: {str(exc)[:80]}"}
                try:
                    mf = mf_counts(fetch_mf(sym, key))
                except Exception as exc:
                    if _is_quota_exhausted(exc):
                        raise
                    mf = {"status": f"fund fetch failed: {str(exc)[:80]}"}
                if ins.get("net_shares") is not None:
                    values["insider_net_shares_6m"] = ins["net_shares"]
                if mf.get("schemes_holding") is not None:
                    holding = mf["schemes_holding"]
                    values["mf_schemes_holding"] = holding
                    values["mf_schemes_added"] = mf.get("schemes_added", 0)
                    values["mf_discovery_tier"] = 1 if holding < 5 else (2 if holding < 20 else 3)
                if mb_res is not None and mb_res.get("score") is not None and mb_res["score"] >= 2:
                    mb_res["promoter"] = ins
                    mb_res["mutual_funds"] = mf
            result = evaluate({k: v for k, v in values.items() if not k.startswith("_")})
            entry = {"symbol": sym, "latest_period": values.get("_latest_period"),
                     "quarters": values.get("_quarters", 0), **result}
            # For the admin stock report (9 Oct 2026): NSE corporate actions (public data, last year
            # plus anything upcoming) and the sector, both already fetched above and previously dropped.
            if ca_list is not None:
                entry["actions"] = ca_list
            if sector:
                entry["sector"] = sector
            if holding_hist:
                entry["holding_history"] = holding_hist
            # For the dashboard's "What changed" feed (9 Oct 2026): when this company was scored, and
            # its key figures as of the previous time it was scored.
            entry["scored_on"] = scored_on
            # Shareholding read with the 10 Oct 2026 corrections (FII = FPI only; quarter-end filings
            # only). The dashboard ignores FII changes on entries without this until they are re-read.
            entry["shp_v"] = SHP_VERSION
            prior_entry = prior_stocks.get(sym)
            if prior_entry and prior_entry.get("cells"):
                snap = snapshot(prior_entry, prior_mb.get(sym))
                if snap:
                    entry["prev"] = snap
            stocks.append(entry)
            if mb_res is not None:
                mb_stocks.append(mb_res)
                mb_failures.pop(sym, None)
        except Exception as exc:
            if _is_quota_exhausted(exc):
                # The day's BharatStock quota is gone, not just this one call -- every remaining
                # company in this batch would fail the exact same way. Stop here instead of
                # "processing" all of them into a worthless all-empty error entry (seen 8 Oct: every
                # company after the first 429 showed zero data on the admin dashboard). processed is
                # rolled back so cursor_next points at this exact symbol again, not past it --
                # nothing was actually learned about it this run, so the next batch should retry it
                # fresh rather than wait a full cycle for this index range to come around again.
                processed -= 1
                partial = True
                break
            stocks.append({"symbol": sym, "error": str(exc)[:120]})
        time.sleep(0.2)

    end_idx = start_idx + processed
    cycle_complete = end_idx >= len(names)
    cursor_next = 0 if cycle_complete else end_idx
    prior_stocks.update({s["symbol"]: s for s in stocks})
    merged_stocks = list(prior_stocks.values())
    apply_sector_aggregates(merged_stocks, sector_map)
    prior_matches.update(symbol_matches)
    mb_total = merge_and_write_multibagger(mb_stocks, prior_mb, mb_failures, names, cycle_complete)

    # Email alert for stocks newly in the discovery tier (thin mutual-fund ownership + strong
    # fundamentals) -- scans the full merged set, not just this batch, since sector aggregation just
    # above can push a company over the met-ratio threshold without it being re-scored this batch.
    today_ist = datetime.now(config.IST).date().isoformat()
    new_findings, alerted = alerts.find_new_discoveries(merged_stocks, prior_mb, already_alerted, today_ist)
    alert_result = alerts.send_alert(new_findings, os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", ""))

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
    return {k: v for k, v in payload.items()
            if k not in ("stocks", "rules", "not_yet_implemented", "investor_matches", "alerted", "names", "industries")} | {
        "stocks_written": len(merged_stocks), "batch_written": len(stocks),
        "symbols_with_matches": len(prior_matches),
        "multibagger_stocks_written": mb_total, "multibagger_batch_written": len(mb_stocks),
        "new_discovery_findings": len(new_findings), "alert_result": alert_result,
        # Diagnostics only, so a zero-written batch (like 8 Oct's) can be explained from the GH
        # Actions log directly instead of needing private-repo access to read the real failures.
        "batch_error_count": sum(1 for s in stocks if "error" in s),
        "batch_error_sample": [s for s in stocks if "error" in s][:3],
        "multibagger_failure_count": len(mb_failures),
        "multibagger_failure_sample": list(mb_failures.values())[:3]}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
