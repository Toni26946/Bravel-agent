"""Povijest vozač ↔ vozilo iz Flota OS-a (Veljko 26.11.2026., WhatsApp #437)."""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import HTTPException

from app import flota
from app.routers import vozila


def test_ruta_prosljeduje_gb_i_vozaca(monkeypatch):
    pozivi = []

    async def lazna(gb=None, vozac=None):
        pozivi.append((gb, vozac))
        return {"od": "2025-11-26", "razdoblja": [{"gb": "433", "vozac": "Regojević Krstan",
                                                    "od": "2026-11-01", "do": "2026-11-02", "dana": 2, "km": 160}]}

    monkeypatch.setattr(flota, "povijest_vozaca", lazna)
    d = asyncio.run(vozila.povijest_vozaca(gb=" 433 ", vozac=None, _=None, db=None))
    assert d["gb"] == "433" and d["razdoblja"][0]["vozac"] == "Regojević Krstan"
    asyncio.run(vozila.povijest_vozaca(gb=None, vozac="regoj", _=None, db=None))
    assert pozivi == [("433", None), (None, "regoj")]


def test_ruta_bez_upita_i_kad_flota_suti(monkeypatch):
    with pytest.raises(HTTPException) as e:
        asyncio.run(vozila.povijest_vozaca(gb="", vozac=" ", _=None, db=None))
    assert e.value.status_code == 400

    async def nema(gb=None, vozac=None):
        return None
    monkeypatch.setattr(flota, "povijest_vozaca", nema)
    with pytest.raises(HTTPException) as e:
        asyncio.run(vozila.povijest_vozaca(gb="433", vozac=None, _=None, db=None))
    assert e.value.status_code == 503


def test_prikolica_iz_dnevnika_prikapcanja():
    from datetime import datetime, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    from app.models import DnevnikPrikapcanja, RegistarVozila, VrstaDogadaja
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, autoflush=False)()
    db.add(RegistarVozila(gb="81", kategorija="prikolica"))
    db.add_all([
        DnevnikPrikapcanja(prikolica_gb="81", vrsta=VrstaDogadaja.prikaceno, kamion_gb="433", vozac="Horvat Ivan",
                           vrijeme=datetime(2026, 11, 1, 8, tzinfo=timezone.utc)),
        DnevnikPrikapcanja(prikolica_gb="81", vrsta=VrstaDogadaja.otkaceno,
                           vrijeme=datetime(2026, 11, 5, 8, tzinfo=timezone.utc)),
        DnevnikPrikapcanja(prikolica_gb="81", vrsta=VrstaDogadaja.prikaceno, kamion_gb="440", vozac="Kovač Ana",
                           vrijeme=datetime(2026, 11, 10, 8, tzinfo=timezone.utc)),
    ])
    db.commit()
    d = asyncio.run(vozila.povijest_vozaca(gb="81", vozac=None, _=None, db=db))
    assert d["prikolica"] is True
    r = d["razdoblja"]
    assert [(x["vozac"], x["kamion_gb"], x["od"], x["traje"]) for x in r] == [
        ("Kovač Ana", "440", "2026-11-10", True), ("Horvat Ivan", "433", "2026-11-01", False)]
    assert r[1]["do"] == "2026-11-05" and r[1]["dana"] == 5
