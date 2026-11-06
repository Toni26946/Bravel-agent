"""Jutarnje auto-slanje plana — zakazano slanje poveznica mehaničarima.

Vlasnik navečer složi plan za sutra i uključi „auto-pošalji ujutro u HH:MM" (Plan →
prekidač). Ovdje pozadinska petlja svake minute provjeri je li došao taj termin i,
ako jest, okine isto što radi gumb „Pošalji sve naloge" (svakom prisutnom mehaničaru
njegov prvi zadatak). Jednokratno je: nakon slanja se sam ugasi (Postavka se očisti).

SIGURNOST:
- radi SAMO ako je dispečersko slanje upaljeno (`dispecer_wa_on`);
- PROPUŠTEN termin (npr. server bio ugašen, pa je dan prošao) se NE šalje naknadno —
  samo se očisti, da mehaničari ne dobiju stari plan satima kasnije;
- isti anti-duplikat i preskakanje odsutnih kao ručni gumb.
"""
import asyncio
import logging

from .config import settings
from .database import SessionLocal
from . import norme
from .models import Uloga
from .push import obavijesti_ulogu
from .routers.plan import (
    KLJUC_AUTO_DATUM, KLJUC_AUTO_HHMM,
    KLJUC_AUTO_PON_HHMM, KLJUC_AUTO_PON_ON, KLJUC_AUTO_PON_ZADNJE,
    _hr_now, posalji_sve_plan,
)

log = logging.getLogger("auto_slanje")
_INTERVAL = 60


def _ocisti(db) -> None:
    norme.set_postavka(db, KLJUC_AUTO_HHMM, None)
    norme.set_postavka(db, KLJUC_AUTO_DATUM, None)
    db.commit()


def _javi_voditelju(db, hhmm: str, rez: dict) -> None:
    try:
        obavijesti_ulogu(db, Uloga.voditelj, "Jutarnji plan poslan",
                         f"Auto-slanje u {hhmm}: poslano {rez.get('poslano')} mehaničarima.", url="/plan")
        db.commit()
    except Exception:  # noqa: BLE001 — obavijest nije kritična
        pass


def _tik_ponavlja(db) -> None:
    """Ponavljajuće jutarnje slanje: svaki radni dan (pon–sub) u zadani sat. Nedjelja se
    preskače. Šalje najviše jednom dnevno (anti-duplikat po datumu). Propušten prozor
    (server bio dolje > 2 h nakon termina) → ne šalje stari plan, samo označi dan."""
    if norme.get_postavka(db, KLJUC_AUTO_PON_ON) != "1":
        return
    hhmm = norme.get_postavka(db, KLJUC_AUTO_PON_HHMM) or "07:00"
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except (ValueError, TypeError):
        return
    now = _hr_now()
    if now.weekday() == 6:      # nedjelja — ne šalji
        return
    danas = now.date().isoformat()
    if norme.get_postavka(db, KLJUC_AUTO_PON_ZADNJE) == danas:
        return                   # danas već obrađeno
    cilj = hh * 60 + mm
    sad = now.hour * 60 + now.minute
    if sad < cilj:
        return                   # još nije vrijeme
    norme.set_postavka(db, KLJUC_AUTO_PON_ZADNJE, danas)  # označi odmah (anti-dup kod paralelnih startova)
    db.commit()
    if sad > cilj + 120:
        log.info("Auto-slanje (ponavlja): propušten termin %s (sad %02d:%02d) — ne šaljem stari plan.",
                 hhmm, now.hour, now.minute)
        return
    rez = posalji_sve_plan(db, settings.javni_url)
    log.info("Auto-slanje (ponavlja %s): poslano %s, već rade %s, već poslano %s, odsutni %s",
             hhmm, rez.get("poslano"), rez.get("vec_rade"), rez.get("vec_poslano"), rez.get("odsutni"))
    # Klik-bonus: zabilježi da je jutro odrađeno (očekivani dan za SVE prisutne, i bez novih poruka).
    try:
        from .routers import ucinak as _uc
        _uc.zabiljezi_jutro(db, now.date())
    except Exception:  # noqa: BLE001 — bilježenje nije kritično
        pass
    _javi_voditelju(db, hhmm, rez)


def _tik(db) -> None:
    _tik_ponavlja(db)
    hhmm = norme.get_postavka(db, KLJUC_AUTO_HHMM)
    datum = norme.get_postavka(db, KLJUC_AUTO_DATUM)
    if not (hhmm and datum):
        return
    try:
        hh, mm = (int(x) for x in hhmm.split(":"))
    except (ValueError, TypeError):
        _ocisti(db)
        return
    now = _hr_now()
    danas = now.date().isoformat()
    if datum < danas:
        # Propušten zakazani dan (server bio dolje / stari termin) → ne šalji naknadno.
        _ocisti(db)
        log.info("Auto-slanje: propušten termin %s %s — očišćeno bez slanja.", datum, hhmm)
        return
    if datum == danas and (now.hour, now.minute) >= (hh, mm):
        rez = posalji_sve_plan(db, settings.javni_url)
        _ocisti(db)
        log.info("Auto-slanje (%s): poslano %s, već rade %s, već poslano %s, odsutni %s",
                 hhmm, rez.get("poslano"), rez.get("vec_rade"), rez.get("vec_poslano"), rez.get("odsutni"))
        _javi_voditelju(db, hhmm, rez)


async def petlja() -> None:
    log.info("Auto-slanje nadzor pokrenut (interval %ss).", _INTERVAL)
    while True:
        try:
            if settings.dispecer_wa_on:
                with SessionLocal() as db:
                    _tik(db)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # ne ruši petlju
            log.warning("Auto-slanje tik iznimka: %s", e)
        await asyncio.sleep(_INTERVAL)
