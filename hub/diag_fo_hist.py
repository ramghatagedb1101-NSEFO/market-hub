"""One-off (13 Oct 2026): which NSE archive files the expiry history test can use, and their columns.
Old F&O bhavcopy (until Jul 2024), the UDiFF F&O bhavcopy (from Jul 2024), and the daily index close file."""
import io
import time
import zipfile

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
     "Accept": "*/*"}
URLS = [
    "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/2023/OCT/fo05OCT2023bhav.csv.zip",
    "https://archives.nseindia.com/content/historical/DERIVATIVES/2023/OCT/fo05OCT2023bhav.csv.zip",
    "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20231005_F_0000.csv.zip",
    "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20251007_F_0000.csv.zip",
    "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20261013_F_0000.csv.zip",
    "https://nsearchives.nseindia.com/content/indices/ind_close_all_05102023.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_close_all_13102026.csv",
    "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20231007_F_0000.csv.zip",   # a Saturday: expect none
]

s = requests.Session()
s.headers.update(H)
for u in URLS:
    try:
        r = s.get(u, timeout=30)
        print("\n==", r.status_code, len(r.content), u)
        if r.status_code != 200:
            continue
        data = r.content
        if data[:2] == b"PK":
            z = zipfile.ZipFile(io.BytesIO(data))
            print("   zip:", z.namelist())
            data = z.read(z.namelist()[0])
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        print("   rows:", len(lines))
        print("   head:", lines[0][:600])
        picks = [l for l in lines if ("NIFTY" in l and ("OPTIDX" in l or "IDO" in l) and "BANKNIFTY" not in l and "FINNIFTY" not in l and "MIDCP" not in l and "NXT50" not in l)][:3]
        for l in picks or [l for l in lines if "Nifty 50" in l or "Nifty Bank" in l][:3]:
            print("   row:", l[:600])
    except Exception as e:
        print("\n== ERR", u, str(e)[:200])
    time.sleep(1.2)
