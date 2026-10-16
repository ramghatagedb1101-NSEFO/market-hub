"""
Daily source check (17 Oct 2026, owner: "yes" to a check that emails when a data source goes stale or empty). NSE's
insider list stopped on 28 Apr 2026 and nothing noticed for six months; this looks every morning at three things:

  files      each private data file changed within its expected time (weekends allowed for weekday jobs)
  sections   the insights sections are not empty and their newest entries are recent (filings, insider trades,
             positions, option prices, surveillance lists, heatmap) and every insights source reported ok
  jobs       no scheduled workflow's latest run failed

Email (relay mode=source_health) only when the list of problems changes, or every 3 days while one lasts, so a known
problem does not mail daily. State in the private repo's state/source_health.json. Reads through GitHub's API; needs
PRIVATE_REPO_TOKEN, RELAY_URL, RELAY_KEY and the workflow's GITHUB_TOKEN (actions: read).
"""
import base64
import json
import os
from datetime import datetime, timedelta, timezone

import requests

from . import config
from .site_data import API, PRIVATE_REPO, PUBLIC_REPO, BRANCH, _headers, _request

STATE = "state/source_health.json"
REMIND_DAYS = 3

# path, hours it may go without a change, True = written on weekdays only (a weekend adds 48 hours), what it is
FILES = [
    ("library.json", 30, False, "stock library (daily 06:15)"),
    ("site/shortlist.json", 30, False, "Shortlist"),
    ("site/multibagger.json", 30, False, "early multibaggers"),
    ("site/digest.json", 30, False, "morning digest"),
    ("site/insights.json", 30, False, "insights (alerts, calendar, filings, positions)"),
    ("site/feed.json", 30, True, "phone feed and forecasts (daily 18:00)"),
    ("site/brief.json", 30, True, "market brief"),
    ("site/fno.json", 30, True, "F&O screens"),
    ("site/bulk_deals.json", 30, True, "bulk deals"),
    ("state/prices.json", 30, True, "daily prices"),
    ("site/summaries.json", 4 * 24, False, "AI summaries"),
    ("site/stocks.json", 8 * 24, False, "stock positions (weekly)"),
]


def _now():
    return datetime.now(config.IST)


def _age_limit(last: datetime, hours: int, weekdays: bool, now: datetime) -> float:
    """Allowed hours, plus 48 when a weekday-only job's gap spans a weekend."""
    if weekdays:
        d = last.date()
        while d <= now.date():
            if d.weekday() == 5:
                return hours + 48
            d += timedelta(days=1)
    return hours


def check_files(now: datetime) -> list:
    out = []
    for path, hours, weekdays, what in FILES:
        r = _request("GET", f"{API}/repos/{PRIVATE_REPO}/commits", headers=_headers(), params={"path": path, "per_page": 1, "sha": BRANCH})
        rows = r.json() if r.status_code == 200 else []
        if not rows:
            out.append({"id": "file:" + path, "what": what, "text": "no copy found in the data store"})
            continue
        last = datetime.fromisoformat(rows[0]["commit"]["committer"]["date"].replace("Z", "+00:00")).astimezone(config.IST)
        age = (now - last).total_seconds() / 3600
        if age > _age_limit(last, hours, weekdays, now):
            out.append({"id": "file:" + path, "what": what, "text": f"not updated since {last:%a %d %b %Y %H:%M} IST ({age / 24:.1f} days)"})
    return out


def _day(s):
    s = str(s or "")
    for fmt, n in (("%Y-%m-%d", 10), ("%d-%b-%Y", 11)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            pass
    return None


def check_sections(now: datetime) -> list:
    r = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/site/insights.json?ref={BRANCH}", headers=_headers("application/vnd.github.raw"))
    if r.status_code != 200:
        return [{"id": "sec:insights", "what": "insights", "text": f"could not be read (HTTP {r.status_code})"}]
    d = r.json()
    today, out = now.date(), []

    def add(key, what, text):
        out.append({"id": "sec:" + key, "what": what, "text": text})

    def newest(dates):
        dates = [x for x in dates if x and x <= today + timedelta(days=1)]      # NSE typos such as the year 2924 are not "fresh"
        return max(dates) if dates else None

    for key, what, minimum in (("risk", "surveillance and F&O ban lists", 20), ("calendar", "results calendar", 10),
                               ("filings", "filings", 50), ("heatmap", "heatmap", 300), ("grades", "grades", 500)):
        n = len(d.get(key) or [])
        if n < minimum:
            add(key, what, f"only {n} entries (expected {minimum}+)")
    checks = [
        ("filings", "filings", newest(_day(x.get("t")) for x in d.get("filings") or []), 4),
        ("insider", "insider trades", newest(_day(r.get("d")) for v in (d.get("insider") or {}).values() for r in v.get("rows") or []), 45),
        ("positions", "FII/DII positions", newest(_day(k) for k in d.get("positions") or {}), 6),
    ]
    for idx, v in (d.get("iv") or {}).items():
        checks.append(("iv:" + idx, idx + " option prices", _day((v.get("last") or [None])[0]), 40 if idx == "BANKNIFTY" else 14))
    for key, what, last, days in checks:
        if last is None:
            add(key, what, "no entries")
        elif (today - last).days > days:
            add(key, what, f"newest entry is from {last:%a %d %b %Y} ({(today - last).days} days old)")
    for src, status in (d.get("log") or {}).items():
        if status != "ok" and not str(status).endswith("companies"):
            add("log:" + src, "insights source: " + src, str(status)[:120])
    return out


def check_jobs() -> list:
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return []
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    try:
        flows = requests.get(f"{API}/repos/{PUBLIC_REPO}/actions/workflows", headers=h, params={"per_page": 100}, timeout=30).json().get("workflows", [])
    except (requests.RequestException, ValueError):
        return []
    out = []
    for w in flows:
        if w.get("state") != "active":
            continue
        try:
            runs = requests.get(f"{API}/repos/{PUBLIC_REPO}/actions/workflows/{w['id']}/runs", headers=h,
                                params={"event": "schedule", "per_page": 1, "status": "completed"}, timeout=30).json().get("workflow_runs", [])
        except (requests.RequestException, ValueError):
            continue
        if runs and runs[0].get("conclusion") == "failure":
            t = datetime.fromisoformat(runs[0]["created_at"].replace("Z", "+00:00")).astimezone(config.IST)
            out.append({"id": "job:" + w["path"], "what": "job " + w["name"], "text": f"last scheduled run failed ({t:%a %d %b %Y %H:%M} IST)"})
    return out


def _state():
    r = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{STATE}?ref={BRANCH}", headers=_headers())
    if r.status_code != 200:
        return {}, None
    j = r.json()
    try:
        return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"]
    except (ValueError, KeyError):
        return {}, j.get("sha")


def _save_state(st, sha):
    body = {"message": "source health " + _now().strftime("%Y-%m-%d"), "branch": BRANCH,
            "content": base64.b64encode(json.dumps(st, indent=1).encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    _request("PUT", f"{API}/repos/{PRIVATE_REPO}/contents/{STATE}", headers=_headers(), json=body)


def main() -> dict:
    now = _now()
    problems = []
    for part in (check_files, check_sections):
        try:
            problems += part(now)
        except Exception as e:                     # one broken check must not hide the others
            problems.append({"id": "check:" + part.__name__, "what": "the check itself", "text": f"{part.__name__}: {e}"[:160]})
    problems += check_jobs()
    st, sha = _state()
    ids = sorted(p["id"] for p in problems)
    last_ids, last_sent = st.get("ids") or [], st.get("sent")
    changed = ids != last_ids
    due = bool(ids) and (not last_sent or (now - datetime.fromisoformat(last_sent)).days >= REMIND_DAYS)
    fixed = [i for i in last_ids if i not in ids]
    send = (changed and (ids or fixed)) or due
    mail = {"sent": False}
    if send and os.getenv("RELAY_URL") and os.getenv("RELAY_KEY"):
        payload = {"day": now.strftime("%a %d %b %Y"), "problems": problems, "fixed": [x.split(":", 1)[1] for x in fixed],
                   "new": [p["id"] for p in problems if p["id"] not in last_ids]}
        try:
            r = requests.post(os.getenv("RELAY_URL"), params={"mode": "source_health", "key": os.getenv("RELAY_KEY")}, data=json.dumps(payload), timeout=60)
            mail = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"sent": False, "status": r.status_code}
        except (requests.RequestException, ValueError) as e:
            mail = {"sent": False, "error": str(e)[:100]}
        if mail.get("ok"):
            st["sent"] = now.isoformat(timespec="minutes")
    st.update({"ids": ids, "checked": now.isoformat(timespec="minutes"), "problems": problems})
    _save_state(st, sha)
    return {"checked": st["checked"], "problems": len(problems), "new": len([i for i in ids if i not in last_ids]), "fixed": len(fixed),
            "mailed": bool(mail.get("ok")), "list": [p["what"] + ": " + p["text"] for p in problems]}


if __name__ == "__main__":
    print(json.dumps(main(), indent=1, default=str))
