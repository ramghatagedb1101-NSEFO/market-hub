"""
Daily bulk-deal collector. NSE publishes every bulk deal (a trade above 0.5% of a company's shares)
with the buyer and seller names. This keeps a running history, because NSE's archive only holds the
current day, so a back-test needs history collected from now on.

Stores each deal in state/bulk_deals.csv. Client names are kept only when they match the investor
registry (hub/registry.json); other names are stored as OTHER. Publishes counts only to
docs/data/bulk_deals.json.
"""
import csv
import io
import json
from datetime import datetime

import requests

from . import config

SOURCE = "https://archives.nseindia.com/content/equities/bulk.csv"
STORE = config.REPO / "state" / "bulk_deals.csv"
REGISTRY = config.REPO / "hub" / "registry.json"
OUT_FILE = config.SITE_DIR / "data" / "bulk_deals.json"
UA = {"User-Agent": "Mozilla/5.0 (market-hub; bulk-deals)"}
FIELDS = ["date", "symbol", "security", "client", "side", "quantity", "price", "registry_match"]


def matched_investors() -> set:
    """Registry investors already found by their exact alias in a company's shareholding filing (the library's
    investor_matches). 16 Nov 2026: the registry's rule is "keep unconfirmed entries until a filing or bulk deal matches
    them", but nothing confirmed them, so all 23 stayed unconfirmed and "Registry buys" was 0 every day."""
    try:
        from . import library
        lib, _ = library.fetch_existing()
        return {m.get("investor") for ms in (lib.get("investor_matches") or {}).values() for m in ms if m.get("investor")}
    except Exception:                                   # no token or no network: confirmed entries only, as before
        return set()


def registry_names(matched: set | None = None) -> dict[str, str]:
    """Maps each confirmed alias (upper case) to the investor it belongs to; an investor counts as confirmed once one of
    their aliases has been matched in a filing."""
    if not REGISTRY.exists():
        return {}
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    matched = matched or set()
    out = {}
    for inv in reg.get("investors", []):
        if inv.get("status") == "confirmed" or inv.get("name") in matched:
            for alias in inv.get("aliases", []):
                out[alias.upper()] = inv["name"]
    return out


def fetch_today() -> list[dict]:
    r = requests.get(SOURCE, headers=UA, timeout=60)
    r.raise_for_status()
    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        rows.append({k.strip(): (v or "").strip() for k, v in row.items() if k})
    return rows


def load_store() -> list[dict]:
    if not STORE.exists():
        return []
    with STORE.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def key(row: dict) -> tuple:
    return (row["date"], row["symbol"], row["client"], row["side"], row["quantity"], row["price"])


HISTORY = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
BACKFILL_DAYS = 90          # how far back a missed session is filled
BACKFILL_MAX = 25           # sessions filled in one run


def fetch_day(s, day) -> list[dict]:
    """One past session's bulk deals from NSE's history service (16 Nov 2026: the daily file holds only the current day,
    so days the job missed - 6 and 9 Nov, when GitHub started it hours late - were lost). Same columns as the daily file.
    One day a request: the service answers a range with its first day only."""
    d = day.strftime("%d-%m-%Y")
    # the JSON answer stops at 70 rows (13 Nov 2026 had 136); the CSV download of the same service has them all
    r = s.get(HISTORY, params={"optionType": "bulk_deals", "from": d, "to": d, "csv": "true"}, timeout=60,
              headers={"Referer": "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"})
    r.raise_for_status()
    out = []
    for row in csv.DictReader(io.StringIO(r.text.lstrip("﻿"))):
        x = {"".join(k.split()): (v or "").strip() for k, v in row.items() if k}      # "Buy / Sell " -> "Buy/Sell"
        out.append({"Date": x.get("Date", "").upper(), "Symbol": x.get("Symbol", ""), "Security Name": x.get("SecurityName", ""),
                    "Client Name": x.get("ClientName", ""), "Buy/Sell": x.get("Buy/Sell", "").upper(),
                    "Quantity Traded": x.get("QuantityTraded", "").replace(",", ""),
                    "Trade Price / Wght. Avg. Price": x.get("TradePrice/Wght.Avg.Price", "").replace(",", "")})
    return out


def missed_sessions(stored_dates: set, today) -> list:
    """Trading sessions in the last BACKFILL_DAYS (before today) with no stored deal."""
    from datetime import timedelta
    from .holidays import is_session
    have = {datetime.strptime(d, "%d-%b-%Y").date() for d in stored_dates if d}
    if not have:
        return []
    start = max(min(have), today - timedelta(days=BACKFILL_DAYS))
    out, d = [], start
    while d < today:
        if is_session(d) and d not in have:
            out.append(d)
        d += timedelta(days=1)
    return out[-BACKFILL_MAX:]


def backfill(stored_dates: set) -> tuple[list[dict], list[str]]:
    import os
    today = datetime.now(config.IST).date()
    days = missed_sessions(stored_dates, today)
    # BULK_REFILL=YYYY-MM-DD,...: sessions read again in full (16 Nov 2026: 6 and 9 Nov were first filled from the JSON
    # answer, which stops at 70 rows); deals already stored are not added twice
    for x in (os.getenv("BULK_REFILL") or "").split(","):
        if x.strip():
            d = datetime.strptime(x.strip(), "%Y-%m-%d").date()
            if d not in days:
                days.append(d)
    if not days:
        return [], []
    try:
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
        s.get("https://www.nseindia.com/", timeout=30)
        s.get("https://www.nseindia.com/report-detail/display-bulk-and-block-deals", timeout=30)
    except Exception as exc:
        return [], [f"history service not reached ({type(exc).__name__})"]
    rows, notes = [], []
    for d in days:
        try:
            got = fetch_day(s, d)
            rows += got
            notes.append(f"{d.isoformat()}: {len(got)} deals filled")
        except Exception as exc:
            notes.append(f"{d.isoformat()}: not filled ({type(exc).__name__})")
    return rows, notes


def main() -> dict:
    names = registry_names(matched_investors())
    new_rows = []
    store_dates = {r["date"] for r in load_store()}
    filled, fill_notes = backfill(store_dates)
    for raw in list(fetch_today()) + filled:
        client = raw.get("Client Name", "")
        rec = {
            "date": raw.get("Date", ""),
            "symbol": raw.get("Symbol", ""),
            "security": raw.get("Security Name", ""),
            "client": client if client.upper() in names else "OTHER",
            "side": raw.get("Buy/Sell", ""),
            "quantity": raw.get("Quantity Traded", ""),
            "price": raw.get("Trade Price / Wght. Avg. Price", ""),
            "registry_match": names.get(client.upper(), ""),
        }
        if rec["date"] and rec["symbol"]:
            new_rows.append(rec)

    store = load_store()
    import os
    refill = {datetime.strptime(x.strip(), "%Y-%m-%d").strftime("%d-%b-%Y").upper()
              for x in (os.getenv("BULK_REFILL") or "").split(",") if x.strip()}
    if refill and any(r["date"] in refill for r in new_rows):          # a re-read day replaces what was stored for it
        store = [r for r in store if r["date"] not in refill]
    seen = {key(r) for r in store}
    added = [r for r in new_rows if key(r) not in seen]
    store.extend(added)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(store)

    # NSE writes "03-NOV-2026"; sorted as text, 02-NOV came before 30-OCT, so "last day" was 5 days stale (4 Nov 2026).
    # Sort by the real date and publish ISO days, which also sort right where the dashboard sorts the keys.
    nse = sorted({r["date"] for r in store}, key=lambda d: datetime.strptime(d, "%d-%b-%Y"))
    dates = [datetime.strptime(d, "%d-%b-%Y").date().isoformat() for d in nse]
    by_date = {}
    for d, raw in zip(dates, nse):
        day = [r for r in store if r["date"] == raw]
        by_date[d] = {
            "deals": len(day),
            "buys": sum(1 for r in day if r["side"] == "BUY"),
            "sells": sum(1 for r in day if r["side"] == "SELL"),
            "registry_buys": sum(1 for r in day if r["side"] == "BUY" and r["registry_match"]),
        }
    out = {
        "ts": datetime.now(config.IST).isoformat(timespec="minutes"),
        "days_stored": len(dates),
        "first_day": dates[0] if dates else None,
        "last_day": dates[-1] if dates else None,
        "added_today": len(added),
        "filled": fill_notes,
        "by_day": by_date,
        "note": "Counts only. Client names appear in the stored history only when they match a confirmed registry entry.",
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
