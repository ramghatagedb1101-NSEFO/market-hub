"""
A year of daily closes for every company, for the charts' free fallback (11 Oct 2026). The relay's chart
uses Kite candles when today's Kite login exists; without it, it used BharatStock prices -- which fail
once BharatStock's daily allowance is used up. These closes come from NSE's own daily price files that
the library run already holds (hub/bhav.py, split/bonus-adjusted), so the fallback costs nothing.

Published to the private repo's `prices` branch as px/<first character>.json (about 27 files of
~150 KB): {"dates": [...], "close": {symbol: [close or null per date]}}. The branch is rewritten each
run as a single commit with no history, so a daily refresh does not grow the repository.
"""
import base64
import json

import requests

BRANCH = "prices"


def listings() -> dict:
    """{symbol: listing date} from NSE's equity list, so the chart can say "lists on 12 Oct" or "listed
    5 Oct" instead of just "no prices"."""
    import csv, io
    from datetime import datetime
    from .multibagger import EQUITY_LIST, UA
    rows = list(csv.reader(io.StringIO(requests.get(EQUITY_LIST, headers=UA, timeout=30).text)))
    head = [h.strip().upper() for h in rows[0]]
    i_sym, i_date = head.index("SYMBOL"), head.index("DATE OF LISTING")
    out = {}
    for r in rows[1:]:
        try:
            out[r[i_sym].strip()] = datetime.strptime(r[i_date].strip(), "%d-%b-%Y").date().isoformat()
        except (ValueError, IndexError):
            pass
    return out


def shards(prices: dict, listed: dict | None = None) -> dict:
    days = sorted({d for series, _, _ in prices.values() for d, _ in series})
    idx = {d: i for i, d in enumerate(days)}
    out = {}
    for sym, (series, _, _) in prices.items():
        row = [None] * len(days)
        for d, c in series:
            row[idx[d]] = round(c, 2)
        key = sym[0].upper() if sym[:1].isalpha() else "0"
        out.setdefault(key, {})[sym] = row
    iso = [d.isoformat() for d in days]
    res = {k: {"dates": iso, "close": v, "listed": {}} for k, v in out.items()}
    # Listing dates for companies with no prices or a short history (new or about to list).
    recent = iso[-60] if len(iso) >= 60 else (iso[0] if iso else "")
    for sym, day in (listed or {}).items():
        if sym not in prices or day >= recent:
            key = sym[0].upper() if sym[:1].isalpha() else "0"
            res.setdefault(key, {"dates": iso, "close": {}, "listed": {}})["listed"][sym] = day
    return res


def publish(repo: str, headers: dict, prices: dict) -> dict:
    api = f"https://api.github.com/repos/{repo}"
    tree = []
    total = 0
    try:
        listed = listings()
    except Exception:
        listed = {}
    for key, payload in sorted(shards(prices, listed).items()):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        total += len(body)
        r = requests.post(f"{api}/git/blobs", headers=headers, timeout=60,
                          json={"content": base64.b64encode(body).decode("ascii"), "encoding": "base64"})
        r.raise_for_status()
        tree.append({"path": f"px/{key}.json", "mode": "100644", "type": "blob", "sha": r.json()["sha"]})
    t = requests.post(f"{api}/git/trees", headers=headers, json={"tree": tree}, timeout=60)
    t.raise_for_status()
    c = requests.post(f"{api}/git/commits", headers=headers, timeout=60,
                      json={"message": "daily closes for the chart fallback (latest only)", "tree": t.json()["sha"], "parents": []})
    c.raise_for_status()
    sha = c.json()["sha"]
    upd = requests.patch(f"{api}/git/refs/heads/{BRANCH}", headers=headers, json={"sha": sha, "force": True}, timeout=60)
    if upd.status_code == 422:      # first run: the branch does not exist yet
        upd = requests.post(f"{api}/git/refs", headers=headers, json={"ref": f"refs/heads/{BRANCH}", "sha": sha}, timeout=60)
    upd.raise_for_status()
    return {"files": len(tree), "bytes": total, "commit": sha[:7]}
