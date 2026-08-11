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


def _je_registracija(t: str) -> bool:
    """Grubo prepoznavanje registarske oznake (npr. ZG3495FR, DQB2425):
    bez razmaka/točke, kratka, ima i slova i brojke."""
    return (
        " " not in t and "." not in t
        and 4 <= len(t) <= 9
        and any(c.isdigit() for c in t)
        and any(c.isalpha() for c in t)
    )


@router.post("/uvoz", response_model=VoziloUvozRezultat)
def uvoz(podaci: VoziloUvoz, _: Korisnik = Depends(samo_voditelj), db: Session = Depends(get_db)):
    """Skupni uvoz kamiona iz zalijepljenog popisa.

    Svaki redak počinje garažnim brojem (GB). Ostali stupci (razdvojeni tabom,
    zarezom ili točka-zarezom) prepoznaju se automatski: registracija po obliku
    (npr. ZG1234AB), a ostalo je naziv vozila (marka). Redoslijed stupaca nije
    bitan — može se lijepiti direktno iz Excela (GB, VOZILO, REG OZNAKA).
    Postojeći GB i redak zaglavlja se preskaču.
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
        if gb.lower() in ("gb", "garažni broj", "garazni broj", "gb kamiona", "gb vozila"):
            continue
        ukupno += 1
        if gb.lower() in postojeci:
            continue
        ostali = [d for d in dijelovi[1:] if d and d != "0"]
        reg = next((d for d in ostali if _je_registracija(d)), None)
        marka = next((d for d in ostali if d != reg and not _je_registracija(d)), None)
        db.add(Vozilo(gb=gb, registracija=reg, marka=marka))
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
