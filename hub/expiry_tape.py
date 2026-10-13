"""
Expiry-day recorder (expiry-tape.yml, 14 Oct 2026). Owner: "we are updating the numbers every 10 seconds but not
tracking these values" -- the option sellers' walls, max pain, and how next week's walls build while sellers roll.

On a day an index expires, calls the relay once a minute from 09:05 to 15:46 IST (?mode=expiry_close, behind RELAY_KEY),
so the relay's minute record (relay/Expiry.gs: walls and their open interest, max pain, sellers' settlement payout, the
next expiry's walls) has no gaps when nobody has the dashboard open. The relay answers from its shared Kite snapshot:
this job makes no Kite call of its own (the relay then makes about 2 Kite requests a minute). The first call of the day
(09:05, before the open) also fixes the baseline every "change since" is measured from: the previous close's OI.

After the close it asks the relay for the whole day (?mode=expiry_tape) and saves one file per index in the private
repository, state/expiry/<date>_<INDEX>.json, kept for good (the relay keeps the minute rows only 6 hours). These files
are what a later study of "which of these signals actually predicted the close" will be run on.
Exits at once on days no index expires.
"""
import base64
import json
import os
import time
from datetime import datetime

import requests

from . import config

PRIVATE_REPO = "ramghatagedb1101-NSEFO/market-hub-private"
START, END = "09:05", "15:46"


def _relay(mode: str) -> dict:
    r = requests.get(os.environ["RELAY_URL"], params={"mode": mode, "key": os.environ["RELAY_KEY"]}, timeout=90)
    return r.json()


def _now() -> datetime:
    return datetime.now(config.IST)


def _hm() -> str:
    return _now().strftime("%H:%M")


def _sleep_to_next_minute() -> None:
    n = _now()
    time.sleep(max(1.0, 63 - n.second - n.microsecond / 1e6))     # a few seconds past the minute


def save(day: dict) -> list:
    """One file per index in the private repository (GitHub contents API; replaces a same-day file)."""
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    saved = []
    for x in day.get("indices") or []:
        path = f"state/expiry/{day['date']}_{x['id']}.json"
        body = dict(x, date=day["date"], saved_at=day.get("ts"),
                    note="Kite OI is in units; *_lakh = units / 1e5; *_cr = rupees crore. Baseline = OI at the day's first reading.")
        url = f"https://api.github.com/repos/{PRIVATE_REPO}/contents/{path}"
        got = requests.get(url, headers=h, timeout=30)
        put = {"message": f"expiry record {x['id']} {day['date']}",
               "content": base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode("ascii")}
        if got.status_code == 200:
            put["sha"] = got.json()["sha"]
        elif got.status_code != 404:
            got.raise_for_status()
        requests.put(url, headers=h, json=put, timeout=60).raise_for_status()
        saved.append(f"{path} ({len(x.get('tape') or [])} minute rows)")
    return saved


def main() -> None:
    last_note = ""
    while _hm() < END:
        hm = _hm()
        if hm >= START:
            try:
                r = _relay("expiry_close")
            except Exception as e:                       # the relay can be slow or briefly unreachable: keep going
                print(f"::warning::{hm} relay call failed: {str(e)[:120]}")
                r = {}
            if r.get("error") == "forbidden":
                raise SystemExit("::error::Relay refused RELAY_KEY")
            # Other days: the relay's contract lists say no index expires today.
            if r.get("note") == "outside reading times" and r.get("lists_ok") and not r.get("listed"):
                print(f"No index expires today ({r.get('date')}).")
                return
            if r.get("expiry_today") is False and r.get("source") == "list":
                print(f"No index expires today ({r.get('date')}).")
                return
            note = r.get("error") or ", ".join(f"{x['label']} {x.get('spot')} -> {x.get('prediction')}"
                                               for x in r.get("indices") or [] if not x.get("error"))
            if note and (hm[-1] in "05" or (r.get("error") and note != last_note)):
                print(f"{hm} IST  {note}")
                last_note = note
        _sleep_to_next_minute()
    # After the close: record the close (the relay does it from 15:45), then keep the whole day.
    try:
        _relay("expiry_close")
    except Exception as e:
        print(f"::warning::close call failed: {str(e)[:120]}")
    day = _relay("expiry_tape")
    if day.get("error"):
        raise SystemExit(f"::error::expiry_tape: {day['error']}")
    if not day.get("indices"):
        print("Nothing recorded today.")
        return
    for line in save(day):
        print(f"::notice::Saved {line}")


if __name__ == "__main__":
    main()
