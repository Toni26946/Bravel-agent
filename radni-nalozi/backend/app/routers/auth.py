"""Prijava i podaci o trenutnom korisniku."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..auth import hash_lozinka, kreiraj_token, provjeri_lozinku, trenutni_korisnik
from ..database import get_db
from ..models import Korisnik
from ..ogranicenje import klijent_ip, ocisti, provjeri, zabiljezi_neuspjeh
from ..schemas import KorisnikOut, PromjenaLozinke, Token

router = APIRouter(prefix="/auth", tags=["auth"])

# Ograničenje prijave: najviše 10 neuspjelih pokušaja po IP-u unutar 5 minuta.
_MAKS_PRIJAVA = 10
_PROZOR_S = 300
# Lažni hash da provjera lozinke traje jednako i kad korisnik ne postoji
# (sprječava otkrivanje postojanja korisnika mjerenjem vremena).
_LAZNI_HASH = "$2b$12$abcdefghijklmnopqrstuuXqZ7Yy0aB1cD2eF3gH4iJ5kL6mN7oP8"


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    kljuc = klijent_ip(request)
    provjeri(kljuc, _MAKS_PRIJAVA, _PROZOR_S)

    korisnik = (
        db.query(Korisnik)
        .filter(Korisnik.korisnicko_ime == form.username)
        .first()
    )
    valjana = provjeri_lozinku(form.password, korisnik.lozinka_hash if korisnik else _LAZNI_HASH)
    if not korisnik or not valjana:
        zabiljezi_neuspjeh(kljuc, _PROZOR_S)
        raise HTTPException(status_code=401, detail="Pogrešno korisničko ime ili lozinka")
    if not korisnik.aktivan:
        raise HTTPException(status_code=403, detail="Korisnički račun je deaktiviran")
    ocisti(kljuc)
    return Token(access_token=kreiraj_token(korisnik), korisnik=KorisnikOut.model_validate(korisnik))


@router.get("/me", response_model=KorisnikOut)
def me(korisnik: Korisnik = Depends(trenutni_korisnik)):
    return korisnik


@router.post("/promijeni-lozinku", status_code=204)
def promijeni_lozinku(
    podaci: PromjenaLozinke,
    korisnik: Korisnik = Depends(trenutni_korisnik),
    db: Session = Depends(get_db),
):
    if not provjeri_lozinku(podaci.stara_lozinka, korisnik.lozinka_hash):
        raise HTTPException(status_code=400, detail="Trenutna lozinka nije točna")
    korisnik.lozinka_hash = hash_lozinka(podaci.nova_lozinka)
    db.commit()
