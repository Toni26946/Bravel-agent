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
from ..database import get_db
from ..models import Korisnik, Uloga, Vozac
from ..schemas import VozacCreate, VozacOut, VozacUpdate

log = logging.getLogger("vozaci")
router = APIRouter(prefix="/vozaci", tags=["vozaci"])

voditelj_ili_poslovodja = zahtijevaj_uloge(Uloga.voditelj, Uloga.poslovodja)
samo_voditelj = zahtijevaj_uloge(Uloga.voditelj)

_SEED = Path(__file__).resolve().parent.parent / "data" / "vozaci_seed.json"


def _kljuc(ime: str) -> frozenset[str]:
    return frozenset(t for t in (ime or "").lower().split() if t)


def seed_vozaci(db: Session) -> None:
    """Jednokratno napuni šifrarnik vozača iz priložene datoteke (ako je prazan
    ili nedostaju neki). Postojeće (po skupu riječi imena) ne dira."""
    if not _SEED.is_file():
        return
    try:
        podaci = json.loads(_SEED.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        log.warning("Ne mogu učitati seed vozača: %s", e)
        return
    postojeci = {_kljuc(v.ime) for v in db.execute(select(Vozac)).scalars().all()}
    dodano = 0
    for r in podaci:
        ime = (r.get("ime") or "").strip()
        if not ime:
            continue
        k = _kljuc(ime)
        if k in postojeci:
            continue
        db.add(Vozac(
            ime=ime,
            sektor=(r.get("sektor") or None),
            telefon=(r.get("telefon") or None),
            aktivan=True,
            izvor="seed",
        ))
        postojeci.add(k)
        dodano += 1
    if dodano:
        db.commit()
        log.info("Seed vozača: dodano %d vozača.", dodano)


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
