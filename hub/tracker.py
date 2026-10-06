"""Live loop: refresh prices, settle what is due, make today's forecasts, publish the feed."""
from datetime import datetime

from . import config, engine, feed, horizons
from .store import Store


def settle_due(store: Store) -> list:
    """Settle every open prediction whose target close now exists. Learns in target-date order."""
    settled = []
    for p in store.unsettled():
        idx, h = p["index"], p["horizon"]
        dates, closes = store.series(idx)
        act = horizons.settle_value(h, _d(p["target"]), dates, list(closes))
        if act is None:
            continue
        settled_on, actual = act
        outcome = engine.score(p, float(actual))
        weights, k = engine.learn(p, float(actual), store.get_weights(idx, h), store.get_band(idx, h))
        store.save_weights(idx, h, weights)
        store.save_band(idx, h, k)
        store.mark_settled(p["id"], settled_on.isoformat(), float(actual),
                           outcome["err_pct"], outcome["in_band"],
                           outcome["direction_hit"], outcome["naive_err_pct"])
        settled.append((idx, h, settled_on.isoformat()))
    return settled


def predict_all(store: Store) -> list:
    """Make one forecast per index per horizon, as of the latest close. Idempotent per day."""
    made = []
    for idx in config.INDICES:
        dates, closes = store.series(idx)
        asof = dates[-1]
        for h in config.HORIZONS:
            if store.prediction_exists(idx, h, asof.isoformat()):
                continue
            fc = engine.forecast(idx, h, asof, dates, closes,
                                 store.get_weights(idx, h), store.get_band(idx, h))
            store.insert_prediction(fc)
            made.append(fc)
    return made


def run_daily() -> dict:
    store = Store()
    counts = store.refresh_prices()          # raises if Yahoo is unavailable: no partial writes
    settled = settle_due(store)
    made = predict_all(store)
    store.set_meta("last_run", datetime.now(config.IST).isoformat(timespec="seconds"))
    store.save()
    feed.write(store)
    return {"prices": counts, "settled": len(settled), "new_forecasts": len(made)}


def _d(s: str):
    from datetime import date
    return date.fromisoformat(s)
