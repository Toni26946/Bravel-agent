"""Primke robe — skladištar fotografira otpremnicu dobavljača (1+ stranica), AI izvuče stavke."""
import os
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..ai import ai_dostupan, parsiraj_otpremnicu
from ..auth import zahtijevaj_uloge
from ..config import settings
from ..database import get_db
from ..models import Korisnik, Primka, Uloga
from ..schemas import (
    OtpremnicaProcitana,
    OtpremnicaZahtjev,
    PrimkaCreate,
    PrimkaOut,
    PrimkaStavka,
    PrimkaUpdate,
    StranicaOtpremnice,
)
from ..storage import spremi_sliku

router = APIRouter(prefix="/primke", tags=["primke"])

# Skladište: skladištari unose primke; voditelj/poslovođa ih vide i uređuju.
skladiste = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)

_MEDIJ = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
          ".webp": "image/webp", ".gif": "image/gif"}


def _ucitaj_sliku(web_putanja: str) -> tuple[bytes, str] | None:
    """Web putanja '/uploads/xxx.jpg' → (bajtovi, media_type) s diska, ili None."""
    naziv = os.path.basename(web_putanja or "")
    disk = os.path.join(settings.upload_dir, naziv)
    if not naziv or not os.path.isfile(disk):
        return None
    ext = os.path.splitext(naziv)[1].lower()
    with open(disk, "rb") as f:
        return f.read(), _MEDIJ.get(ext, "image/jpeg")


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


@router.post("/stranica", response_model=StranicaOtpremnice)
def stranica(slika: UploadFile = File(...), _: Korisnik = Depends(skladiste)):
    """Spremi jednu stranicu otpremnice (bez AI-ja). Vrati web putanju."""
    return StranicaOtpremnice(foto=spremi_sliku(slika))


@router.post("/procitaj", response_model=OtpremnicaProcitana)
def procitaj(zahtjev: OtpremnicaZahtjev, _: Korisnik = Depends(skladiste)):
    """AI pročita sve priložene stranice otpremnice (uzastopne stranice jednog dokumenta)."""
    if not ai_dostupan():
        return OtpremnicaProcitana(ai=False)
    slike = [s for s in (_ucitaj_sliku(p) for p in zahtjev.fotke) if s]
    if not slike:
        raise HTTPException(status_code=400, detail="Nema slika za čitanje.")
    try:
        podaci = parsiraj_otpremnicu(slike)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"AI nije uspio pročitati otpremnicu: {e}")
    return OtpremnicaProcitana(
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
    fotografije = [f for f in (podaci.fotografije or []) if f]
    if not fotografije and podaci.foto:            # kompatibilnost sa starim klijentom
        fotografije = [podaci.foto]
    if not (podaci.dobavljac or podaci.broj_otpremnice or stavke or fotografije):
        raise HTTPException(status_code=400, detail="Primka je prazna — dodaj barem dobavljača, broj otpremnice ili stavku.")
    p = Primka(
        dobavljac=(podaci.dobavljac or None),
        broj_otpremnice=(podaci.broj_otpremnice or None),
        datum=podaci.datum,
        napomena=(podaci.napomena or None),
        foto_putanja=(fotografije[0] if fotografije else None),
        fotografije=fotografije or None,
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
