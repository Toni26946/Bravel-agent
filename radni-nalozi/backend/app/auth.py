"""Autentikacija: hashiranje lozinki (bcrypt), JWT tokeni i ovisnosti za uloge."""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .config import jwt_secret, settings
from .database import get_db
from .models import Korisnik, Uloga

# auto_error=False: zahtjev smije doći i bez Bearer tokena — tada se gleda
# servisni ključ (M2M iz Flota OS-a). Ako nema ni jedno, sami vraćamo 401.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Račun pod kojim se bilježe promjene stigle iz Flota OS-a (M2M). Dnevnik tako
# i dalje ima „tko je kreirao", a u napomeni stoji ime stvarne osobe.
SERVIS_KORISNIK = "flota-os"


def _servisni_korisnik(db: Session) -> Korisnik:
    """Servisni račun za M2M pozive (kreira se pri prvom pozivu, bez upotrebljive lozinke)."""
    k = db.query(Korisnik).filter(Korisnik.korisnicko_ime == SERVIS_KORISNIK).first()
    if not k:
        k = Korisnik(
            ime="Flota OS",
            korisnicko_ime=SERVIS_KORISNIK,
            lozinka_hash="!",                 # nemoguć hash → prijava lozinkom nije moguća
            uloga=Uloga.voditelj,
            aktivan=True,
            prijavljuje_se=False,
        )
        db.add(k)
        db.commit()
        db.refresh(k)
    return k


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
    return jwt.encode(payload, jwt_secret(), algorithm=settings.jwt_algorithm)


def _dekodiraj(token: str) -> dict:
    try:
        return jwt.decode(token, jwt_secret(), algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nevažeći ili istekli token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --- ovisnosti ---------------------------------------------------------------
def trenutni_korisnik(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
    x_servis_kljuc: str | None = Header(default=None),
) -> Korisnik:
    # M2M: Flota OS se javlja servisnim ključem (bez korisničkog tokena).
    if not token and x_servis_kljuc:
        if not settings.servis_kljuc or x_servis_kljuc != settings.servis_kljuc:
            raise HTTPException(status_code=401, detail="Nevažeći servisni ključ")
        return _servisni_korisnik(db)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nedostaje token",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
