"""
Keeps the private working data in the private repository market-hub-private, not in this public
repository:

    docs/data/*.json   ->  site/    the phone app's files (read through the relay after sign-in)
    state/*            ->  state/   forecast state, price history, bulk-deal store (daily job)

The phone page signs in with the same email code as the admin dashboard and reads site/ through the
relay (relay/Admin.gs, appData_). state/ is only ever read by the jobs themselves.

Every job still reads and writes the local files exactly as before. Around that:

    python -m hub.site_data pull    # after checkout: bring the last saved files into place
    python -m hub.site_data push    # at the end: send the files this run changed, in one commit

pull matters because jobs build on the previous run: state.json and prices.json grow every day,
bulk_deals keeps history, the library batch merges into multibagger.json and reads prices.json.
push sends only files whose content differs from what pull brought in, so two jobs running at the
same time (daily and the library batch) never overwrite each other's newer file with a stale copy.

Running locally: `python -m hub.site_data pull` first (with PRIVATE_REPO_TOKEN set), or the jobs
start from empty state.

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
BRANCH = "main"
PUBLIC_REPO = "ramghatagedb1101-NSEFO/market-hub"
MANIFEST = config.REPO / ".private_pulled.json"     # git blob sha of each file as pulled; gitignored

# Local folder, folder in the private repo, file patterns, files that stay public, and a one-time
# seed: the commit of this public repo that last held the folder. The seed is used only when the
# private copy of a file does not exist yet, so the first run after a move starts from real history.
FOLDERS = [
    {"local": config.SITE_DIR / "data", "remote": "site", "patterns": ["*.json"], "public": {"live.json"},
     "seed_commit": "13e3a8354080e1645d701011edcf8108288c7a73", "seed_path": "docs/data",
     "seed_files": ["backtest_multibagger.json", "brief.json", "bulk_deals.json", "context.json", "feed.json",
                    "fno.json", "indicator_test.json", "multibagger.json", "stocks.json", "threshold_test.json"]},
    {"local": config.REPO / "state", "remote": "state", "patterns": ["*.json", "*.csv"], "public": set(),
     "seed_commit": "2e10d3f341ec1371ab93e026312744d3e6420021", "seed_path": "state",
     "seed_files": ["state.json", "prices.json", "bulk_deals.csv"]},
]

API = "https://api.github.com"


def _headers(accept="application/vnd.github+json"):
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    return {"Authorization": f"Bearer {token}", "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}


def _request(method, url, retries=4, **kw):
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


def _local_files(folder):
    found = set()
    for pat in folder["patterns"]:
        found.update(p for p in folder["local"].glob(pat)
                     if p.name not in folder["public"] and not p.name.startswith("."))
    return sorted(found)


def _load_manifest():
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pull() -> dict:
    manifest, report = {}, {}
    for folder in FOLDERS:
        local, remote = folder["local"], folder["remote"]
        local.mkdir(parents=True, exist_ok=True)
        listing = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{remote}?ref={BRANCH}", headers=_headers())
        if listing.status_code == 404:
            names = []
        else:
            listing.raise_for_status()
            names = [x["name"] for x in listing.json() if x.get("type") == "file"]

        got, seeded = [], []
        for name in names:
            # The raw media type serves files of any size (the JSON form inlines content only below 1 MB).
            r = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{remote}/{name}?ref={BRANCH}",
                         headers=_headers("application/vnd.github.raw"))
            r.raise_for_status()
            (local / name).write_bytes(r.content)
            manifest[f"{remote}/{name}"] = blob_sha(r.content)
            got.append(name)

        for name in folder["seed_files"]:
            if name in names:
                continue
            r = _request("GET", f"https://raw.githubusercontent.com/{PUBLIC_REPO}/{folder['seed_commit']}/"
                                f"{folder['seed_path']}/{name}")
            if r.status_code == 200:
                (local / name).write_bytes(r.content)
                seeded.append(name)        # not in the manifest, so push sends it
        report[remote] = {"pulled": got, "seeded_from_public_history": seeded}

    MANIFEST.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return report


def push(message=None) -> dict:
    pulled = _load_manifest()
    changed = []
    for folder in FOLDERS:
        for p in _local_files(folder):
            data = p.read_bytes()
            key = f"{folder['remote']}/{p.name}"
            if pulled.get(key) != blob_sha(data):
                changed.append((key, data))
    if not changed:
        return {"pushed": [], "note": "no changes"}

    h = _headers()
    repo = f"{API}/repos/{PRIVATE_REPO}"
    blobs = []
    for path, data in changed:
        r = _request("POST", f"{repo}/git/blobs", headers=h,
                     json={"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"})
        r.raise_for_status()
        blobs.append({"path": path, "mode": "100644", "type": "blob", "sha": r.json()["sha"]})

    msg = message or f"private data {datetime.now(config.IST).date().isoformat()}"
    # Build on whatever main is now; if another job moved it in between, start again from the new head.
    for attempt in range(1, 6):
        ref = _request("GET", f"{repo}/git/ref/heads/{BRANCH}", headers=h)
        ref.raise_for_status()
        head = ref.json()["object"]["sha"]
        base = _request("GET", f"{repo}/git/commits/{head}", headers=h)
        base.raise_for_status()
        tree = _request("POST", f"{repo}/git/trees", headers=h,
                        json={"base_tree": base.json()["tree"]["sha"], "tree": blobs})
        tree.raise_for_status()
        commit = _request("POST", f"{repo}/git/commits", headers=h,
                          json={"message": msg, "tree": tree.json()["sha"], "parents": [head]})
        commit.raise_for_status()
        upd = _request("PATCH", f"{repo}/git/refs/heads/{BRANCH}", headers=h,
                       json={"sha": commit.json()["sha"], "force": False})
        if upd.status_code == 200:
            pulled.update({path: blob_sha(data) for path, data in changed})
            MANIFEST.write_text(json.dumps(pulled, indent=1), encoding="utf-8")
            return {"pushed": [p for p, _ in changed], "commit": commit.json()["sha"][:7]}
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
