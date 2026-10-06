"""Builds docs/data/feed.json: everything the phone app shows, computed from state.json."""
import json
from datetime import datetime

from . import config
from .store import Store


def _rnd(x, n=2):
    return None if x is None else round(float(x), n)


def _latest(store: Store, idx: str, h: str):
    rows = [p for p in store.data["predictions"] if p["index"] == idx and p["horizon"] == h]
    return max(rows, key=lambda p: (p["asof"], p["id"])) if rows else None


def _stats(settled: list) -> dict:
    if not settled:
        return {"n": 0}
    n = len(settled)
    return {
        "n": n,
        "direction_hit_pct": _rnd(100 * sum(p["direction_hit"] for p in settled) / n, 1),
        "coverage_pct": _rnd(100 * sum(p["in_band"] for p in settled) / n, 1),
        "mae_model_pct": _rnd(sum(abs(p["err_pct"]) for p in settled) / n, 3),
        "mae_naive_pct": _rnd(sum(abs(p["naive_err_pct"]) for p in settled) / n, 3),
    }


def build(store: Store) -> dict:
    out = {"generated_at": datetime.now(config.IST).isoformat(timespec="minutes"),
           "indices": {}, "trades": [], "notes": []}
    for idx in config.INDICES:
        dates, closes = store.prices[idx]
        block = {
            "last_close": _rnd(closes[-1]),
            "last_date": dates[-1].isoformat(),
            "history": [{"d": d.isoformat(), "c": _rnd(c)}
                        for d, c in zip(dates[-250:], closes[-250:])],
            "horizons": {},
        }
        for h in config.HORIZONS:
            latest = _latest(store, idx, h)
            settled = [p for p in store.data["predictions"]
                       if p["index"] == idx and p["horizon"] == h and p["settled_on"]]
            settled.sort(key=lambda p: p["target"])
            weights = store.get_weights(idx, h)
            block["horizons"][h] = {
                "forecast": None if latest is None else {
                    "made_on": latest["asof"], "target": latest["target"],
                    "base": _rnd(latest["base"]), "pred": _rnd(latest["pred"]),
                    "lo": _rnd(latest["lo"]), "hi": _rnd(latest["hi"]),
                    "expected_move_pct": _rnd((latest["pred"] / latest["base"] - 1) * 100),
                },
                "stats": _stats(settled),
                "history": [{"target": p["target"], "pred": _rnd(p["pred"]),
                             "lo": _rnd(p["lo"]), "hi": _rnd(p["hi"]),
                             "actual": _rnd(p["actual"]), "err_pct": _rnd(p["err_pct"], 3),
                             "in_band": p["in_band"], "direction_hit": p["direction_hit"]}
                            for p in settled[-200:]],
                "tools": sorted(
                    [{"tool": t, "weight": _rnd(w, 4)} for t, w in weights.items()],
                    key=lambda r: -r["weight"]),
                "band_k": _rnd(store.get_band(idx, h), 3),
            }
        out["indices"][idx] = block

    if config.TRADES_FILE.exists():
        out["trades"] = json.loads(config.TRADES_FILE.read_text(encoding="utf-8"))
    else:
        out["notes"].append("F&O trade picks are not connected yet (see README).")
    return out


def write(store: Store) -> None:
    config.FEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.FEED_FILE.write_text(json.dumps(build(store), separators=(",", ":")), encoding="utf-8")
