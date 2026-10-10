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


def shards(prices: dict) -> dict:
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
    return {k: {"dates": iso, "close": v} for k, v in out.items()}


def publish(repo: str, headers: dict, prices: dict) -> dict:
    api = f"https://api.github.com/repos/{repo}"
    tree = []
    total = 0
    for key, payload in sorted(shards(prices).items()):
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
