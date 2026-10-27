"""Kraj smjene — pitaj mehaničare koji još rade jesu li gotovi za danas.

Na kraju radnog vremena (pon–pet 15:00, subota 14:00; nedjeljom ništa) svakom
mehaničaru koji AKTIVNO radi (mjerač teče) pošalje se WhatsApp s linkom ?kraj=1
gdje bira: „Ostajem dulje" ili „Gotov za danas". Ako u `CEKANJE_MIN` minuta nema
odgovora → njegovi pokrenuti zadaci se automatski zatvore kao „Nije gotovo"
(pauza, čuvaju vrijeme).

SIGURNOST:
- cijela petlja radi SAMO ako je `kraj_smjene_on` upaljen (zadano isključeno);
- u test-modu (`dispecer_test_broj` postavljen) poruke idu na test broj, pa se
  auto-zatvaranje PRESKAČE (pravi rad se ne dira dok se testira).

Radi u pozadini (asyncio petlja), kao i podsjetnici.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .config import settings
from .database import SessionLocal
from .models import Korisnik, MehanicarLink, Zadatak
from .routers.dispecer import _red, posalji_poveznicu
from .routers.nalozi import _auto_status_naloga, _zatvori_kao_nije_gotovo
from .routers.plan import _gb, _hr_now

log = logging.getLogger("kraj_smjene")

_INTERVAL = 60          # provjera svake minute
CEKANJE_MIN = 15        # bez odgovora ovoliko min → auto "Nije gotovo"
_PROZOR_H = 2           # pitanje se inicira samo unutar ovoliko sati od kraja smjene
_PORUKA = "Kraj radnog vremena. Jesi gotov za danas ili ostaješ dulje? Otvori: {url}"


def _kraj_sat(hr: datetime) -> int | None:
    """Sat kraja smjene za dani HR datum: pon–pet 15, subota 14, nedjelja ništa."""
    wd = hr.weekday()        # 0=pon … 5=sub 6=ned
    if wd <= 4:
        return 15
    if wd == 5:
        return 14
    return None


def _aktivni_radnici(db) -> list[Korisnik]:
    """Mehaničari koji trenutno rade (barem jedan zadatak s pokrenutim mjeračem)."""
    zad = (db.query(Zadatak)
           .filter(Zadatak.zapoceto.isnot(None), Zadatak.gotovo.is_(False)).all())
    po_id: dict[int, Korisnik] = {}
    for z in zad:
        for r in z.radnici:
            po_id[r.id] = r
    return list(po_id.values())


def _tik(db) -> None:
    now = datetime.now(timezone.utc)
    hr = _hr_now()
    offset = hr - now.replace(tzinfo=None)   # HR = UTC + offset (naive delta)
    sat = _kraj_sat(hr)
    test_mod = bool((settings.dispecer_test_broj or "").strip())

    def pitano_danas(link: MehanicarLink) -> bool:
        if not link.smjena_pitano:
            return False
        p = link.smjena_pitano
        if p.tzinfo is None:
            p = p.replace(tzinfo=timezone.utc)
        return (p + offset).date() == hr.date()

    # 1) Inicijalno pitanje — unutar prozora [kraj, kraj+_PROZOR_H) i ako još radi.
    if sat is not None and sat <= hr.hour < sat + _PROZOR_H:
        for r in _aktivni_radnici(db):
            link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == r.id,
                                                  MehanicarLink.aktivan.is_(True)).first()
            if link and pitano_danas(link):
                continue
            # gb nije bitan za ovu poruku (poruka_override)
            rez = posalji_poveznicu(db, r, "", "", settings.javni_url,
                                    poruka_override=_PORUKA, link_suffix="?kraj=1")
            if rez.get("poslano"):
                link = db.query(MehanicarLink).filter(MehanicarLink.radnik_id == r.id).first()
                if link:
                    link.smjena_pitano = now
                    link.smjena_odgovor = None
                    db.commit()
                log.info("Kraj smjene: pitanje poslano za %s", r.ime)

    # 2) Auto-zatvaranje — pitan danas, bez odgovora, isteklo CEKANJE_MIN (ne u test-modu).
    if not test_mod:
        granica = now - timedelta(minutes=CEKANJE_MIN)
        linkovi = (db.query(MehanicarLink)
                   .filter(MehanicarLink.smjena_pitano.isnot(None),
                           MehanicarLink.smjena_odgovor.is_(None)).all())
        for link in linkovi:
            if not pitano_danas(link):
                continue
            p = link.smjena_pitano
            if p.tzinfo is None:
                p = p.replace(tzinfo=timezone.utc)
            if p > granica:
                continue  # još ima vremena za odgovor
            zatvoreno = 0
            for (_n, _op, z) in _red(db, link.radnik):
                if z.zapoceto or (z.utroseno_sek or 0) > 0:
                    _zatvori_kao_nije_gotovo(z)
                    _auto_status_naloga(db, z.operacija.nalog, link.radnik)
                    zatvoreno += 1
            link.smjena_odgovor = "auto"
            db.commit()
            if zatvoreno:
                log.info("Kraj smjene: auto 'Nije gotovo' za %s (%d zadataka)",
                         link.radnik.ime, zatvoreno)


async def petlja() -> None:
    log.info("Kraj-smjene nadzor pokrenut (interval %ss, čekanje %smin).", _INTERVAL, CEKANJE_MIN)
    while True:
        try:
            if settings.kraj_smjene_on:
                with SessionLocal() as db:
                    _tik(db)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # ne ruši petlju
            log.warning("Kraj-smjene tik iznimka: %s", e)
        await asyncio.sleep(_INTERVAL)
