"""
Kite login reminder, pushed straight to the owner's iPhone through the Market Hub PWA (14 Oct 2026).

Runs twice on weekday mornings (workflow kite-reminder.yml, ~07:36 and ~08:33 IST -- after Kite's own
~07:30 morning clear-out, before the 09:05 close of the window the owner is asked to log in by). Skips
NSE holidays and skips if Kite is already logged in today (relay/KiteWatch.gs's kiteStatus_(), read
through the relay's key-protected ?mode=push_state); otherwise sends "Log in to Kite now" (opens the
Kite login link on tap) to every subscribed device with pywebpush, and reports any endpoint Web Push
says is gone (404/410, e.g. the app was removed) back to the relay so it stops being tried.

Needs VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY (GitHub secrets -- the owner's own
`npx web-push generate-vapid-keys` output, never typed by Claude) alongside the existing
RELAY_URL/RELAY_KEY secrets. The public key is also posted to the relay (mode=push_key) so the phone
can read it without the owner ever opening Apps Script's script-properties page.
"""
import json
import os
from datetime import datetime

import requests
from pywebpush import WebPushException, webpush

from . import config, shareholding as shp

HOLIDAY_API = "https://www.nseindia.com/api/holiday-master?type=trading"
CONTACT = "mailto:ramghatagedb1101@gmail.com"


def _today_ist() -> str:
    return datetime.now(config.IST).date().isoformat()


def is_nse_holiday(today: str | None = None) -> bool:
    """True on a day NSE's own trading calendar marks as a holiday. Fails toward False (send the
    reminder) on any error: an occasional reminder on a holiday is a minor nuisance, a missed one on a
    real trading day is not -- tested only from GitHub Actions (hub/diag_nse_alt.py's pattern); NSE
    blocks the owner's laptop."""
    today = today or _today_ist()
    try:
        s = shp.session()
        r = s.get(HOLIDAY_API, headers={**shp.HEADERS, "Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        body = r.json()
        rows = body.get("CM") or [] if isinstance(body, dict) else []
        for row in rows:
            d = datetime.strptime(str(row.get("tradingDate", "")).strip(), "%d-%b-%Y").date().isoformat()
            if d == today:
                return True
        return False
    except Exception:
        return False


def push_state(relay_url: str, relay_key: str) -> dict:
    r = requests.get(relay_url, params={"mode": "push_state", "key": relay_key}, timeout=30)
    r.raise_for_status()
    return r.json()


def publish_public_key(relay_url: str, relay_key: str, public_key: str) -> str:
    """Keeps the relay's copy of the public key in sync with the GitHub secret -- cheap, so just done
    every run rather than tracked as a one-off setup step. Returns "ok" or the reason it failed: the
    relay answers HTTP 200 even for {"error": ...}, so the body is checked, not just the status."""
    try:
        r = requests.post(relay_url, params={"mode": "push_key", "key": relay_key},
                          json={"public_key": public_key}, timeout=30)
        r.raise_for_status()
        body = r.json()
        return "ok" if not body.get("error") else str(body["error"])
    except Exception as exc:
        return str(exc)[:120]


def drop_endpoints(relay_url: str, relay_key: str, endpoints: list[str]) -> None:
    if not endpoints:
        return
    try:
        requests.post(relay_url, params={"mode": "push_drop", "key": relay_key},
                      json={"endpoints": endpoints}, timeout=30).raise_for_status()
    except Exception:
        pass   # tried again naturally next run: a dead endpoint just keeps failing harmlessly until then


def send_to(sub: dict, payload: dict, vapid_private_key: str) -> str:
    """Returns 'sent', 'gone' (caller should drop the endpoint), or 'error' (left alone, retried later).
    pywebpush derives the VAPID public key from the private key itself; no need to pass it."""
    try:
        webpush(subscription_info=sub, data=json.dumps(payload),
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": CONTACT})
        return "sent"
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        return "gone" if status in (404, 410) else "error"
    except Exception:
        return "error"


def main(mode: str = "send") -> dict:
    relay_url, relay_key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    vapid_public = os.getenv("VAPID_PUBLIC_KEY", "")
    vapid_private = os.getenv("VAPID_PRIVATE_KEY", "")
    if not relay_url or not relay_key:
        return {"sent": 0, "reason": "RELAY_URL/RELAY_KEY not set"}
    if not vapid_public or not vapid_private:
        return {"sent": 0, "reason": "VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY not set"}

    key_status = publish_public_key(relay_url, relay_key, vapid_public)

    if mode != "test" and is_nse_holiday():
        return {"sent": 0, "key_published": key_status, "reason": "NSE holiday today"}

    st = push_state(relay_url, relay_key)
    if "error" in st:
        return {"sent": 0, "key_published": key_status, "reason": "push_state: " + str(st["error"])}
    if mode != "test" and st.get("kite_state") == "ok":
        return {"sent": 0, "key_published": key_status, "reason": "already logged in to Kite today"}

    subs = st.get("subscriptions") or []
    if not subs:
        return {"sent": 0, "key_published": key_status, "reason": "no subscribed devices"}

    login_link = st.get("login_link") or ""
    title = "Log in to Kite" if mode != "test" else "Market Hub: test notification"
    body = "Tap to log in now -- needed for today's live quotes and the daily run." if mode != "test" \
        else "If you see this, push notifications are working."
    payload = {"title": title, "body": body, "url": login_link}

    sent, gone, errors = 0, [], 0
    for sub in subs:
        result = send_to(sub, payload, vapid_private)
        if result == "sent":
            sent += 1
        elif result == "gone":
            gone.append(sub["endpoint"])
        else:
            errors += 1
    drop_endpoints(relay_url, relay_key, gone)
    return {"sent": sent, "dropped": len(gone), "errors": errors, "subscribed": len(subs),
            "key_published": key_status}


if __name__ == "__main__":
    import sys
    result = main(sys.argv[1] if len(sys.argv) > 1 else "send")
    print(json.dumps(result, indent=2))
    if os.getenv("GITHUB_ACTIONS"):
        # Also as a run annotation: shown on the run's summary page and readable through the check-runs
        # API, unlike the log itself (a cloud Claude session's egress policy blocks log downloads).
        print(f"::notice title=push result::{json.dumps(result)}")
