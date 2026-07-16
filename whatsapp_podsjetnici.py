# ============================================================
#  whatsapp_podsjetnici.py — automatski tjedni podsjetnici vozačima
#
#  Bot proaktivno (izvan 24 h prozora) šalje odobreni predložak podsjetnik_racun
#  vozačima iz WHATSAPP_DRIVERS koji zadnjih N dana NISU ništa poslali. Aktivne
#  (koji su nedavno slali) preskače — da ne gnjavi i da ne troši.
#
#  Sigurnosni prekidač: WHATSAPP_PODSJETNICI_ON=1 (default isključeno). Ručno
#  okidanje (force=True) radi i dok je isključeno — za test s /wa_podsjetnici.
#
#  Env:
#    WHATSAPP_PODSJETNICI_ON     "1" = uključeno (inače se raspored ne okida)
#    WHATSAPP_PODSJETNIK_DANI    prag: preskoči ako je slao unutar toliko dana (5)
#    WHATSAPP_PODSJETNIK_PERIOD  tekst {{2}} u predlošku ("ovaj tjedan")
#    WHATSAPP_PODSJETNIK_TMPL    naziv predloška ("podsjetnik_racun")
#  Raspored (kad ga main.py okida) je u main.py: WHATSAPP_PODSJETNIK_DAN/SAT/MIN.
# ============================================================

import os

import whatsapp
import whatsapp_racuni
import monitoring


def _body(*vals):
    """Graph 'components' za body varijable predloška, redom {{1}}, {{2}}…"""
    return [{"type": "body",
             "parameters": [{"type": "text", "text": str(v)} for v in vals]}]


def posalji_tjedne(force=False):
    """Pošalji tjedni podsjetnik vozačima koji nisu nedavno slali. Vrati sažetak
    (string) za Telegram. Ne baca — greške po vozaču se skupe u sažetak."""
    if not whatsapp.is_configured():
        return "⚠️ WhatsApp nije konfiguriran (token/broj) — podsjetnici preskočeni."

    ukljuceno = os.getenv("WHATSAPP_PODSJETNICI_ON", "").strip() == "1"
    if not ukljuceno and not force:
        return "ℹ️ Tjedni podsjetnici su ISKLJUČENI (WHATSAPP_PODSJETNICI_ON≠1)."

    drivers = whatsapp_racuni._drivers_map()
    if not drivers:
        return "⚠️ Nema vozača u WHATSAPP_DRIVERS — nema kome slati podsjetnik."

    try:
        prag = float(os.getenv("WHATSAPP_PODSJETNIK_DANI", "5"))
    except ValueError:
        prag = 5.0
    period = os.getenv("WHATSAPP_PODSJETNIK_PERIOD", "ovaj tjedan")
    tmpl = os.getenv("WHATSAPP_PODSJETNIK_TMPL", "podsjetnik_racun")

    poslano, preskoceno, greske = [], [], []
    for broj, (ime, _gb) in drivers.items():
        ime = ime or "vozaču"
        d = whatsapp_racuni.dani_od_zadnje(broj)
        if d is not None and d < prag:
            preskoceno.append(f"{ime} ({d:.0f}d)")
            continue
        res = whatsapp.send_template(broj, tmpl, "hr", components=_body(ime, period))
        if res.get("ok"):
            poslano.append(ime)
        else:
            greske.append(f"{ime}: {whatsapp.opisi_gresku(res)}")

    if greske:
        monitoring.warning(f"WhatsApp podsjetnici: {len(greske)} grešaka pri slanju",
                           source="wa_podsjetnici")

    dijelovi = [f"📣 Tjedni podsjetnici ({tmpl})",
                f"✅ Poslano ({len(poslano)}): " + (", ".join(poslano) or "—"),
                f"⏭️ Preskočeno – nedavno slali ({len(preskoceno)}): "
                + (", ".join(preskoceno) or "—")]
    if greske:
        dijelovi.append(f"❌ Greške ({len(greske)}):\n" + "\n".join(greske))
    return "\n".join(dijelovi)
