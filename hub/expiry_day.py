"""
Expiry-day file for the phone (docs/data/expiry.json): one item per index expiring today (NIFTY, SENSEX, BANK NIFTY).
Runs inside live.yml every run; writes nothing unless the relay says an index expires today.

Makes no Kite call: it asks the relay (?mode=expiry_close, behind RELAY_KEY), which computes the expiry meter's readings
from the platform's one shared Kite snapshot (relay/Market.gs, Expiry.gs) and records them for the meter's learning.
3 Nov 2026: the prediction is the morning call (GIFT Nifty at 09:00, fixed for the day) and the chance of settling above
each strike (relay expMorning_/expOdds_, hub/expiry_meter.py); the old "expected close" was the live price and is gone.

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
# The meter's record for the phone (hub/expiry_meter.py via the relay, 3 Nov 2026; was the replay scoreboard): written on
# any day the relay returns it. No timestamp inside, so live.yml's every-5-minutes run commits it only when it changes.
SCORE_FILE = config.SITE_DIR / "data" / "expiry_score.json"


def write_score(r: dict) -> dict | None:
    rec = r.get("record")
    if not rec:
        return None
    body = {"record": rec}
    text = json.dumps(body, separators=(",", ":"), sort_keys=True)
    if not SCORE_FILE.exists() or SCORE_FILE.read_text(encoding="utf-8") != text:
        SCORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SCORE_FILE.write_text(text, encoding="utf-8")
    return body


def _walls(ws: list) -> list:
    return [{"strike": w[0], "oi": w[1], "change": w[2] if len(w) > 2 else None} for w in ws or []]


def _item(x: dict, ts: str, date: str) -> dict:
    rows = [{"strike": r[0], "ce_oi": r[1], "pe_oi": r[2]} for r in x["rows"]]
    ce, pe = sum(r["ce_oi"] for r in rows), sum(r["pe_oi"] for r in rows)
    lo, hi = x["range"]                                 # +- the ATM straddle: the option market's own expected move
    n = x.get("next") or {}
    return {
        "id": x["id"], "label": x["label"], "ts": ts, "expiry": date, "spot": x["spot"], "atm": x["atm"],
        "straddle": x["straddle"], "implied_range": [lo, hi], "call": x.get("call"), "odds": x.get("odds"),
        "call_walls": _walls(x["call_walls"]), "put_walls": _walls(x["put_walls"]),
        "max_pain": x["max_pain"], "pin": max(rows, key=lambda r: r["ce_oi"] + r["pe_oi"])["strike"] if rows else x["atm"],
        "pcr_near": round(pe / ce, 2) if ce else None, "pcr_all": x.get("pcr"),
        "rows": rows,
        "oi_since": (x.get("oi") or {}).get("since"), "sellers": x.get("sellers"), "step": x.get("step"),
        "next": None if not n or n.get("error") else {
            "expiry": n["expiry"], "call_walls": _walls(n.get("call_walls")), "put_walls": _walls(n.get("put_walls")),
            "max_pain": n.get("max_pain"), "pcr": n.get("pcr")},
    }


def main() -> dict:
    url = os.environ["RELAY_URL"] + "?" + urllib.parse.urlencode({"mode": "expiry_close", "key": os.environ["RELAY_KEY"]})
    r = json.loads(urllib.request.urlopen(url, timeout=90).read())
    write_score(r)
    items = [_item(x, r["ts"], r["date"]) for x in (r.get("indices") or []) if not x.get("error") and x.get("rows")]
    if not r.get("expiry_today") or r.get("error") or not items:
        print(f"No expiry reading: {r.get('error') or r.get('note') or 'no index expires today'}")
        return {}
    out = {"ts": r["ts"], "date": r["date"], "items": items}
    EXPIRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPIRY_FILE.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    for x in items:
        c = x.get("call") or {}
        print(f"::notice::EXPIRY {x['label']} {r['ts'][11:16]} IST spot {x['spot']} | morning call {c.get('dir')} {c.get('chance')}% "
              f"{c.get('pred')} | 80% {(x.get('odds') or {}).get('range80')} | straddle range {x['implied_range'][0]}-{x['implied_range'][1]} | walls {x['put_walls'][0]['strike'] if x['put_walls'] else '-'}"
              f"/{x['call_walls'][0]['strike'] if x['call_walls'] else '-'} | max pain {x['max_pain']} | PCR {x['pcr_all']}")
    return out


if __name__ == "__main__":
    main()
