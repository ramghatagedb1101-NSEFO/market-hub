"""
The rules. A strategy has wants(view) -> contracts to stream, and step(view) -> order requests. Nothing trades unless
Settings.strategy names one here; an empty name means watch only.
"""
from ..model import Settings


def make(s: Settings):
    if not s.strategy:
        return None
    if s.strategy == "rules":                       # a strategy from the dashboard's builder, in s.params
        from .rules import Rules
        return Rules(s.params)
    if s.strategy == "expiry_condor":
        from .expiry_condor import ExpiryCondor
        return ExpiryCondor(s.params)
    raise SystemExit(f"unknown strategy {s.strategy!r}")
