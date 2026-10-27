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
RETIRE_DAYS = 20         # scored days of the new close estimate before the old forecast's retirement is put to the owner
REMIND_DAYS = 3

# path, hours it may go without a change, True = written on weekdays only (a weekend adds 48 hours), what it is
FILES = [
    ("library.json", 30, False, "stock library (daily 06:15)"),
    ("site/shortlist.json", 30, False, "Shortlist"),
    ("state/close_estimate_log.json", 30, True, "close-estimate record (close-estimate.yml)"),
    ("state/news_score_log.json", 30, True, "daily news score (close-estimate.yml)"),
    ("site/multibagger.json", 30, False, "early multibaggers"),
    ("site/digest.json", 30, False, "morning digest"),
    ("site/insights.json", 30, False, "insights (alerts, calendar, filings, positions)"),
    ("site/feed.json", 30, True, "phone feed and forecasts (daily 18:00)"),
    ("site/brief.json", 30, True, "market brief"),
    ("site/fno.json", 30, True, "F&O screens"),
    ("site/bulk_deals.json", 30, True, "bulk deals"),
    ("state/prices.json", 30, True, "daily prices"),
    ("site/summaries.json", 4 * 24, False, "AI summaries"),
    ("site/stocks.json", 30, True, "NIFTY 50 option screen (daily 18:00)"),   # was 8 days: wrong, it is daily (23 Oct 2026)
]


def _now():
    return datetime.now(config.IST)


_HOLIDAYS = "unread"


def _holidays():
    """NSE's trading holidays (hub/push.py's reader, also used by the Kite reminder), read once per run.
    21 Oct 2026: the check had only a weekend allowance and mailed "daily prices not updated" the morning
    after the Dussehra holiday (Tue 20 Oct)."""
    global _HOLIDAYS
    if _HOLIDAYS == "unread":
        from .push import nse_holidays
        _HOLIDAYS = nse_holidays()
    return _HOLIDAYS


def _age_limit(last: datetime, hours: int, weekdays: bool, now: datetime) -> float:
    """Allowed hours; a weekday-only job gets 24 more for every weekend day and NSE holiday after its last
    update. If NSE's calendar cannot be read, one day of grace stands in for an unknown holiday."""
    if not weekdays:
        return hours
    hol = _holidays()
    extra, d = 0, last.date() + timedelta(days=1)
    while d <= now.date():
        if d.weekday() >= 5 or (hol and d.isoformat() in hol):
            extra += 24
        d += timedelta(days=1)
    return hours + extra + (0 if hol is not None else 24)


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


# Inside the other files (25 Oct 2026): a file can be rewritten every day while what it holds is old or an error. The
# written brief said "could not be written" on 10 of 12 runs from 20 Oct and the file check saw a fresh file each time.
# path, what, rule(d, today) -> problem text or None. Ages are calendar days, generous enough for a weekend.
def _newest(o, out=None):
    out = [] if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            x = _day(k)
            if x: out.append(x)
            _newest(v, out)
    elif isinstance(o, list):
        for v in o: _newest(v, out)
    elif isinstance(o, str) and len(o) < 40:
        x = _day(o)
        if x: out.append(x)
    return out


def _older(last, today, days, what="newest entry"):
    if last is None:
        return "no dated entries"
    return f"{what} is from {last:%a %d %b %Y} ({(today - last).days} days old)" if (today - last).days > days else None


def _max_ok(dates, today):
    dates = [x for x in dates if x and x <= today + timedelta(days=1)]
    return max(dates) if dates else None


CONTENTS = [
    ("site/brief.json", "written market brief",
     lambda d, t: ("could not be written: " + str((d.get("last_error") or {}).get("error") or d.get("text"))[:140])
     if d.get("source") in (None, "", "none") or d.get("last_error") else None),
    ("site/context.json", "FII/DII cash flows", lambda d, t: _older(_max_ok([_day(r.get("date")) for r in d.get("fii_dii") or []], t), t, 4)),
    ("site/context.json", "US closes (FRED, fallback)", lambda d, t: _older(_max_ok([_day(v.get("date")) for v in (d.get("global") or {}).values()], t), t, 5)),
    ("site/context.json", "market context sources", lambda d, t: ("; ".join(f"{k}: {v}" for k, v in d["errors"].items())[:160]) if d.get("errors") else None),
    ("site/feed.json", "NIFTY forecast data", lambda d, t: _older(_day(((d.get("indices") or {}).get("NIFTY") or {}).get("last_date")), t, 4, "last close")),
    ("site/shortlist.json", "Shortlist weekly list", lambda d, t: _older(_max_ok(_newest(d.get("lists")), t), t, 9)),
    ("site/bulk_deals.json", "bulk deals", lambda d, t: _older(_day(d.get("last_day")), t, 4, "last day")),
    ("site/summaries.json", "AI summaries", lambda d, t: _older(_max_ok(_newest(d), t), t, 5, "newest summary")),
]


def check_contents(now: datetime) -> list:
    today, out, cache = now.date(), [], {}
    for path, what, rule in CONTENTS:
        if path not in cache:
            r = _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{path}?ref={BRANCH}", headers=_headers("application/vnd.github.raw"))
            try:
                cache[path] = r.json() if r.status_code == 200 else None
            except ValueError:
                cache[path] = None
        d = cache[path]
        try:
            text = "could not be read" if d is None else rule(d, today)
        except Exception as e:
            text = f"check failed: {e}"[:120]
        if text:
            out.append({"id": "in:" + path + ":" + what, "what": what, "text": text})
    return out


def check_forecasts(now: datetime) -> list:
    """26 Oct 2026 (owner: "how come the audit did not identify these issues"): the SENSEX forecasts had been made and
    scored from mid-session prices for two weeks, and the estimate had no skill, and no check looked at either. Every
    stored forecast's starting close and settled close must equal the official close in prices.json; the phone card's
    recorded estimate must beat "no change" once it has 20 settled days."""
    from datetime import date
    from . import horizons
    get = lambda path: _request("GET", f"{API}/repos/{PRIVATE_REPO}/contents/{path}?ref={BRANCH}",
                                headers=_headers("application/vnd.github.raw")).json()
    st, px, out = get("state/state.json"), get("state/prices.json"), []
    bad = {}
    for p in st.get("predictions", []):
        rows = sorted(px.get(p["index"], {}).items())
        dates, closes = [date.fromisoformat(d) for d, _ in rows], [c for _, c in rows]
        close = dict(rows)
        wrong = p["asof"] in close and abs(close[p["asof"]] - p["base"]) > 0.01
        if p.get("settled_on") and p["horizon"] in ("day", "expiry"):
            act = horizons.settle_value(p["horizon"], date.fromisoformat(p["target"]), dates, closes)
            wrong = wrong or (act is not None and abs(float(act[1]) - p["actual"]) > 0.01)
        if wrong:
            bad[p["index"]] = bad.get(p["index"], 0) + 1
    for idx, n in bad.items():
        out.append({"id": "forecast:records:" + idx, "what": idx + " forecasts",
                    "text": f"{n} stored forecasts start from or were scored on a close that differs from the official close"})
    feed = get("site/feed.json")
    # an index expiring on its next session must have the evening-before straddle (its expiry-day range), else the card
    # quietly falls back to daily volatility
    for idx, b in (feed.get("indices") or {}).items():
        t = b.get("next") if (b.get("today") or {}).get("actual") is not None and b.get("next") else (b.get("today") or {})
        if t.get("own_expiry") and not t.get("straddle_pct"):
            out.append({"id": "forecast:straddle:" + idx, "what": idx + " expiry-day range",
                        "text": f"{idx} expires on {t.get('target')} but the evening-before straddle was not read from Kite"})
    # Retirement decision for the old ten-tool forecast (outside review 27 Oct 2026, finding 1): once the new close
    # estimate has RETIRE_DAYS scored days, compare both on the same days and email until the owner decides.
    try:
        log = get("state/close_estimate_log.json")
    except Exception:                               # noqa: BLE001 -- no log yet
        log = []
    for idx in (feed.get("indices") or {}):
        close = px.get(idx, {})
        new = {e["date"]: abs(close[e["date"]] / e["pred"] - 1) * 100 for e in log
               if e["index"] == idx and e["kind"] == "pre" and e["date"] in close}
        old = {p["target"]: abs(p["err_pct"]) for p in st.get("predictions", [])
               if p["index"] == idx and p["horizon"] == "day" and p.get("settled_on") and p["target"] in new}
        same = sorted(set(new) & set(old))
        if len(same) >= RETIRE_DAYS:
            n_err, o_err = sum(new[d] for d in same) / len(same), sum(old[d] for d in same) / len(same)
            better = "new estimate better" if n_err < o_err else "old forecast not beaten"
            out.append({"id": "forecast:retire:" + idx, "what": idx + " forecast retirement",
                        "text": f"{len(same)} days scored: new estimate error {n_err:.2f}% vs old ten-tool forecast {o_err:.2f}% "
                                f"({better}). Decide whether the new one replaces the old on the Desk tab and in the F&O/Brief ranges."})
    rec = (feed.get("close_estimate_record") or {})
    for idx, r in rec.items():
        if r.get("pre_n", 0) >= 20 and r.get("pre_err_pct", 0) > r.get("no_change_err_pct", 9):
            out.append({"id": "forecast:skill:" + idx, "what": idx + " close estimate",
                        "text": f"over {r['pre_n']} days its error ({r['pre_err_pct']}%) is worse than assuming no change ({r['no_change_err_pct']}%)"})
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
        if runs and runs[0].get("conclusion") in ("failure", "cancelled", "timed_out"):   # cancelled: hit its time limit (summaries, 20-23 Oct 2026)
            t = datetime.fromisoformat(runs[0]["created_at"].replace("Z", "+00:00")).astimezone(config.IST)
            word = {"failure": "failed", "cancelled": "was cancelled (time limit)", "timed_out": "timed out"}[runs[0]["conclusion"]]
            out.append({"id": "job:" + w["path"], "what": "job " + w["name"], "text": f"last scheduled run {word} ({t:%a %d %b %Y %H:%M} IST)"})
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
    for part in (check_files, check_sections, check_contents, check_forecasts):
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
