"""What the relay sends the trading machine (?mode=strategies): mode, active, counts; no keys printed (17 Nov 2026)."""
import json
import os
import urllib.parse
import urllib.request


def main():
    q = urllib.parse.urlencode({"mode": "strategies", "key": os.environ["RELAY_KEY"]})
    d = json.loads(urllib.request.urlopen(os.environ["RELAY_URL"] + "?" + q, timeout=60).read())
    names = {x.get("id"): x.get("name") for x in d.get("items") or []}
    print({"error": d.get("error"), "mode": d.get("mode"), "active": d.get("active"), "active_name": names.get(d.get("active")),
           "items": len(names), "ids": list(names), "method": d.get("method"), "changed": d.get("changed"),
           "match_pick": (d.get("match_pick") or {}).get("name")})


if __name__ == "__main__":
    main()
