#!/usr/bin/env bash
# The owner types the IBKR PAPER account login here, once (13 Nov 2026). Nothing is shown on screen or printed;
# the password goes to /opt/trader/secrets/tws_password.txt (only this user can read it). Then the gateway starts.
set -euo pipefail
cd /opt/trader
read -r -p "IBKR paper trading username: " user
read -r -s -p "IBKR paper trading password (hidden): " pass; echo
[ -n "$user" ] && [ -n "$pass" ] || { echo "Both are needed; nothing saved."; exit 1; }
umask 077
printf 'TWS_USERID=%s\n' "$user" > .env
printf '%s' "$pass" > secrets/tws_password.txt
unset pass
sudo docker compose up -d
echo "Saved. The gateway is starting (about a minute); then run: /opt/trader/venv/bin/python /opt/trader/check.py"
