# app/routes/admin_network.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.services.ap_service import APService

bp = Blueprint("admin_network", __name__, url_prefix="/admin/network")

def _get_setting(key):
    from app.services.settings_service import get_setting
    return get_setting(key)

def _set_setting(key, value):
    from app.services.settings_service import set_setting
    return set_setting(key, value)

@bp.route("/", methods=["GET", "POST"])
def network_settings():
    svc = APService(_get_setting, _set_setting)

    if request.method == "POST":
        # Rohwerte
        ap_ssid   = (request.form.get("ap_ssid") or "").strip()
        ap_pass   = (request.form.get("ap_password") or "").strip()
        ap_country= (request.form.get("ap_country") or "").strip().upper()
        ap_channel= (request.form.get("ap_channel") or "").strip()
        ap_subnet = (request.form.get("ap_subnet") or "").strip()
        r_start   = (request.form.get("ap_range_start") or "").strip()
        r_end     = (request.form.get("ap_range_end") or "").strip()

        # Mini-Validierung
        if len(ap_pass) < 8:
            flash("Passwort muss mindestens 8 Zeichen haben.", "danger")
            return redirect(url_for("admin_network.network_settings"))

        # Channel in 1..13 erzwingen (EU)
        try:
            ch = int(ap_channel)
            if not (1 <= ch <= 13):
                raise ValueError
            ap_channel = str(ch)
        except Exception:
            ap_channel = "6"
            flash("Ungültiger Kanal – auf 6 zurückgesetzt.", "warning")

        # Settings schreiben
        for k, v in [
            ("ap_ssid", ap_ssid),
            ("ap_password", ap_pass),
            ("ap_country", ap_country or "DE"),
            ("ap_channel", ap_channel),
            ("ap_subnet", ap_subnet or "10.10.0.1"),
            ("ap_range_start", r_start or "10.10.0.50"),
            ("ap_range_end", r_end or "10.10.0.150"),
        ]:
            if v:
                _set_setting(k, v)

        # Anwenden
        try:
            svc.render_and_apply()
            flash("AP-Konfiguration angewendet.", "success")
        except Exception as e:
            flash(f"Fehler beim Anwenden: {e}", "danger")

        return redirect(url_for("admin_network.network_settings"))

    # GET
    ctx = {k: _get_setting(k) for k in [
        "ap_ssid","ap_password","ap_country","ap_channel","ap_subnet","ap_range_start","ap_range_end"
    ]}
    return render_template("admin_network.html", **ctx)
