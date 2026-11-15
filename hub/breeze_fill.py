"""
Whole-week gaps the other sources cannot fill (16 Nov 2026, owner: "are you sure all the IBKR live rates are being saved
and can be used for future analysis?"). The owner's ICICI files end on 30 Oct 2026 and IBKR serves no expired options,
so the IBKR backfill of 2-13 Nov could not record the sessions whose nearest expiry had already expired by 14 Nov.
The ICICI download (hub/breeze_history.py) holds only the day before and the day of each expiry; this adds the earlier
sessions of such a week from ICICI and writes the week file the back-tests read:

  NIFTY expiry Mon 9 Nov 2026 (10 Nov was a holiday): 4 and 5 Nov from ICICI + 6 and 9 Nov from the download.

state/breeze/expiry_weeks/<INDEX>/<expiry>.json.gz (hub/icici_files.py layout), source "ICICI download"; the expiry is
marked "weeks": true in state/breeze/expiry_days/_done.json. One ICICI request a contract (two sessions are ~750 candles,
under ICICI's 1,000 a request). Called at the start of every breeze_history run until done; skipped when the run's
allowance cannot cover it.
"""
from .breeze_history import DIR, FIELDS, INDEX, ICICI, CLOSE, OPEN, _strike, load_gz, save_gz
from .expiry_history import load, save
from .icici_files import WEEKS

# (index, expiry, sessions to fetch from ICICI); the download already has the day before and the expiry day
GAPS = [("NIFTY", "2026-11-09", ["2026-11-04", "2026-11-05"])]


def _rows(rows: list, days: list) -> dict:
    out = {}
    for r in rows:
        dt = str(r.get("datetime", ""))
        d, t = dt[:10], dt[11:16]
        if d not in days or not (OPEN <= t <= CLOSE):
            continue
        try:
            o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        m = (int(t[:2]) * 60 + int(t[3:5])) - (9 * 60 + 15)
        out.setdefault(d, []).append([m, o, h, l, c, int(float(r.get("volume") or 0)), int(float(r.get("open_interest") or 0))])
    return out


def needed() -> list:
    done = load(INDEX) or {}
    return [g for g in GAPS if not (done.get(f"{g[0]}_{g[1]}") or {}).get("weeks")
            and (done.get(f"{g[0]}_{g[1]}") or {}).get("candles")]          # the two-day download must exist first


def cost(gap) -> int:
    two = load_gz(f"{DIR}/{gap[0]}/{gap[1]}.json.gz") or {}
    return len(two.get("call") or {}) + len(two.get("put") or {})


def fill(b, gap) -> str:
    index, exp, extra = gap
    two = load_gz(f"{DIR}/{index}/{exp}.json.gz")
    code, exch = ICICI[index]
    days = sorted(set(extra) | {two["prev_day"], two["expiry"]})
    pos = {d: i for i, d in enumerate(days)}
    e = {"days": days, "expiry": exp, "fields": FIELDS, "call": {}, "put": {}, "source": "ICICI download"}
    errors = 0
    for side in ("call", "put"):
        for k, rows in two[side].items():
            got = [[pos[(two["prev_day"], two["expiry"])[r[0]]]] + r[1:] for r in rows]
            try:
                new = _rows(b.history(code, exch, "1minute", f"{extra[0]}T{OPEN}:00.000Z", f"{extra[-1]}T{CLOSE}:00.000Z",
                                      product="options", expiry=f"{exp}T07:00:00.000Z", right=side,
                                      strike=_strike(float(k))), extra)
            except RuntimeError as exc:
                if "no data" not in str(exc).lower():
                    errors += 1
                    if errors >= 5:
                        raise RuntimeError(f"ICICI kept failing on {index} {exp}: {str(exc)[:120]}")
                new = {}
            for d, rs in new.items():
                got += [[pos[d]] + r for r in rs]
            e[side][k] = sorted(got)
    filled = {d: sum(1 for side in ("call", "put") for rows in e[side].values() if any(r[0] == pos[d] for r in rows))
              for d in days}
    if any(filled[d] == 0 for d in extra):
        return f"{index} {exp}: ICICI returned nothing for {[d for d in extra if not filled[d]]}; not saved, tried again next run"
    save_gz(f"{WEEKS}/{index}/{exp}.json.gz", e, f"ICICI minutes, whole week: {index} {exp}")
    done = load(INDEX) or {}
    done.setdefault(f"{index}_{exp}", {})["weeks"] = True
    save(INDEX, done, f"Expiry week complete: {index}_{exp}", merge=True)
    return f"{index} {exp}: week saved, contracts with trades per session {filled}; {errors} errors"


def run(b, budget: int) -> int:
    """Fills what it can within budget; returns the requests used."""
    start = b.calls
    for gap in needed():
        n = cost(gap)
        if b.calls - start + n > budget:
            print(f"week fill {gap[0]} {gap[1]}: needs {n} requests, not enough left today")
            continue
        print(fill(b, gap), flush=True)
    return b.calls - start
