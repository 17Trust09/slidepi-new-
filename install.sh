#!/usr/bin/env bash
set -euo pipefail

# =========================================
# SlidePi Installer (Raspberry Pi OS Bookworm, Pi 4/5)
# AP: hostapd + eigenes dnsmasq-Service
# wlan0: statische IP via systemd-oneshot (ohne dhcpcd)
# Flask als systemd Service
# Kiosk: Xorg + Openbox + Chromium (200/302-Warte-Logik + Timeout)
# HDMI-Fallback, Energiesparen aus, xrandr-Ausgangswahl, robustes Logging
# + Chromium Enterprise Policy: Translate aus
# =========================================

# -------- Konfiguration --------
APP_USER="${APP_USER:-pi}"
APP_DIR="${APP_DIR:-/home/pi/slidepi}"
APP_VENV="${APP_VENV:-$APP_DIR/venv}"
APP_PORT="${APP_PORT:-8000}"
APP_HOST="${APP_HOST:-0.0.0.0}"

# WICHTIG: richtiger Kiosk-Endpunkt
KIOSK_URL="${KIOSK_URL:-http://localhost:${APP_PORT}/present/kiosk}"

AP_SSID="${AP_SSID:-SlidePi}"
AP_PSK="${AP_PSK:-SlidePi123}"                # min. 8 Zeichen
AP_IFACE="${AP_IFACE:-wlan0}"
AP_IP="${AP_IP:-10.42.0.1}"
AP_NETMASK="${AP_NETMASK:-255.255.255.0}"
AP_DHCP_START="${AP_DHCP_START:-10.42.0.10}"
AP_DHCP_END="${AP_DHCP_END:-10.42.0.250}"
AP_LEASE_TIME="${AP_LEASE_TIME:-24h}"
AP_CHANNEL="${AP_CHANNEL:-6}"
WIFI_COUNTRY="${WIFI_COUNTRY:-DE}"

# Kiosk-Artefakte EXPLIZIT im Home des Users
KIOSK_SCRIPT="/home/${APP_USER}/start_kiosk.sh"
KIOSK_LOG="/home/${APP_USER}/kiosk.log"
OPENBOX_AUTOSTART="/home/${APP_USER}/.config/openbox/autostart"

CHROMIUM_BIN_CANDIDATES=("chromium" "chromium-browser")
XWRAPPER="/etc/X11/Xwrapper.config"
BOOT_CONFIG="/boot/config.txt"

# -------- Helpers --------
need_root(){ [[ $EUID -eq 0 ]] || { echo "Bitte mit sudo ausführen"; exit 1; }; }
sysd_reload_enable_start(){ systemctl daemon-reload; systemctl enable "$1"; systemctl restart "$1" || systemctl start "$1"; }
detect_chromium_bin(){ for b in "${CHROMIUM_BIN_CANDIDATES[@]}"; do command -v "$b" >/dev/null && { echo "$b"; return; }; done; echo ""; }
append_once(){ local line="$1" file="$2"; grep -qF "$line" "$file" 2>/dev/null || echo "$line" >>"$file"; }

# -------- Preflight --------
need_root
echo "==> Pakete installieren/aktualisieren …"
apt-get update
apt-get install -y \
  git curl ufw network-manager \
  python3-pip python3-venv \
  hostapd dnsmasq \
  xserver-xorg x11-xserver-utils xinit openbox \
  chromium chromium-browser unclutter python3-xdg \
  fonts-dejavu-core ca-certificates

# Xorg Legacy erlauben (X auch aus Service startbar)
echo "==> Xorg-Legacy erlauben"
mkdir -p /etc/X11
echo "allowed_users=anybody" > "$XWRAPPER"

# HDMI-Fallback (Hotplug + 1080p) – nur einmal anhängen
echo "==> HDMI-Fallback in ${BOOT_CONFIG} setzen (falls nicht vorhanden)"
append_once "" "$BOOT_CONFIG"
append_once "# --- SlidePi HDMI Fix ---" "$BOOT_CONFIG"
append_once "hdmi_force_hotplug=1" "$BOOT_CONFIG"
append_once "hdmi_group=2" "$BOOT_CONFIG"
append_once "hdmi_mode=82   # 1080p @ 60Hz" "$BOOT_CONFIG"

# WiFi RegDomain
echo "==> WiFi-Land auf ${WIFI_COUNTRY} setzen"
iw reg set "${WIFI_COUNTRY}" || true
if command -v raspi-config >/dev/null 2>&1; then
  raspi-config nonint do_wifi_country "${WIFI_COUNTRY}" || true
fi

# -------- NetworkManager von wlan0 fernhalten --------
echo "==> NetworkManager: ${AP_IFACE} unmanaged"
mkdir -p /etc/NetworkManager/conf.d
cat >/etc/NetworkManager/conf.d/unmanaged-wlan0.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${AP_IFACE}
EOF
systemctl restart NetworkManager || true

# -------- Statische IP für wlan0 (ohne dhcpcd) --------
echo "==> ${AP_IFACE} statische IP per systemd setzen (${AP_IP}/24)"
cat >/etc/systemd/system/wlan0-static.service <<EOF
[Unit]
Description=Assign static IP to ${AP_IFACE} for AP
Before=hostapd.service dnsmasq-simple.service
After=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/ip addr flush dev ${AP_IFACE}
ExecStart=/usr/sbin/ip addr add ${AP_IP}/24 dev ${AP_IFACE}
ExecStart=/usr/sbin/ip link set ${AP_IFACE} up
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sysd_reload_enable_start wlan0-static.service

# -------- hostapd konfigurieren --------
echo "==> hostapd konfigurieren"
mkdir -p /etc/hostapd
cat >/etc/hostapd/hostapd.conf <<EOF
interface=${AP_IFACE}
driver=nl80211

ssid=${AP_SSID}
country_code=${WIFI_COUNTRY}
ieee80211d=1
hw_mode=g
channel=${AP_CHANNEL}
wmm_enabled=0

auth_algs=1
ignore_broadcast_ssid=0

wpa=2
wpa_passphrase=${AP_PSK}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
ieee80211n=1
EOF

systemctl unmask hostapd || true
sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
systemctl enable hostapd

# -------- dnsmasq als eigenes „dnsmasq-simple“-Service --------
echo "==> dnsmasq-simple Service einrichten"
systemctl disable --now dnsmasq 2>/dev/null || true

cat >/etc/dnsmasq.conf <<EOF
interface=${AP_IFACE}
except-interface=lo
no-dhcp-interface=lo
bind-interfaces
dhcp-range=${AP_DHCP_START},${AP_DHCP_END},${AP_NETMASK},${AP_LEASE_TIME}
EOF

cat >/etc/systemd/system/dnsmasq-simple.service <<'EOF'
[Unit]
Description=Simple dnsmasq for wlan0
After=network.target wlan0-static.service
Wants=wlan0-static.service

[Service]
ExecStart=/usr/sbin/dnsmasq -k --no-resolv --no-poll --conf-file=/etc/dnsmasq.conf --log-queries --log-dhcp
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sysd_reload_enable_start dnsmasq-simple.service

# -------- UFW (Firewall) --------
echo "==> UFW konfigurieren (SSH, App-Port, DHCP/DNS auf ${AP_IFACE})"
ufw allow ssh || true
ufw allow ${APP_PORT}/tcp || true
ufw allow in on ${AP_IFACE} to any port 67 proto udp || true
ufw allow in on ${AP_IFACE} to any port 53 || true
ufw --force enable || true

# -------- Dienste starten --------
echo "==> Dienste starten: wlan0-static -> dnsmasq-simple -> hostapd"
systemctl restart wlan0-static
systemctl restart dnsmasq-simple
systemctl restart hostapd

# -------- App vorbereiten --------
echo "==> App-Umgebung vorbereiten: ${APP_DIR}"
mkdir -p "$APP_DIR"
chown -R "${APP_USER}:${APP_USER}" "$APP_DIR"

if [[ ! -d "$APP_VENV" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_VENV"
fi

if [[ -f "$APP_DIR/requirements.txt" ]]; then
  sudo -u "$APP_USER" bash -lc "source '$APP_VENV/bin/activate' && pip install --upgrade pip && pip install -r '$APP_DIR/requirements.txt'"
else
  echo "Hinweis: Keine requirements.txt gefunden – pip install übersprungen."
fi

# -------- Flask systemd Service --------
echo "==> systemd Dienst: slidepi.service"
cat >/etc/systemd/system/slidepi.service <<EOF
[Unit]
Description=SlidePi Flask App
After=network-online.target
Wants=network-online.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_VENV}/bin/python main.py runserver --host=${APP_HOST} --port=${APP_PORT}
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sysd_reload_enable_start slidepi.service

# -------- Chromium-Policy: Übersetzen deaktivieren --------
echo "==> Chromium-Policy einrichten (Translate deaktivieren)"
mkdir -p /etc/chromium/policies/managed
tee /etc/chromium/policies/managed/slidepi.json >/dev/null <<'JSON'
{
  "TranslateEnabled": false,
  "EnableTranslateSubFrames": false,
  "PasswordManagerEnabled": false,
  "SpellcheckEnabled": false,
  "BrowserSignin": 0
}
JSON

# -------- Kiosk (Chromium) --------
echo "==> Kiosk-Modus einrichten"
CHROMIUM_BIN="$(detect_chromium_bin)"
[[ -n "$CHROMIUM_BIN" ]] || { echo "Chromium nicht gefunden (chromium/chromium-browser)"; exit 1; }

# XDG_RUNTIME_DIR bereitstellen (vermeidet dconf/DBus-Warnungen)
mkdir -p /run/user/1000
chown 1000:1000 /run/user/1000
chmod 700 /run/user/1000

cat >"$KIOSK_SCRIPT" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
LOG="__KIOSK_LOG__"
exec > >(awk '{ print strftime("[%F %T]"), $0; fflush() }' >> "$LOG") 2>&1

echo "=== KIOSK START ==="
export DISPLAY=:0
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/1000}

URL_DEFAULT="__KIOSK_URL__"
URL="${KIOSK_URL:-$URL_DEFAULT}"
DELAY_AFTER_OK="${DELAY_AFTER_OK:-3}"
MAX_WAIT="${MAX_WAIT:-60}"

# Maus ausblenden & Energiesparen aus
command -v unclutter >/dev/null && unclutter -idle 0.5 -root &
command -v xset >/dev/null && { xset s off; xset -dpms; xset s noblank; }

# Anzeigeausgang finden & aktivieren
if command -v xrandr >/dev/null; then
  echo "[kiosk] Monitore:"
  xrandr -q || true
  OUT=$(xrandr -q | awk '/ connected/{print $1}' | head -n1)
  [[ -z "$OUT" ]] && OUT="HDMI-2"
  echo "[kiosk] Aktiviere Ausgang: $OUT"
  xrandr --output "$OUT" --primary --auto || true
fi

# Auf App warten – 200 oder 302 akzeptieren, nach Timeout weiter
echo "[kiosk] Warte auf Flask @ $URL (200/302) ..."
i=0; last=000
while :; do
  code="$(curl -fsS -o /dev/null -w "%{http_code}" "$URL" || echo 000)"
  last="$code"
  [[ "$code" == "200" || "$code" == "302" ]] && { echo "[kiosk] Server ready (HTTP $code). Warte ${DELAY_AFTER_OK}s…"; sleep "$DELAY_AFTER_OK"; break; }
  i=$((i+1)); [[ $i -ge $MAX_WAIT ]] && { echo "[kiosk] WARN: Timeout nach ${MAX_WAIT}s (letzter Code: ${last})."; break; }
  sleep 1
done

# Fallback auf lokale Testseite, wenn App nicht bereit/404
if [[ "$last" == "404" || "$last" == "000" ]]; then
  TEST_HTML="/home/__APP_USER__/kiosk_test.html"
  if [[ ! -f "$TEST_HTML" ]]; then
    cat >"$TEST_HTML" <<'H'
<!doctype html><meta charset="utf-8">
<title>SlidePi Test</title>
<style>html,body{height:100%;margin:0}body{display:grid;place-items:center;background:#111;color:#0f0;font:700 40px system-ui}</style>
<div>✅ Kiosk sichtbar</div>
H
  fi
  echo "[kiosk] Fallback auf lokale Datei: $TEST_HTML"
  URL="file://$TEST_HTML"
fi

# Chromium finden
find_chromium(){ for b in chromium chromium-browser; do command -v "$b" >/dev/null 2>&1 && { echo "$b"; return; }; done; echo ""; }
CHROMIUM_BIN="$(find_chromium)"
[[ -z "$CHROMIUM_BIN" ]] && { echo "[kiosk] Chromium nicht gefunden"; exit 1; }

# stabile Flags (entfernt Leisten/Translate; robust auf Pi/Xorg)
CHROME_FLAGS=(
  --kiosk
  --incognito
  --no-first-run
  --no-default-browser-check
  --noerrdialogs
  --disable-infobars
  --disable-translate
  --disable-features=TranslateUI,Translate,PasswordManager,AutofillServerCommunication
  --disable-component-update
  --disable-extensions
  --password-store=basic
  --autoplay-policy=no-user-gesture-required
  --lang=de
  --accept-lang=de,de-DE
  --ozone-platform=x11
  --disable-gpu            # vermeidet GBM/ANGLE-Zicken
  --use-angle=gles         # Alternative: swiftshader
  --in-process-gpu
)

echo "[kiosk] Starte Chromium mit URL: $URL"
exec "$CHROMIUM_BIN" "${CHROME_FLAGS[@]}" "$URL"
EOS
sed -i "s|__KIOSK_URL__|${KIOSK_URL}|g" "$KIOSK_SCRIPT"
sed -i "s|__KIOSK_LOG__|${KIOSK_LOG}|g" "$KIOSK_SCRIPT"
sed -i "s|__APP_USER__|${APP_USER}|g" "$KIOSK_SCRIPT"
chmod +x "$KIOSK_SCRIPT"
chown "${APP_USER}:${APP_USER}" "$KIOSK_SCRIPT"
touch "$KIOSK_LOG" && chown "${APP_USER}:${APP_USER}" "$KIOSK_LOG"

# Openbox Autostart
sudo -u "$APP_USER" mkdir -p "$(dirname "$OPENBOX_AUTOSTART")"
cat >"$OPENBOX_AUTOSTART" <<EOF
# Openbox Autostart
${KIOSK_SCRIPT} &
EOF
chown -R "${APP_USER}:${APP_USER}" "/home/${APP_USER}/.config"

# Kiosk-Service (X + Openbox)
cat >/etc/systemd/system/kiosk.service <<EOF
[Unit]
Description=SlidePi Kiosk (X11 + Openbox + Chromium)
After=slidepi.service
Wants=slidepi.service

[Service]
User=${APP_USER}
Environment=XDG_RUNTIME_DIR=/run/user/1000
WorkingDirectory=/home/${APP_USER}
TTYPath=/dev/tty1
ExecStart=/usr/bin/startx /usr/bin/openbox-session --
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

# Optional: Drop-in zum einfachen Ändern der URL/Timeouts künftig
mkdir -p /etc/systemd/system/kiosk.service.d
cat >/etc/systemd/system/kiosk.service.d/override.conf <<EOF
[Service]
Environment=KIOSK_URL=${KIOSK_URL}
Environment=DELAY_AFTER_OK=3
Environment=MAX_WAIT=60
EOF

# Grafik-Target für Autostart des Kiosk
systemctl set-default graphical.target
sysd_reload_enable_start kiosk.service

# -------- Ausgabe --------
echo
echo "==================== FERTIG ===================="
echo "AP SSID:     ${AP_SSID}"
echo "AP Passwort: ${AP_PSK}"
echo "AP IFACE:    ${AP_IFACE}"
echo "AP IP:       ${AP_IP}  (Client-URL: http://${AP_IP}:${APP_PORT})"
echo
echo "Kiosk-URL:   ${KIOSK_URL}"
echo "Kiosk-Log:   ${KIOSK_LOG}"
echo
echo "Services:"
echo "  sudo systemctl status hostapd"
echo "  sudo systemctl status dnsmasq-simple"
echo "  sudo systemctl status wlan0-static"
echo "  sudo systemctl status slidepi"
echo "  sudo systemctl status kiosk"
echo "================================================"
