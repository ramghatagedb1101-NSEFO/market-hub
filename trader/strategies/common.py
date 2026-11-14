"""Helpers every strategy can use."""
from ..model import Contract, Quote


def forward_and_straddle(quotes: dict[Contract, Quote], index: str, expiry: str):
    """
    The options market's own forward and at-the-money straddle, from put-call parity: at the strike where call and
    put prices are closest, forward = strike + call - put and straddle = call + put. (None, None) without a pair.
    """
    calls, puts = {}, {}
    for c, q in quotes.items():
        if c.index == index and c.expiry == expiry and q.mid:
            (calls if c.right == "C" else puts)[c.strike] = q.mid
    both = [k for k in calls if k in puts]
    if not both:
        return None, None
    k = min(both, key=lambda k: abs(calls[k] - puts[k]))
    return k + calls[k] - puts[k], calls[k] + puts[k]


def around(strikes: list[float], centre: float, each_side: int) -> list[float]:
    """The each_side strikes below and above the one nearest the centre (and that one)."""
    if not strikes:
        return []
    i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - centre))
    return strikes[max(0, i - each_side): i + each_side + 1]


def nearest(quotes: dict[Contract, Quote], index: str, expiry: str, right: str, target: float) -> Contract | None:
    """The contract with a price whose strike is nearest the target."""
    ok = [c for c, q in quotes.items() if c.index == index and c.expiry == expiry and c.right == right and q.mid]
    return min(ok, key=lambda c: abs(c.strike - target)) if ok else None
