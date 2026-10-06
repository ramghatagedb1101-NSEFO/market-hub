"""
Trade a one-time request_token for today's Kite access token and store it as a GitHub secret.

Runs inside the kite-login workflow only. Never prints the token.
Needs: KITE_API_KEY, KITE_API_SECRET, REQUEST_TOKEN (input), GH_TOKEN (PAT with repo secrets
write), GITHUB_REPOSITORY (set by Actions).
"""
import os
import subprocess
from urllib.parse import parse_qs, urlparse

from kiteconnect import KiteConnect


def _request_token(raw: str) -> str:
    """Accept either the bare token or the full redirect URL pasted from the address bar."""
    raw = raw.strip()
    if "request_token=" in raw:
        return parse_qs(urlparse(raw).query)["request_token"][0]
    return raw


def main() -> None:
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]
    request_token = _request_token(os.environ["REQUEST_TOKEN"])

    kite = KiteConnect(api_key=api_key)
    session = kite.generate_session(request_token, api_secret=api_secret)
    access_token = session["access_token"]

    kite.set_access_token(access_token)
    user = kite.profile()["user_name"]

    subprocess.run(
        ["gh", "secret", "set", "KITE_ACCESS_TOKEN",
         "--repo", os.environ["GITHUB_REPOSITORY"], "--body", access_token],
        check=True,
    )
    print(f"Kite access token stored for {user}. Valid until about 06:00 IST tomorrow.")


if __name__ == "__main__":
    main()
