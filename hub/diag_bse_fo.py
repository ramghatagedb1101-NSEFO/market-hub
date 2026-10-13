"""One-off (14 Oct 2026): BSE's derivatives end-of-day file and a daily SENSEX open/close, for adding SENSEX to the
expiry history test. BSE needs curl_cffi (Chrome impersonation); plain requests get "Access Denied"."""
import io
import re
import time
import zipfile

from curl_cffi import requests as cr

s = cr.Session(impersonate="chrome")
s.headers.update({"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"})


def show(u, n=4):
    try:
        r = s.get(u, timeout=40)
        print("\n==", r.status_code, len(r.content), r.headers.get("content-type"), u)
        if r.status_code != 200 or len(r.content) < 200:
            print("   ", r.text[:200].replace("\n", " "))
            return r
        data = r.content
        if data[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(data))
            print("   zip:", z.namelist())
            data = z.read(z.namelist()[0])
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        print("   rows:", len(lines))
        for l in lines[:2]:
            print("   ", l[:700])
        for l in [l for l in lines if "SENSEX" in l.upper() and "BANKEX" not in l.upper()][:n]:
            print("   S:", l[:700])
        return r
    except Exception as e:
        print("\n== ERR", u, str(e)[:200])
    finally:
        time.sleep(1.3)


# The bhavcopy page: what the derivatives links actually look like
r = s.get("https://www.bseindia.com/markets/marketinfo/BhavCopy.aspx", timeout=40)
print("page", r.status_code, len(r.text))
for h in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
    if re.search(r"(?i)deriv|bhav|\.zip|\.csv", h):
        print("   link:", h)
time.sleep(1.3)

for d in ("20231012", "20240704", "20240708", "20251008", "20261013"):
    y, m, dd = d[:4], d[4:6], d[6:]
    for u in (f"https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_{d}_F_0000.CSV",
              f"https://www.bseindia.com/download/Bhavcopy/Derivative/bhavcopy{dd}-{m}-{y[2:]}.zip",
              f"https://www.bseindia.com/download/Bhavcopy/Derivative/MS_{d}-01.csv"):
        r = show(u)
        if r is not None and r.status_code == 200 and len(r.content) > 1000:
            break

# Daily SENSEX open/high/low/close
show("https://api.bseindia.com/BseIndiaAPI/api/IndexArchDaily/w?fmdt=06/10/2025&todt=10/10/2025&index=16")
show("https://api.bseindia.com/BseIndiaAPI/api/ProduceCSVForDate/w?strIndex=SENSEX&dtFromDate=06/10/2025&dtToDate=10/10/2025")
show("https://api.bseindia.com/BseIndiaAPI/api/IndexArchDaily/w?fmdt=09/10/2023&todt=13/10/2023&index=SENSEX")
show("https://query1.finance.yahoo.com/v8/finance/chart/%5EBSESN?period1=1759708800&period2=1760140800&interval=1d")
