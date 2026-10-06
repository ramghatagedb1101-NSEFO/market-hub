"""
F&O suggestions for NIFTY and BANKNIFTY: nearest expiry and monthly expiry.

Uses the Kite option chain and the forecast bands from feed.json. Rule-based structure choice:
  - Band roughly centred on spot (|move| < NEUTRAL_MOVE_PCT): iron condor, short strikes just outside
    the band, long wings two strikes further out (defined risk).
  - Band clearly above spot: bull call spread. Clearly below: bear put spread.
Premiums are last traded prices. These are model suggestions with no track record yet.
"""
import json
from datetime import datetime

from . import config
from .sources import kite

FNO_FILE = config.SITE_DIR / "data" / "fno.json"
UNDERLYINGS = {"NIFTY": ("NSE:NIFTY 50", "NIFTY"), "BANKNIFTY": ("NSE:NIFTY BANK", "BANKNIFTY")}
NEUTRAL_MOVE_PCT = 0.5
WING_STRIKES = 2
CHAIN_RANGE_PCT = 8.0
MIN_CREDIT_TO_WIDTH = 0.10     # condor credit must be at least 10% of the wing width
MIN_SHORT_PREMIUM = 5.0        # short strikes must trade for at least Rs 5
MAX_DIRECTIONAL_HALF_WIDTH_PCT = 1.5   # directional calls only when the band is tight


def _expiries(opts, today):
    # Strictly after today: an expiry that closes today has no forecast band to trade against.
    exps = sorted({i["expiry"] for i in opts if i["expiry"] > today})
    nearest = exps[0] if exps else None
    by_month = {}
    for e in exps:
        by_month[(e.year, e.month)] = e          # last expiry in each month = monthly
    monthly = next((e for e in sorted(by_month.values()) if e >= today), None)
    return nearest, monthly


def _chain(k, opts, expiry, spot):
    rows = [i for i in opts if i["expiry"] == expiry
            and abs(i["strike"] / spot - 1) * 100 <= CHAIN_RANGE_PCT]
    syms = [f"NFO:{i['tradingsymbol']}" for i in rows]
    quotes = {}
    for start in range(0, len(syms), 400):
        quotes.update(k.quote(syms[start:start + 400]))
    chain = {}
    for i in rows:
        q = quotes.get(f"NFO:{i['tradingsymbol']}")
        if not q:
            continue
        side = chain.setdefault(float(i["strike"]), {"CE": None, "PE": None, "ce_oi": 0, "pe_oi": 0})
        side[i["instrument_type"]] = float(q["last_price"])
        side[f"{i['instrument_type'].lower()}_oi"] = int(q.get("oi", 0))
    return chain, rows[0]["lot_size"] if rows else None


def _pcr(chain):
    ce = sum(v["ce_oi"] for v in chain.values())
    pe = sum(v["pe_oi"] for v in chain.values())
    return round(pe / ce, 2) if ce else None


def _suggest(spot, lo, hi, chain, lot):
    strikes = sorted(s for s in chain if chain[s]["CE"] is not None and chain[s]["PE"] is not None)
    if len(strikes) < 6:
        return {"structure": None, "reason": "Not enough liquid strikes in the chain."}
    step = strikes[1] - strikes[0]
    move = ((lo + hi) / 2 / spot - 1) * 100
    atm = min(strikes, key=lambda s: abs(s - spot))

    half_width_pct = (hi - lo) / 2 / spot * 100

    if abs(move) < NEUTRAL_MOVE_PCT:
        ce_s = min((s for s in strikes if s >= hi), default=None)
        pe_s = max((s for s in strikes if s <= lo), default=None)
        if ce_s is None or pe_s is None:
            return {"structure": None, "reason": "Forecast band reaches beyond the listed strikes."}
        ce_l, pe_l = ce_s + WING_STRIKES * step, pe_s - WING_STRIKES * step
        legs = [
            {"action": "SELL", "type": "CE", "strike": ce_s, "price": chain[ce_s]["CE"]},
            {"action": "BUY", "type": "CE", "strike": ce_l, "price": chain.get(ce_l, {}).get("CE")},
            {"action": "SELL", "type": "PE", "strike": pe_s, "price": chain[pe_s]["PE"]},
            {"action": "BUY", "type": "PE", "strike": pe_l, "price": chain.get(pe_l, {}).get("PE")},
        ]
        if any(l["price"] is None for l in legs):
            return {"structure": None, "reason": "Wing strikes are not quoted."}
        credit = legs[0]["price"] - legs[1]["price"] + legs[2]["price"] - legs[3]["price"]
        width = WING_STRIKES * step
        if credit <= 0:
            return {"structure": None, "reason": "No net credit at these strikes."}
        if credit < MIN_CREDIT_TO_WIDTH * width or min(legs[0]["price"], legs[2]["price"]) < MIN_SHORT_PREMIUM:
            return {"structure": None,
                    "reason": "Premiums too thin to trade (credit or short-strike price below the minimum)."}
        return _pack("Iron condor (sell outside the band)", legs, credit, width - credit,
                     [pe_s - credit, ce_s + credit], lot,
                     f"Band centred {move:+.2f}% from spot. Short strikes sit just outside the 80% band.")

    if half_width_pct > MAX_DIRECTIONAL_HALF_WIDTH_PCT:
        return {"structure": None,
                "reason": f"Band is ±{half_width_pct:.1f}% wide, too wide for a directional call."}

    if move > 0:
        long_k = atm
        short_k = min((s for s in strikes if s >= hi), default=None)
        if short_k is None or short_k <= long_k:
            return {"structure": None, "reason": "Band does not leave room for a call spread."}
        legs = [{"action": "BUY", "type": "CE", "strike": long_k, "price": chain[long_k]["CE"]},
                {"action": "SELL", "type": "CE", "strike": short_k, "price": chain[short_k]["CE"]}]
        debit = legs[0]["price"] - legs[1]["price"]
        width = short_k - long_k
        if debit <= 0 or debit >= width:
            return {"structure": None, "reason": "Spread pricing is not usable."}
        return _pack("Bull call spread (directional up)", legs, -debit, debit, [long_k + debit], lot,
                     f"Band centred {move:+.2f}% above spot.")

    short_k = max((s for s in strikes if s <= lo), default=None)
    long_k = atm
    if short_k is None or short_k >= long_k:
        return {"structure": None, "reason": "Band does not leave room for a put spread."}
    legs = [{"action": "BUY", "type": "PE", "strike": long_k, "price": chain[long_k]["PE"]},
            {"action": "SELL", "type": "PE", "strike": short_k, "price": chain[short_k]["PE"]}]
    debit = legs[0]["price"] - legs[1]["price"]
    width = long_k - short_k
    if debit <= 0 or debit >= width:
        return {"structure": None, "reason": "Spread pricing is not usable."}
    return _pack("Bear put spread (directional down)", legs, -debit, debit, [long_k - debit], lot,
                 f"Band centred {move:+.2f}% below spot.")


def _pack(name, legs, net, max_loss_unit, breakevens, lot, reason):
    # net > 0 is a credit received per unit; net < 0 is a debit paid per unit.
    max_profit_unit = net if net > 0 else None
    return {
        "structure": name,
        "legs": legs,
        "net_per_unit": round(net, 2),
        "max_loss_per_unit": round(max_loss_unit, 2),
        "max_profit_per_unit": round(max_profit_unit, 2) if max_profit_unit else None,
        "lot_size": lot,
        "max_loss_per_lot": round(max_loss_unit * lot, 0) if lot else None,
        "breakevens": [round(b, 2) for b in breakevens],
        "reason": reason,
    }


def main() -> dict:
    feed = json.loads(config.FEED_FILE.read_text(encoding="utf-8"))
    k = kite.client()
    instruments = k.instruments("NFO")
    spot_quotes = k.quote([v[0] for v in UNDERLYINGS.values()])
    today = datetime.now(config.IST).date()
    out = {"ts": datetime.now(config.IST).isoformat(timespec="seconds"), "underlyings": {},
           "disclaimer": "Model suggestions. No track record yet. Premiums are last traded prices."}

    for name, (spot_sym, root) in UNDERLYINGS.items():
        spot = float(spot_quotes[spot_sym]["last_price"])
        opts = [i for i in instruments if i["name"] == root and i["instrument_type"] in ("CE", "PE")]
        nearest, monthly = _expiries(opts, today)
        block = {"spot": round(spot, 2), "views": []}

        # Data only: the chain for an expiry that settles today (no trade suggestion).
        todays = next((i["expiry"] for i in opts if i["expiry"] == today), None)
        if todays is not None:
            chain, _ = _chain(k, opts, todays, spot)
            rows = [{"strike": s, "ce_ltp": v["CE"], "ce_oi": v["ce_oi"], "pe_ltp": v["PE"], "pe_oi": v["pe_oi"]}
                    for s, v in sorted(chain.items()) if abs(s / spot - 1) * 100 <= 3.0]
            block["expiring_today"] = {"expiry": todays.isoformat(), "pcr": _pcr(chain), "rows": rows}
        for label, expiry, hz in (("Nearest expiry", nearest, "expiry"), ("Monthly expiry", monthly, "month")):
            if expiry is None:
                continue
            band = feed["indices"][name]["horizons"][hz]["forecast"]
            chain, lot = _chain(k, opts, expiry, spot)
            view = {"label": label, "expiry": expiry.isoformat(), "pcr": _pcr(chain),
                    "band": [band["lo"], band["hi"]] if band else None}
            if band:
                view.update(_suggest(spot, band["lo"], band["hi"], chain, lot))
            else:
                view.update({"structure": None, "reason": "No forecast band available."})
            block["views"].append(view)
        out["underlyings"][name] = block

    FNO_FILE.parent.mkdir(parents=True, exist_ok=True)
    FNO_FILE.write_text(json.dumps(out, separators=(",", ":"), default=str), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, default=str))
