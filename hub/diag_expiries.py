"""One-off check (13 Oct 2026): which index option expiries exist (weekly / monthly) for NIFTY, BANKNIFTY, SENSEX."""
import gzip
import urllib.request
from collections import defaultdict
from datetime import date

def lst(exch):
    raw = urllib.request.urlopen(urllib.request.Request(f"https://api.kite.trade/instruments/{exch}", headers={"Accept-Encoding": "gzip"}), timeout=60).read()
    return (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode().split("\n")

for exch, names in (("NFO", ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")), ("BFO", ("SENSEX", "BANKEX"))):
    lines = lst(exch); head = lines[0].split(",")
    iN, iE, iT, iS, iK, iL = (head.index(c) for c in ("name", "expiry", "instrument_type", "tradingsymbol", "strike", "lot_size"))
    exp = defaultdict(set); sample = {}; step = defaultdict(set); lot = {}
    for l in lines[1:]:
        c = l.split(",")
        if len(c) <= iL: continue
        n = c[iN].strip('"')
        if n in names and c[iT] in ("CE", "PE"):
            exp[n].add(c[iE]); sample.setdefault((n, c[iE]), c[iS]); step[(n, c[iE])].add(float(c[iK])); lot[n] = c[iL]
    for n in names:
        e = sorted(exp[n])[:6]
        wd = [date.fromisoformat(x).strftime("%a") for x in e]
        st = [sorted(step[(n, x)]) for x in e[:1]]
        gap = min(b - a for a, b in zip(st[0], st[0][1:])) if st and len(st[0]) > 1 else None
        print(f"::notice::{exch} {n}: lot {lot.get(n)} step {gap} | next expiries {list(zip(e, wd))} | e.g. {[sample[(n, x)] for x in e[:2]]}")
