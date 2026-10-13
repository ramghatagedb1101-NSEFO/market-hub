"""
NIFTY expiry-day read (13 Oct 2026): where the market is likely to settle, from the option chain expiring today.

Runs inside live.yml on an expiry day (every few minutes in market hours); does nothing on other days.
Writes docs/data/expiry.json and prints a one-line summary as a GitHub notice.

What it measures (all from Kite quotes of today's NIFTY options, strikes within 4% of spot):
  - Call wall / put wall: the strikes with the most open call OI above spot and put OI below spot.
    Option sellers defend these; on expiry day price often stays between them.
  - Max pain: the settlement level at which option buyers as a whole collect the least.
  - ATM straddle: call + put at the strike nearest spot. On expiry day its price is the market's own
    estimate of the move left until the close (roughly a one-standard-deviation range).
  - PCR: put OI / call OI (near spot and overall).
None of these predicts the close exactly; together they give a range and the levels price tends to stick to.
"""
import json
from datetime import datetime

from . import config
from .sources import kite

EXPIRY_FILE = config.SITE_DIR / "data" / "expiry.json"
SPOT = "NSE:NIFTY 50"
RANGE_PCT = 4.0
NEAR_PCT = 1.5


def _chain(k, opts, spot):
    rows = [i for i in opts if abs(i["strike"] / spot - 1) * 100 <= RANGE_PCT]
    syms = [f"NFO:{i['tradingsymbol']}" for i in rows]
    quotes = {}
    for start in range(0, len(syms), 400):
        quotes.update(k.quote(syms[start:start + 400]))
    chain = {}
    for i in rows:
        q = quotes.get(f"NFO:{i['tradingsymbol']}")
        if not q:
            continue
        t = i["instrument_type"].lower()
        s = chain.setdefault(float(i["strike"]), {"ce": None, "pe": None, "ce_oi": 0, "pe_oi": 0})
        s[t] = float(q["last_price"])
        s[f"{t}_oi"] = int(q.get("oi") or 0)
    return chain


def _max_pain(chain):
    strikes = sorted(chain)
    def payout(x):
        return sum(v["ce_oi"] * max(0.0, x - s) + v["pe_oi"] * max(0.0, s - x) for s, v in chain.items())
    return min(strikes, key=payout)


def main() -> dict:
    now = datetime.now(config.IST)
    today = now.date()
    k = kite.client()
    opts = [i for i in k.instruments("NFO") if i["name"] == "NIFTY" and i["instrument_type"] in ("CE", "PE")
            and i["expiry"] == today]
    if not opts:
        print("Not a NIFTY expiry day.")
        return {}
    spot = float(k.quote([SPOT])[SPOT]["last_price"])
    chain = _chain(k, opts, spot)
    strikes = sorted(chain)
    atm = min(strikes, key=lambda s: abs(s - spot))
    above = [s for s in strikes if s > spot]
    below = [s for s in strikes if s < spot]
    by_ce = sorted(above, key=lambda s: chain[s]["ce_oi"], reverse=True)
    by_pe = sorted(below, key=lambda s: chain[s]["pe_oi"], reverse=True)
    straddle = (chain[atm]["ce"] or 0) + (chain[atm]["pe"] or 0)
    near = [s for s in strikes if abs(s / spot - 1) * 100 <= NEAR_PCT]
    ce_near = sum(chain[s]["ce_oi"] for s in near)
    pe_near = sum(chain[s]["pe_oi"] for s in near)
    ce_all = sum(v["ce_oi"] for v in chain.values())
    pe_all = sum(v["pe_oi"] for v in chain.values())
    pin = max(near, key=lambda s: chain[s]["ce_oi"] + chain[s]["pe_oi"]) if near else atm
    lo, hi = spot - straddle, spot + straddle
    call_wall, put_wall = (by_ce[0] if by_ce else None), (by_pe[0] if by_pe else None)
    likely = [max(lo, put_wall) if put_wall else lo, min(hi, call_wall) if call_wall else hi]

    out = {
        "ts": now.isoformat(timespec="seconds"), "expiry": today.isoformat(), "spot": round(spot, 2),
        "atm": atm, "straddle": round(straddle, 2),
        "implied_range": [round(lo, 2), round(hi, 2)],
        "call_walls": [{"strike": s, "oi": chain[s]["ce_oi"]} for s in by_ce[:3]],
        "put_walls": [{"strike": s, "oi": chain[s]["pe_oi"]} for s in by_pe[:3]],
        "max_pain": _max_pain(chain), "pin": pin,
        "pcr_near": round(pe_near / ce_near, 2) if ce_near else None,
        "pcr_all": round(pe_all / ce_all, 2) if ce_all else None,
        "likely_range": [round(likely[0], 2), round(likely[1], 2)],
        "rows": [{"strike": s, "ce_oi": chain[s]["ce_oi"], "pe_oi": chain[s]["pe_oi"],
                  "ce": chain[s]["ce"], "pe": chain[s]["pe"]} for s in near],
    }
    EXPIRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    EXPIRY_FILE.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    cw = ", ".join(f"{w['strike']:.0f} ({w['oi']:,})" for w in out["call_walls"])
    pw = ", ".join(f"{w['strike']:.0f} ({w['oi']:,})" for w in out["put_walls"])
    print(f"::notice::EXPIRY {now:%H:%M} IST spot {spot:.2f} | ATM {atm:.0f} straddle {straddle:.1f} -> implied "
          f"{lo:.0f}-{hi:.0f} | call walls {cw} | put walls {pw} | max pain {out['max_pain']:.0f} | "
          f"pin {pin:.0f} | PCR near {out['pcr_near']} all {out['pcr_all']} | likely {likely[0]:.0f}-{likely[1]:.0f}")
    return out


if __name__ == "__main__":
    main()
