"""Entry point for the scheduled job:  python -m hub"""
import json

from .tracker import run_daily

if __name__ == "__main__":
    print(json.dumps(run_daily(), indent=2))
