"""
The owner's own ICICI one-minute option files (14 Nov 2026, owner: "where i should save the ICICI historic data for
you?"), saved on the laptop, imported into the private repo once. Run on the laptop (the files never leave it except
into the private repo):

    python -m hub.icici_files "D:\\ICICI data historic\\NSEData" --check     (counts and a price check, writes nothing)
    python -m hub.icici_files "D:\\ICICI data historic\\NSEData" --import    (writes the private repo)

What the folder holds (checked 14 Nov 2026): <INDEX>/OPT/<year>/orgzip/*.zip for NIFTY and BANKNIFTY, every trading
day 1 Jan 2024 - 30 Oct 2026, in two layouts:
  - ICICI Breeze rows, one CSV per contract and day: <INDEX>_<day>_<expiry>_<strike>_<CE|PE>.csv with columns
    datetime, stock_code, ..., right, strike_price, open, high, low, close, volume, open_interest, count
    (nearest expiry, strikes within about 1.5-2% of the index);
  - NIFTY 2024: NIFTY-<EXPIRY>-<DAY>.csv (e.g. NIFTY-01AUG24-08JUL24.csv), every strike of every expiry, columns
    datetime (HH:MM), strike_price, right, open, high, low, close, open_interest, volume.
<INDEX>/IDX/*.csv holds the index's minutes (not imported: hub/breeze_index.py already has them; used as a check).

Stored as one file per expiry with every session the files have for it (normally the days it was the nearest expiry):
state/breeze/expiry_weeks/<INDEX>/<expiry>.json.gz =
  {"days": [...], "expiry", "fields": [day, min, open, high, low, close, volume, oi], "call": {strike: rows},
   "put": {...}, "source": "owner files"}
day = position in "days". Strikes kept: within 5% of that day's index open (the same reach as hub/breeze_history.py).
Where the ICICI download already has the day before and the expiry day (state/breeze/expiry_days/), its wider strikes
are merged in. The expiries imported are marked in state/breeze/expiry_days/_done.json ("source": "owner files"), so
the download skips them.
"""
import csv
import glob
import io
import os
import re
import sys
import time
import zipfile
from collections import defaultdict

from .breeze_history import DIR as EXP_DIR, FIELDS, INDEX as EXP_DONE, load_gz, save_gz

WEEKS = "state/breeze/expiry_weeks"
REACH = 0.05
MON = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
BREEZE_NAME = re.compile(r"(NIFTY|BANKNIFTY)_(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)_([\d.]+)_(CE|PE)\.csv$")
NF24_NAME = re.compile(r"NIFTY-(\d\d[A-Z]{3}\d\d)-(\d\d[A-Z]{3}\d\d)\.csv$")


def _iso(s: str) -> str:                                   # 01AUG24 -> 2024-08-01
    return f"20{s[5:7]}-{MON[s[2:5]]:02d}-{s[:2]}"


def _minute(hhmm: str):
    m = (int(hhmm[:2]) * 60 + int(hhmm[3:5])) - (9 * 60 + 15)
    return m if 0 <= m <= 375 else None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _k(x: float):
    return int(x) if float(x).is_integer() else x


def index_opens(root: str, index: str) -> dict:
    """{day: first minute's open} from the folder's index file."""
    out = {}
    for f in glob.glob(os.path.join(root, index, "IDX", "*.csv")):
        with open(f, encoding="utf-8") as fh:
            r = csv.reader(fh)
            next(r, None)
            for row in r:
                d = row[0][:10]
                if d not in out and _f(row[1]):
                    out[d] = float(row[1])
    return out


def members(root: str, index: str) -> dict:
    """{expiry: [(zip, member, day, strike or None, side or None), ...]} from the zips' file names (nothing read yet).
    Each day goes to its NEAREST expiry only (the 2024 file has every expiry each day, and some days hold two), so a
    back-test never trades the same session twice under two expiries."""
    out = defaultdict(list)
    for z in sorted(glob.glob(os.path.join(root, index, "OPT", "*", "orgzip", "*.zip"))):
        with zipfile.ZipFile(z) as f:
            names = f.namelist()
        nf24 = defaultdict(set)
        for n in names:
            base = n.rsplit("/", 1)[-1]
            m = BREEZE_NAME.match(base)
            if m and m[1] == index and m[3] >= m[2]:
                out[m[3]].append((z, n, m[2], float(m[4]), "call" if m[5] == "CE" else "put"))
                continue
            m = NF24_NAME.match(base)
            if m and index == "NIFTY":
                nf24[_iso(m[2])].add((_iso(m[1]), n))
        for day, es in nf24.items():
            for exp, n in es:
                if exp >= day:
                    out[exp].append((z, n, day, None, None))
    on = defaultdict(set)                                   # day -> expiries on file
    for exp, mem in out.items():
        for x in mem:
            on[x[2]].add(exp)
    nearest = {d: min(es) for d, es in on.items()}
    kept = {exp: [x for x in mem if nearest[x[2]] == exp] for exp, mem in out.items()}
    return {exp: mem for exp, mem in kept.items() if mem}


def _rows(f: zipfile.ZipFile, n: str, day: str, strike, side) -> dict:
    """{(side, strike): [[min, o, h, l, c, v, oi], ...]} for one member file."""
    per = defaultdict(list)
    for r in csv.DictReader(io.TextIOWrapper(f.open(n), encoding="utf-8")):
        if strike is None:                                  # 2024 layout: every strike in one file, time only
            mi, key = _minute(r["datetime"][:5]), ("call" if r["right"] == "CE" else "put", float(r["strike_price"]))
        else:
            if str(r.get("datetime", ""))[:10] != day:
                continue
            mi, key = _minute(r["datetime"][11:16]), (side, strike)
        if mi is not None:
            per[key].append([mi, _f(r["open"]), _f(r["high"]), _f(r["low"]), _f(r["close"]),
                             int(_f(r.get("volume")) or 0), int(_f(r.get("open_interest")) or 0)])
    return per


def weeks(root: str, index: str):
    """Yields (expiry, entry), oldest first, one expiry in memory at a time: every day it was the nearest expiry,
    strikes within REACH of that day's index open."""
    opens = index_opens(root, index)
    zips = {}
    try:
        for exp, mem in sorted(members(root, index).items()):
            byk = defaultdict(dict)                         # (side, strike) -> day -> rows
            for z, n, day, strike, side in mem:
                o = opens.get(day)
                if strike is not None and o and abs(strike - o) > REACH * o:
                    continue
                f = zips.get(z) or zips.setdefault(z, zipfile.ZipFile(z))
                for (sd, k), rows in _rows(f, n, day, strike, side).items():
                    if o and abs(k - o) > REACH * o:
                        continue
                    byk[(sd, k)][day] = sorted(rows)
            days = sorted({d for per in byk.values() for d in per})
            if not days:
                continue
            pos = {d: i for i, d in enumerate(days)}
            e = {"days": days, "expiry": exp, "fields": FIELDS, "call": {}, "put": {}, "source": "owner files"}
            for (side, k), per in sorted(byk.items()):
                e[side][str(_k(k))] = [[pos[d]] + r for d in days if d in per for r in per[d]]
            yield exp, e
    finally:
        for f in zips.values():
            f.close()


def two_days(e: dict) -> dict | None:
    """A week entry in the download's layout (day 0 = the day before expiry, 1 = expiry day), for code written for it.
    None when the files lack either day."""
    days = e.get("days") or []
    if len(days) < 2 or days[-1] != e["expiry"]:
        return None
    i = len(days) - 2
    out = {"prev_day": days[i], "expiry": e["expiry"], "fields": FIELDS, "call": {}, "put": {}, "source": e.get("source")}
    for side in ("call", "put"):
        for k, rows in (e.get(side) or {}).items():
            got = [[r[0] - i] + r[1:] for r in rows if r[0] >= i]
            if got:
                out[side][k] = got
    return out


def merge_download(e: dict, got: dict | None) -> int:
    """Adds the ICICI download (day before + expiry day, wider reach) to a week from the files: its strikes the files
    lack, and either day the files lack (the files end on 30 Oct 2026, part-way through some weeks). Returns the number
    of contracts that gained candles."""
    if not got:
        return 0
    remap = {0: got["prev_day"], 1: got["expiry"]}
    old = e["days"]
    days = sorted(set(old) | set(remap.values()))
    if days != old:                                     # re-number the files' rows to the new list of days
        move = {i: days.index(d) for i, d in enumerate(old)}
        for side in ("call", "put"):
            for k, rows in e[side].items():
                e[side][k] = [[move[r[0]]] + r[1:] for r in rows]
        e["days"] = days
    pos = {d: i for i, d in enumerate(days)}
    added = 0
    for side in ("call", "put"):
        for k, rows in (got.get(side) or {}).items():
            have = e[side].setdefault(k, [])
            days_have = {r[0] for r in have}
            new = [[pos[remap[r[0]]]] + r[1:] for r in rows if pos[remap[r[0]]] not in days_have]
            if new:
                e[side][k] = sorted(have + new)
                added += 1
    return added


def check(root: str) -> int:
    """Counts per index, and the files' closes against the ICICI download for the expiries both have."""
    from .expiry_history import load
    done = load(EXP_DONE) or {}
    for index in ("NIFTY", "BANKNIFTY"):
        exps, sess, both, ks, diffs, n = [], 0, 0, 0, [], 0
        for x, e in weeks(root, index):
            exps.append(x)
            sess += len(e["days"])
            ks += len(e["call"]) + len(e["put"])
            if f"{index}_{x}" not in done or done[f"{index}_{x}"].get("source") == "owner files":
                continue
            both += 1
            got = load_gz(f"{EXP_DIR}/{index}/{x}.json.gz")
            for side in ("call", "put"):
                for k, rows in (got or {}).get(side, {}).items():
                    mine = {(e["days"][r[0]], r[1]): r[5] for r in e[side].get(k, [])}
                    for r in rows:
                        d = got["prev_day"] if r[0] == 0 else got["expiry"]
                        if (d, r[1]) in mine and r[5]:
                            n += 1
                            diffs.append(abs(mine[(d, r[1])] - r[5]))
        print(f"{index}: {len(exps)} expiries {exps[0]} to {exps[-1]}, {sess} expiry-sessions, {ks} contracts")
        if n:
            same = sum(1 for x in diffs if x < 0.001)
            print(f"  checked against the ICICI download on {both} expiries: {n} minute closes, {same} identical, "
                  f"largest difference {max(diffs):.2f}")
        else:
            print("  no overlap with the ICICI download to check")
    return 0


def run_import(root: str) -> int:
    from .expiry_history import load, save
    done = load(EXP_DONE) or {}
    for index in ("NIFTY", "BANKNIFTY"):
        total, n_exp = 0, 0
        for i, (exp, e) in enumerate(weeks(root, index), 1):
            n_exp = i
            key = f"{index}_{exp}"
            merged = merge_download(e, load_gz(f"{EXP_DIR}/{index}/{exp}.json.gz")) if key in done else 0
            if e["days"][-1] != exp:                    # the files stop before expiry day: the download fetches it
                print(f"{key}: the files stop on {e['days'][-1]}, before expiry day; left to the ICICI download")
                continue
            size = save_gz(f"{WEEKS}/{index}/{exp}.json.gz", e, f"Owner's ICICI files: {key}")
            total += size
            n = len(e["call"]) + len(e["put"])
            print(f"{key}: {len(e['days'])} sessions, {n} contracts{f' (+{merged} from the download)' if merged else ''}, "
                  f"{size // 1024} KB")
            if key not in done:
                done[key] = {"source": "owner files", "contracts": n, "sessions": len(e["days"])}
            else:
                done[key]["weeks"] = len(e["days"])     # the back-test reads the week file for this expiry
            if i % 20 == 0:
                save(EXP_DONE, done, f"ICICI minutes: {len(done)} expiries (owner's files)")
            time.sleep(1)                       # GitHub's limit on writes per minute
        save(EXP_DONE, done, f"ICICI minutes: {len(done)} expiries (owner's files)")
        print(f"{index}: {n_exp} expiries, {total // 1_000_000} MB")
    return 0


if __name__ == "__main__":
    root = sys.argv[1]
    sys.exit(run_import(root) if "--import" in sys.argv else check(root))
