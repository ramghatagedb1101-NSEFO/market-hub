"""One-off (13 Oct 2026): NSE's participant-wise open interest file (client / DII / FII / pro), for the expiry history
test. Prints the layout for one old and one recent day."""
import time

import requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
     "Accept": "*/*"}
for d in ("04102023", "06102025", "12102026"):
    for u in (f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv",
              f"https://archives.nseindia.com/content/nsccl/fao_participant_oi_{d}.csv"):
        r = requests.get(u, headers=H, timeout=30)
        print("\n==", r.status_code, len(r.content), u)
        if r.status_code == 200:
            print(r.text[:1500])
            break
        time.sleep(1.2)
    time.sleep(1.2)
