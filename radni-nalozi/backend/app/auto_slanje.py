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
from .routers.plan import KLJUC_AUTO_DATUM, KLJUC_AUTO_HHMM, _hr_now, posalji_sve_plan

log = logging.getLogger("auto_slanje")
_INTERVAL = 60


def _ocisti(db) -> None:
    norme.set_postavka(db, KLJUC_AUTO_HHMM, None)
    norme.set_postavka(db, KLJUC_AUTO_DATUM, None)
    db.commit()


def _tik(db) -> None:
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
        try:
            obavijesti_ulogu(db, Uloga.voditelj, "Jutarnji plan poslan",
                             f"Auto-slanje u {hhmm}: poslano {rez.get('poslano')} mehaničarima.", url="/plan")
            db.commit()
        except Exception:  # noqa: BLE001 — obavijest nije kritična
            pass


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
