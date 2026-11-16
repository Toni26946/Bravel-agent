# ===================================================================
#  WHATSAPP → MOZAK: prijave kvarova / izmjena aplikacija (16.11.2026.)
#
#  Tonijevi ljudi (popis brojeva vodi MOZAK na moj-mozak.fly.dev/whatsapp)
#  pišu na Bravelov WhatsApp kad nešto ne radi u aplikacijama. Bot svaku
#  TEKSTUALNU dolaznu poruku prvo ponudi mozgu:
#    POST {MOZAK_WA_URL}  (X-Mozak-WA = MOZAK_WA_KLJUC)  {od, ime, tekst, id}
#    ← {"preuzeto": bool, "odgovor": str|None}
#  preuzeto=True  → mozak je to uzeo (zadatak agentu / čeka Tonija); bot pošalje
#                   „odgovor" pošiljatelju i NE nastavlja svojim tokom.
#  preuzeto=False → bot radi kao i dosad (računi, obavijest vlasnicima).
#
#  Kad agent popravi, mozak javi pošiljatelju preko POST /api/whatsapp/posalji
#  (web_api.py) — dopušteno SAMO brojevima koje je mozak preuzeo u zadnjih
#  7 dana (zapis u /data/wa_mozak.json), pa ključ ne može slati drugima.
#  Bez MOZAK_WA_KLJUC je sve isključeno (bot radi točno kao prije).
# ===================================================================
import json
import os
import threading
import time

import requests

_URL = os.getenv("MOZAK_WA_URL", "https://moj-mozak.fly.dev/api/whatsapp/bravel").strip()
_TRAJANJE = 7 * 86400
_DATOTEKA = "/data/wa_mozak.json" if os.path.isdir("/data") else "wa_mozak.json"
_lock = threading.Lock()


def kljuc():
    return os.getenv("MOZAK_WA_KLJUC", "").strip()


def ukljuceno():
    return bool(kljuc())


def _norm(broj):
    d = "".join(c for c in str(broj or "") if c.isdigit())
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("0"):
        d = "385" + d[1:]
    return d


def _ucitaj():
    try:
        with open(_DATOTEKA, encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _zapamti(broj):
    """Mozak je preuzeo poruku s ovog broja → smije mu odgovoriti idućih 7 dana."""
    with _lock:
        d = _ucitaj()
        sad = time.time()
        d = {b: t for b, t in d.items() if sad - t < _TRAJANJE}
        d[_norm(broj)] = sad
        try:
            with open(_DATOTEKA, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except Exception:
            pass


def dozvoljen(broj):
    """Smije li mozak (i globalno ugašeno slanje) poslati poruku ovom broju."""
    if not ukljuceno():
        return False
    t = _ucitaj().get(_norm(broj))
    return bool(t) and time.time() - t < _TRAJANJE


def ponudi(frm, ime, msg):
    """Ponudi tekstualnu poruku mozgu. Vrati True ako ju je mozak preuzeo
    (tada je odgovor već poslan). Bilo kakva greška → False (bot nastavlja kao prije)."""
    if not ukljuceno() or msg.get("type") != "text":
        return False
    tekst = ((msg.get("text") or {}).get("body") or "").strip()
    if not tekst:
        return False
    try:
        r = requests.post(_URL, timeout=25, headers={"X-Mozak-WA": kljuc()},
                          json={"od": frm, "ime": ime, "tekst": tekst, "id": msg.get("id") or ""})
        if r.status_code != 200:
            return False
        rez = r.json()
    except Exception:
        return False
    if not rez.get("preuzeto"):
        return False
    _zapamti(frm)
    odgovor = (rez.get("odgovor") or "").strip()
    if odgovor:
        try:
            import whatsapp
            whatsapp.send_text(_norm(frm), odgovor)
        except Exception:
            pass
    return True
