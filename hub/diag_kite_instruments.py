"""One-off check (13 Oct 2026): what Kite's public NFO instrument list returns to a plain request (the relay fetches it without a login)."""
import gzip
import urllib.request

r = urllib.request.urlopen(urllib.request.Request("https://api.kite.trade/instruments/NFO", headers={"Accept-Encoding": "gzip"}), timeout=60)
raw = r.read()
body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
text = body.decode("utf-8", "replace")
lines = text.split("\n")
nifty = [l for l in lines if ',"NIFTY",' in l or ",NIFTY," in l]
print(f"::notice::status {r.status} type {r.headers.get('Content-Type')} enc {r.headers.get('Content-Encoding')} bytes {len(raw)}/{len(body)} lines {len(lines)} crlf {chr(13) in lines[0]}")
print(f"::notice::header {lines[0][:200]!r}")
print(f"::notice::nifty rows {len(nifty)}; first {nifty[0][:200] if nifty else None!r}")
exps = sorted({l.split(',')[5] for l in nifty})[:4]
print(f"::notice::nifty expiries {exps}; today rows {sum(1 for l in nifty if '2026-10-13' in l)}")
