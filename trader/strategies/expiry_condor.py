"""
The expiry iron condor of hub/rule_test.py, run live: on the day before an index's expiry, at `entry` (15:25), sell
the call nearest forward + m*S and the put nearest forward - m*S (S = the at-the-money straddle), buy the call and put
a further w*S out as wings, hold to settlement. The wings are hedges (no stop-loss on them: a stop would remove the
cap on the sold legs' loss). The back-tests rejected this rule (state/rule_test/ in the private repo); it is here as
the first rule to exercise the whole program end to end, not as a recommendation.

params: indices (["NIFTY"]), m (1.0), w (1.0), lots (1), entry ("15:25"), each_side (20 strikes each side streamed)
"""
from ..model import Contract, OrderRequest
from .common import around, forward_and_straddle, nearest


class ExpiryCondor:
    def __init__(self, params: dict):
        self.indices = params.get("indices") or ["NIFTY"]
        self.m, self.w = float(params.get("m", 1.0)), float(params.get("w", 1.0))
        self.lots, self.entry = int(params.get("lots", 1)), params.get("entry", "15:25")
        self.each_side = int(params.get("each_side", 20))
        self.done: set[str] = set()
        self.centre: dict[str, float] = {}

    def _expiry(self, view, index: str) -> str | None:
        for e in view.feed.expiries(index):
            if view.feed.is_day_before(e):
                return e
        return None

    def wants(self, view) -> set[Contract]:
        out = set()
        for idx in self.indices:
            e = self._expiry(view, idx)
            if not e or f"{idx}_{e}" in self.done:
                continue
            ks = view.feed.strikes(idx, e)
            f, _ = forward_and_straddle(view.quotes, idx, e)
            centre = f or self.centre.get(idx) or (ks[len(ks) // 2] if ks else 0)
            self.centre[idx] = centre
            for k in around(ks, centre, self.each_side):
                out |= {Contract(idx, e, k, "C"), Contract(idx, e, k, "P")}
        return out

    def step(self, view) -> list[OrderRequest]:
        if view.now.strftime("%H:%M") < self.entry:
            return []
        reqs = []
        for idx in self.indices:
            e = self._expiry(view, idx)
            if not e or f"{idx}_{e}" in self.done:
                continue
            f, s = forward_and_straddle(view.quotes, idx, e)
            if not f or not s:
                continue
            sc = nearest(view.quotes, idx, e, "C", f + self.m * s)
            sp = nearest(view.quotes, idx, e, "P", f - self.m * s)
            if not sc or not sp or sc.strike <= sp.strike:
                continue
            legs = []
            if self.w > 0:
                lc = nearest(view.quotes, idx, e, "C", sc.strike + self.w * s)
                lp = nearest(view.quotes, idx, e, "P", sp.strike - self.w * s)
                if not lc or not lp or lc.strike <= sc.strike or lp.strike >= sp.strike:
                    continue                    # chain too short for the wings: skip, never guess
                why = f"wing {self.w:g} straddles past the sold leg"
                legs += [OrderRequest(lc, "BUY", self.lots, None, why, tag="condor-wing", hedge=True),
                         OrderRequest(lp, "BUY", self.lots, None, why, tag="condor-wing", hedge=True)]
            why = f"forward {f:,.0f}, straddle {s:,.0f}: sell {self.m:g} straddles out"
            legs += [OrderRequest(sc, "SELL", self.lots, None, why, tag="condor-short"),
                     OrderRequest(sp, "SELL", self.lots, None, why, tag="condor-short")]
            self.done.add(f"{idx}_{e}")             # one try per expiry, filled or refused
            reqs += legs
        return reqs
