"""
One-off diagnostic (12 Oct 2026): which other free NSE sources cover the companies the results check
could not read (no integrated-filing XBRL, no year-ago filing, unreadable bank-style facts) and those
BharatStock returned no results for. Prints the shape of each source's answer; writes nothing.
"""
import json
import sys

from . import shareholding as shp

SAMPLES = {
    "no BharatStock results": ["ABBOTINDIA", "AASTHA", "ACEVECTOR"],
    "no machine-readable filing": ["3BBLACKBIO", "ADDIND", "ALFREDHE"],
    "no year-ago filing": ["ABB", "ADVAIT", "AARNAV"],
    "facts unreadable": ["BURNPUR", "BOHRAIND", "DCMFINSERV"],
}
SOURCES = {
    "results-comparision": "https://www.nseindia.com/api/results-comparision?symbol={sym}",
    "financial-results (quarterly list)": "https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={sym}&period=Quarterly",
    "integrated-filing (all types)": "https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={sym}&period_ended=all&page=1&size=10",
}


def shape(body, depth=0):
    if isinstance(body, dict):
        return {k: shape(v, depth + 1) if depth < 2 else type(v).__name__ for k, v in list(body.items())[:25]}
    if isinstance(body, list):
        return [len(body), shape(body[0], depth + 1) if body else None]
    return body if isinstance(body, (int, float)) or (isinstance(body, str) and len(body) < 80) else type(body).__name__


def main():
    s = shp.session()
    for group, syms in SAMPLES.items():
        print(f"\n===== {group}")
        for sym in syms:
            for name, url in SOURCES.items():
                try:
                    r = s.get(url.format(sym=sym), headers={**shp.HEADERS, "Accept": "application/json"}, timeout=45)
                    try:
                        body = r.json()
                    except ValueError:
                        print(f"{sym:11} {name:36} {r.status_code} not JSON: {r.text[:120]!r}")
                        continue
                    print(f"{sym:11} {name:36} {r.status_code} {json.dumps(shape(body), default=str)[:900]}")
                except Exception as exc:
                    print(f"{sym:11} {name:36} ERROR {str(exc)[:150]}")
    # one full sample of the comparison source, to see its fields and periods
    for sym in ("ABBOTINDIA", "BURNPUR"):
        try:
            r = s.get(SOURCES["results-comparision"].format(sym=sym), headers={**shp.HEADERS, "Accept": "application/json"}, timeout=45)
            print(f"\n----- full results-comparision for {sym}:\n{r.text[:4000]}")
        except Exception as exc:
            print(sym, "ERROR", exc)
    try:
        r = s.get(SOURCES["financial-results (quarterly list)"].format(sym="ABBOTINDIA"), headers={**shp.HEADERS, "Accept": "application/json"}, timeout=45)
        print(f"\n----- financial-results list for ABBOTINDIA:\n{r.text[:3000]}")
    except Exception as exc:
        print("ERROR", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
