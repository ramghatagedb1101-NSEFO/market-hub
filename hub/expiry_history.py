"""
Expiry history test (13 Oct 2026, item 4 of the expiry meter plan). Owner-approved question: do the option sellers'
walls and max pain actually predict where NIFTY and BANK NIFTY settle on expiry day, beyond what the market already
knows at the open? And what starting weights should the meter use instead of guesses (k 0.30, m 0.20)?

Data: NSE's free end-of-day files only (Kite has no data for expired options):
  - F&O bhavcopy, every option's close and open interest: the old format until Jul 2024
    (content/historical/DERIVATIVES/YYYY/MON/foDDMONYYYYbhav.csv.zip), the UDiFF format after
    (content/fo/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip);
  - the daily index file (content/indices/ind_close_all_DDMMYYYY.csv): each index's open, high, low, close.
Both checked from GitHub on 13 Oct 2026 (hub/diag_fo_hist.py). NSE blocks the owner's laptop: run this on GitHub
(expiry-history.yml). SENSEX (BSE) is not covered yet.

For every expiry E of an index, from the PREVIOUS trading day's file (what is known the evening before):
  the expiring chain within +-3% of that day's close (as the live meter reads it), the forward from put-call parity at
  the ATM strike, the ATM straddle, max pain, call wall and put wall (largest call OI at/above the ATM strike, largest
  put OI at/below), and the next expiry's walls and max pain; then E's actual open and close.

What it measures (all from the open, the first moment a live reading exists; the meter's later readings are not in
end-of-day data):
  - errors of the open, max pain and wall midpoint as forecasts of the close; how often the close ends between walls;
  - the meter's model fitted on history, C - O = k (MP - O) + m (W - O) + v (NW - O), with the relay's Bayesian ridge
    (same priors; each expiry's noise = the day-before ATM straddle / 0.8);
  - walk-forward: each expiry forecast only from earlier ones, against the open alone ("beat the open in X of Y").
Results go to the private repository (state/expiry_history/records.json and summary.json); later runs fetch only
expiries not yet recorded (about 1 request a second to NSE; a full 3-year first run is ~500 requests).
"""
import base64
import csv
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta

import requests

from . import config

PRIVATE_REPO = "ramghatagedb1101-NSEFO/market-hub-private"
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
     "Accept": "*/*"}
UDIFF_FROM = date(2024, 7, 8)              # first UDiFF F&O file; the old format ends the trading day before
IDX = {"NIFTY": {"name": "Nifty 50", "step": 50}, "BANKNIFTY": {"name": "Nifty Bank", "step": 100}}
RANGE_PCT = 3.0                            # strikes read around spot, as the live meter (relay/Expiry.gs EXP_RANGE_PCT)
PRIOR = [(0.30, 0.5), (0.20, 0.5), (0.0, 0.3)]          # k, m, v: the relay's starting values and spreads
BOUNDS = [(-0.5, 1.5), (-0.5, 1.5), (-0.5, 1.0)]
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# ------------------------------------------------------------------ fetching (polite: >= 1.1 s between requests)
class Nse:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(H)
        self.last = 0.0
        self.requests = 0
        self.fo, self.ix = {}, {}

    def get(self, url: str) -> bytes | None:
        for attempt in range(4):
            wait = 1.1 - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.requests += 1
            try:
                r = self.s.get(url, timeout=60)
            except requests.RequestException:
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 404:
                return None
            if r.status_code == 200:
                return r.content
            time.sleep(10 * (attempt + 1))          # 403/429/5xx: back off
        raise RuntimeError(f"NSE kept refusing {url}")

    def fo_day(self, d: date) -> dict | None:
        """{symbol: {expiry: {strike: [ce_close, pe_close, ce_oi, pe_oi]}}} for NIFTY and BANKNIFTY options, or None
        (no file: holiday)."""
        if d in self.fo:
            return self.fo[d]
        old = f"https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{d.year}/{MON[d.month - 1]}/fo{d.day:02d}{MON[d.month - 1]}{d.year}bhav.csv.zip"
        new = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
        raw = self.get(new if d >= UDIFF_FROM else old)
        out = parse_fo(unzip(raw)) if raw else None
        self.fo[d] = out
        return out

    def index_day(self, d: date) -> dict | None:
        """{symbol: (open, high, low, close)} or None (no file: holiday)."""
        if d in self.ix:
            return self.ix[d]
        raw = self.get(f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv")
        out = parse_index(raw.decode("utf-8", "replace")) if raw else None
        self.ix[d] = out
        return out


def unzip(raw: bytes) -> str:
    if raw[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(raw))
        raw = z.read(z.namelist()[0])
    return raw.decode("utf-8", "replace")


def _f(s) -> float:
    try:
        return float(str(s).strip() or 0)
    except ValueError:
        return 0.0


def parse_fo(text: str) -> dict:
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    out = {s: {} for s in IDX}
    if "INSTRUMENT" in head:                        # old format
        i = {k: head.index(k) for k in ("INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "CLOSE", "OPEN_INT")}
        for r in rows:
            if len(r) < len(head) - 1 or r[i["INSTRUMENT"]] != "OPTIDX" or r[i["SYMBOL"]] not in out:
                continue
            e = datetime.strptime(r[i["EXPIRY_DT"]].strip(), "%d-%b-%Y").date().isoformat()
            _put(out[r[i["SYMBOL"]]], e, _f(r[i["STRIKE_PR"]]), r[i["OPTION_TYP"]], _f(r[i["CLOSE"]]), _f(r[i["OPEN_INT"]]))
    else:                                           # UDiFF
        i = {k: head.index(k) for k in ("FinInstrmTp", "TckrSymb", "XpryDt", "FininstrmActlXpryDt", "StrkPric", "OptnTp", "ClsPric", "OpnIntrst")}
        for r in rows:
            if len(r) < len(head) - 5 or r[i["FinInstrmTp"]] != "IDO" or r[i["TckrSymb"]] not in out:
                continue
            e = (r[i["FininstrmActlXpryDt"]] or r[i["XpryDt"]]).strip()[:10]
            _put(out[r[i["TckrSymb"]]], e, _f(r[i["StrkPric"]]), r[i["OptnTp"]], _f(r[i["ClsPric"]]), _f(r[i["OpnIntrst"]]))
    return out


def _put(by_exp: dict, e: str, k: float, t: str, close: float, oi: float) -> None:
    row = by_exp.setdefault(e, {}).setdefault(k, [0.0, 0.0, 0.0, 0.0])
    if t == "CE":
        row[0], row[2] = close, oi
    elif t == "PE":
        row[1], row[3] = close, oi


def parse_index(text: str) -> dict:
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    i = {k: head.index(k) for k in ("Index Name", "Open Index Value", "High Index Value", "Low Index Value", "Closing Index Value")}
    names = {v["name"].lower(): s for s, v in IDX.items()}
    out = {}
    for r in rows:
        s = names.get(r[i["Index Name"]].strip().lower()) if len(r) > max(i.values()) else None
        if s:
            out[s] = tuple(_f(r[i[k]]) for k in ("Open Index Value", "High Index Value", "Low Index Value", "Closing Index Value"))
    return out


# ------------------------------------------------------------------ one chain's walls, max pain, forward
def chain_stats(chain: dict, spot: float) -> dict | None:
    rows = sorted((k, v) for k, v in chain.items() if abs(k / spot - 1) * 100 <= RANGE_PCT and (v[2] or v[3]))
    if len(rows) < 5:
        return None
    priced = [(k, v) for k, v in rows if v[0] > 0 and v[1] > 0]
    if not priced:
        return None
    atm_k, atm = min(priced, key=lambda kv: abs(kv[0] - spot))
    above = [(k, v) for k, v in rows if k >= atm_k]
    below = [(k, v) for k, v in rows if k <= atm_k]
    cw = max(above, key=lambda kv: kv[1][2])
    pw = max(below, key=lambda kv: kv[1][3])

    def payout(x):
        return sum(v[2] * max(0.0, x - k) + v[3] * max(0.0, k - x) for k, v in rows)
    mp = min(rows, key=lambda kv: payout(kv[0]))[0]
    return {"atm": atm_k, "forward": round(atm_k + atm[0] - atm[1], 2), "straddle": round(atm[0] + atm[1], 2), "max_pain": mp,
            "call_wall": cw[0], "call_wall_oi": cw[1][2], "put_wall": pw[0], "put_wall_oi": pw[1][3],
            "wall_mid": (cw[0] + pw[0]) / 2, "strikes": len(rows),
            "calls_oi": sum(v[2] for _, v in rows), "puts_oi": sum(v[3] for _, v in rows)}


# ------------------------------------------------------------------ walking the expiry calendar
def prev_trading_day(nse: Nse, d: date) -> tuple[date, dict] | tuple[None, None]:
    p = d - timedelta(days=1)
    for _ in range(10):
        if p.weekday() < 5:
            f = nse.fo_day(p)
            if f is not None:
                return p, f
        p -= timedelta(days=1)
    return None, None


def collect(nse: Nse, start: date, end: date, have: dict, budget: int) -> dict:
    """New records {SYM_E: record} for expiries in [start, end] not in have. Discovery: each day-before file lists the
    coming expiries; the walk starts from a file at or after start."""
    new = {}
    d0 = start
    first = None
    while d0 <= end and first is None:
        if d0.weekday() < 5:
            first = nse.fo_day(d0)
        if first is None:
            d0 += timedelta(days=1)
    if first is None:
        return new
    queue = {}                                        # expiry date -> indices that list it

    def add(f):
        for s in IDX:
            for e in f.get(s, {}):
                e_d = date.fromisoformat(e)
                if start < e_d <= end:
                    queue.setdefault(e_d, set()).add(s)
    add(first)
    done = set()
    while queue:
        e_d = min(queue)
        listed = queue.pop(e_d)
        if e_d in done:
            continue
        done.add(e_d)
        syms = [s for s in IDX if s in listed and f"{s}_{e_d}" not in have]
        if not syms and max(queue, default=e_d) > e_d:
            continue                                  # already recorded; later expiries are still in the queue
        if nse.requests >= budget:
            print(f"::warning::request budget {budget} reached at {e_d}; run again to continue")
            break
        p, f = prev_trading_day(nse, e_d)
        if not f:
            continue
        add(f)
        day_e, day_p = nse.index_day(e_d), nse.index_day(p)
        if not day_e or not day_p:
            continue                                  # E was not a trading day (the contract moved): skip
        for s in syms:
            if e_d.isoformat() not in f.get(s, {}) or s not in day_e or s not in day_p:
                continue
            spot = day_p[s][3]
            st = chain_stats(f[s][e_d.isoformat()], spot)
            if not st:
                continue
            later = sorted(e for e in f[s] if e > e_d.isoformat())
            nx = chain_stats(f[s][later[0]], spot) if later else None
            o, hi, lo, c = day_e[s]
            new[f"{s}_{e_d}"] = {
                "symbol": s, "expiry": e_d.isoformat(), "weekday": e_d.strftime("%a"), "prev_day": p.isoformat(),
                "monthly": bool(later) and later[0][:7] != e_d.isoformat()[:7],
                "prev_close": spot, **{k: st[k] for k in st},
                "next_expiry": later[0] if later else None,
                "next": {k: nx[k] for k in ("max_pain", "call_wall", "put_wall", "wall_mid", "straddle")} if nx else None,
                "open": o, "high": hi, "low": lo, "close": c}
        if nse.requests // 50 != getattr(nse, "_shown", -1):
            nse._shown = nse.requests // 50
            print(f"{len(new)} new records, through {e_d}, {nse.requests} requests")
    return new


# ------------------------------------------------------------------ analysis
def ridge(rows: list) -> list:
    """Bayesian ridge as in relay/Expiry.gs expiryModel_: rows of (x[3], y, sd); returns [k, m, v] within bounds."""
    P = 3
    A = [[0.0] * P for _ in range(P)]
    b = [0.0] * P
    for x, y, sd in rows:
        w = 1 / (sd * sd)
        for a in range(P):
            b[a] += w * x[a] * y
            for c in range(P):
                A[a][c] += w * x[a] * x[c]
    for a in range(P):
        prec = 1 / PRIOR[a][1] ** 2
        A[a][a] += prec
        b[a] += prec * PRIOR[a][0]
    # Gaussian elimination
    for c in range(P):
        piv = max(range(c, P), key=lambda i: abs(A[i][c]))
        A[c], A[piv], b[c], b[piv] = A[piv], A[c], b[piv], b[c]
        for i in range(c + 1, P):
            f = A[i][c] / A[c][c]
            for k in range(c, P):
                A[i][k] -= f * A[c][k]
            b[i] -= f * b[c]
    w = [0.0] * P
    for c in range(P - 1, -1, -1):
        w[c] = (b[c] - sum(A[c][k] * w[k] for k in range(c + 1, P))) / A[c][c]
    return [round(max(BOUNDS[a][0], min(BOUNDS[a][1], w[a])), 3) for a in range(P)]


def sample(r: dict) -> tuple:
    O = r["open"]
    nw = r["next"]["wall_mid"] - O if r.get("next") else 0.0
    sd = max(r["straddle"] / 0.8, O * 0.0005)
    return [r["max_pain"] - O, r["wall_mid"] - O, nw], r["close"] - O, sd


def predict(w: list, r: dict) -> float:
    x, _, _ = sample(r)
    return r["open"] + sum(a * b for a, b in zip(w, x))


def bp(v: float, c: float) -> float:
    return (v - c) / c * 1e4


def summarise(recs: list) -> dict:
    recs = sorted(recs, key=lambda r: r["expiry"])
    n = len(recs)
    if not n:
        return {"expiries": 0}
    med = lambda a: sorted(a)[len(a) // 2] if a else None
    mae = lambda a: round(sum(abs(x) for x in a) / len(a), 1) if a else None
    err = {k: [bp(f(r), r["close"]) for r in recs] for k, f in
           {"open": lambda r: r["open"], "prev_close": lambda r: r["prev_close"], "prev_forward": lambda r: r["forward"],
            "max_pain": lambda r: r["max_pain"], "wall_mid": lambda r: r["wall_mid"]}.items()}
    start_w = [p[0] for p in PRIOR]
    out = {
        "expiries": n, "from": recs[0]["expiry"], "to": recs[-1]["expiry"],
        "mean_abs_error_bp": {k: mae(v) for k, v in err.items()},
        "median_abs_error_bp": {k: round(med([abs(x) for x in v]), 1) for k, v in err.items()},
        "close_between_walls_pct": round(100 * sum(r["put_wall"] <= r["close"] <= r["call_wall"] for r in recs) / n, 1),
        "close_within_half_step_of_max_pain_pct": round(100 * sum(abs(r["close"] - r["max_pain"]) <= IDX[r["symbol"]]["step"] / 2 for r in recs) / n, 1),
        "max_pain_closer_than_open_pct": round(100 * sum(abs(r["close"] - r["max_pain"]) < abs(r["close"] - r["open"]) for r in recs) / n, 1),
        "close_toward_max_pain_pct": None,
        "within_1sd_pct": round(100 * sum(abs(r["close"] - r["open"]) <= r["straddle"] / 0.8 for r in recs) / n, 1),
    }
    away = [r for r in recs if abs(r["max_pain"] - r["open"]) >= IDX[r["symbol"]]["step"]]
    if away:
        out["close_toward_max_pain_pct"] = round(100 * sum((r["close"] - r["open"]) * (r["max_pain"] - r["open"]) > 0 for r in away) / len(away), 1)
        out["days_open_away_from_max_pain"] = len(away)
    out["fit_all"] = dict(zip("kmv", ridge([sample(r) for r in recs])))
    # walk-forward: each expiry forecast with weights fitted on earlier expiries only (prior alone for the first)
    wf = {"model": [], "start_weights": [], "open": []}
    beat, beat_start = 0, 0
    for t, r in enumerate(recs):
        w = ridge([sample(q) for q in recs[:t]]) if t else start_w
        pm, ps = predict(w, r), predict(start_w, r)
        wf["model"].append(bp(pm, r["close"]))
        wf["start_weights"].append(bp(ps, r["close"]))
        wf["open"].append(bp(r["open"], r["close"]))
        beat += abs(pm - r["close"]) < abs(r["open"] - r["close"])
        beat_start += abs(ps - r["close"]) < abs(r["open"] - r["close"])
    out["walk_forward"] = {"mean_abs_error_bp": {k: mae(v) for k, v in wf.items()},
                           "fitted_beat_open": f"{beat} of {n}", "start_weights_beat_open": f"{beat_start} of {n}"}
    return out


def report(recs: dict) -> dict:
    rows = list(recs.values())
    out = {"generated": datetime.now(config.IST).strftime("%Y-%m-%dT%H:%M%z"),
           "method": "From the day before each expiry (NSE end-of-day files): chain within +-3% of the close, forward, ATM straddle, "
                     "max pain, walls, next expiry's walls; against the expiry day's open and close. Errors in bp of the close."}
    for s in IDX:
        mine = [r for r in rows if r["symbol"] == s]
        out[s] = {"all": summarise(mine),
                  "weekly": summarise([r for r in mine if not r["monthly"]]),
                  "monthly": summarise([r for r in mine if r["monthly"]]),
                  "since_2025_09": summarise([r for r in mine if r["expiry"] >= "2025-09-01"])}
    return out


# ------------------------------------------------------------------ private repository
def _gh(path: str):
    token = os.getenv("PRIVATE_REPO_TOKEN")
    if not token:
        raise RuntimeError("PRIVATE_REPO_TOKEN is not set")
    return f"https://api.github.com/repos/{PRIVATE_REPO}/contents/{path}", {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def load(path: str):
    url, h = _gh(path)
    r = requests.get(url, headers=dict(h, Accept="application/vnd.github.raw"), timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def save(path: str, body, message: str) -> None:
    url, h = _gh(path)
    got = requests.get(url, headers=h, timeout=30)
    put = {"message": message, "content": base64.b64encode(json.dumps(body, separators=(",", ":")).encode()).decode("ascii")}
    if got.status_code == 200:
        put["sha"] = got.json()["sha"]
    elif got.status_code != 404:
        got.raise_for_status()
    requests.put(url, headers=h, json=put, timeout=120).raise_for_status()


def main() -> None:
    start = date.fromisoformat(os.getenv("START") or "2023-10-01")
    end = datetime.now(config.IST).date() - timedelta(days=1)
    budget = int(os.getenv("BUDGET") or 1500)
    have = load("state/expiry_history/records.json") or {}
    print(f"{len(have)} expiries already recorded; collecting {start} to {end} (budget {budget} requests)")
    nse = Nse()
    try:
        new = collect(nse, start, end, have, budget)
    except Exception as e:                            # keep what was collected
        print(f"::warning::stopped early: {str(e)[:200]}")
        new = {}
    have.update(new)
    print(f"{len(new)} new expiries, {len(have)} in all, {nse.requests} NSE requests")
    if new:
        save("state/expiry_history/records.json", have, f"expiry history: {len(have)} expiries")
    rep = report(have)
    save("state/expiry_history/summary.json", rep, "expiry history summary")
    lines = []
    for s in IDX:
        a = rep[s]["all"]
        if not a.get("expiries"):
            continue
        wf = a["walk_forward"]
        lines.append(f"{s}: {a['expiries']} expiries {a['from']} to {a['to']} | mean abs error vs close (bp): open {a['mean_abs_error_bp']['open']}, "
                     f"max pain {a['mean_abs_error_bp']['max_pain']}, wall mid {a['mean_abs_error_bp']['wall_mid']} | walk-forward: fitted {wf['mean_abs_error_bp']['model']}, "
                     f"start weights {wf['mean_abs_error_bp']['start_weights']}, open {wf['mean_abs_error_bp']['open']}; fitted beat open {wf['fitted_beat_open']} | "
                     f"fit k {a['fit_all']['k']} m {a['fit_all']['m']} v {a['fit_all']['v']} | close between walls {a['close_between_walls_pct']}%, "
                     f"toward max pain {a['close_toward_max_pain_pct']}% of {a.get('days_open_away_from_max_pain')} days")
    for l in lines:
        print("::notice::" + l)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("## Expiry history test\n\n" + "\n\n".join(lines) + "\n\n```json\n" + json.dumps({s: rep[s] for s in IDX}, indent=1) + "\n```\n")


if __name__ == "__main__":
    sys.exit(main())
