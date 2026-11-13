"""
ICICI Direct Breeze (13 Nov 2026): minute-by-minute futures and options history, free with the owner's ICICI account,
for back-tests on real option prices (the rule tests so far had daily data only).

- ICICI ties the API key to one fixed internet address (SEBI rule from 1 Apr 2026). That address is the owner's free
  Oracle Cloud server (130.210.31.37, Always Free, Mumbai); the job reaches ICICI through it over SSH
  (.github/workflows/breeze.yml opens the tunnel and sets BREEZE_PROXY). Nothing is installed on the server.
- One ICICI sign-in a day: the login link sends the browser to the phone app, which hands the day's session to the
  relay (relay/Breeze.gs); the job reads it with RELAY_KEY (BREEZE_SESSION in the environment).
- Secrets: BREEZE_API_KEY, BREEZE_API_SECRET, ORACLE_SSH_KEY (GitHub). Never printed.
- Data licence: the downloaded prices go to the private repo only; logs print counts and dates, never prices.

Minimal client after the official SDK (breeze-connect 1.0.69): customerdetails turns the day's session into the
user's token; historicalcharts (v2) returns up to 1,000 candles per call.
"""
import base64
import json
import os
import time
import urllib.parse

import requests

API_URL = "https://api.icicidirect.com/breezeapi/api/v1/"
V2_URL = "https://breezeapi.icicidirect.com/api/v2/"
LOGIN_URL = "https://api.icicidirect.com/apiuser/login?api_key="
PAUSE = 0.7          # under ICICI's 100 calls a minute


def login_link(api_key: str) -> str:
    return LOGIN_URL + urllib.parse.quote_plus(api_key)


class Breeze:
    def __init__(self, api_key=None, session=None, proxy=None):
        self.api_key = api_key or os.environ["BREEZE_API_KEY"]
        session = session or os.environ["BREEZE_SESSION"]
        proxy = proxy if proxy is not None else os.environ.get("BREEZE_PROXY", "")
        self.http = requests.Session()
        if proxy:
            self.http.proxies = {"http": proxy, "https": proxy}
        body = json.dumps({"SessionToken": session, "AppKey": self.api_key}, separators=(",", ":"))
        r = self.http.get(API_URL + "customerdetails", data=body, headers={"Content-Type": "application/json"}, timeout=60)
        j = r.json()
        if not j.get("Success"):
            raise RuntimeError(f"ICICI refused the sign-in: {j.get('Error') or j.get('Status')}")
        user, key = base64.b64decode(j["Success"]["session_token"]).decode("ascii").split(":", 1)
        self.token = base64.b64encode(f"{user}:{key}".encode("ascii")).decode("ascii")
        self.calls = 0

    def history(self, stock_code, exch, interval, start, end, product=None, expiry=None, right=None, strike=None):
        """Candles between start and end, written 'YYYY-MM-DDTHH:MM:SS.000Z' but read by ICICI as INDIAN clock time
        despite the Z (first check, 13 Nov 2026: 03:45Z-10:00Z returned 09:15-10:00 IST candles). Returns ICICI's rows:
        datetime (IST), open, high, low, close, volume, and open_interest for F&O."""
        params = {"interval": interval, "from_date": start, "to_date": end, "stock_code": stock_code, "exch_code": exch}
        if product:
            params["product_type"] = product
        if expiry:
            params["expiry_date"] = expiry
        if strike is not None:
            params["strike_price"] = str(strike)
        if right:
            params["right"] = right
        time.sleep(PAUSE)
        self.calls += 1
        r = self.http.get(V2_URL + "historicalcharts", params=params,
                          headers={"Content-Type": "application/json", "X-SessionToken": self.token, "apikey": self.api_key},
                          timeout=60)
        j = r.json()
        if j.get("Status") not in (200, None) or j.get("Error"):
            raise RuntimeError(f"ICICI history: {j.get('Error') or j.get('Status')}")
        return j.get("Success") or []
