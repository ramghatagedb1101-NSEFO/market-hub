"""Email alerts for "new finding" stocks: a company whose mutual-fund ownership is still thin
(mf_discovery_tier 1 or 2, see hub/library.py) alongside strong library/multi-bagger fundamentals,
so it is worth the owner's attention before "it becomes part of the crowd."

Delivery goes through the existing Kite-login relay (Google Apps Script, already free, already
sends email for the admin dashboard's sign-in code) rather than a new email service -- same
RELAY_URL/RELAY_KEY secrets the daily job already uses, no new credential to create.

Needs relay/Code.gs's mode=alert handler deployed (see relay/README.md) before this can actually
send anything; until then send_alert() just gets a non-200 and the caller logs it, same as any
other best-effort network call in this codebase.
"""
import requests

MIN_TESTABLE = 10     # too little data tested is not a real signal either way
MIN_MET_RATIO = 0.7   # at least 70% of what was actually testable must be a pass (was 60%)
# Tightened 11 Oct 2026 after a fact check of the first Sunday alert (owner): Time Technoplast was sent as
# "watch" with mutual funds already owning 13.5% of it; Seshasayee Paper as "pounce" with profit up in
# only 2 of 8 quarters and Rs 1.5 cr traded a day. Few schemes is not enough on its own:
MAX_DII_PCT = 5.0       # funds (with insurers and banks) own under 5% of the company: really undiscovered
MIN_TURNOVER_CR = 2.0   # tradable: the Shortlist's floor, Rs 2 cr a day over 20 days
MIN_PROFIT_UP_8Q = 5    # profit grew in 5+ of the last 8 quarters: an improving business, not one good quarter
MIN_MB_SCORE = 3        # at least 3 of the 4 multi-bagger gates


def find_new_discoveries(stocks: list[dict], mb_by_symbol: dict, already_alerted: dict,
                          today: str, min_testable: int = MIN_TESTABLE,
                          min_met_ratio: float = MIN_MET_RATIO) -> tuple[list[dict], dict]:
    """Finds companies newly worth a discovery alert this batch, and the updated alerted-state to
    persist. A stock already alerted at its current tier is not re-alerted; a tier change (1<->2)
    is treated as new information and alerted again -- simple and errs toward over-notifying rather
    than silently dropping a stock the moment its status shifts, matching the owner's own stated
    preference for the tier split itself."""
    findings = []
    updated = dict(already_alerted)
    for s in stocks:
        cell = (s.get("cells") or {}).get("mf_discovery_tier")
        if not cell or cell.get("value") not in (1, 2):
            continue
        testable, met = s.get("testable", 0), s.get("met", 0)
        if testable < min_testable or (met / testable) < min_met_ratio:
            continue
        val = lambda k: ((s.get("cells") or {}).get(k) or {}).get("value")
        dii, turnover, up8 = val("dii_holding"), val("avg_turnover_20d"), val("profit_consistency_8q")
        if dii is None or dii >= MAX_DII_PCT or turnover is None or turnover < MIN_TURNOVER_CR \
                or up8 is None or up8 < MIN_PROFIT_UP_8Q:
            continue
        if ((mb_by_symbol.get(s.get("symbol")) or {}).get("score") or 0) < MIN_MB_SCORE:
            continue
        sym = s.get("symbol")
        tier = cell["value"]
        prev = already_alerted.get(sym)
        if prev is not None and prev.get("tier") == tier:
            continue
        findings.append({
            "symbol": sym, "tier": tier, "met": met, "testable": testable,
            "data_quality_pct": s.get("data_quality_pct"),
            "dii_pct": round(dii, 2), "turnover_cr": round(turnover, 1), "profit_up_8q": up8,
            "mb_score": (mb_by_symbol.get(sym) or {}).get("score"),
        })
        updated[sym] = {"tier": tier, "date": today}
    return findings, updated


def send_alert(findings: list[dict], relay_url: str, relay_key: str) -> dict:
    """Best-effort: a relay/network failure here must never fail the library batch. Returns a small
    status dict for the caller to log, never raises."""
    if not findings or not relay_url or not relay_key:
        return {"sent": False, "reason": "no findings or relay not configured"}
    try:
        r = requests.post(relay_url, params={"mode": "alert", "key": relay_key},
                           json={"findings": findings}, timeout=30)
        r.raise_for_status()
        return {"sent": True, "count": len(findings), "relay_response": r.json()}
    except Exception as exc:
        return {"sent": False, "reason": str(exc)[:160]}
