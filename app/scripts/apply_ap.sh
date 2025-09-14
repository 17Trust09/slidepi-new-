#!/usr/bin/env bash
set -euo pipefail

# Dieses Skript ruft die Flask-Logik auf,
# die hostapd/dnsmasq/dhcpcd konfiguriert.
# Passe "venv" und "app.py" auf dein Projekt an.

APP_DIR="/opt/slidepi"
VENV_DIR="$APP_DIR/venv"
FLASK_CMD="$VENV_DIR/bin/python -c 'from app.services.ap_service import APService; \
from app.services.settings_service import get_setting,set_setting; \
APService(get_setting,set_setting).render_and_apply(); print(\"AP applied\")'"

if [ ! -d "$VENV_DIR" ]; then
  echo "WARN: venv nicht gefunden unter $VENV_DIR, versuche System-Python."
  FLASK_CMD="python3 -c 'from app.services.ap_service import APService; \
from app.services.settings_service import get_setting,set_setting; \
APService(get_setting,set_setting).render_and_apply(); print(\"AP applied\")'"
fi

eval $FLASK_CMD
