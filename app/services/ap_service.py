# app/services/ap_service.py
import os
import subprocess
import tempfile
from pathlib import Path

# WICHTIG: Ziel ist die echte hostapd.conf, NICHT die .j2-Vorlage
HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
DNSMASQ_CONF = "/etc/dnsmasq.d/slidepi.conf"
DHCPCD_CONF_APPEND = "/etc/dhcpcd.conf"
WLAN_IFACE = "wlan0"

DEFAULTS = {
    "ap_ssid": "SlidePi",
    "ap_password": "slidepi1234",   # min. 8 Zeichen für WPA2
    "ap_country": "DE",
    "ap_channel": "6",
    "ap_subnet": "10.10.0.1",       # statische IP des Pi auf wlan0
    "ap_range_start": "10.10.0.50", # DHCP-Range
    "ap_range_end": "10.10.0.150",
}

class APService:
    def __init__(self, settings_get, settings_set, template_dir="deploy"):
        self.get_setting = settings_get
        self.set_setting = settings_set
        self.template_dir = Path(template_dir)

    def _val(self, key):
        return (self.get_setting(key) or DEFAULTS[key]).strip()

    def ensure_defaults(self):
        for k, v in DEFAULTS.items():
            if not self.get_setting(k):
                self.set_setting(k, v)

    def render_and_apply(self):
        """
        Rendert hostapd/dnsmasq/dhcpcd aus Templates + Settings
        und startet/reloadet die Dienste. Benötigt sudo-Rechte.
        """
        self.ensure_defaults()
        ctx = {k: self._val(k) for k in DEFAULTS.keys()}

        # Templates: genau EINE .j2-Endung
        hostapd_tpl_path = self.template_dir / "hostapd" / "hostapd.conf.j2"
        dnsmasq_tpl_path = self.template_dir / "dnsmasq" / "dnsmasq.conf.j2"
        dhcpcd_append_path = self.template_dir / "dhcpcd" / "dhcpcd.conf.append"

        hostapd_tpl = hostapd_tpl_path.read_text(encoding="utf-8")
        dnsmasq_tpl = dnsmasq_tpl_path.read_text(encoding="utf-8")
        dhcpcd_append = dhcpcd_append_path.read_text(encoding="utf-8")

        # Platzhalter mit {ap_ssid} etc. via .format()
        hostapd_conf = hostapd_tpl.format(**ctx)
        dnsmasq_conf = dnsmasq_tpl.format(**ctx)

        # Dateien atomar schreiben
        self._atomic_write(HOSTAPD_CONF, hostapd_conf, mode=0o644)
        self._atomic_write(DNSMASQ_CONF, dnsmasq_conf, mode=0o644)
        self._append_once(DHCPCD_CONF_APPEND, dhcpcd_append.strip())

        # wlan0 konfigurieren (down/up erzwingt IP-Neusetzungen)
        self._run(["sudo", "systemctl", "stop", "hostapd"])
        self._run(["sudo", "systemctl", "restart", "dnsmasq"])
        self._run(["sudo", "ip", "link", "set", WLAN_IFACE, "down"])
        self._run(["sudo", "ip", "addr", "flush", "dev", WLAN_IFACE])
        self._run(["sudo", "ip", "addr", "add", f"{ctx['ap_subnet']}/24", "dev", WLAN_IFACE])
        self._run(["sudo", "ip", "link", "set", WLAN_IFACE, "up"])
        self._run(["sudo", "systemctl", "start", "hostapd"])
        return True

    def _atomic_write(self, path, content, mode=0o644):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as tmp:
            tmp.write(content)
            tmppath = tmp.name
        os.chmod(tmppath, mode)
        os.replace(tmppath, path)

    def _append_once(self, file_path, block):
        # hängt Block ans Ende, wenn er noch nicht enthalten ist (idempotent)
        p = Path(file_path)
        text = ""
        if p.exists():
            text = p.read_text(encoding="utf-8")
            if block in text:
                return
        with p.open("a", encoding="utf-8") as f:
            if not text.endswith("\n"):
                f.write("\n")
            f.write("\n# --- slidepi AP config ---\n")
            f.write(block)
            f.write("\n")

    def _run(self, cmd):
        subprocess.run(cmd, check=True)
