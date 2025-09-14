#!/usr/bin/env bash
set -euo pipefail

# ====== EINSTELLUNGEN ======
WLAN_IF="wlan0"
AP_SSID="SlidePi"
AP_PSK="slidepi1234"        # min. 8 Zeichen
COUNTRY_CODE="DE"
CHANNEL="6"                 # 1,6,11 sind üblich im 2.4GHz-Band
AP_IP="10.0.0.1"
SUBNET_CIDR="255.255.255.0"
DHCP_START="10.0.0.10"
DHCP_END="10.0.0.100"
DHCP_LEASE="12h"
LOCAL_DOMAIN="slidepi.lan"  # optionaler lokaler DNS-Name

# ====== PRÜFUNGEN ======
if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte als root ausführen: sudo $0"
  exit 1
fi

# ====== PAKETE ======
echo "[*] Installiere Pakete hostapd & dnsmasq …"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y hostapd dnsmasq
systemctl stop hostapd || true
systemctl stop dnsmasq || true

# ====== DHCPCD: statische IP auf wlan0 ======
echo "[*] Konfiguriere statische IP für ${WLAN_IF} via dhcpcd …"
DHCPCD_CONF="/etc/dhcpcd.conf"
if ! grep -q "# SlidePi AP BEGIN" "$DHCPCD_CONF"; then
  cat <<EOF >>"$DHCPCD_CONF"

# SlidePi AP BEGIN
interface ${WLAN_IF}
static ip_address=${AP_IP}/24
nohook wpa_supplicant
# SlidePi AP END
EOF
fi
systemctl restart dhcpcd

# ====== dnsmasq: DHCP/DNS nur für AP-Netz ======
echo "[*] Schreibe dnsmasq-Konfiguration …"
DNSMASQ_CONF_DIR="/etc/dnsmasq.d"
mkdir -p "$DNSMASQ_CONF_DIR"
SLIDEPI_DNSMASQ_CONF="${DNSMASQ_CONF_DIR}/slidepi.conf"
cat > "$SLIDEPI_DNSMASQ_CONF" <<EOF
# SlidePi - dnsmasq ohne Captive-Portal
interface=${WLAN_IF}
bind-interfaces
domain=${LOCAL_DOMAIN}
dhcp-range=${DHCP_START},${DHCP_END},${DHCP_LEASE}
# Pi selbst auf Hostnamen 'slidepi' auflösbar machen (optional)
address=/slidepi/${AP_IP}
# keine Upstream-DNS-Server erzwingen; Clients bleiben offline ok
# (wer mag, kann hier z.B. server=1.1.1.1 setzen)
EOF

# ====== hostapd: WLAN-AP ohne Captive ======
echo "[*] Schreibe hostapd-Konfiguration …"
HOSTAPD_CONF="/etc/hostapd/hostapd.conf"
cat > "$HOSTAPD_CONF" <<EOF
# SlidePi - hostapd
country_code=${COUNTRY_CODE}
interface=${WLAN_IF}
ssid=${AP_SSID}
hw_mode=g       # 2.4GHz
channel=${CHANNEL}
ieee80211n=1
wmm_enabled=1

auth_algs=1
wpa=2           # WPA2-PSK
wpa_passphrase=${AP_PSK}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP

# KEIN Captive-Portal, KEIN Hotspot-Redirect
EOF

# hostapd default-Datei auf unser conf zeigen
if grep -q '^#DAEMON_CONF' /etc/default/hostapd 2>/dev/null; then
  sed -i 's|^#DAEMON_CONF.*|DAEMON_CONF="/etc/hostapd/hostapd.conf.j2"|' /etc/default/hostapd
elif grep -q '^DAEMON_CONF' /etc/default/hostapd 2>/dev/null; then
  sed -i 's|^DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf.j2"|' /etc/default/hostapd
else
  echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf.j2"' >> /etc/default/hostapd
fi

# ====== Services aktivieren ======
echo "[*] Aktiviere & starte Dienste …"
systemctl unmask hostapd || true
systemctl enable hostapd
systemctl enable dnsmasq
systemctl restart dnsmasq
systemctl restart hostapd

# ====== Info ======
echo
echo "==============================================="
echo " SlidePi AP ist aktiv:"
echo "  SSID:        ${AP_SSID}"
echo "  Passwort:    ${AP_PSK}"
echo "  IP (Pi):     ${AP_IP}"
echo "  Aufruf:      http://${AP_IP}"
echo "==============================================="
echo "Hinweis: Einige Geräte melden 'Kein Internet' – das ist OK."
echo "Öffne den Browser manuell und rufe die IP auf."
