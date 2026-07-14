# ============================================================
#  whatsapp.py — WhatsApp Cloud API (Meta Graph) integracija
#
#  Tajne (fly secrets, SAMO nazivi — vrijednosti nikad u repo/chat):
#    WHATSAPP_TOKEN     — System User token (Bearer)
#    WHATSAPP_PHONE_ID  — Phone number ID (npr. 1270404739480944)
#    WHATSAPP_GRAPH_VERSION — opcionalno, default "v21.0"
#
#  Funkcije:
#    register(pin)                 -> registracija broja na Cloud API
#    send_text(to, text)           -> obična poruka (unutar 24 h prozora)
#    send_template(to, name, ...)  -> predložak (za prvi kontakt / izvan 24 h)
#
#  Sve vraćaju dict {ok, status, data} pa pozivatelj vidi TOČAN odgovor Mete
#  (uključujući poruku greške), bez bacanja iznimke na HTTP grešci.
# ============================================================

import os

import requests

import monitoring

GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v21.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
TIMEOUT = 25  # sekundi


class WhatsAppError(Exception):
    """Konfiguracijska greška (tajna nije postavljena i sl.)."""


def _token():
    t = os.getenv("WHATSAPP_TOKEN", "").strip()
    if not t:
        raise WhatsAppError("WHATSAPP_TOKEN nije postavljen (fly secrets).")
    return t


def _phone_id():
    p = os.getenv("WHATSAPP_PHONE_ID", "").strip()
    if not p:
        raise WhatsAppError("WHATSAPP_PHONE_ID nije postavljen (fly secrets).")
    return p


def _headers():
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def is_configured():
    """Ima li smisla uopće pokušavati (oba secreta postavljena)."""
    return bool(os.getenv("WHATSAPP_TOKEN", "").strip()
                and os.getenv("WHATSAPP_PHONE_ID", "").strip())


def _post(path, payload):
    """POST na Graph; vrati (status_code, dict). Ne baca na HTTP grešci —
    tijelo greške je dio odgovora koji zovemo želi vidjeti."""
    url = f"{GRAPH_BASE}/{path}"
    r = requests.post(url, headers=_headers(), json=payload, timeout=TIMEOUT)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text}
    return r.status_code, data


def register(pin):
    """Registriraj broj na Cloud API (postavlja i dvokoračni PIN ako ga nema).
    Vrati {ok, status, data}. Meta na uspjeh vraća {"success": true}."""
    pin = str(pin).strip()
    status, data = _post(
        f"{_phone_id()}/register",
        {"messaging_product": "whatsapp", "pin": pin},
    )
    ok = status == 200 and isinstance(data, dict) and data.get("success") is True
    if not ok:
        monitoring.warning(f"WhatsApp register nije uspio: HTTP {status} {data}",
                           source="whatsapp")
    return {"ok": ok, "status": status, "data": data}


def send_template(to, name, lang_code="en_US", components=None):
    """Pošalji predložak (jedini dopušten za prvi kontakt / izvan 24 h prozora).
    `components` (opcionalno) = lista Graph 'components' za varijable predloška."""
    tmpl = {"name": name, "language": {"code": lang_code}}
    if components:
        tmpl["components"] = components
    status, data = _post(
        f"{_phone_id()}/messages",
        {"messaging_product": "whatsapp", "to": str(to), "type": "template", "template": tmpl},
    )
    ok = status == 200 and isinstance(data, dict) and "messages" in data
    if not ok:
        monitoring.warning(f"WhatsApp send_template nije uspio: HTTP {status} {data}",
                           source="whatsapp")
    return {"ok": ok, "status": status, "data": data}


def send_text(to, text):
    """Pošalji običnu tekstualnu poruku. RADI SAMO unutar 24 h otkako je
    korisnik zadnji pisao; inače Meta vrati grešku (tad ide send_template)."""
    status, data = _post(
        f"{_phone_id()}/messages",
        {"messaging_product": "whatsapp", "to": str(to), "type": "text",
         "text": {"body": text}},
    )
    ok = status == 200 and isinstance(data, dict) and "messages" in data
    if not ok:
        monitoring.warning(f"WhatsApp send_text nije uspio: HTTP {status} {data}",
                           source="whatsapp")
    return {"ok": ok, "status": status, "data": data}


def opisi_gresku(res):
    """Pretvori {ok,status,data} u čitljiv sažetak (za Telegram/log)."""
    d = res.get("data") if isinstance(res, dict) else None
    err = d.get("error", {}) if isinstance(d, dict) else {}
    if not isinstance(err, dict):
        err = {}
    dijelovi = [f"HTTP {res.get('status')}"]
    if err.get("message"):
        dijelovi.append(f"poruka: {err['message']}")
    if err.get("code") is not None:
        sub = err.get("error_subcode")
        dijelovi.append(f"kod: {err['code']}" + (f"/{sub}" if sub else ""))
    ed = err.get("error_data")
    if isinstance(ed, dict) and ed.get("details"):
        dijelovi.append(f"detalji: {ed['details']}")
    return " · ".join(dijelovi)
