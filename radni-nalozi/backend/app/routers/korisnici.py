"""Upravljanje korisnicima — samo voditelj."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import hash_lozinka, trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Uloga
from ..schemas import (
    KorisnikCreate,
    KorisnikOut,
    KorisnikUpdate,
    KorisnikUvoz,
    KorisnikUvozRezultat,
    KorisnikUvozStavka,
)

router = APIRouter(prefix="/korisnici", tags=["korisnici"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)

# Preslikavanje hrvatskih/stranih slova u ASCII za korisničko ime.
_ASCII = str.maketrans({
    "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d",
    "Č": "c", "Ć": "c", "Š": "s", "Ž": "z", "Đ": "d",
})


def _slug(ime: str) -> str:
    baza = ime.translate(_ASCII).lower()
    rijeci = ["".join(c for c in r if c.isalnum()) for r in baza.split()]
    rijeci = [r for r in rijeci if r]
    return ".".join(rijeci) or "radnik"


def _jedinstveno(db: Session, kandidat: str, zauzeti: set[str]) -> str:
    ime = kandidat
    i = 1
    while ime in zauzeti or db.query(Korisnik).filter(Korisnik.korisnicko_ime == ime).first():
        i += 1
        ime = f"{kandidat}{i}"
    zauzeti.add(ime)
    return ime


@router.get("", response_model=list[KorisnikOut])
def popis(
    uloga: Uloga | None = Query(default=None),
    korisnik: Korisnik = Depends(trenutni_korisnik),
    db: Session = Depends(get_db),
):
    # Voditelj vidi sve; ostali smiju dohvatiti samo popis radnika (za dodjele nije potrebno, ali radnici/vozači ne trebaju)
    if korisnik.uloga != Uloga.voditelj and uloga != Uloga.radnik:
        raise HTTPException(status_code=403, detail="Nemate ovlasti")
    q = db.query(Korisnik)
    if uloga:
        q = q.filter(Korisnik.uloga == uloga)
    return q.order_by(Korisnik.ime).all()


@router.post("", response_model=KorisnikOut, status_code=201)
def kreiraj(podaci: KorisnikCreate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    if db.query(Korisnik).filter(Korisnik.korisnicko_ime == podaci.korisnicko_ime).first():
        raise HTTPException(status_code=409, detail="Korisničko ime već postoji")
    k = Korisnik(
        ime=podaci.ime,
        korisnicko_ime=podaci.korisnicko_ime,
        lozinka_hash=hash_lozinka(podaci.lozinka),
        uloga=podaci.uloga,
        telefon=podaci.telefon,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@router.post("/uvoz", response_model=KorisnikUvozRezultat)
def uvoz(podaci: KorisnikUvoz, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    """Skupni uvoz korisnika iz zalijepljenog popisa imena (jedno po retku).

    Korisničko ime se generira iz imena (bez kvačica), zadana lozinka je ista za
    sve (poslije se mijenja). Postojeća imena (isto ime i uloga) se preskaču.
    """
    postojeca = {
        k.ime.strip().lower()
        for k in db.query(Korisnik).filter(Korisnik.uloga == podaci.uloga).all()
    }
    zauzeti: set[str] = set()
    dodani: list[KorisnikUvozStavka] = []
    ukupno = 0
    for redak in podaci.tekst.splitlines():
        ime = redak.strip()
        # makni eventualni broj s početka i status s kraja (npr. "1  KOBEŠČAK DAVOR  NOVI")
        ime = ime.replace("\t", " ").strip()
        if not ime:
            continue
        # ako redak počinje rednim brojem, makni ga
        dijelovi = ime.split()
        if dijelovi and dijelovi[0].rstrip(".").isdigit():
            dijelovi = dijelovi[1:]
        # makni oznaku statusa na kraju
        if dijelovi and dijelovi[-1].upper() in ("NOVI", "NOVA", "STATUS"):
            dijelovi = dijelovi[:-1]
        ime = " ".join(dijelovi).strip()
        if not ime or ime.upper() in ("RADNIK", "RB", "POPIS RADNIKA RADIONE"):
            continue
        ukupno += 1
        if ime.lower() in postojeca:
            continue
        korisnicko = _jedinstveno(db, _slug(ime), zauzeti)
        db.add(Korisnik(
            ime=ime.title(),
            korisnicko_ime=korisnicko,
            lozinka_hash=hash_lozinka(podaci.lozinka),
            uloga=podaci.uloga,
        ))
        postojeca.add(ime.lower())
        dodani.append(KorisnikUvozStavka(ime=ime.title(), korisnicko_ime=korisnicko))
    db.commit()
    return KorisnikUvozRezultat(
        dodano=len(dodani), preskoceno=ukupno - len(dodani), ukupno=ukupno,
        lozinka=podaci.lozinka, korisnici=dodani,
    )


@router.patch("/{korisnik_id}", response_model=KorisnikOut)
def azuriraj(
    korisnik_id: int,
    podaci: KorisnikUpdate,
    _: Korisnik = Depends(samo_voditelj),
    db: Session = Depends(get_db),
):
    k = db.get(Korisnik, korisnik_id)
    if not k:
        raise HTTPException(status_code=404, detail="Korisnik ne postoji")
    if podaci.ime is not None:
        k.ime = podaci.ime
    if podaci.uloga is not None:
        k.uloga = podaci.uloga
    if podaci.telefon is not None:
        k.telefon = podaci.telefon
    if podaci.aktivan is not None:
        k.aktivan = podaci.aktivan
    if podaci.lozinka:
        k.lozinka_hash = hash_lozinka(podaci.lozinka)
    db.commit()
    db.refresh(k)
    return k
