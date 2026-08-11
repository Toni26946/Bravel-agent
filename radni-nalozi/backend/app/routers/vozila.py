"""Vozila (kamioni). Svi prijavljeni mogu vidjeti; uređuje samo voditelj."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import re

from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, Uloga, Vozilo
from ..schemas import (
    VoziloCreate,
    VoziloOut,
    VoziloUpdate,
    VoziloUvoz,
    VoziloUvozRezultat,
)

router = APIRouter(prefix="/vozila", tags=["vozila"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


@router.get("", response_model=list[VoziloOut])
def popis(_: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    return db.query(Vozilo).filter(Vozilo.aktivan.is_(True)).order_by(Vozilo.gb).all()


@router.post("", response_model=VoziloOut, status_code=201)
def kreiraj(podaci: VoziloCreate, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    if db.query(Vozilo).filter(Vozilo.gb == podaci.gb).first():
        raise HTTPException(status_code=409, detail="Vozilo s tim GB već postoji")
    v = Vozilo(**podaci.model_dump())
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.post("/uvoz", response_model=VoziloUvozRezultat)
def uvoz(podaci: VoziloUvoz, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    """Skupni uvoz kamiona iz zalijepljenog popisa.

    Svaki redak: GB[,reg[,marka]] (razdvojeno tabom, zarezom ili točka-zarezom).
    Prvi stupac = garažni broj (obavezno). Postojeći GB se preskaču.
    """
    postojeci = {v.gb.lower() for v in db.query(Vozilo).all()}
    dodano = 0
    ukupno = 0
    for redak in podaci.tekst.splitlines():
        redak = redak.strip()
        if not redak:
            continue
        dijelovi = [d.strip() for d in re.split(r"[\t,;]", redak)]
        gb = dijelovi[0] if dijelovi else ""
        if not gb:
            continue
        # Preskoči vjerojatni redak zaglavlja ("GB", "Garažni broj"…)
        if ukupno == 0 and gb.lower() in ("gb", "garažni broj", "garazni broj", "gb kamiona"):
            continue
        ukupno += 1
        if gb.lower() in postojeci:
            continue
        v = Vozilo(
            gb=gb,
            registracija=(dijelovi[1] if len(dijelovi) > 1 and dijelovi[1] else None),
            marka=(dijelovi[2] if len(dijelovi) > 2 and dijelovi[2] else None),
        )
        db.add(v)
        postojeci.add(gb.lower())
        dodano += 1
    db.commit()
    return VoziloUvozRezultat(dodano=dodano, preskoceno=ukupno - dodano, ukupno=ukupno)


@router.patch("/{vozilo_id}", response_model=VoziloOut)
def azuriraj(
    vozilo_id: int,
    podaci: VoziloUpdate,
    _: Korisnik = Depends(samo_voditelj),
    db: Session = Depends(get_db),
):
    v = db.get(Vozilo, vozilo_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    for polje, vrijednost in podaci.model_dump(exclude_unset=True).items():
        setattr(v, polje, vrijednost)
    db.commit()
    db.refresh(v)
    return v
