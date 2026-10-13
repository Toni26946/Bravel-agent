"""Brojevi za „pažnju voditelja" — koristi se za crvene oznake na karticama izbornika.

Lagano i otporno: svaki brojač u svom try/except, da nikad ne sruši izbornik.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Nalog, Prijava, StatusNaloga, StatusPrijave, Uloga
from .vozila import _prikolice_za_upisati

router = APIRouter(prefix="/paznja", tags=["paznja"])

_voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)


@router.get("")
def paznja(db: Session = Depends(get_db), _: Korisnik = Depends(_voditelj_ili_poslovodja)) -> dict:
    """Brojevi stavki koje traže pažnju, po kartici izbornika.

    - spremne: priključna vozila sa završenim nalogom koja čekaju upis spremnosti+lokacije
    - izasli: vozila izvan radione s otvorenim nalogom
    - prijave: nove prijave kvara (čekaju voditelja)
    """
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
