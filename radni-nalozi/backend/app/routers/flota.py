"""Dijagnostika Flota OS (GPS) nadzora — je li živ i što vidi (samo voditelj)."""
from fastapi import APIRouter, Depends

from .. import flota
from ..auth import zahtijevaj_uloge
from ..models import Korisnik, Uloga

router = APIRouter(prefix="/flota", tags=["flota"])

_samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


@router.get("/health")
def health() -> dict:
    """Javni, minimalni status GPS nadzora (bez vozila/korisnika) — za brzu
    provjeru je li Flota živa, bez prijave."""
    return flota.health()


@router.get("/radionica")
def radionica() -> dict:
    """Javni izvedeni broj vozila 'u radionici' (status ILI GPS u krugu + otvoren
    nalog) s raščlambom. Samo brojevi, bez vozila/registracija."""
    return flota.broj_u_radionici()


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
