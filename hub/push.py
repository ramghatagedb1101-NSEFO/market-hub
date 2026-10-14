"""
Kite login reminder, pushed straight to the owner's iPhone through the Market Hub PWA (14 Oct 2026).

Runs twice on weekday mornings (workflow kite-reminder.yml, ~07:36 and ~08:33 IST -- after Kite's own
~07:30 morning clear-out, before the 09:05 close of the window the owner is asked to log in by). Skips
NSE holidays and skips if Kite is already logged in today (relay/KiteWatch.gs's kiteStatus_(), read
through the relay's key-protected ?mode=push_state); otherwise sends "Log in to Kite now" (opens the
Kite login link on tap) to every subscribed device with pywebpush, and reports any endpoint Web Push
says is gone (404/410, e.g. the app was removed) back to the relay so it stops being tried.

VAPID keys (owner's choice, 14 Oct 2026 evening -- no key-copying by anyone): by default the relay
holds the pair. The first run finds none there, generates one here on GitHub's runner in web-push's
own format, masks the private key from the Actions log, and stores it on the relay once
(mode=push_keys_init, which never overwrites a working pair); later runs read it back through the
key-protected push_state. If the GitHub secrets VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY are ever added
they take precedence, and their public key is posted to the relay (mode=push_key) for the phone.
Needs only the existing RELAY_URL/RELAY_KEY secrets.
"""
import base64
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
    """Never raises: the response carries the private key, and an uncaught requests error would print
    the one-time Google URL (script.googleusercontent.com/macros/echo?...) that serves it."""
    try:
        r = requests.get(relay_url, params={"mode": "push_state", "key": relay_key}, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        return {"error": "push_state failed: " + _err(exc)}


def _err(exc: Exception) -> str:
    """A failure reason safe to print: the exception type and HTTP status only. requests' own messages
    quote the full URL, which carries RELAY_KEY as a query parameter."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return type(exc).__name__ + (f" (HTTP {status})" if status else "")


def _mask(value: str) -> None:
    """Hides a secret from the rest of this run's Actions log. Called before anything could print it."""
    if value and os.getenv("GITHUB_ACTIONS"):
        print(f"::add-mask::{value}", flush=True)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_vapid_keys() -> tuple[str, str]:
    """A fresh P-256 pair in `npx web-push generate-vapid-keys`'s own format (base64url, no padding): the
    65-byte uncompressed public point, which the phone hands to pushManager.subscribe, and the 32-byte
    private scalar, which pywebpush accepts as is."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    priv = k.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(pub), _b64url(priv)


def _post(relay_url: str, relay_key: str, mode: str, body: dict) -> dict:
    """The relay answers HTTP 200 even for {"error": ...}, so callers check the body, not the status."""
    r = requests.post(relay_url, params={"mode": mode, "key": relay_key}, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def init_relay_keys(relay_url: str, relay_key: str) -> str:
    """Generates a pair and offers it to the relay, which stores it only if it holds no working pair.
    Returns "created", "existing" (a pair was already there; this one is discarded), or why it failed."""
    pub, priv = generate_vapid_keys()
    _mask(priv)
    try:
        body = _post(relay_url, relay_key, "push_keys_init", {"public_key": pub, "private_key": priv})
    except Exception as exc:
        return "init failed: " + _err(exc)
    if body.get("error"):
        return "init failed: " + str(body["error"])[:80]
    return "created" if body.get("created") else "existing"


def publish_public_key(relay_url: str, relay_key: str, public_key: str) -> str:
    """GitHub-secrets route only: keeps the relay's copy of the public key in sync with the secret --
    cheap, so done every run rather than tracked as a one-off setup step. Returns "ok" or why not."""
    try:
        body = _post(relay_url, relay_key, "push_key", {"public_key": public_key})
    except Exception as exc:
        return _err(exc)
    return "ok" if not body.get("error") else str(body["error"])[:80]


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


def resolve_keys(relay_url: str, relay_key: str, st: dict) -> tuple[str, str, dict]:
    """Returns (private key or "", how the keys were found, push_state -- re-read after a first-run
    init). GitHub secrets win when both are set; otherwise the relay's pair, created on the first run."""
    env_pub = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    env_priv = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    if env_pub and env_priv:
        published = publish_public_key(relay_url, relay_key, env_pub)
        if published != "ok" and st.get("vapid_public_key") != env_pub:
            # The phone subscribes with the relay's public key; signing with a private key the relay does
            # not have the public half of would fail on every device.
            return "", "github secrets, public key not on relay: " + published, st
        return env_priv, "github secrets, public key to relay: " + published, st
    priv = st.get("vapid_private_key") or ""
    if priv:
        return priv, "relay", st
    how = "relay, " + init_relay_keys(relay_url, relay_key)
    st = push_state(relay_url, relay_key)
    return ("" if "error" in st else st.get("vapid_private_key") or ""), how, st


def main(mode: str = "send") -> dict:
    relay_url, relay_key = os.getenv("RELAY_URL", ""), os.getenv("RELAY_KEY", "")
    if not relay_url or not relay_key:
        return {"sent": 0, "reason": "RELAY_URL/RELAY_KEY not set"}

    st = push_state(relay_url, relay_key)
    if "error" in st:
        return {"sent": 0, "reason": "push_state: " + str(st["error"])[:80]}
    _mask(st.get("vapid_private_key") or "")
    vapid_private, keys, st = resolve_keys(relay_url, relay_key, st)
    _mask(vapid_private)
    if not vapid_private:
        return {"sent": 0, "keys": keys, "reason": "no VAPID private key available"}

    if mode != "test" and is_nse_holiday():
        return {"sent": 0, "keys": keys, "reason": "NSE holiday today"}
    if mode != "test" and st.get("kite_state") == "ok":
        return {"sent": 0, "keys": keys, "reason": "already logged in to Kite today"}

    subs = st.get("subscriptions") or []
    if not subs:
        return {"sent": 0, "keys": keys, "reason": "no subscribed devices"}

    login_link = st.get("login_link") or ""
    title = "Log in to Kite" if mode != "test" else "Market Hub: test notification"
    body = "Tap, then \"Log in to Kite\" -- needed for today's live quotes and the daily run." if mode != "test" \
        else "If you see this, push notifications are working. Tap: Market Hub opens on \"Log in to Kite\"."
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
    return {"sent": sent, "dropped": len(gone), "errors": errors, "subscribed": len(subs), "keys": keys}


if __name__ == "__main__":
    import sys
    result = main(sys.argv[1] if len(sys.argv) > 1 else "send")
    print(json.dumps(result, indent=2))
    if os.getenv("GITHUB_ACTIONS"):
        # Also as a run annotation: shown on the run's summary page and readable through the check-runs
        # API, unlike the log itself (a cloud Claude session's egress policy blocks log downloads).
        print(f"::notice title=push result::{json.dumps(result)}")
