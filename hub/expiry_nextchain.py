"""
Next expiry's option chain at the CLOSE of each expiry day (15 Oct 2026). Owner: "my tool is keeping watch what's
happening on the next expiry option chain... smart money is preparing for the next expiry after making money today".

The expiry history (hub/expiry_history.py) holds the next expiry's chain only as of the evening BEFORE each expiry.
This adds the same chain at the expiry day's own close, from the same free end-of-day F&O files (NSE for NIFTY and
BANK NIFTY, BSE for SENSEX), so the build-up during expiry day (expiry-day close minus the evening before) can be
tested against where the next expiry settles. Also NSE's participant-wise open interest at the expiry-day close.

Research data only: nothing on the dashboard or phone reads it. Reads state/expiry_history/records.json in the private
repo, writes state/expiry_history/next_chains/<INDEX>_<YEAR>.json there ({SYM_EXPIRY: {"next_expiry", "spot",
"chain", "participants"}}; chain rows as raw_chain: [strike, call close, put close, call OI, put OI]). Merges with what
is stored; later runs fetch only what is missing. About one request a second; ~250 NSE + ~160 BSE requests in all.
"""
import os
from datetime import date, datetime, timedelta

from . import config
from .expiry_history import Bse, Nse, load, raw_chain, save


def main() -> None:
    budget = int(os.getenv("BUDGET") or 1500)
    recs = load("state/expiry_history/records.json") or {}
    files: dict[str, dict] = {}
    for k, r in recs.items():
        files.setdefault(f"state/expiry_history/next_chains/{r['symbol']}_{r['expiry'][:4]}.json", {})
    stored = {p: (load(p) or {}) for p in files}
    have = {k for v in stored.values() for k in v}
    todo = sorted((r for k, r in recs.items() if k not in have and r.get("next_expiry")), key=lambda r: r["expiry"])
    print(f"{len(recs)} expiries recorded, {len(have)} next chains stored, {len(todo)} to fetch (budget {budget})")
    if not todo:
        return
    start = date.fromisoformat(todo[0]["expiry"]) - timedelta(days=5)
    end = datetime.now(config.IST).date()
    src = {"NSE": Nse(), "BSE": Bse(start, end)}
    got = missing = 0
    changed = set()
    for r in todo:
        s, e = r["symbol"], date.fromisoformat(r["expiry"])
        x = src["BSE" if s == "SENSEX" else "NSE"]
        if x.requests >= budget:
            print(f"::warning::request budget {budget} reached at {e}; run again to continue")
            break
        try:
            f = x.fo_day(e)
        except Exception as err:                       # keep what was collected so far
            print(f"::warning::{s} {e}: {str(err)[:160]}")
            break
        chain = (f or {}).get(s, {}).get(r["next_expiry"])
        if not chain:
            missing += 1
            continue
        po = x.participant(e) if s != "SENSEX" else None
        path = f"state/expiry_history/next_chains/{s}_{r['expiry'][:4]}.json"
        stored[path][f"{s}_{r['expiry']}"] = {"next_expiry": r["next_expiry"], "spot": r["close"],
                                              "chain": raw_chain(chain, r["close"]), "participants": po}
        changed.add(path)
        got += 1
        if got % 50 == 0:
            print(f"{got} next chains, through {e}; NSE {src['NSE'].requests} / BSE {src['BSE'].requests} requests")
    for path in sorted(changed):
        body = stored[path]
        if body:
            save(path, body, f"expiry history next chains: {path.rsplit('/', 1)[-1]} ({len(body)} expiries)")
    print(f"::notice::next chains: {got} fetched, {missing} with no chain in the day's file; "
          f"NSE {src['NSE'].requests} / BSE {src['BSE'].requests} requests")


if __name__ == "__main__":
    main()
