"""Šifrarnik vozača — naša evidencija tko je vozač (ime, sektor, telefon).

Popis se jednokratno napuni iz matične tablice (seed), a voditelj ga dalje
uređuje. Obrazac zaduženja crpi popis vozača odavde (aktivni)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import zahtijevaj_uloge
from ..config import settings
from ..database import get_db
from ..models import Korisnik, Uloga, Vozac
from ..schemas import VozacCreate, VozacOut, VozacUpdate

log = logging.getLogger("vozaci")
router = APIRouter(prefix="/vozaci", tags=["vozaci"])

voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)
samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)

_SEED = Path(__file__).resolve().parent.parent / "data" / "vozaci_seed.json"
# Verzija seed-popisa — povećaj kad se popis zamijeni (v2 = potpun popis iz
# „VOZACI DODJELJENI KAMIONIMA" s telefonima i sektorom).
_SEED_VERZIJA = ".vozaci_seed_v2"


def _kljuc(ime: str) -> frozenset[str]:
    return frozenset(t for t in (ime or "").lower().split() if t)


def seed_vozaci(db: Session) -> None:
    """Napuni/uskladi šifrarnik vozača iz priložene datoteke.

    - Novi vozači iz datoteke se dodaju; postojećima (po imenu) se dopunjuju
      sektor/telefon ako nedostaju.
    - Jednokratno po verziji (`_SEED_VERZIJA`): seed-unosi kojih više nema u
      datoteci se uklanjaju (zamjena popisa). Ručno dodani (izvor='rucno') i
      ručne izmjene (aktivan) se NE diraju."""
    if not _SEED.is_file():
        return
    try:
        podaci = json.loads(_SEED.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        log.warning("Ne mogu učitati seed vozača: %s", e)
        return

    postojeci = db.execute(select(Vozac)).scalars().all()
    po_kljucu: dict[frozenset[str], Vozac] = {}
    for v in postojeci:
        po_kljucu.setdefault(_kljuc(v.ime), v)

    kljucevi_datoteke: set[frozenset[str]] = set()
    dodano = 0
    for r in podaci:
        ime = (r.get("ime") or "").strip()
        if not ime:
            continue
        k = _kljuc(ime)
        kljucevi_datoteke.add(k)
        sektor = (r.get("sektor") or None)
        telefon = (r.get("telefon") or None)
        v = po_kljucu.get(k)
        if v is None:
            v = Vozac(ime=ime, sektor=sektor, telefon=telefon, aktivan=True, izvor="seed")
            db.add(v)
            po_kljucu[k] = v
            dodano += 1
        else:
            # dopuni detalje ako nedostaju (ne gazi ručne izmjene imena)
            if not v.telefon and telefon:
                v.telefon = telefon
            if not v.sektor and sektor:
                v.sektor = sektor

    # Zamjena popisa (jednokratno po verziji): makni seed-vozače kojih nema u datoteci.
    zastavica = Path(settings.upload_dir).parent / _SEED_VERZIJA
    uklonjeno = 0
    if not zastavica.exists():
        for v in postojeci:
            if (v.izvor or "seed") != "rucno" and _kljuc(v.ime) not in kljucevi_datoteke:
                db.delete(v)
                uklonjeno += 1
        zastavica.parent.mkdir(parents=True, exist_ok=True)
        zastavica.write_text("done", encoding="utf-8")

    if dodano or uklonjeno:
        db.commit()
        log.info("Seed vozača: dodano %d, uklonjeno %d.", dodano, uklonjeno)


@router.get("", response_model=list[VozacOut])
def popis(
    aktivni: bool = Query(default=False, description="Samo aktivni vozači"),
    db: Session = Depends(get_db),
    _: Korisnik = Depends(voditelj_ili_poslovodja),
):
    q = select(Vozac)
    if aktivni:
        q = q.where(Vozac.aktivan == True)  # noqa: E712
    return db.execute(q.order_by(Vozac.ime)).scalars().all()


@router.post("", response_model=VozacOut, status_code=201)
def kreiraj(podaci: VozacCreate, db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    ime = (podaci.ime or "").strip()
    if not ime:
        raise HTTPException(status_code=400, detail="Ime vozača je obavezno")
    v = Vozac(
        ime=ime,
        sektor=(podaci.sektor or "").strip() or None,
        telefon=(podaci.telefon or "").strip() or None,
        aktivan=True,
        izvor="rucno",
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


@router.patch("/{vozac_id}", response_model=VozacOut)
def azuriraj(vozac_id: int, izmjene: VozacUpdate, db: Session = Depends(get_db), _: Korisnik = Depends(voditelj_ili_poslovodja)):
    v = db.get(Vozac, vozac_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozač ne postoji")
    podaci = izmjene.model_dump(exclude_unset=True)
    if "ime" in podaci:
        novo = (podaci["ime"] or "").strip()
        if not novo:
            raise HTTPException(status_code=400, detail="Ime vozača ne može biti prazno")
        v.ime = novo
    if "sektor" in podaci:
        v.sektor = (podaci["sektor"] or "").strip() or None
    if "telefon" in podaci:
        v.telefon = (podaci["telefon"] or "").strip() or None
    if "aktivan" in podaci and podaci["aktivan"] is not None:
        v.aktivan = bool(podaci["aktivan"])
    db.commit()
    db.refresh(v)
    return v


@router.delete("/{vozac_id}", status_code=204)
def obrisi(vozac_id: int, db: Session = Depends(get_db), _: Korisnik = Depends(samo_voditelj)):
    v = db.get(Vozac, vozac_id)
    if not v:
        raise HTTPException(status_code=404, detail="Vozač ne postoji")
    db.delete(v)
    db.commit()
    return None
