"""Autentikacija: hashiranje lozinki (bcrypt), JWT tokeni i ovisnosti za uloge."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import Korisnik, Uloga

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


# --- lozinke -----------------------------------------------------------------
def hash_lozinka(lozinka: str) -> str:
    return bcrypt.hashpw(lozinka.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def provjeri_lozinku(lozinka: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(lozinka.encode("utf-8"), hash_.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --- JWT ---------------------------------------------------------------------
def kreiraj_token(korisnik: Korisnik) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(korisnik.id),
        "uloga": korisnik.uloga.value,
        "ime": korisnik.ime,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _dekodiraj(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nevažeći ili istekli token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- ovisnosti ---------------------------------------------------------------
def trenutni_korisnik(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Korisnik:
    podaci = _dekodiraj(token)
    korisnik = db.get(Korisnik, int(podaci.get("sub", 0)))
    if not korisnik or not korisnik.aktivan:
        raise HTTPException(status_code=401, detail="Korisnik ne postoji ili je deaktiviran")
    return korisnik


def zahtijevaj_uloge(*uloge: Uloga):
    """Vrati ovisnost koja dopušta pristup samo navedenim ulogama."""
    dozvoljene = set(uloge)

    def _provjera(korisnik: Korisnik = Depends(trenutni_korisnik)) -> Korisnik:
        if korisnik.uloga not in dozvoljene:
            raise HTTPException(status_code=403, detail="Nemate ovlasti za ovu radnju")
        return korisnik

    return _provjera
