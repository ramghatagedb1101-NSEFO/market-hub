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


def registry_names() -> dict[str, str]:
    """Maps each confirmed alias (upper case) to the investor it belongs to."""
    if not REGISTRY.exists():
        return {}
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    out = {}
    for inv in reg.get("investors", []):
        for alias in inv.get("aliases", []):
            if inv.get("status") == "confirmed":
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


def main() -> dict:
    names = registry_names()
    new_rows = []
    for raw in fetch_today():
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
    seen = {key(r) for r in store}
    added = [r for r in new_rows if key(r) not in seen]
    store.extend(added)
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(store)

    dates = sorted({r["date"] for r in store})
    by_date = {}
    for d in dates:
        day = [r for r in store if r["date"] == d]
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
        "by_day": by_date,
        "note": "Counts only. Client names appear in the stored history only when they match a confirmed registry entry.",
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, ensure_ascii=False))
