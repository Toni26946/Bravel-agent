"""Skladištar s uključenim „radi na nalozima" (npr. Akshay) smije se dodijeliti na
nalog kao mehaničar i pojavljuje se u popisu radnika; bez oznake ne smije."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Uloga
from app.routers.korisnici import azuriraj, popis
from app.routers.nalozi import _provjeri_radnik, je_serviser
from app.schemas import KorisnikUpdate


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_skladistar_radi_na_nalozima():
    db = _db()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    ak = Korisnik(ime="Konathukatiil Akshay", korisnicko_ime="akshay", lozinka_hash="x",
                  uloga=Uloga.skladistar, prijavljuje_se=False)
    db.add_all([vod, meh, ak]); db.commit()

    # bez oznake: nije mehaničar, nema ga u popisu radnika
    assert not je_serviser(ak)
    with pytest.raises(HTTPException):
        _provjeri_radnik(db, ak.id)
    assert [k.ime for k in popis(uloga=Uloga.radnik, korisnik=vod, db=db)] == ["Meh"]

    # voditelj uključi „radi na nalozima" → prijava se uključi, pojavi se u popisu
    azuriraj(ak.id, KorisnikUpdate(radi_na_nalozima=True), _=vod, db=db)
    db.refresh(ak)
    assert ak.radi_na_nalozima and ak.prijavljuje_se and ak.uloga == Uloga.skladistar
    assert je_serviser(ak)
    _provjeri_radnik(db, ak.id)   # ne baca
    assert {k.ime for k in popis(uloga=Uloga.radnik, korisnik=vod, db=db)} == {"Meh", "Konathukatiil Akshay"}
