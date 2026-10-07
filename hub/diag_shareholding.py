"""
One-off diagnostic: calls the three BharatStock endpoints not used anywhere yet (shareholding,
ratios, corporate-actions) for a handful of sample companies across the market-cap range, and
prints the real field names and one raw example per endpoint. Nothing is published or written
to disk. Run this before wiring up new parameters so rules are built on confirmed field names,
never guesses -- the same discipline already applied to financials/insider-trades/mf-holdings.

Needs BHARATSTOCK_API_KEY. Delete this file once the field names below are copied into
hub/library.py and hub/parameters.py.
"""
import json
import os

from .multibagger import fetch_shareholding, fetch_ratios, fetch_corporate_actions

SAMPLES = ["RELIANCE", "TCS", "ZAGGLE", "RBZJEWEL", "CENTUM", "20MICRONS"]


def main() -> None:
    key = os.getenv("BHARATSTOCK_API_KEY")
    if not key:
        raise RuntimeError("BHARATSTOCK_API_KEY is not set")
    for sym in SAMPLES:
        print(f"\n=== {sym} ===")
        try:
            sh = fetch_shareholding(sym, key)
            print("shareholding rows:", len(sh))
            if sh:
                print("shareholding fields:", sorted(sh[0].keys()))
                print("shareholding example:", json.dumps(sh[0], indent=1, default=str))
        except Exception as exc:
            print("shareholding error:", repr(exc)[:200])
        try:
            ra = fetch_ratios(sym, key)
            print("ratios:", json.dumps(ra, indent=1, default=str) if ra else "(empty)")
        except Exception as exc:
            print("ratios error:", repr(exc)[:200])
        try:
            ca = fetch_corporate_actions(sym, key)
            print("corp_actions rows:", len(ca))
            if ca:
                print("corp_actions fields:", sorted(ca[0].keys()))
                print("corp_actions example:", json.dumps(ca[0], indent=1, default=str))
        except Exception as exc:
            print("corp_actions error:", repr(exc)[:200])


if __name__ == "__main__":
    main()
