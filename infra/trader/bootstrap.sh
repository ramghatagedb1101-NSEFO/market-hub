#!/usr/bin/env bash
# One-time setup of market-hub-trader (Oracle Arm, Ubuntu 24.04) for IBKR paper trading, 13 Nov 2026.
# Run as the ubuntu user:  curl -fsSL https://raw.githubusercontent.com/ramghatagedb1101-NSEFO/market-hub/main/infra/trader/bootstrap.sh | bash
# Installs Docker and Python, puts the gateway's files in /opt/trader, and stops before the login: the owner then
# runs set-login.sh once and types the IBKR paper username and password (hidden). Safe to run again.
set -euo pipefail
RAW=https://raw.githubusercontent.com/ramghatagedb1101-NSEFO/market-hub/main/infra/trader

sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io docker-compose-v2 python3-venv curl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
sudo timedatectl set-timezone Asia/Kolkata

sudo mkdir -p /opt/trader/secrets /opt/trader/tws_settings
sudo chown -R "$USER":"$USER" /opt/trader
chmod 700 /opt/trader/secrets
for f in docker-compose.yml set-login.sh check.py; do curl -fsSL "$RAW/$f" -o "/opt/trader/$f"; done
chmod +x /opt/trader/set-login.sh

python3 -m venv /opt/trader/venv
/opt/trader/venv/bin/pip install --quiet "ib_async>=1.0" "requests>=2.31"

# The program itself (trader/ and the hub/ pieces it reuses): a copy of this public repo, refreshed with git pull.
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git
if [ -d /opt/trader/app/.git ]; then git -C /opt/trader/app pull -q --ff-only; else
  git clone -q --depth 1 https://github.com/ramghatagedb1101-NSEFO/market-hub.git /opt/trader/app; fi
mkdir -p /opt/trader/journal
curl -fsSL "$RAW/trader.service" | sudo tee /etc/systemd/system/trader.service >/dev/null
sudo systemctl daemon-reload            # installed, not started: it starts once the paper login works
sudo docker compose -f /opt/trader/docker-compose.yml pull --quiet

echo "Ready. Next (owner, once): /opt/trader/set-login.sh"
