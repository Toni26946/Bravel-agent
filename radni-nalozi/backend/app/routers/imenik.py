"""Imenik telefona — čitanje svih odjela, UPIS samo za odjel RADIONA.

Izvor istine je Flota OS (vidi app/imenik.py): RN ne sprema brojeve u svoju bazu, nego ih
upisuje izravno u Flotu ključem radione, koji Flota prihvaća SAMO za odjel RADIONA.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import imenik
from ..auth import zahtijevaj_imenik_pristup
from ..config import settings
from ..models import Korisnik

router = APIRouter(prefix="/imenik", tags=["imenik"])


def _s_oznakom(d: dict) -> dict:
    return {**d, "upis_radiona": bool(settings.imenik_radiona_kljuc)}


@router.get("")
def popis(osvjezi: bool = False, _: Korisnik = Depends(zahtijevaj_imenik_pristup())) -> dict:
    """Brojevi iz Flota OS-a (predmemorija 5 min; `osvjezi=1` odmah povuče svježe)."""
    return _s_oznakom(imenik.dohvati(osvjezi=osvjezi))


class RadionaUnos(BaseModel):
    id: int | None = None
    ime: str | None = None
    opis: str | None = None
    broj: str
    kratki: str | None = None
    tarifa: str | None = None
    napomena: str | None = None


@router.post("/radiona")
def spremi_radiona(unos: RadionaUnos, korisnik: Korisnik = Depends(zahtijevaj_imenik_pristup())) -> dict:
    """Dodaj ili ispravi broj u odjelu RADIONA (upis ide u Flotu; ondje se bilježi ime korisnika)."""
    try:
        return _s_oznakom(imenik.spremi_radiona(unos.model_dump(), korisnik.ime))
    except imenik.GreskaUpisa as e:
        raise HTTPException(status_code=e.status, detail=e.poruka)


@router.post("/radiona/{rid}/aktivan")
def aktivan_radiona(rid: int, aktivan: bool = True, korisnik: Korisnik = Depends(zahtijevaj_imenik_pristup())) -> dict:
    """Deaktiviraj / ponovno aktiviraj broj u odjelu RADIONA."""
    try:
        return _s_oznakom(imenik.postavi_aktivan_radiona(rid, aktivan, korisnik.ime))
    except imenik.GreskaUpisa as e:
        raise HTTPException(status_code=e.status, detail=e.poruka)
