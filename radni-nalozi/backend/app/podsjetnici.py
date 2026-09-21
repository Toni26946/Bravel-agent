"""Podsjetnici za parkiranje nezaduženih šlepa.

Kad se nezadužena šlepa (prikolica koja nije ni u jednoj kompoziciji — provjera
u Flota OS-u) završi, javi voditelju naloga da upiše gdje je parkirana. Ako ne
upiše, podsjeti ga svaki dan dok ne riješi. Radi u pozadini (asyncio petlja).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import flota
from .database import SessionLocal
from .models import Nalog, StatusNaloga, Uloga
from .push import obavijesti_korisnika, obavijesti_ulogu

log = logging.getLogger("parking")

_INTERVAL = 900        # 15 min
_PROZOR_DANA = 3       # promatra naloge završene u zadnjih N dana (da ne spama stare)
_ZAVRSENI = (StatusNaloga.gotov, StatusNaloga.zatvoren)


def _javi(db, nalog: Nalog, prvi: bool) -> None:
    gb = nalog.vozilo.gb if nalog.vozilo else "?"
    naslov = "Nezadužena šlepa — gdje je parkirana?"
    tijelo = (f"Šlepa {gb} je gotova. Upiši gdje je parkirana."
              if prvi else
              f"Podsjetnik: šlepa {gb} — još nije upisano gdje je parkirana.")
    if nalog.voditelj_id:
        obavijesti_korisnika(db, nalog.voditelj_id, naslov, tijelo, url="/parkiranje")
    else:
        obavijesti_ulogu(db, Uloga.voditelj, naslov, tijelo, url="/parkiranje")


async def obradi_parking() -> None:
    sada = datetime.now(timezone.utc)
    danas = sada.date()
    granica = sada - timedelta(days=_PROZOR_DANA)

    # 1) Detekcija: novozavršene nezadužene šlepe (jednom po nalogu).
    with SessionLocal() as db:
        kandidati = (
            db.query(Nalog)
            .filter(Nalog.status.in_(_ZAVRSENI),
                    Nalog.parking_obavijest_poslano.is_(None),
                    Nalog.zatvoren.isnot(None),
                    Nalog.zatvoren >= granica)
            .all()
        )
        parovi = [(n.id, (n.vozilo.gb if n.vozilo else None)) for n in kandidati]

    za_javiti = []
    for nid, gb in parovi:
        if gb and flota.je_nezaduzena_slepa(await flota.zaduzenje(gb)):
            za_javiti.append(nid)

    if za_javiti:
        with SessionLocal() as db:
            for nid in za_javiti:
                n = db.get(Nalog, nid)
                if not n or n.parking_obavijest_poslano:
                    continue
                n.parking_obavijest_poslano = sada
                n.parking_zadnji_podsjetnik = danas
                _javi(db, n, prvi=True)
            db.commit()

    # 2) Podsjetnici: neriješeni, zadnji podsjetnik prije danas → opet javi.
    with SessionLocal() as db:
        nerijeseni = (
            db.query(Nalog)
            .filter(Nalog.parking_obavijest_poslano.isnot(None),
                    Nalog.parking_rijeseno.is_(None),
                    ((Nalog.parking_zadnji_podsjetnik.is_(None))
                     | (Nalog.parking_zadnji_podsjetnik < danas)))
            .all()
        )
        for n in nerijeseni:
            n.parking_zadnji_podsjetnik = danas
            _javi(db, n, prvi=False)
        if nerijeseni:
            db.commit()


async def petlja() -> None:
    log.info("Podsjetnici za parkiranje pokrenuti (interval %ss).", _INTERVAL)
    while True:
        try:
            await obradi_parking()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Parking tick greška: %s", e)
        await asyncio.sleep(_INTERVAL)
