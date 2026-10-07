"""
Sends the admin summary to the Apps Script relay, which stores it in the owner's private Drive, not in
the public repository. Needs RELAY_URL and RELAY_KEY (GitHub secrets, already used by the token step).

Contents: daily run times, the parameter registry, the investor registry (names and aliases, as the
owner keeps them), bulk-deal counts, multi-bagger totals, and the summary results of the back-tests.
"""
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


def main() -> dict:
    url = os.getenv("RELAY_URL")
    key = os.getenv("RELAY_KEY")
    if not url or not key:
        raise RuntimeError("RELAY_URL or RELAY_KEY is not set")
    payload = json.dumps(build(), ensure_ascii=False)
    r = requests.post(url, params={"mode": "publish_admin", "key": key},
                      data=payload.encode("utf-8"), headers={"Content-Type": "text/plain;charset=utf-8"},
                      timeout=60)
    r.raise_for_status()
    body = r.json() if r.text.strip().startswith("{") else {"status": r.status_code}
    return {"sent_bytes": len(payload), "relay_reply": body.get("error") or body.get("ok", True)}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
