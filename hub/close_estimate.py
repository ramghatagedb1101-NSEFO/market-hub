"""
The phone's close estimate, recorded so it builds its own track record (26 Oct 2026, owner's go-ahead).
Same formulas as docs/index.html closeEstimate (keep both in step; evidence in hub/us_cue_test.py):

  pre-open  centre = last close x exp(GIFT_BETA x log(GIFT Nifty at 09:00 / at 15:30 on the last session)), range = the
            day forecast's 80% half-width x GIFT_RANGE; without GIFT (no Kite token): last close x exp(US_BETA x S&P 500
            log move) when the S&P moved CLOSE_MIN_US_MOVE % or more over the US sessions dated on or after the last
            Indian close, else the last close, with the full half-width. GIFT comes from Kite's 15-minute candles (the bar
            ending 09:00), so a run that GitHub starts late still records the pre-open figure.
  live      centre = the live level; half-width = daily vol x (CLOSE_RANGE_A x sqrt(share of session left) + CLOSE_RANGE_C).

python -m hub.close_estimate record   (close-estimate.yml, a few times a day) appends to the private repo's
state/close_estimate_log.json. Only this job writes that file; the daily job reads it to score the entries against the
official closes (summary(), shown on the phone), so the two never write the same file.
Needs PRIVATE_REPO_TOKEN and RELAY_URL.
"""
import base64
import bisect
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone

import requests

from . import config

LOG_PATH = "state/close_estimate_log.json"
LOCAL_LOG = config.REPO / "state" / "close_estimate_log.json"
PRIVATE = "https://api.github.com/repos/ramghatagedb1101-NSEFO/market-hub-private/contents/"


def preopen(t: dict, spx_move_pct: float | None, gift_x: float | None = None, idx: str = "") -> dict:
    k = math.log(t["hi"] / t["lo"]) / 2
    lean = 0.0
    if gift_x is not None and idx in config.GIFT_BETA:
        beta = (t.get("gift") or {}).get("beta") or config.GIFT_BETA[idx]   # the feed gives the expiry-day beta when due
        lean, k = beta * gift_x, k * config.GIFT_RANGE[idx]
    elif spx_move_pct is not None and abs(spx_move_pct) >= config.CLOSE_MIN_US_MOVE and t.get("us_beta") is not None:
        lean = t["us_beta"] * math.log(1 + spx_move_pct / 100)
    c = t["base"] * math.exp(lean)
    return {"pred": c, "lo": c * math.exp(-k), "hi": c * math.exp(k), "lean_pct": lean * 100, **_odds(t["base"], c, k)}


def live(t: dict, level: float, mins: int) -> dict:
    w = t["sig_d"] * (config.CLOSE_RANGE_A * math.sqrt(max(930 - mins, 0) / 375) + config.CLOSE_RANGE_C)
    return {"pred": level, "lo": level * math.exp(-w), "hi": level * math.exp(w), **_odds(t["base"], level, w)}


def _odds(base: float, centre: float, half80: float) -> dict:
    """The card's read-outs (docs/index.html estimateRows): normal in log terms, sigma = 80% half-width / 1.2816;
    p_up = chance of closing above the last close. Recorded so the odds can be checked for calibration."""
    sigma = half80 / 1.2816
    return {"p_up": 0.5 * math.erfc(-math.log(centre / base) / sigma / math.sqrt(2)), "sigma_pct": sigma * 100}


def _spx_move(asof: str, target: str):
    """S&P 500 % move over the US sessions dated in [asof, target), from Yahoo's daily closes (free)."""
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1mo&interval=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30).json()["chart"]["result"][0]
    off = r["meta"].get("gmtoffset", 0)
    rows = sorted((datetime.fromtimestamp(t + off, timezone.utc).date().isoformat(), v)
                  for t, v in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if v)
    days = [d for d, _ in rows]
    i, j = bisect.bisect_left(days, asof), bisect.bisect_left(days, target)
    if i == j or i == 0:
        return None
    return (rows[j - 1][1] / rows[i - 1][1] - 1) * 100


def _gift_move(asof: str, today: str):
    """log(GIFT Nifty at 09:00 IST today (the bar starting 08:45) / at 15:30 IST on asof), from Kite's 15-minute candles; None without Kite."""
    if not os.getenv("KITE_ACCESS_TOKEN"):
        return None
    from datetime import date, timedelta
    from .sources import kite
    try:
        k = kite.client()
        # "to" is a midnight: one day past today, or today's morning bars are left out
        rows = kite._retry(lambda: k.historical_data(GIFT_TOKEN, date.fromisoformat(asof),
                                                     date.fromisoformat(today) + timedelta(days=1), "15minute"))
    except Exception as exc:                            # noqa: BLE001 -- fall back to the S&P cue
        print("GIFT candles unavailable:", str(exc)[:120])
        return None
    at = {(c["date"].astimezone(config.IST).date().isoformat(), c["date"].astimezone(config.IST).strftime("%H:%M")): float(c["close"])
          for c in rows}
    a, b = at.get((asof, "15:15")), at.get((today, "08:45"))
    return math.log(b / a) if a and b else None


GIFT_TOKEN = 291849                                     # NSEIX:GIFT NIFTY


def _gh(method, path, **kw):
    h = {"Authorization": "Bearer " + os.environ["PRIVATE_REPO_TOKEN"], "Accept": "application/vnd.github+json"}
    return requests.request(method, PRIVATE + path, headers=h, timeout=30, **kw)


def record() -> list:
    now = datetime.now(config.IST)
    today, mins = now.date().isoformat(), now.hour * 60 + now.minute
    feed = requests.get(PRIVATE + "site/feed.json", timeout=30, headers={
        "Authorization": "Bearer " + os.environ["PRIVATE_REPO_TOKEN"], "Accept": "application/vnd.github.raw"}).json()
    quote = json.loads(urllib.request.urlopen(os.environ["RELAY_URL"] + "?mode=quote&t=" + str(int(time.time())),
                                              timeout=40).read())
    spx = gift = None
    new = []
    for idx, b in feed["indices"].items():
        t = b.get("today") or {}
        if t.get("target") != today or t.get("actual") is not None or not t.get("sig_d"):
            continue                                    # not a session day, or already closed
        if spx is None:
            spx, gift = _spx_move(t["asof"], today), _gift_move(t["asof"], today)
        new.append({"date": today, "index": idx, "kind": "pre", "at": now.strftime("%H:%M"), "base": t["base"],
                    "cue": "gift" if gift is not None else "spx", "spx_pct": None if spx is None else round(spx, 3),
                    "gift_pct": None if gift is None else round(gift * 100, 3),
                    **{k: round(v, 4 if k in ("p_up", "sigma_pct") else 2) for k, v in preopen(t, spx, gift, idx).items()}})
        q = (quote.get("indices") or {}).get(idx) or {}
        if 555 <= mins < 930 and q.get("last") and str(quote.get("ts", ""))[:10] == today:
            new.append({"date": today, "index": idx, "kind": "live", "at": now.strftime("%H:%M"), "base": t["base"],
                        "level": q["last"], **{k: round(v, 4 if k in ("p_up", "sigma_pct") else 2) for k, v in live(t, q["last"], mins).items()}})
    for attempt in range(4):                            # append; the sha guard refuses a stale write, then retry
        r = _gh("GET", LOG_PATH)
        sha, log = (r.json()["sha"], json.loads(base64.b64decode(r.json()["content"]))) if r.status_code == 200 else (None, [])
        have = {(e["date"], e["index"]) for e in log if e["kind"] == "pre"}
        add = [e for e in new if e["kind"] == "live" or (e["date"], e["index"]) not in have]
        if not add:
            return []
        body = {"message": f"close estimates {today} {now.strftime('%H:%M')} IST",
                "content": base64.b64encode(json.dumps(log + add, separators=(",", ":")).encode()).decode()}
        if sha:
            body["sha"] = sha
        if _gh("PUT", LOG_PATH, json=body).status_code in (200, 201):
            return add
        time.sleep(3 * (attempt + 1))
    raise SystemExit("could not write the close-estimate log")


def summary(prices: dict) -> dict:
    """Per index: the recorded estimates scored against the official closes. prices: idx -> (dates, closes)."""
    try:
        log = json.loads(LOCAL_LOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for idx, (dates, closes) in prices.items():
        close = {d.isoformat(): float(c) for d, c in zip(dates, closes)}
        rows = [(e, close[e["date"]]) for e in log if e["index"] == idx and e["date"] in close]
        pre = [(e, a) for e, a in rows if e["kind"] == "pre"]
        lv = [(e, a) for e, a in rows if e["kind"] == "live"]
        leaned = [(e, a) for e, a in pre if abs(e.get("lean_pct") or 0) > 0]
        s = {"pre_n": len(pre), "live_n": len(lv)}
        odds = [(e["p_up"], a > e["base"]) for e, a in pre if e.get("p_up") is not None]
        if odds:                                        # calibration: the mean stated chance vs how often it came true
            s["pre_p_up_mean"] = round(100 * sum(p for p, _ in odds) / len(odds), 1)
            s["pre_up_share"] = round(100 * sum(u for _, u in odds) / len(odds), 1)
            s["pre_brier"] = round(sum((p - u) ** 2 for p, u in odds) / len(odds), 3)
        if pre:
            s["pre_in_band_pct"] = round(100 * sum(e["lo"] <= a <= e["hi"] for e, a in pre) / len(pre), 1)
            s["pre_err_pct"] = round(sum(abs(a / e["pred"] - 1) for e, a in pre) / len(pre) * 100, 3)
            s["no_change_err_pct"] = round(sum(abs(a / e["base"] - 1) for e, a in pre) / len(pre) * 100, 3)
        if leaned:
            s["leaned_n"] = len(leaned)
            s["leaned_hit_pct"] = round(100 * sum((e["pred"] - e["base"]) * (a - e["base"]) > 0 for e, a in leaned) / len(leaned), 1)
        if lv:
            s["live_in_band_pct"] = round(100 * sum(e["lo"] <= a <= e["hi"] for e, a in lv) / len(lv), 1)
        out[idx] = s
    return out


if __name__ == "__main__":
    if (sys.argv[1:] or [""])[0] == "record":
        print(json.dumps(record(), indent=1))
    else:
        print(__doc__)
