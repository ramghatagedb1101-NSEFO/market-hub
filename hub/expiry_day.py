"""
Expiry-day file for the phone (docs/data/expiry.json): one item per index expiring today (NIFTY, SENSEX, BANK NIFTY).
Runs inside live.yml every run; writes nothing unless the relay says an index expires today.

Makes no Kite call: it asks the relay (?mode=expiry_close, behind RELAY_KEY), which computes the expiry meter's readings
from the platform's one shared Kite snapshot (relay/Market.gs, Expiry.gs) and records them for the meter's learning.
Also prints each index's track record (expected close at 10:00/12:00/14:00/15:00 vs the close, in bp) as run notices.
Not a prediction of the exact close: walls and max pain are where price often sticks on expiry, the range is the
market's own estimate (ATM straddle).

14 Oct 2026: each item also carries the change in wall OI since the day's first reading, what option sellers would pay
at settlement here and at max pain, and the next expiry's walls (relay reads that chain once a minute on expiry days).
Rows and walls accept both the old relay answer ([strike, oi]) and the new one ([strike, oi, change]).
"""
import json
import os
import urllib.parse
import urllib.request

from . import config

EXPIRY_FILE = config.SITE_DIR / "data" / "expiry.json"


def _walls(ws: list) -> list:
    return [{"strike": w[0], "oi": w[1], "change": w[2] if len(w) > 2 else None} for w in ws or []]


def _item(x: dict, ts: str, date: str) -> dict:
    rows = [{"strike": r[0], "ce_oi": r[1], "pe_oi": r[2]} for r in x["rows"]]
    ce, pe = sum(r["ce_oi"] for r in rows), sum(r["pe_oi"] for r in rows)
    # The relay's "likely" range is one standard deviation of the move left (ATM straddle / 0.8, about 2 in 3; relay
    # Version 62, 13 Oct 2026); "range" (+-straddle, about 3 in 5) is the fallback for an older relay.
    lo, hi = x.get("likely") or x["range"]
    n = x.get("next") or {}
    return {
        "id": x["id"], "label": x["label"], "ts": ts, "expiry": date, "spot": x["spot"], "atm": x["atm"],
        "straddle": x["straddle"], "sd": x.get("sd"), "prediction": x["prediction"], "implied_range": [lo, hi],
        "call_walls": _walls(x["call_walls"]), "put_walls": _walls(x["put_walls"]),
        "max_pain": x["max_pain"], "pin": max(rows, key=lambda r: r["ce_oi"] + r["pe_oi"])["strike"] if rows else x["atm"],
        "pcr_near": round(pe / ce, 2) if ce else None, "pcr_all": x.get("pcr"),
        "likely_range": [max(lo, x["put_wall"]), min(hi, x["call_wall"])], "rows": rows,
        "oi_since": (x.get("oi") or {}).get("since"), "sellers": x.get("sellers"), "step": x.get("step"),
        "next": None if not n or n.get("error") else {
            "expiry": n["expiry"], "call_walls": _walls(n.get("call_walls")), "put_walls": _walls(n.get("put_walls")),
            "max_pain": n.get("max_pain"), "pcr": n.get("pcr")},
    }


def _bp(v, close):
    return None if v is None else round((v - close) / close * 1e4)


def main() -> dict:
    url = os.environ["RELAY_URL"] + "?" + urllib.parse.urlencode({"mode": "expiry_close", "key": os.environ["RELAY_KEY"]})
    r = json.loads(urllib.request.urlopen(url, timeout=90).read())
    for idx, t in (r.get("tracks") or {}).items():
        for a in (t.get("accuracy") or [])[:1]:
            c = a["close"]
            print(f"::notice::TRACK {idx} {a['date']} close {c} | 10:00 {a.get('at10')} ({_bp(a.get('at10'), c)} bp) | "
                  f"12:00 {a.get('at12')} ({_bp(a.get('at12'), c)} bp) | 14:00 {a.get('at14')} ({_bp(a.get('at14'), c)} bp) | "
                  f"15:00 {a.get('at15')} ({_bp(a.get('at15'), c)} bp) | readings {a.get('readings')} | model {t.get('model')}")
    items = [_item(x, r["ts"], r["date"]) for x in (r.get("indices") or []) if not x.get("error") and x.get("rows")]
    if not r.get("expiry_today") or r.get("error") or not items:
        print(f"No expiry reading: {r.get('error') or r.get('note') or 'no index expires today'}")
        return {}
    out = {"ts": r["ts"], "date": r["date"], "items": items}
    EXPIRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPIRY_FILE.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    for x in items:
        print(f"::notice::EXPIRY {x['label']} {r['ts'][11:16]} IST spot {x['spot']} | expected close {x['prediction']} | "
              f"range {x['implied_range'][0]}-{x['implied_range'][1]} | walls {x['put_walls'][0]['strike'] if x['put_walls'] else '-'}"
              f"/{x['call_walls'][0]['strike'] if x['call_walls'] else '-'} | max pain {x['max_pain']} | PCR {x['pcr_all']}")
    return out


if __name__ == "__main__":
    main()
