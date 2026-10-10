"""
The admin dashboard's copy of the stock library (11 Oct 2026): the same content as library.json in a
compact shape, published beside it as library_compact.json in the private repo.

library.json repeats each rule's wording and the words met / not_met / not_testable in every company's
66 cells -- 13 of its 22 MB. Here the wording is stored once (top-level "rules"), each company's values
are one list in "pids" order ("v") and its statuses one string ("s": Y met, N not met, . not testable,
x not scored), and the quarterly holding history is rows of [quarter, promoter, public, fii, dii].
Per-company refresh dates ("fresh"), which the page does not use, are left out. The page rebuilds the
original shape on arrival (hydrateLib in relay/AdminPage.html), so nothing else in it changes.

library.json itself is unchanged: the batch reads it back and other tools use it.
"""
import base64
import json

import requests

STATUS = {"met": "Y", "not_met": "N", "not_testable": "."}
HH_KEYS = ("promoter", "public", "fii", "dii")
DROP = ("cells", "holding_history", "fresh")


def compact(payload: dict) -> dict:
    pids = list(payload.get("rules") or {})
    out = {k: v for k, v in payload.items() if k not in ("stocks", "alerted")}
    out["format"] = "compact-1"
    out["pids"] = pids
    stocks = []
    for s in payload.get("stocks") or []:
        e = {k: v for k, v in s.items() if k not in DROP}
        cells = s.get("cells")
        if cells:
            e["v"] = [(cells.get(p) or {}).get("value") for p in pids]
            e["s"] = "".join(STATUS.get((cells.get(p) or {}).get("status"), ".") if p in cells else "x" for p in pids)
        hh = s.get("holding_history")
        if hh:
            e["hh"] = [[r.get("quarter")] + [r.get(k) for k in HH_KEYS] for r in hh]
        stocks.append(e)
    out["stocks"] = stocks
    return out


def publish(repo: str, path: str, payload: dict, headers: dict) -> int:
    """Writes the compact copy to the private repo; returns its size in bytes."""
    body = json.dumps(compact(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    got = requests.get(url, headers=headers, timeout=30)
    msg = {"message": f"stock library (dashboard copy) {payload.get('generated', '')[:10]}",
           "content": base64.b64encode(body).decode("ascii")}
    if got.status_code == 200:
        msg["sha"] = got.json().get("sha")
    requests.put(url, headers=headers, json=msg, timeout=120).raise_for_status()
    return len(body)
