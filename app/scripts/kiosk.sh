#!/usr/bin/env bash
set -euo pipefail

URL="http://10.10.0.1/present/kiosk"   # deine Kiosk-Route (HDMI)

# Warte bis X läuft
for i in {1..10}; do
  if xset q >/dev/null 2>&1; then
    break
  fi
  echo "[$(date)] Warte auf X-Server..." >&2
  sleep 2
done

# Chromium Binary suchen (verschiedene Distros nutzen unterschiedliche Namen)
CHROMIUM_BIN="$(command -v chromium-browser || command -v chromium || true)"
if [ -z "$CHROMIUM_BIN" ]; then
  echo "Fehler: Chromium nicht gefunden." >&2
  exit 1
fi

# Chromium im Kiosk-Modus starten
exec "$CHROMIUM_BIN" \
  --kiosk "$URL" \
  --noerrdialogs \
  --disable-infobars \
  --incognito \
  --check-for-update-interval=0 \
  --overscroll-history-navigation=0 \
  --autoplay-policy=no-user-gesture-required \
  --disable-session-crashed-bubble \
  --disable-restore-session-state \
  --window-position=0,0 \
  --start-fullscreen \
  >>/var/log/slidepi-kiosk.log 2>&1
