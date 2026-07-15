# ============================================================
#  whatsapp_racuni.py — Faza 1: obrada RAČUNA/PRIMKI na WhatsApp
#
#  Ovlašteni zaposlenik (broj u WHATSAPP_ALLOWED) pošalje FOTOGRAFIJU računa
#  ili primke na WhatsApp poslovni broj. Tok:
#    slika → Claude vision (racuni._read_document) → pitaj GB → potvrda
#    (gumbi) → upis na SharePoint (racuni._write_once) → poruka natrag.
#
#  Ponovno koristi ČISTU jezgru iz racuni.py (vision + build_rows + upis +
#  upload slike + summary). Vlastito stanje sesije (po broju telefona) i
#  vlastiti WhatsApp I/O — Telegram tok ostaje netaknut.
#
#  Ograničenje: sve poruke idu unutar 24 h prozora (zaposlenik piše prvi),
#  pa NE treba predložak.
# ============================================================

import os
import time
import threading

import racuni
import whatsapp
import monitoring

_sessions = {}          # broj → sess (racuni-kompatibilan dict)
_lock = threading.RLock()

# Potvrde: id gumba / prihvatljivi tekst
_DA = {"wa_ok", "upiši", "upisi", "da", "ok", "potvrdi", "✅"}
_NE = {"wa_no", "odbaci", "ne", "poništi", "ponisti", "❌"}


def _log(msg):
    print(f"[wa_racuni] {msg}", flush=True)


def allowed_set():
    """Skup ovlaštenih brojeva iz WHATSAPP_ALLOWED (zarez/točka-zarez)."""
    raw = os.getenv("WHATSAPP_ALLOWED", "")
    return {b.strip() for b in raw.replace(";", ",").split(",") if b.strip()}


def is_allowed(frm):
    return frm in allowed_set()


def handle(frm, ime, msg):
    """Ulazna WhatsApp poruka ovlaštenog zaposlenika (msg = raw message dict)."""
    try:
        _handle(frm, ime, msg)
    except Exception as e:
        _log(f"GREŠKA: {e}")
        monitoring.error("WhatsApp računi: greška u obradi", source="wa_racuni", exc=e)
        try:
            whatsapp.send_text(frm, "❌ Došlo je do greške pri obradi. Pošalji ponovno.")
        except Exception:
            pass


def _handle(frm, ime, msg):
    tip = msg.get("type")

    # 1) SLIKA / DOKUMENT → novi dokument
    media_id = None
    if tip == "image":
        media_id = (msg.get("image") or {}).get("id")
    elif tip == "document":
        media_id = (msg.get("document") or {}).get("id")
    if media_id:
        _pokreni_dokument(frm, ime, media_id)
        return

    # 2) INTERAKTIVNI ODGOVOR (gumb)
    if tip == "interactive":
        inter = msg.get("interactive") or {}
        bid = ((inter.get("button_reply") or {}).get("id")
               or (inter.get("list_reply") or {}).get("id") or "")
        _odgovor(frm, bid)
        return

    # 3) TEKST
    if tip == "text":
        _odgovor(frm, (msg.get("text") or {}).get("body", "").strip())
        return

    # ostali tipovi (audio, lokacija…) — kratka uputa
    whatsapp.send_text(frm, "Pošalji fotografiju računa ili primke pa te vodim dalje.")


def _pokreni_dokument(frm, ime, media_id):
    whatsapp.send_text(frm, "🔎 Čitam dokument…")
    b, mime = whatsapp.download_media(media_id)
    data = racuni._read_document([(b, mime)])
    spec = racuni._spec_for(data.get("vrsta"))
    sess = {
        "token": 0, "chat_id": frm, "user_id": frm, "who": ime or frm,
        "data": data, "images": [(b, mime)], "spec": spec, "vrsta": spec.vrsta,
        "gb": None, "vozac": None, "zaprimio": None, "stage": "need_gb",
        "edit_key": None,
    }
    if spec.vrsta == "primka":
        sess["zaprimio"] = ime or frm
        pitanje = "Za koje vozilo (GB)? (napiši „-” ako nije za konkretno vozilo)"
    else:
        sess["vozac"] = ime or frm
        pitanje = "Koje vozilo (GB)? Napiši oznaku, npr. GB123-AB."
    with _lock:
        _sessions[frm] = sess
    whatsapp.send_text(frm, f"{spec.emoji} Prepoznato: {spec.naziv}.\n{pitanje}")


def _odgovor(frm, tekst):
    with _lock:
        sess = _sessions.get(frm)
    if not sess:
        whatsapp.send_text(frm, "Pošalji fotografiju računa ili primke pa te vodim dalje.")
        return

    stage = sess.get("stage")
    low = (tekst or "").strip().lower()

    if stage == "need_gb":
        gb = (tekst or "").strip()
        sess["gb"] = None if gb in ("-", "") else gb
        sess["stage"] = "confirm"
        with _lock:
            _sessions[frm] = sess
        whatsapp.send_text(frm, racuni._summary_text(sess))
        whatsapp.send_buttons(frm, "Upisati u SharePoint?",
                              [("wa_ok", "✅ Upiši"), ("wa_no", "❌ Odbaci")])
        return

    if stage == "confirm":
        if low in _DA:
            whatsapp.send_text(frm, "💾 Upisujem…")
            poruka = _upisi(sess)
            with _lock:
                _sessions.pop(frm, None)
            whatsapp.send_text(frm, poruka)
            return
        if low in _NE:
            with _lock:
                _sessions.pop(frm, None)
            whatsapp.send_text(frm, "❌ Odbačeno. Pošalji novu fotografiju kad želiš.")
            return
        # nejasan odgovor u fazi potvrde
        whatsapp.send_buttons(frm, "Odaberi:",
                              [("wa_ok", "✅ Upiši"), ("wa_no", "❌ Odbaci")])
        return


def _upisi(sess):
    """Upis uz par pokušaja ako je Excel zaključan (isti _Locked kao Telegram)."""
    # Slika se MORA uploadati PRIJE _write_once — ona postavlja sess['slika_url']
    # koju _build_rows/_slika_cell ugrađuju u redak (kolona 'Slika'). Bez ovog
    # koraka redak se upiše bez linka slike.
    try:
        racuni._prepare_image(sess)
    except Exception as e:
        monitoring.warning(f"WhatsApp računi: priprema slike pala: {e}", source="wa_racuni")

    for pokusaj in range(4):
        try:
            ok, poruka = racuni._write_once(sess)
            return poruka + (sess.get("slika_note") or "")
        except racuni._Locked:
            time.sleep(2 * (pokusaj + 1))
        except Exception as e:
            monitoring.error("WhatsApp računi: upis pao", source="wa_racuni", exc=e)
            return "❌ Neočekivana greška pri upisu."
    return "⚠️ Datoteka je trenutno zauzeta (netko je uređuje). Pokušaj za koju minutu."
