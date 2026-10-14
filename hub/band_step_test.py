"""
Walk-forward test (Group F2 groundwork, 14 Oct 2026): does a decaying band-learning step actually
improve calibration over the live model's fixed step, or is it just a different way of being wrong?

    python -m hub.band_step_test            # print the comparison
    python -m hub.band_step_test --publish   # also write docs/data/band_step_test.json

The live model nudges the confidence-band multiplier by a constant ETA_BAND after every settlement
(hub.engine.learn). A constant step never converges: it keeps moving the band by the same amount
forever, so coverage oscillates around the 80% target rather than settling near it. A step that
decays as more settlements accumulate (eta0/sqrt(1+n), see hub.engine.learn's n parameter) should
converge -- which would show up as second-half coverage closer to the 80% target than first-half
coverage, for the same history. A fixed step has no reason to show that pattern.

Verdict per (index, horizon): adaptive wins only if its second-half coverage is both closer to 80%
than the fixed step's second-half coverage AND closer to 80% than its own first-half (showing actual
convergence, not just a lucky sample). Anything else: hold, keep the fixed step live.
"""
import json
import sys

from . import backtest, config
from .store import Store


def _coverage(bools: list) -> float | None:
    return None if not bools else 100 * sum(bools) / len(bools)


def compare(index: str, dates: list, closes: list) -> dict:
    out = {}
    for adaptive in (False, True):
        scores, weights, bands = backtest.run(index, dates, closes, adaptive_band=adaptive)
        key = "adaptive" if adaptive else "fixed"
        out[key] = {}
        for h in config.HORIZONS:
            s = scores.get(h, [])
            n = len(s)
            if n < 10:
                out[key][h] = {"n": n}
                continue
            half = n // 2
            in_band = [x["in_band"] for x in s]
            out[key][h] = {
                "n": n,
                "coverage_pct": _coverage(in_band),
                "coverage_first_half_pct": _coverage(in_band[:half]),
                "coverage_second_half_pct": _coverage(in_band[half:]),
                "final_band_k": round(bands[h], 4),
            }
    return out


def verdict(row: dict) -> str:
    f, a = row.get("fixed", {}), row.get("adaptive", {})
    if f.get("n", 0) < 10 or a.get("n", 0) < 10:
        return "not enough settled history"
    target = config.TARGET_COVERAGE * 100
    f_dev = abs(f["coverage_second_half_pct"] - target)
    a_dev = abs(a["coverage_second_half_pct"] - target)
    a_converged = abs(a["coverage_second_half_pct"] - target) < abs(a["coverage_first_half_pct"] - target)
    if a_dev < f_dev and a_converged:
        return "adaptive wins: closer to target AND converging -- consider switching the live default"
    return "hold: keep the fixed step live"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    store = Store()
    store.refresh_prices()
    report = {}
    for idx in config.INDICES:
        dates, closes = store.prices[idx]
        by_horizon = compare(idx, dates, closes)
        report[idx] = {}
        print(f"\n{idx}  ({len(closes)} sessions, {dates[0]} -> {dates[-1]})")
        for h in config.HORIZONS:
            row = {"fixed": by_horizon["fixed"][h], "adaptive": by_horizon["adaptive"][h]}
            row["verdict"] = verdict(row)
            report[idx][h] = row
            print(f"  {h}: fixed={by_horizon['fixed'][h]}  adaptive={by_horizon['adaptive'][h]}")
            print(f"       -> {row['verdict']}")
    if "--publish" in argv:
        config.SITE_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)
        out_file = config.SITE_DIR / "data" / "band_step_test.json"
        out_file.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"\nWrote {out_file}")


if __name__ == "__main__":
    main()
