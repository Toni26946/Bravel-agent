"""Registar vozila RN se puni iz Flota OS-a (šifrarnik Garažni brojevi je glavni, 24.11.2026.).

- novo vozilo iz Flote se pojavi u registru s matičnim podacima;
- Flota prepisuje što ima, prazno iz Flote NE briše postojeće RN podatke.
"""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import RegistarVozila
from app.routers import vozila as vozila_router


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_novo_vozilo_iz_flote_i_ne_brisi(monkeypatch):
    db = _session()
    db.add(RegistarVozila(gb="501", registracija="ZG1111AA", vozilo="MERCEDES AROCS",
                          broj_sasije="WDB964", vrsta="Šumar"))
    db.commit()

    async def lazna_flota():
        return [
            {"gb": "999", "reg": "ZG9999ZZ", "tip": "KAMION", "kategorija": "kamion", "status": "aktivno",
             "vozilo": "VOLVO FH 500", "vrsta": "TEGLJAČ", "prva_registracija": "2026",
             "firma": "BRAVEL", "broj_sasije": "YV2TEST"},
            {"gb": "501", "reg": None, "tip": "KAMION", "kategorija": "kamion", "status": None,
             "firma": "BRAVEL"},
        ]
    monkeypatch.setattr(vozila_router.flota, "vozila_flota", lazna_flota)
    assert asyncio.run(vozila_router._sync_registar(db)) is True

    novo = db.get(RegistarVozila, "999")
    assert novo is not None
    assert (novo.registracija, novo.vozilo, novo.vrsta, novo.broj_sasije, novo.firma) == \
        ("ZG9999ZZ", "VOLVO FH 500", "TEGLJAČ", "YV2TEST", "BRAVEL")

    staro = db.get(RegistarVozila, "501")
    assert staro.registracija == "ZG1111AA", "prazna reg iz Flote ne smije obrisati RN reg"
    assert staro.vozilo == "MERCEDES AROCS" and staro.broj_sasije == "WDB964"
    assert staro.firma == "BRAVEL", "što Flota ima, to upiše"
