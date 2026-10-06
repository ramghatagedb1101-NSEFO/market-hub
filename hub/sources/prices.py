"""
Incremental daily-close store. Keeps state/prices.json growing by new sessions only.

Per index, in order:
  1. Kite, if KITE_ACCESS_TOKEN is set and the index has a Kite mapping.
  2. NSE's free bhavcopy, if the index has an nse_csv mapping (NIFTY).
  3. Otherwise the index is left empty and the caller fails loudly.
"""
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import config
from . import kite, nse


def _load(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save(path: Path, raw: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def refresh(path: Path = config.PRICES_FILE) -> dict:
    raw = _load(path)
    today = datetime.now(config.IST).date()
    k = kite.client() if os.getenv("KITE_ACCESS_TOKEN") else None

    for idx, spec in config.INDEX_SOURCES.items():
        have = raw.setdefault(idx, {})
        start = (date.fromisoformat(max(have)) + timedelta(days=1)) if have \
            else today - timedelta(days=config.HISTORY_DAYS)
        if start > today:
            continue
        if k is not None and "kite" in spec:
            exchange, symbol = spec["kite"]
            token = kite.instrument_token(k, exchange, symbol)
            have.update(kite.daily_closes(k, token, start, today))
        elif "nse_csv" in spec:
            have.update(nse.fetch_range(start, today, spec["nse_csv"]))

    _save(path, raw)
    return raw
