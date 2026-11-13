"""Narudžbe dijelova — iz radnog naloga se upiše što treba naručiti (može i slika
dijela). Skladištar ih vidi skupno u kartici „Narudžbe" i označava naručeno/stiglo.

status: trazeno → naruceno → stiglo
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import trenutni_korisnik, zahtijevaj_uloge
from ..database import get_db
from ..models import Korisnik, NarudzbaDio, Uloga
from ..storage import spremi_sliku
from .nalozi import _dohvati_ovlasten

router = APIRouter(prefix="/narudzbe", tags=["narudzbe"])

# Skupni popis i obrada (naručeno/stiglo): skladištar + voditelj/poslovođa.
skladiste = zahtijevaj_uloge(Uloga.skladistar, Uloga.voditelj, Uloga.poslovodja)

_STATUSI = ("trazeno", "naruceno", "stiglo")


def _out(n: NarudzbaDio) -> dict:
    return {
        "id": n.id, "nalog_id": n.nalog_id, "vozilo_gb": n.vozilo_gb,
        "naziv": n.naziv, "kataloski": n.kataloski, "kolicina": n.kolicina,
        "jmj": n.jmj, "napomena": n.napomena, "fotografije": n.fotografije or [],
        "status": n.status,
        "trazio": (n.trazio.ime if n.trazio else None),
        "trazeno": n.trazeno.isoformat() if n.trazeno else None,
        "naruceno": n.naruceno.isoformat() if n.naruceno else None,
        "stiglo": n.stiglo.isoformat() if n.stiglo else None,
        "obradio": (n.obradio.ime if n.obradio else None),
        "broj_naloga": (n.nalog.broj if n.nalog else None),
    }


class NarudzbaIn(BaseModel):
    naziv: str | None = None   # neobavezno — dio se može zadati i samo slikom/kataloškim brojem
    kataloski: str | None = None
    kolicina: float = 1
    jmj: str = "kom"
    napomena: str | None = None
    fotografije: list[str] = []


class StatusIn(BaseModel):
    status: str


# --- slika dijela (iz naloga) -----------------------------------------------
@router.post("/foto")
def upload_foto(slika: UploadFile = File(...), _: Korisnik = Depends(trenutni_korisnik)):
    """Spremi sliku dijela i vrati web putanju (uključuje se u 'fotografije')."""
    return {"foto": spremi_sliku(slika)}


# --- unos iz radnog naloga ---------------------------------------------------
@router.get("/nalog/{nalog_id}")
def popis_naloga(nalog_id: int, korisnik: Korisnik = Depends(trenutni_korisnik),
                 db: Session = Depends(get_db)):
    _dohvati_ovlasten(db, nalog_id, korisnik)
    red = (db.query(NarudzbaDio).filter(NarudzbaDio.nalog_id == nalog_id)
           .order_by(NarudzbaDio.trazeno.desc()).all())
    return [_out(x) for x in red]


@router.post("/nalog/{nalog_id}", status_code=201)
def dodaj(nalog_id: int, p: NarudzbaIn, korisnik: Korisnik = Depends(trenutni_korisnik),
          db: Session = Depends(get_db)):
    nalog = _dohvati_ovlasten(db, nalog_id, korisnik)
    naziv = (p.naziv or "").strip()
    kataloski = (p.kataloski or "").strip() or None
    napomena = (p.napomena or "").strip() or None
    foto = [f for f in (p.fotografije or []) if f]
    # Naziv više NIJE obavezan, ali mora postojati bar nešto (da ne ostane prazan unos).
    if not (naziv or kataloski or napomena or foto):
        raise HTTPException(status_code=400, detail="Upiši barem naziv, kataloški broj, napomenu ili dodaj sliku.")
    if (p.kolicina or 0) <= 0:
        raise HTTPException(status_code=400, detail="Količina mora biti veća od 0.")
    gb = (nalog.vozilo.gb if nalog.vozilo else "") or ""
    n = NarudzbaDio(
        nalog_id=nalog_id, vozilo_gb=gb, naziv=naziv, kataloski=kataloski,
        kolicina=float(p.kolicina), jmj=(p.jmj or "kom"), napomena=napomena,
        fotografije=(foto or None),
        status="trazeno", trazio_id=korisnik.id,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return _out(n)


@router.delete("/{nid}", status_code=204)
def obrisi(nid: int, korisnik: Korisnik = Depends(trenutni_korisnik),
           db: Session = Depends(get_db)):
    n = db.get(NarudzbaDio, nid)
    if not n:
        raise HTTPException(status_code=404, detail="Narudžba ne postoji")
    _dohvati_ovlasten(db, n.nalog_id, korisnik)   # mora imati pristup nalogu
    db.delete(n)
    db.commit()


# --- skladištar: skupni popis + obrada --------------------------------------
@router.get("")
def popis(status: str | None = None, _: Korisnik = Depends(skladiste),
          db: Session = Depends(get_db)):
    """Sve narudžbe za skladištara. `status` filtrira (trazeno|naruceno|stiglo);
    bez njega vraća sve, najnovije prvo."""
    q = db.query(NarudzbaDio)
    if status in _STATUSI:
        q = q.filter(NarudzbaDio.status == status)
    red = q.order_by(NarudzbaDio.trazeno.desc()).all()
    return [_out(x) for x in red]


@router.post("/{nid}/status")
def postavi_status(nid: int, p: StatusIn, korisnik: Korisnik = Depends(skladiste),
                   db: Session = Depends(get_db)):
    n = db.get(NarudzbaDio, nid)
    if not n:
        raise HTTPException(status_code=404, detail="Narudžba ne postoji")
    if p.status not in _STATUSI:
        raise HTTPException(status_code=400, detail="Nepoznat status")
    sad = datetime.now(timezone.utc)
    n.status = p.status
    if p.status == "naruceno":
        n.naruceno = n.naruceno or sad
        n.stiglo = None
    elif p.status == "stiglo":
        n.naruceno = n.naruceno or sad
        n.stiglo = sad
    else:   # trazeno — vraćanje na početak
        n.naruceno = None
        n.stiglo = None
    n.obradio_id = korisnik.id
    db.commit()
    db.refresh(n)
    return _out(n)
