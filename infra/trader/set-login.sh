#!/usr/bin/env bash
# The owner types the IBKR PAPER account login here, once (13 Nov 2026). Nothing is shown on screen or printed;
# the password goes to /opt/trader/secrets/tws_password.txt (only the gateway's user can read it). Then the gateway
# starts. Run it again to change the login (e.g. after the paper password is changed).
set -euo pipefail
cd /opt/trader
read -r -p "IBKR paper trading username: " user
read -r -s -p "IBKR paper trading password (hidden): " pass; echo
[ -n "$user" ] && [ -n "$pass" ] || { echo "Both are needed; nothing saved."; exit 1; }
umask 077
printf 'TWS_USERID=%s\n' "$user" > .env
# The gateway runs inside its container as user 1000 (ibgateway), not this machine's ubuntu user (1001): the password
# file and its settings folder must belong to 1000, or it cannot read them and restarts forever (14 Nov 2026).
printf '%s' "$pass" | sudo tee secrets/tws_password.txt >/dev/null
unset pass
sudo chown 1000:1000 secrets/tws_password.txt && sudo chmod 600 secrets/tws_password.txt
sudo chown -R 1000:1000 tws_settings
sudo docker compose up -d --force-recreate
echo "Saved. The gateway is starting (about a minute); then run: /opt/trader/venv/bin/python /opt/trader/check.py"
