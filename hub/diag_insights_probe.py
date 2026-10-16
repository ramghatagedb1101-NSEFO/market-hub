"""
Probe (16 Oct 2026): can GitHub reach the free NSE sources the new insight features need? Writes only
status codes, row counts and field NAMES to diag_output/insights_probe.json (this repo is public: no
company data, no values).
"""
import json
from datetime import datetime, timedelta

from . import config
from . import shareholding as shp

today = datetime.now(config.IST).date()
d = lambda x: x.strftime("%d-%m-%Y")
a, b = d(today - timedelta(days=7)), d(today)
prev = today - timedelta(days=1)
while prev.weekday() >= 5:
    prev -= timedelta(days=1)

API = {
    "insider_pit": f"https://www.nseindia.com/api/corporates-pit?index=equities&from_date={a}&to_date={b}",
    "board_meetings": f"https://www.nseindia.com/api/corporate-board-meetings?index=equities&from_date={d(today)}&to_date={d(today + timedelta(days=30))}",
    "announcements": f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={d(today - timedelta(days=2))}&to_date={b}",
    "asm_report": "https://www.nseindia.com/api/reportASM",
    "gsm_report": "https://www.nseindia.com/api/reportGSM",
    "pledge": f"https://www.nseindia.com/api/corporate-pledgedata?index=equities&from_date={a}&to_date={b}",
}
FILES = {
    "fo_secban": f"https://nsearchives.nseindia.com/content/fo/fo_secban_{prev:%d%m%Y}.csv",
    "reg_ind": f"https://nsearchives.nseindia.com/content/equities/REG_IND{prev:%d%m%y}.csv",
    "participant_oi": f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{prev:%d%m%Y}.csv",
}


def shape(body):
    if isinstance(body, list):
        return {"type": "list", "rows": len(body), "keys": sorted(body[0].keys())[:40] if body and isinstance(body[0], dict) else None}
    if isinstance(body, dict):
        out = {"type": "dict", "keys": sorted(body.keys())[:40]}
        for k in ("data", "rows", "longterm", "shortterm"):
            v = body.get(k)
            if isinstance(v, list):
                out[k] = {"rows": len(v), "keys": sorted(v[0].keys())[:40] if v and isinstance(v[0], dict) else None}
        return out
    return {"type": type(body).__name__}


def main():
    s = shp.session()
    res = {"run": datetime.now(config.IST).isoformat(timespec="minutes")}
    for k, url in API.items():
        try:
            r = s.get(url, headers={**shp.HEADERS, "Accept": "application/json"}, timeout=60)
            res[k] = {"status": r.status_code}
            if r.status_code == 200:
                try:
                    res[k].update(shape(r.json()))
                except ValueError:
                    res[k]["json"] = False
        except Exception as e:
            res[k] = {"error": str(e)[:120]}
    for k, url in FILES.items():
        try:
            r = s.get(url, headers=shp.HEADERS, timeout=60)
            res[k] = {"status": r.status_code, "bytes": len(r.content)}
            if r.status_code == 200:
                lines = r.content.decode("utf-8", "replace").splitlines()
                res[k].update({"lines": len(lines), "header": lines[0][:300] if lines else None})
        except Exception as e:
            res[k] = {"error": str(e)[:120]}
    out = config.REPO / "diag_output" / "insights_probe.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
