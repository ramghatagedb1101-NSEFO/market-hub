"""
Industry classification for every listed company (13 Nov 2026, owner: "peer selection is totally bad ... use a better
way to find the peers"). The dashboard's peers came from NSE's NIFTY Total Market list, which names the industry of only
~760 of the ~2,600 companies; every other company was compared with "companies of the same size" from any business
(Antelopus Selan, an oil producer, was shown next to a microlender and a property developer).

BSE's company header (api.bseindia.com ComHeadernew, free, read with curl_cffi like hub/bse.py) gives each company's
place in the four-level classification NSE and BSE share:
    Sector "Energy" > Industry "Oil, Gas & Consumable Fuels" > Group "Oil" > Basic industry "Oil Exploration & Production"
One request per company; kept in the private repo (state/classification.json) and refreshed after REFRESH_DAYS, so a
daily run asks only for new or stale companies. NSE-only companies (no BSE listing) stay unclassified here; the page
then falls back to NSE's own industry, and never to "any company of the same size".

    python -m hub.classify [--budget SECONDS]     (PRIVATE_REPO_TOKEN; library.yml runs it before the library batch)
"""
import sys
import time
from datetime import date, datetime, timedelta

from . import bse
from .expiry_history import load, save

PATH = "state/classification.json"
REFRESH_DAYS = 180
GAP = 0.35


def fetch_one(code: str):
    r = bse._get(f"{bse.API}/ComHeadernew/w", params={"quotetype": "EQ", "scripcode": code, "seriesid": ""})
    if r.status_code != 200:
        return None
    try:
        j = r.json()
    except ValueError:
        return None
    parts = [(j.get(k) or "").strip() for k in ("Sector", "IndustryNew", "IGroup", "ISubGroup")]
    return parts if any(parts) else None


def run(budget: float = 1500) -> dict:
    t0 = time.time()
    have = load(PATH) or {}
    codes = bse.codes()
    stale = (date.today() - timedelta(days=REFRESH_DAYS)).isoformat()
    todo = [s for s in sorted(codes) if s not in have or (have[s].get("d") or "") < stale]
    done = failed = 0
    for sym in todo:
        if time.time() - t0 > budget:
            break
        try:
            got = fetch_one(codes[sym])
        except Exception:                       # noqa: BLE001 -- one company's failure must not stop the rest
            got = None
        if got:
            have[sym] = {"s": got[0], "i": got[1], "g": got[2], "b": got[3], "d": date.today().isoformat()}
            done += 1
        else:
            failed += 1
        time.sleep(GAP)
    if done:
        save(PATH, have, f"classification {datetime.now().strftime('%Y-%m-%d')} (+{done})")
    return {"classified": len(have), "bse_listed": len(codes), "fetched": done, "failed": failed,
            "left": max(0, len(todo) - done - failed)}


if __name__ == "__main__":
    b = float(sys.argv[sys.argv.index("--budget") + 1]) if "--budget" in sys.argv else 1500
    print(run(b))
