"""Upravljanje korisnicima — samo voditelj."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import hash_lozinka, trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Uloga
from ..schemas import KorisnikCreate, KorisnikOut, KorisnikUpdate

router = APIRouter(prefix="/korisnici", tags=["korisnici"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


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
