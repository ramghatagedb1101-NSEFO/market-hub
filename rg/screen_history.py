"""
screen_history.py — append-only daily log of the Screen Diagnostics section.

Every run computes, for each universe symbol, exactly one verdict — recommended,
rejected (and why), or errored — and until now that list only ever lived in the
one PDF the run produced, then was gone. That is the same trap `risk_flags.py`
and the chain-snapshot cache were built to avoid: the day the data is discarded
is a day of history no later analysis can recover.

Deliberately UNBOUNDED, unlike `market_data`'s chain-snapshot cache. The chain
cache is a bulky, near-term replay aid (full bid/ask/OI/greeks per strike) and
self-prunes after CHAIN_CACHE_KEEP_DAYS for exactly that reason. A day's
diagnostics is ~100 short strings — a year of daily runs is a few MB — and the
entire point of keeping it is to answer questions that need MONTHS of history
("does this symbol ever clear the gates", "how often is a run cap-bound"), so
it is never pruned here.

Record shape (schema 1), one file per calendar day, holding every run made
that day (a day commonly sees more than one run):
  data/screen_history/<YYYY-MM-DD>.json
  {
    "schema": 1,
    "day": "2026-08-19",
    "runs": [
      {"run_at": "2026-08-19T18:50:13", "diagnostics": [...]},
      ...
    ]
  }

`diagnostics` is exactly the list strategy.generate_recommendations returns —
{"symbol", "status", "detail"} per universe symbol, where `status` is already
the FINAL verdict (CANDIDATE = survived every gate and every portfolio cap,
REJECTED = failed a gate OR was cap-bound — _attribute_drops folds both into
the same field, so this one list is a complete daily record with no second
source needed).
"""

import json
from datetime import date, datetime
from pathlib import Path

from . import config

_STORE_DIR = config.DATA_DIR / "screen_history"
_SCHEMA = 1


def _path_for(day=None):
    day = day or date.today()
    return _STORE_DIR / f"{day}.json"


def write(diagnostics, day=None, run_at=None) -> Path | None:
    """
    Append this run's diagnostics as one more entry in today's file. NEVER
    raises — this is a logging side effect, not a dependency of the run it
    rides along with, so a full disk or a permission error degrades to a
    printed warning rather than failing the report that already paid for its
    Kite quotes.
    """
    if not diagnostics:
        return None
    path = _path_for(day)
    try:
        _STORE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            store = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            store = {"schema": _SCHEMA, "day": str(day or date.today()), "runs": []}
        store.setdefault("runs", []).append({
            "run_at": run_at or datetime.now().isoformat(timespec="seconds"),
            "diagnostics": diagnostics,
        })
        path.write_text(json.dumps(store, indent=2))
        return path
    except Exception as e:
        print(f"  [SCREEN-HISTORY] write failed — {e}")
        return None


def read(day=None) -> list:
    """Every run recorded for `day` (today if omitted). [] if none / unreadable."""
    path = _path_for(day)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text()).get("runs") or []
    except (json.JSONDecodeError, OSError):
        return []


def available_days() -> list:
    """Every calendar day with at least one recorded run, sorted ascending."""
    if not _STORE_DIR.exists():
        return []
    return sorted(p.stem for p in _STORE_DIR.glob("*.json"))
