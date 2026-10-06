"""
JSON-backed state for the hub (free hosting: no database server, no binary files in git).

  prices       fetched fresh from Yahoo on every run (kept in memory only)
  predictions  every forecast ever made, plus its settlement once known
  weights      learned tool weights per (index, horizon)
  band         learned confidence-band multiplier per (index, horizon)
  meta         run log (last daily run date, etc.)

The state file is small (a few hundred KB after years of daily runs), so committing it
once a day is cheap. Writes are atomic so a crashed run cannot corrupt history.
"""
import json
import os
import tempfile
from datetime import date

import numpy as np

from . import config


class Store:
    def __init__(self, path=config.STATE_FILE):
        self.path = path
        self.prices: dict = {}  # idx -> (dates, closes)
        self.data = {"predictions": [], "weights": {}, "band": {}, "meta": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))

    # ── persistence ───────────────────────────────────────────────────

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.data, f, separators=(",", ":"))
        os.replace(tmp, self.path)

    # ── prices ────────────────────────────────────────────────────────

    def refresh_prices(self) -> dict:
        """
        Grow the stored price history with any new sessions (Kite if configured, else NSE's
        free bhavcopy for NIFTY), then load it. Fails loudly rather than forecasting on gaps.
        """
        from .sources import prices as price_sources
        raw = price_sources.refresh(config.PRICES_FILE)
        counts = {}
        for idx in config.INDICES:
            rows = sorted(raw.get(idx, {}).items())
            if len(rows) < config.MIN_HISTORY:
                raise RuntimeError(f"{idx}: only {len(rows)} closes available; refusing to forecast")
            self.prices[idx] = (
                [date.fromisoformat(d) for d, _ in rows],
                np.array([c for _, c in rows], dtype=float),
            )
            counts[idx] = len(rows)
        return counts

    def series(self, idx: str, upto: date | None = None):
        dates, closes = self.prices[idx]
        if upto is None:
            return dates, closes
        n = sum(1 for d in dates if d <= upto)
        return dates[:n], closes[:n]

    # ── learned state ─────────────────────────────────────────────────

    @staticmethod
    def _key(idx: str, horizon: str) -> str:
        return f"{idx}|{horizon}"

    def get_weights(self, idx: str, horizon: str) -> dict:
        return dict(self.data["weights"].get(self._key(idx, horizon), {}))

    def save_weights(self, idx: str, horizon: str, weights: dict) -> None:
        self.data["weights"][self._key(idx, horizon)] = weights

    def get_band(self, idx: str, horizon: str) -> float:
        return self.data["band"].get(self._key(idx, horizon), config.BAND_K0)

    def save_band(self, idx: str, horizon: str, k: float) -> None:
        self.data["band"][self._key(idx, horizon)] = k

    # ── predictions ───────────────────────────────────────────────────

    def prediction_exists(self, idx: str, horizon: str, made_on: str) -> bool:
        return any(p["index"] == idx and p["horizon"] == horizon and p["asof"] == made_on
                   for p in self.data["predictions"])

    def insert_prediction(self, fc: dict) -> None:
        pid = 1 + max((p["id"] for p in self.data["predictions"]), default=0)
        self.data["predictions"].append({**fc, "id": pid, "settled_on": None,
                                         "actual": None, "err_pct": None, "in_band": None})

    def unsettled(self) -> list:
        rows = [p for p in self.data["predictions"] if p["settled_on"] is None]
        return sorted(rows, key=lambda p: (p["target"], p["id"]))

    def mark_settled(self, pid: int, settled_on: str, actual: float, err_pct: float,
                     in_band: bool, direction_hit: bool, naive_err_pct: float):
        for p in self.data["predictions"]:
            if p["id"] == pid:
                p.update(settled_on=settled_on, actual=actual, err_pct=err_pct,
                         in_band=in_band, direction_hit=direction_hit,
                         naive_err_pct=naive_err_pct)
                return
        raise KeyError(pid)

    # ── meta ──────────────────────────────────────────────────────────

    def get_meta(self, key: str):
        return self.data["meta"].get(key)

    def set_meta(self, key: str, value: str) -> None:
        self.data["meta"][key] = value


