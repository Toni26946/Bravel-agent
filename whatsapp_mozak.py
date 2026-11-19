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


def _tekst_i_slika(msg):
    """(tekst, media_id) — tekst poruke, ili slika (s opisom ili bez). Mozak sam odluči:
    slike od NEPOZNATIH brojeva vrati (preuzeto=False) pa idu kao i dosad."""
    tip = msg.get("type")
    if tip == "text":
        return ((msg.get("text") or {}).get("body") or "").strip(), None
    if tip in ("image", "document", "video"):
        m = msg.get(tip) or {}
        if tip == "document" and not str(m.get("mime_type") or "").startswith(("image/", "video/")):
            return "", None
        if m.get("id"):
            return (m.get("caption") or "").strip(), m["id"]
    return "", None


def _je_video(msg):
    """Video poruka (ili dokument s video/* tipom) – Toni 19.11.2026.: tatin video se izgubio."""
    tip = msg.get("type")
    return tip == "video" or (tip == "document" and
                              str((msg.get("document") or {}).get("mime_type") or "").startswith("video/"))


def _posalji_sliku(zid, media_id):
    """Skini sliku s WhatsAppa i priloži je zadatku u mozgu (best-effort)."""
    try:
        import whatsapp
        sadrzaj, mime = whatsapp.download_media(media_id)
        url = _URL.rstrip("/") + f"/slika/{zid}"
        # video: mozak ga spremi i izvuče sličice (traje dulje od slike)
        requests.post(url, timeout=120 if mime.startswith("video/") else 40,
                      headers={"X-Mozak-WA": kljuc(), "Content-Type": mime},
                      data=sadrzaj)
    except Exception:
        pass


def ponudi(frm, ime, msg):
    """Ponudi poruku (tekst, ili sliku s opisom) mozgu. Vrati True ako ju je mozak preuzeo
    (tada je odgovor već poslan). Bilo kakva greška → False (bot nastavlja kao prije)."""
    if not ukljuceno():
        return False
    tekst, media_id = _tekst_i_slika(msg)
    if not tekst and not media_id:
        return False
    try:
        r = requests.post(_URL, timeout=25, headers={"X-Mozak-WA": kljuc()},
                          json={"od": frm, "ime": ime, "tekst": tekst, "id": msg.get("id") or "",
                                "slika": bool(media_id), "video": bool(media_id) and _je_video(msg)})
        if r.status_code != 200:
            return False
        rez = r.json()
    except Exception:
        return False
    if not rez.get("preuzeto"):
        return False
    _zapamti(frm)
    if media_id and rez.get("zadatak"):
        _posalji_sliku(rez["zadatak"], media_id)
    odgovor = (rez.get("odgovor") or "").strip()
    if odgovor:
        try:
            import whatsapp
            whatsapp.send_text(_norm(frm), odgovor)
        except Exception:
            pass
    return True
