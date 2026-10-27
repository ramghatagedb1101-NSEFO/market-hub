"""Probe (27 Oct 2026): NSE's trading-holiday list as hub/holidays.py reads it (diag.yml; NSE blocks the laptop)."""
import json

from . import holidays

if __name__ == "__main__":
    print(json.dumps(holidays.fetch()))
