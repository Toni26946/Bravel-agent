"""Dijagnostika Flota OS (GPS) nadzora — je li živ i što vidi (samo voditelj)."""
from fastapi import APIRouter, Depends

from .. import flota
from ..auth import zahtijevaj_uloge
from ..models import Korisnik, Uloga

router = APIRouter(prefix="/flota", tags=["flota"])

_samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


@router.get("/status")
def status(_: Korisnik = Depends(_samo_voditelj)) -> dict:
    """Trenutno stanje GPS nadzora: zadnji dohvat, broj pozicija, aktivni nalozi."""
    return flota.status()


@router.post("/provjeri")
async def provjeri_sada(_: Korisnik = Depends(_samo_voditelj)) -> dict:
    """Ručno pokreni jedan ciklus provjere (dohvat pozicija + obrada) i vrati stanje."""
    poslano = 0
    if flota.konfigurirano():
        pozicije = await flota.dohvati_pozicije()
        flota._zabiljezi(pozicije, None if pozicije is not None else "dohvat pozicija nije uspio")
        if pozicije:
            poslano = flota.obradi_pozicije(pozicije)
    return {"poslano": poslano, "status": flota.status()}
