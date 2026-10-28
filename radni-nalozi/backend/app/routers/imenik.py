"""Imenik telefona — SAMO ČITANJE (izvor istine je Flota OS, vidi app/imenik.py)."""
from fastapi import APIRouter, Depends

from .. import imenik
from ..auth import zahtijevaj_imenik_pristup
from ..models import Korisnik

router = APIRouter(prefix="/imenik", tags=["imenik"])


@router.get("")
def popis(osvjezi: bool = False, _: Korisnik = Depends(zahtijevaj_imenik_pristup())) -> dict:
    """Brojevi iz Flota OS-a (predmemorija 5 min; `osvjezi=1` odmah povuče svježe)."""
    return imenik.dohvati(osvjezi=osvjezi)
