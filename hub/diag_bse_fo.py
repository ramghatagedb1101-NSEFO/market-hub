"""One-off (14 Oct 2026), second probe: BSE's derivatives end-of-day file before Jul 2024, how far back the UDiFF file
goes, how complete a day's SENSEX chain is, and whether SENSEX's daily open/close comes back for 3 years in one call."""
import io
import time
import zipfile

from curl_cffi import requests as cr

s = cr.Session(impersonate="chrome")
s.headers.update({"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})


def get(u):
    r = s.get(u, timeout=60)
    time.sleep(1.3)
    data = r.content
    ok = r.status_code == 200 and not data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html"))
    if ok and data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        data = z.read(z.namelist()[0])
    return r.status_code, ok, data.decode("utf-8", "replace") if ok else ""


for d in ("20231012", "20240102", "20240301", "20240503", "20240603", "20240628", "20240701", "20240703"):
    y, m, dd = d[:4], d[4:6], d[6:]
    for u in (f"https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_{d}_F_0000.CSV",
              f"https://www.bseindia.com/download/Bhavcopy/Derivative/bhavcopy{dd}-{m}-{y[2:]}.zip",
              f"https://www.bseindia.com/download/Bhavcopy/Derivative/bhavcopy{dd}-{m}-{y[2:]}.csv",
              f"https://www.bseindia.com/download/Bhavcopy/Derivative/EQD_DP_{dd}{m}{y[2:]}.zip"):
        code, ok, text = get(u)
        print(d, code, "FILE" if ok else "-", len(text), u)
        if ok:
            lines = text.splitlines()
            print("    head:", lines[0][:600])
            for l in [l for l in lines if "SENSEX" in l.upper()][:2]:
                print("    S:", l[:600])
            break

# completeness of one SENSEX day (day before Thu 9 Oct 2025 expiry)
code, ok, text = get("https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_20251008_F_0000.CSV")
rows = [l.split(",") for l in text.splitlines()[1:]]
sx = [r for r in rows if len(r) > 22 and r[7] == "SENSEX" and r[4] == "IDO"]
by = {}
for r in sx:
    by.setdefault(r[10], []).append(r)
for e, rs in sorted(by.items()):
    ks = sorted(float(r[11]) for r in rs)
    oi = sum(float(r[22] or 0) for r in rs)
    print("expiry", e, "contracts", len(rs), "strikes", ks[0], "-", ks[-1], "OI", oi, "underlying", rs[0][20])

# SENSEX daily open/close: 3 years in one call?
code, ok, text = get("https://api.bseindia.com/BseIndiaAPI/api/ProduceCSVForDate/w?strIndex=SENSEX&dtFromDate=01/10/2023&dtToDate=13/10/2026")
lines = text.splitlines()
print("index csv", code, ok, "rows", len(lines), lines[:2], lines[-2:])
