"""Primke robe — skladištar fotografira otpremnicu dobavljača, AI izvuče stavke."""
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..ai import ai_dostupan, parsiraj_otpremnicu
from ..auth import zahtijevaj_uloge
from ..config import settings
from ..database import get_db
from ..models import Korisnik, Primka, Uloga
from ..schemas import OtpremnicaProcitana, PrimkaCreate, PrimkaOut, PrimkaStavka, PrimkaUpdate
from ..storage import spremi_sliku

router = APIRouter(prefix="/primke", tags=["primke"])

# Skladište: skladištari unose primke; voditelj/poslovođa ih vide i uređuju.
skladiste = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)


def _parse_datum(s):
    if not s:
        return None
    t = str(s).strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%Y.", "%Y-%m-%d", "%d/%m/%Y", "%d. %m. %Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _stavke(sirove) -> list[PrimkaStavka]:
    out: list[PrimkaStavka] = []
    for s in (sirove or []):
        artikl = str(s.get("artikl") or "").strip()
        if not artikl:
            continue
        try:
            kol = float(s.get("kolicina")) if s.get("kolicina") not in (None, "") else 1
        except (TypeError, ValueError):
            kol = 1
        jed = str(s.get("jedinica") or "kom").strip() or "kom"
        try:
            cij = float(s.get("cijena")) if s.get("cijena") not in (None, "") else None
        except (TypeError, ValueError):
            cij = None
        out.append(PrimkaStavka(artikl=artikl, kolicina=kol or 1, jedinica=jed, cijena=cij))
    return out


@router.post("/procitaj", response_model=OtpremnicaProcitana)
def procitaj(slika: UploadFile = File(...), _: Korisnik = Depends(skladiste)):
    """Spremi fotografiju otpremnice i (ako je AI dostupan) pročitaj dobavljača i stavke."""
    putanja = spremi_sliku(slika)  # validira tip/veličinu + sprema na disk
    if not ai_dostupan():
        return OtpremnicaProcitana(foto=putanja, ai=False)
    disk = os.path.join(settings.upload_dir, os.path.basename(putanja))
    try:
        with open(disk, "rb") as f:
            podaci_slike = f.read()
        podaci = parsiraj_otpremnicu(podaci_slike, slika.content_type or "image/jpeg")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI nije uspio pročitati otpremnicu: {e}")
    return OtpremnicaProcitana(
        foto=putanja,
        dobavljac=(podaci.get("dobavljac") or None),
        broj_otpremnice=(podaci.get("broj_otpremnice") or None),
        datum=_parse_datum(podaci.get("datum")),
        stavke=_stavke(podaci.get("stavke")),
        ai=True,
    )


@router.get("", response_model=list[PrimkaOut])
def popis(_: Korisnik = Depends(skladiste), db: Session = Depends(get_db)):
    return db.query(Primka).order_by(Primka.kreiran.desc()).all()


@router.get("/{primka_id}", response_model=PrimkaOut)
def dohvati(primka_id: int, _: Korisnik = Depends(skladiste), db: Session = Depends(get_db)):
    p = db.get(Primka, primka_id)
    if not p:
        raise HTTPException(status_code=404, detail="Primka ne postoji")
    return p


@router.post("", response_model=PrimkaOut, status_code=201)
def kreiraj(podaci: PrimkaCreate, korisnik: Korisnik = Depends(skladiste), db: Session = Depends(get_db)):
    stavke = [x.model_dump() for x in podaci.stavke if x.artikl.strip()]
    if not (podaci.dobavljac or podaci.broj_otpremnice or stavke or podaci.foto):
        raise HTTPException(status_code=400, detail="Primka je prazna — dodaj barem dobavljača, broj otpremnice ili stavku.")
    p = Primka(
        dobavljac=(podaci.dobavljac or None),
        broj_otpremnice=(podaci.broj_otpremnice or None),
        datum=podaci.datum,
        napomena=(podaci.napomena or None),
        foto_putanja=(podaci.foto or None),
        stavke=stavke,
        kreirao_id=korisnik.id,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/{primka_id}", response_model=PrimkaOut)
def azuriraj(primka_id: int, podaci: PrimkaUpdate, _: Korisnik = Depends(skladiste), db: Session = Depends(get_db)):
    p = db.get(Primka, primka_id)
    if not p:
        raise HTTPException(status_code=404, detail="Primka ne postoji")
    izmjene = podaci.model_dump(exclude_unset=True)
    if izmjene.get("stavke") is not None:
        izmjene["stavke"] = [s for s in izmjene["stavke"] if (s.get("artikl") or "").strip()]
    for polje, vrijednost in izmjene.items():
        setattr(p, polje, vrijednost)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{primka_id}", status_code=204)
def obrisi(primka_id: int, _: Korisnik = Depends(skladiste), db: Session = Depends(get_db)):
    p = db.get(Primka, primka_id)
    if not p:
        raise HTTPException(status_code=404, detail="Primka ne postoji")
    db.delete(p)
    db.commit()
