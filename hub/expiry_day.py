"""
NIFTY expiry-day file for the phone (docs/data/expiry.json). Runs inside live.yml every run; does nothing unless the
relay says today is a NIFTY expiry.

Since 13 Oct 2026 it makes no Kite call: it asks the relay (?mode=expiry_close, behind RELAY_KEY), which computes the
expiry meter's reading from the platform's one shared Kite snapshot (relay/Market.gs, Expiry.gs) and records the
reading for the meter's learning. Fields kept as the phone panel expects them, plus "prediction" (the meter's expected
close). Not a prediction of the exact close: walls and max pain are where price often sticks on expiry, the range is
the market's own estimate (ATM straddle).
"""
import json
import os
import urllib.parse
import urllib.request

from . import config

EXPIRY_FILE = config.SITE_DIR / "data" / "expiry.json"


def main() -> dict:
    url = os.environ["RELAY_URL"] + "?" + urllib.parse.urlencode({"mode": "expiry_close", "key": os.environ["RELAY_KEY"]})
    r = json.loads(urllib.request.urlopen(url, timeout=60).read())
    if not r.get("expiry_today") or r.get("error") or not r.get("rows"):
        print(f"No expiry reading: {r.get('error') or r.get('note') or 'not an expiry day'}")
        return {}
    rows = [{"strike": s, "ce_oi": c, "pe_oi": p} for s, c, p in r["rows"]]
    ce, pe = sum(x["ce_oi"] for x in rows), sum(x["pe_oi"] for x in rows)
    lo, hi = r["range"]
    out = {
        "ts": r["ts"], "expiry": r["date"], "spot": r["spot"], "atm": r["atm"], "straddle": r["straddle"],
        "prediction": r["prediction"], "implied_range": [lo, hi],
        "call_walls": [{"strike": s, "oi": o} for s, o in r["call_walls"]],
        "put_walls": [{"strike": s, "oi": o} for s, o in r["put_walls"]],
        "max_pain": r["max_pain"], "pin": max(rows, key=lambda x: x["ce_oi"] + x["pe_oi"])["strike"],
        "pcr_near": round(pe / ce, 2) if ce else None, "pcr_all": r.get("pcr"),
        "likely_range": [max(lo, r["put_wall"]), min(hi, r["call_wall"])], "rows": rows,
    }
    EXPIRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPIRY_FILE.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"::notice::EXPIRY {r['ts'][11:16]} IST spot {r['spot']} | expected close {r['prediction']} | range {lo}-{hi} | "
          f"walls {r['put_wall']}/{r['call_wall']} | max pain {r['max_pain']} | PCR {r.get('pcr')} | model {r.get('model')}")
    return out


if __name__ == "__main__":
    main()
