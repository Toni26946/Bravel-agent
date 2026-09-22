"""Prisila na upis spremnosti šlepa (nema GPS-a, ljudi zaborave upisati).

Kad se nalog na ŠLEPI (prikolici) završi, radionica je mora označiti kao
„Spremno" i upisati GDJE je parkirana — ili „Pokvareno". Dok to ne naprave,
sustav svaki dan podsjeća voditelja (push) da to nije upisano. Time se zna
koje su šlepe spremne i gdje, pa se ne zaborave.

Radi u pozadini (asyncio petlja).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .database import SessionLocal
from .models import Nalog, RegistarVozila, StatusNaloga, StatusVozila, Uloga
from .push import obavijesti_korisnika, obavijesti_ulogu

log = logging.getLogger("spremnost")

_INTERVAL = 900        # 15 min
_PROZOR_DANA = 5       # promatra šlepe s nalogom završenim u zadnjih N dana (da ne spama stare)
_ZAVRSENI = (StatusNaloga.gotov, StatusNaloga.zatvoren)


def _javi(db, gb: str, voditelj_id: int | None, prvi: bool) -> None:
    naslov = "Šlepa — je li spremna i gdje je?"
    tijelo = (f"Šlepa {gb} je gotova. Označi je Spremno i upiši gdje je parkirana."
              if prvi else
              f"Podsjetnik: za šlepu {gb} nije upisano je li spremna ni gdje je parkirana.")
    if voditelj_id:
        obavijesti_korisnika(db, voditelj_id, naslov, tijelo, url="/spremne")
    else:
        obavijesti_ulogu(db, Uloga.voditelj, naslov, tijelo, url="/spremne")


def _rijeseno(r: RegistarVozila) -> bool:
    """Šlepa ima ishod: spremna (uz lokaciju) ili pokvarena/prodana."""
    if r.status == StatusVozila.spremno and (r.lokacija or "").strip():
        return True
    return r.status in (StatusVozila.pokvareno, StatusVozila.prodano)


async def obradi_spremnost() -> None:
    sada = datetime.now(timezone.utc)
    danas = sada.date()
    granica = sada - timedelta(days=_PROZOR_DANA)

    with SessionLocal() as db:
        # Šlepe s nedavno završenim nalogom → zadnji nalog po garažnom broju.
        nalozi = (
            db.query(Nalog)
            .filter(Nalog.status.in_(_ZAVRSENI),
                    Nalog.zatvoren.isnot(None),
                    Nalog.zatvoren >= granica)
            .order_by(Nalog.azuriran.desc())
            .all()
        )
        gb_nalog: dict = {}
        for n in nalozi:
            gb = str(n.vozilo.gb) if n.vozilo else None
            if gb and gb not in gb_nalog:
                gb_nalog[gb] = n

        promjena = False
        for gb, n in gb_nalog.items():
            r = db.get(RegistarVozila, gb) or db.query(RegistarVozila).filter(
                RegistarVozila.gb == (gb.lstrip("0") or gb)).first()
            if not r or r.kategorija != "prikolica" or _rijeseno(r):
                continue
            if r.podsjetnik_zadnji is None or r.podsjetnik_zadnji < danas:
                _javi(db, gb, n.voditelj_id, prvi=(r.podsjetnik_zadnji is None))
                r.podsjetnik_zadnji = danas
                promjena = True
        if promjena:
            db.commit()


async def petlja() -> None:
    log.info("Podsjetnici za spremnost šlepa pokrenuti (interval %ss).", _INTERVAL)
    while True:
        try:
            await obradi_spremnost()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Spremnost tick greška: %s", e)
        await asyncio.sleep(_INTERVAL)
