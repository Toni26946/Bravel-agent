"""Brojevi za „pažnju voditelja" — koristi se za crvene oznake na karticama izbornika.

Lagano i otporno: svaki brojač u svom try/except, da nikad ne sruši izbornik.
Uz to `/paznja/mozak` — sažetak radione SAMO ZA ČITANJE za Tonijev „Moj mozak".
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import zahtijevaj_uloge
from ..database import get_db
from ..models import (
    Korisnik,
    Nalog,
    Prijava,
    RegistarVozila,
    StatusNaloga,
    StatusPrijave,
    Uloga,
)
from .poslovodja import vlasnik_ili_mozak
from .vozila import _prikolice_za_upisati

router = APIRouter(prefix="/paznja", tags=["paznja"])

_voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)

_OTVORENI = (StatusNaloga.otvoren, StatusNaloga.u_radu, StatusNaloga.ceka_dijelove)
_PRIORITET_RED = {"hitan": 0, "visok": 1, "srednji": 2, "nizak": 3}


def _brojevi(db: Session) -> dict:
    out = {"spremne": 0, "izasli": 0, "prijave": 0}
    try:
        out["spremne"] = len(_prikolice_za_upisati(db))
    except Exception:  # noqa: BLE001
        pass
    try:
        out["izasli"] = (
            db.query(Nalog)
            .filter(Nalog.status == StatusNaloga.u_radu, Nalog.izvan_radione_javljeno.is_(True))
            .count()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        out["prijave"] = db.query(Prijava).filter(Prijava.status == StatusPrijave.nova).count()
    except Exception:  # noqa: BLE001
        pass
    return out


@router.get("")
def paznja(db: Session = Depends(get_db), _: Korisnik = Depends(_voditelj_ili_poslovodja)) -> dict:
    """Brojevi stavki koje traže pažnju, po kartici izbornika.

    - spremne: priključna vozila sa završenim nalogom koja čekaju upis spremnosti+lokacije
    - izasli: vozila izvan radione s otvorenim nalogom
    - prijave: nove prijave kvara (čekaju voditelja)
    """
    return _brojevi(db)


@router.get("/mozak")
def paznja_mozak(db: Session = Depends(get_db), _: Korisnik | None = Depends(vlasnik_ili_mozak)) -> dict:
    """Sažetak radione za Tonijev „Moj mozak" (zaglavlje X-Mozak-Kljuc ili prijava vlasnika).

    Samo čitanje: nalozi po statusu, otvoreni nalozi (s vozilom, prioritetom, rokom i
    koliko dugo stoje), zatvoreno u zadnjih 7 dana, matični popis vozila po statusu i
    brojevi pažnje. Ništa se ne mijenja."""
    danas = date.today()
    sad = datetime.now(timezone.utc)
    out: dict = {"danas": danas.isoformat(), "paznja": _brojevi(db)}
    try:
        po_statusu = Counter(s.value if hasattr(s, "value") else str(s)
                             for (s,) in db.query(Nalog.status).all())
        out["nalozi_po_statusu"] = dict(po_statusu)
    except Exception:  # noqa: BLE001
        out["nalozi_po_statusu"] = {}
    try:
        tjedan = sad - timedelta(days=7)
        out["zatvoreno_7_dana"] = (
            db.query(Nalog).filter(Nalog.zatvoren.is_not(None), Nalog.zatvoren >= tjedan).count()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        otvoreni = db.query(Nalog).filter(Nalog.status.in_(_OTVORENI)).all()
        redovi = []
        for n in otvoreni:
            kreiran = n.kreiran if n.kreiran.tzinfo else n.kreiran.replace(tzinfo=timezone.utc)
            redovi.append({
                "broj": n.broj,
                "gb": n.vozilo.gb if n.vozilo else None,
                "naslov": (n.naslov or "")[:90],
                "status": n.status.value,
                "prioritet": n.prioritet.value if n.prioritet else None,
                "rok": n.rok.isoformat() if n.rok else None,
                "kasni": bool(n.rok and n.rok < danas),
                "dana_otvoren": (sad - kreiran).days,
            })
        redovi.sort(key=lambda r: (not r["kasni"], _PRIORITET_RED.get(r["prioritet"] or "", 9),
                                   -r["dana_otvoren"]))
        out["otvoreni_ukupno"] = len(redovi)
        out["otvoreni"] = redovi[:30]
    except Exception:  # noqa: BLE001
        out["otvoreni"] = []
    try:
        vozila = Counter(s.value if hasattr(s, "value") else str(s)
                         for (s,) in db.query(RegistarVozila.status).all())
        out["vozila_po_statusu"] = dict(vozila)
    except Exception:  # noqa: BLE001
        pass
    return out
