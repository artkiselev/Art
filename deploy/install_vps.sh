#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/wedding-bot"
SERVICE_FILE="/etc/systemd/system/wedding-bot.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root: sudo bash deploy/install_vps.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip

mkdir -p "$APP_DIR/data/voice" "$APP_DIR/outputs"
cp -r bot.py config.py documents.py email_sender.py openai_service.py questionnaire.py requirements.txt storage.py "$APP_DIR/"

if [[ ! -f "$APP_DIR/.env" ]]; then
  cp .env.example "$APP_DIR/.env"
  echo "Created $APP_DIR/.env. Fill it before starting the service."
fi

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

cp deploy/wedding-bot.service "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable wedding-bot

echo "Installed. Edit $APP_DIR/.env, then run: systemctl restart wedding-bot"
