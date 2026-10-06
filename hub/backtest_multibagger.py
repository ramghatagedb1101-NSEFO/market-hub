"""
Back-test of the multi-bagger gates on BharatStock history. Manual run only (workflow_dispatch).

For each past quarter-end (as-of date), the gates use only financials reported at least 60 days
before that date, so no later information leaks in. The forward return is measured from the as-of
date over 1 and 3 years, on adjusted closes, and compared with the median return of the universe on
the same dates.

Publishes summary statistics only (hit rates, average excess return by score, sample counts). No
per-company figures are written to disk or to the public repository.

Caveat stated in the output: the universe is today's index members, so the back-test is optimistic
(survivorship bias). It is still the right first test of whether the gates separate winners.
"""
import json
import os
import statistics as st
from datetime import date, datetime, timedelta

import requests

from . import config
from .multibagger import UA, universe, fetch, score

OUT_FILE = config.SITE_DIR / "data" / "backtest_multibagger.json"
PRICES = "https://bharatstockapi.com/v1/stocks/{t}/prices"
LAG_DAYS = 60            # results are available about 60 days after quarter-end
AS_OF_START = date(2016, 3, 31)
HORIZONS = (365, 1095)   # 1 and 3 years


# Diagnostics only: status counts, field names (never values) and error counts, so an empty run explains itself.
DIAG = {"price_http_status": {}, "price_field_names": [], "price_errors": 0, "first_error": None}


def prices(symbol: str, key: str) -> list[tuple[date, float]]:
    out, page = [], 1
    while True:
        r = requests.get(PRICES.format(t=symbol),
                         params={"from": "2010-01-01", "page": page, "page_size": 1000},
                         headers={"X-API-Key": key, **UA}, timeout=30)
        code = str(r.status_code)
        DIAG["price_http_status"][code] = DIAG["price_http_status"].get(code, 0) + 1
        if r.status_code == 404:
            break
        r.raise_for_status()
        body = r.json()
        rows = body.get("data", [])
        if rows and not DIAG["price_field_names"]:
            DIAG["price_field_names"] = sorted(rows[0].keys())
        for x in rows:
            c = x.get("adjusted_close") or x.get("close")
            if c is None or not x.get("trade_date"):
                continue
            out.append((date.fromisoformat(str(x["trade_date"])[:10]), float(c)))
        pag = body.get("pagination") or {}
        if not rows or not pag.get("has_next", page < (pag.get("total_pages") or 1)):
            break
        page += 1
    return sorted(out)


def price_on(series: list[tuple[date, float]], d: date):
    for day, c in series:
        if day >= d:
            return day, c
    return None


def quarter_ends():
    """Every quarter-end from AS_OF_START until about 13 months ago, so the 1-year return exists."""
    cutoff = date.today() - timedelta(days=400)
    for y in range(AS_OF_START.year, cutoff.year + 1):
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)):
            q = date(y, m, d)
            if AS_OF_START <= q <= cutoff:
                yield q


def main() -> dict:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    names = universe()
    fin, px = {}, {}
    for s in names:
        try:
            fin[s] = fetch(s, key)
            px[s] = prices(s, key)
        except Exception as exc:
            DIAG["price_errors"] += 1
            DIAG["first_error"] = DIAG["first_error"] or str(exc)[:120]
            continue
    dates = list(quarter_ends())
    obs = []   # (score, excess_1y, excess_3y, passed_all)
    for asof in dates:
        cutoff = asof - timedelta(days=LAG_DAYS)
        rets = {h: {} for h in HORIZONS}
        scores = {}
        for s in fin:
            rows = [x for x in fin[s] if x.get("period_end_date") and
                    date.fromisoformat(str(x["period_end_date"])[:10]) <= cutoff]
            sc = score(s, rows)
            if sc.get("score") is None:
                continue
            base = price_on(px.get(s, []), asof)
            if not base:
                continue
            ok = True
            for h in HORIZONS:
                end = price_on(px.get(s, []), asof + timedelta(days=h))
                if end and end[0] <= date.today():
                    rets[h][s] = end[1] / base[1] - 1
                else:
                    ok = False
            scores[s] = (sc["score"], ok)
        for s, (scr, ok) in scores.items():
            if not ok:
                continue
            e1 = rets[365].get(s)
            e3 = rets[1095].get(s)
            if e1 is None or e3 is None:
                continue
            med1 = st.median(rets[365].values()) if rets[365] else None
            med3 = st.median(rets[1095].values()) if rets[1095] else None
            if med1 is None or med3 is None:
                continue
            obs.append((scr, e1 - med1, e3 - med3))
    by = {}
    for scr in (0, 1, 2, 3, 4):
        rows = [o for o in obs if o[0] == scr]
        if not rows:
            by[str(scr)] = {"n": 0}
            continue
        by[str(scr)] = {
            "n": len(rows),
            "avg_excess_1y_pct": round(st.mean(o[1] for o in rows) * 100, 2),
            "beat_median_1y_pct": round(sum(1 for o in rows if o[1] > 0) / len(rows) * 100, 1),
            "avg_excess_3y_pct": round(st.mean(o[2] for o in rows) * 100, 2),
            "beat_median_3y_pct": round(sum(1 for o in rows if o[2] > 0) / len(rows) * 100, 1),
        }
    out = {
        "ts": datetime.now(config.IST).isoformat(timespec="minutes"),
        "universe": len(names),
        "names_with_data": len(fin),
        "as_of_dates": len(dates),
        "observations": len(obs),
        "diagnostics": {"names_with_prices": sum(1 for v in px.values() if v),
                        "price_rows": sum(len(v) for v in px.values()), **DIAG},
        "by_score": by,
        "caveats": [
            "Survivorship bias: the universe is today's Midcap 150 and Smallcap 250, so past winners that later left the index are missing. Results are optimistic.",
            "Gates use results reported at least 60 days before each as-of date.",
            "Returns are on adjusted closes against the median of the same universe on the same dates.",
            "Shareholding, insider and fund-holding signals are not back-tested: their history is not point-in-time in this run.",
        ],
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
