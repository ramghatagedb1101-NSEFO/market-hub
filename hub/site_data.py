"""
Keeps the phone app's data files in the private repository market-hub-private (folder site/), not in
this public repository. The phone page signs in with the same email code as the admin dashboard and
reads the files through the relay (relay/Admin.gs, appData), so nothing here is public any more.

Every job still writes docs/data/*.json locally exactly as before. Around that:

    python -m hub.site_data pull    # after checkout: bring the last published files into docs/data/
    python -m hub.site_data push    # at the end: send the files this run changed, in one commit

pull matters because some jobs read the previous run's file (bulk_deals.json keeps history, the
library batch merges into multibagger.json, admin_publish summarises several of them).
push sends only files whose content differs from what pull brought in, so two jobs running at the
same time (daily and the library batch) never overwrite each other's newer file with a stale copy.

live.json stays in the public repo: it is index quotes only, the same thing the relay's public
mode=quote returns, and live.yml rewrites it every five minutes.

Needs PRIVATE_REPO_TOKEN: the fine-grained token admin_publish already uses (Contents read and
write on market-hub-private).
"""
import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime

import requests

from . import config

PRIVATE_REPO = "ramghatagedb1101-NSEFO/market-hub-private"
PRIVATE_DIR = "site"
BRANCH = "main"
DATA_DIR = config.SITE_DIR / "data"
PUBLIC_ONLY = {"live.json"}
MANIFEST = DATA_DIR / ".pulled.json"      # git blob sha of each file as pulled; gitignored

# One-time seed: the files as they stood in the public repo before they moved. Used only when the
# private copy does not exist yet, so the first run after the move starts from the real history.
PUBLIC_REPO = "ramghatagedb1101-NSEFO/market-hub"
SEED_COMMIT = "13e3a8354080e1645d701011edcf8108288c7a73"
SEED_FILES = ["backtest_multibagger.json", "brief.json", "bulk_deals.json", "context.json", "feed.json",
              "fno.json", "indicator_test.json", "multibagger.json", "stocks.json", "threshold_test.json"]

API = "https://api.github.com"


def _headers(accept="application/vnd.github+json"):
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    return {"Authorization": f"Bearer {token}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}


def _request(method, url, retries=4, ok=(200, 201), **kw):
    """GitHub call with a short backoff on network errors and 5xx. Other statuses are returned as-is."""
    for attempt in range(1, retries + 1):
        try:
            r = requests.request(method, url, timeout=60, **kw)
            if r.status_code < 500 or attempt == retries:
                return r
        except requests.RequestException:
            if attempt == retries:
                raise
        time.sleep(attempt * 3)
    return r


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _local_files():
    return sorted(p for p in DATA_DIR.glob("*.json") if p.name not in PUBLIC_ONLY and not p.name.startswith("."))


def pull() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    listing = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{PRIVATE_DIR}?ref={BRANCH}", headers=_headers())
    if listing.status_code == 404:
        remote = {}
    else:
        listing.raise_for_status()
        remote = {x["name"]: x["sha"] for x in listing.json() if x.get("type") == "file"}

    manifest, got, seeded = {}, [], []
    for name, sha in remote.items():
        # The raw media type serves files of any size (the JSON form inlines content only below 1 MB).
        r = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{PRIVATE_DIR}/{name}?ref={BRANCH}",
                     headers=_headers("application/vnd.github.raw"))
        r.raise_for_status()
        (DATA_DIR / name).write_bytes(r.content)
        manifest[name] = blob_sha(r.content)
        got.append(name)

    for name in SEED_FILES:
        if name in remote:
            continue
        r = _request("GET", f"https://raw.githubusercontent.com/{PUBLIC_REPO}/{SEED_COMMIT}/docs/data/{name}")
        if r.status_code == 200:
            (DATA_DIR / name).write_bytes(r.content)
            seeded.append(name)        # not in the manifest, so push sends it

    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return {"pulled": got, "seeded_from_public_history": seeded}


def push(message=None) -> dict:
    try:
        pulled = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pulled = {}
    changed = []
    for p in _local_files():
        data = p.read_bytes()
        if pulled.get(p.name) != blob_sha(data):
            changed.append((p.name, data))
    if not changed:
        return {"pushed": [], "note": "no changes"}

    h = _headers()
    repo = f"{API}/repos/{PRIVATE_REPO}"
    blobs = []
    for name, data in changed:
        r = _request("POST", f"{repo}/git/blobs", headers=h,
                     json={"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})
        r.raise_for_status()
        blobs.append({"path": f"{PRIVATE_DIR}/{name}", "mode": "100644", "type": "blob", "sha": r.json()["sha"]})

    msg = message or f"site data {datetime.now(config.IST).date().isoformat()}"
    # Build on whatever main is now; if another job moved it in between, start again from the new head.
    for attempt in range(1, 6):
        ref = _request("GET", f"{repo}/git/ref/heads/{BRANCH}", headers=h)
        ref.raise_for_status()
        head = ref.json()["object"]["sha"]
        base_tree = _request("GET", f"{repo}/git/commits/{head}", headers=h)
        base_tree.raise_for_status()
        tree = _request("POST", f"{repo}/git/trees", headers=h,
                        json={"base_tree": base_tree.json()["tree"]["sha"], "tree": blobs})
        tree.raise_for_status()
        commit = _request("POST", f"{repo}/git/commits", headers=h,
                          json={"message": msg, "tree": tree.json()["sha"], "parents": [head]})
        commit.raise_for_status()
        upd = _request("PATCH", f"{repo}/git/refs/heads/{BRANCH}", headers=h,
                       json={"sha": commit.json()["sha"], "force": False})
        if upd.status_code == 200:
            pulled.update({name: blob_sha(data) for name, data in changed})
            MANIFEST.write_text(json.dumps(pulled, indent=1), encoding="utf-8")
            return {"pushed": [n for n, _ in changed], "commit": commit.json()["sha"][:7]}
        if upd.status_code != 422:          # 422 = main moved; anything else is a real failure
            upd.raise_for_status()
        time.sleep(attempt * 2)
    raise RuntimeError("could not update market-hub-private: main kept moving")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        print(json.dumps(pull(), indent=2))
    elif cmd == "push":
        print(json.dumps(push(" ".join(sys.argv[2:]) or None), indent=2))
    else:
        sys.exit("usage: python -m hub.site_data pull|push [commit message]")
