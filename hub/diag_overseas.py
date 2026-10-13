"""One-off check (13 Oct 2026): can one free request give live European indices and US index futures?"""
import json
import urllib.request

SYMS = "^GDAXI,^FTSE,^STOXX50E,^FCHI,ES=F,NQ=F,YM=F"
for host in ("query1", "query2"):
    url = f"https://{host}.finance.yahoo.com/v8/finance/spark?symbols={SYMS}&range=1d&interval=5m"
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30)
        j = json.loads(r.read())
        out = []
        for k, v in j.items():
            c = [x for x in (v.get("close") or []) if x is not None]
            out.append(f"{k}: last {c[-1] if c else None} prev {v.get('chartPreviousClose')} pts {len(c)} t {v.get('timestamp', [None])[-1]}")
        print(f"::notice::{host} OK {r.status} | " + " | ".join(out))
    except Exception as e:
        print(f"::notice::{host} FAILED {e}")
