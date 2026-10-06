"""
Walk-forward backtest: replays history day by day, forecasting each horizon BEFORE the outcome
is known and learning only from outcomes that have already been observed. Same code path as live.

    python -m hub.backtest              # print honest scorecard per index and horizon
    python -m hub.backtest --seed       # also save the learned weights/bands into state.json

The model is judged against a naive random-walk baseline (predict tomorrow = today).
"""
import sys
from collections import defaultdict
from datetime import date

from . import config, engine, horizons
from .store import Store


def run(index: str, dates: list, closes: list, start: int = config.MIN_HISTORY):
    weights = {h: {} for h in config.HORIZONS}
    bands = {h: config.BAND_K0 for h in config.HORIZONS}
    pending = {h: [] for h in config.HORIZONS}
    scores = defaultdict(list)

    for i in range(start, len(closes)):
        cd, cc = dates[: i + 1], closes[: i + 1]
        asof = dates[i]
        for h in config.HORIZONS:
            still = []
            for fc in pending[h]:
                act = horizons.settle_value(h, date.fromisoformat(fc["target"]), cd, cc)
                if act is None:
                    still.append(fc)
                    continue
                scores[h].append(engine.score(fc, float(act[1])))
                weights[h], bands[h] = engine.learn(fc, float(act[1]), weights[h], bands[h])
            pending[h] = still
            pending[h].append(engine.forecast(index, h, asof, cd, cc, weights[h], bands[h]))
    return scores, weights, bands


def summarise(scores: dict) -> list:
    rows = []
    for h in config.HORIZONS:
        s = scores.get(h, [])
        if not s:
            rows.append((h, 0, None, None, None, None, None))
            continue
        n = len(s)
        rows.append((
            h, n,
            100 * sum(x["direction_hit"] for x in s) / n,
            100 * sum(x["in_band"] for x in s) / n,
            sum(abs(x["err_pct"]) for x in s) / n,
            sum(abs(x["naive_err_pct"]) for x in s) / n,
            None,
        ))
    return rows


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    store = Store()
    store.refresh_prices()
    for idx in config.INDICES:
        dates, closes = store.prices[idx]
        scores, weights, bands = run(idx, dates, closes)
        print(f"\n{idx}  ({len(closes)} sessions, {dates[0]} → {dates[-1]})")
        print(f"{'horizon':<8}{'n':>6}{'dir hit%':>10}{'band cov%':>11}"
              f"{'MAE model%':>12}{'MAE naive%':>12}  verdict")
        for h, n, dh, cov, mm, mn, _ in summarise(scores):
            if n == 0:
                print(f"{h:<8}{0:>6}  (not enough settled history)")
                continue
            verdict = "beats naive" if mm < mn else "does NOT beat naive"
            print(f"{h:<8}{n:>6}{dh:>10.1f}{cov:>11.1f}{mm:>12.3f}{mn:>12.3f}  {verdict}")
        if "--seed" in argv:
            for h in config.HORIZONS:
                store.save_weights(idx, h, weights[h])
                store.save_band(idx, h, bands[h])
    if "--seed" in argv:
        store.save()
        print("\nSeeded learned weights and bands into state.json")


if __name__ == "__main__":
    main()
