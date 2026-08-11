"""Prijave kvarova. Vozač kreira; voditelj vidi sve i mijenja status."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import (
    Fotografija,
    Hitnost,
    Korisnik,
    Prijava,
    StatusPrijave,
    TipFotografije,
    Uloga,
    Vozilo,
)
from ..push import obavijesti_ulogu
from ..schemas import PrijavaOut, PrijavaStatusUpdate
from ..storage import spremi_sliku

router = APIRouter(prefix="/prijave", tags=["prijave"])

samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)


@router.get("", response_model=list[PrijavaOut])
def popis(
    korisnik: Korisnik = Depends(trenutni_korisnik),
    db: Session = Depends(get_db),
):
    q = db.query(Prijava)
    # Vozač vidi samo svoje prijave; voditelj vidi sve.
    if korisnik.uloga == Uloga.vozac:
        q = q.filter(Prijava.prijavio_id == korisnik.id)
    elif korisnik.uloga == Uloga.radnik:
        raise HTTPException(status_code=403, detail="Radnici ne vide prijave")
    return q.order_by(Prijava.kreirana.desc()).all()


@router.get("/{prijava_id}", response_model=PrijavaOut)
def dohvati(prijava_id: int, korisnik: Korisnik = Depends(trenutni_korisnik), db: Session = Depends(get_db)):
    p = db.get(Prijava, prijava_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prijava ne postoji")
    if korisnik.uloga == Uloga.vozac and p.prijavio_id != korisnik.id:
        raise HTTPException(status_code=403, detail="Nemate ovlasti")
    return p


@router.post("", response_model=PrijavaOut, status_code=201)
async def kreiraj(
    vozilo_id: int = Form(...),
    opis: str = Form(...),
    hitnost: Hitnost = Form(Hitnost.srednja),
    slike: list[UploadFile] = File(default=[]),
    korisnik: Korisnik = Depends(zahtijevaj_uloge(Uloga.vozac, Uloga.voditelj)),
    db: Session = Depends(get_db),
):
    if not db.get(Vozilo, vozilo_id):
        raise HTTPException(status_code=404, detail="Vozilo ne postoji")
    p = Prijava(vozilo_id=vozilo_id, prijavio_id=korisnik.id, opis=opis.strip(), hitnost=hitnost)
    db.add(p)
    db.flush()
    for sl in slike or []:
        if sl and sl.filename:
            putanja = spremi_sliku(sl)
            db.add(Fotografija(prijava_id=p.id, putanja=putanja, tip=TipFotografije.prije, postavio_id=korisnik.id))
    db.commit()
    db.refresh(p)
    obavijesti_ulogu(
        db, Uloga.voditelj, "Nova prijava kvara",
        f"{korisnik.ime}: {opis[:80]}", url=f"/prijave/{p.id}",
    )
    return p


@router.patch("/{prijava_id}/status", response_model=PrijavaOut)
def promijeni_status(
    prijava_id: int,
    podaci: PrijavaStatusUpdate,
    _: Korisnik = Depends(samo_voditelj),
    db: Session = Depends(get_db),
):
    p = db.get(Prijava, prijava_id)
    if not p:
        raise HTTPException(status_code=404, detail="Prijava ne postoji")
    p.status = podaci.status
    db.commit()
    db.refresh(p)
    return p
