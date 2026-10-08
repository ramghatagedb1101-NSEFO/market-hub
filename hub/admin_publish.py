"""
Writes the admin summary to the private repository market-hub-private (not the public repository).
Needs PRIVATE_REPO_TOKEN (a GitHub secret, created by the owner).

Contents: daily run times, the parameter registry, the investor registry (names and aliases, as the
owner keeps them), bulk-deal counts, multi-bagger totals, and the summary results of the back-tests.
"""
import base64
import json
import os
from datetime import datetime

import requests

from . import config
from .parameters import PARAMETERS, summary as param_summary

REG_FILE = config.REPO / "hub" / "registry.json"
DOCS = config.SITE_DIR / "data"
TESTS = {
    "indicator_test": DOCS / "indicator_test.json",
    "backtest_multibagger": DOCS / "backtest_multibagger.json",
    "threshold_test": DOCS / "threshold_test.json",
    "stock_track_record": DOCS / "stocks_track_record.json",
}


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build() -> dict:
    registry = (_load(REG_FILE) or {}).get("investors", [])
    mb = _load(DOCS / "multibagger.json") or {}
    bulk = _load(DOCS / "bulk_deals.json") or {}
    tests = {name: _load(path) for name, path in TESTS.items() if _load(path) is not None}
    return {
        "generated": datetime.now(config.IST).isoformat(timespec="minutes"),
        "status": {
            "daily_ts": (_load(DOCS / "context.json") or {}).get("ts"),
            "parameters": param_summary(),
        },
        "parameters": [{"id": pid, "family": fam, "definition": d, "source": src, "status": st}
                       for pid, fam, d, src, st in PARAMETERS],
        "registry": registry,
        "bulk_deals": bulk,
        "multibagger": {k: mb.get(k) for k in ("ts", "universe", "scored", "rated", "turnarounds",
                                               "rated_all_four_gates", "failures", "endpoint_fields")},
        "tests": tests,
    }


PRIVATE_REPO = "ramghatagedb1101-NSEFO/market-hub-private"
PRIVATE_FILE = "admin.json"


def main() -> dict:
    """Writes the admin summary to the private repo through GitHub's contents API.
    Needs PRIVATE_REPO_TOKEN: a fine-grained token with Contents read and write on market-hub-private only."""
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    payload = json.dumps(build(), ensure_ascii=False, indent=1).encode("utf-8")
    url = f"https://api.github.com/repos/{PRIVATE_REPO}/contents/{PRIVATE_FILE}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    sha = None
    got = requests.get(url, headers=headers, timeout=30)
    if got.status_code == 200:
        sha = got.json().get("sha")
    elif got.status_code != 404:
        got.raise_for_status()
    body = {"message": f"admin summary {datetime.now(config.IST).date().isoformat()}",
            "content": base64.b64encode(payload).decode("ascii")}
    if sha:
        body["sha"] = sha
    put = requests.put(url, headers=headers, json=body, timeout=60)
    put.raise_for_status()
    return {"sent_bytes": len(payload), "saved": True, "file": f"{PRIVATE_REPO}/{PRIVATE_FILE}"}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
