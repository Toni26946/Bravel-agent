"""Prijava i podaci o trenutnom korisniku."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..auth import hash_lozinka, kreiraj_token, provjeri_lozinku, trenutni_korisnik
from ..database import get_db
from ..models import Korisnik
from ..schemas import KorisnikOut, PromjenaLozinke, Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    korisnik = (
        db.query(Korisnik)
        .filter(Korisnik.korisnicko_ime == form.username)
        .first()
    )
    if not korisnik or not provjeri_lozinku(form.password, korisnik.lozinka_hash):
        raise HTTPException(status_code=401, detail="Pogrešno korisničko ime ili lozinka")
    if not korisnik.aktivan:
        raise HTTPException(status_code=403, detail="Korisnički račun je deaktiviran")
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
