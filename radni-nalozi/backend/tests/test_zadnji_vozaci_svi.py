"""Ime zadnjeg vozača uz GB na svim ekranima (Veljko 26.11.2026., WhatsApp #436)."""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import flota, zadnji_vozaci
from app.database import Base
from app.models import DnevnikPrikapcanja, RegistarVozila, VrstaDogadaja


@pytest.fixture(autouse=True)
def _cisti_kes():
    flota._vozaci_kes.clear()
    flota._vozaci_trazeni.clear()
    yield
    flota._vozaci_kes.clear()
    flota._vozaci_trazeni.clear()


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_svi_kamion_prikolica_i_rezerva():
    db = _session()
    db.add_all([
        RegistarVozila(gb="134", kategorija="kamion"),
        RegistarVozila(gb="200", kategorija="kamion", vozac="Iz Registra"),
        RegistarVozila(gb="81", kategorija="prikolica"),
        RegistarVozila(gb="90", kategorija="prikolica"),
    ])
    sada = datetime.now(timezone.utc)
    db.add_all([
        DnevnikPrikapcanja(prikolica_gb="81", vrsta=VrstaDogadaja.prikaceno, kamion_gb="134",
                           vozac="Stari", vrijeme=sada - timedelta(days=3)),
        DnevnikPrikapcanja(prikolica_gb="81", vrsta=VrstaDogadaja.prikaceno, kamion_gb="134",
                           vozac=None, vrijeme=sada - timedelta(days=1)),
    ])
    db.commit()
    flota._vozaci_kes["134"] = (time.monotonic(), "Horvat Ivan")

    m = zadnji_vozaci.svi(db)
    assert m["134"] == "Horvat Ivan"            # kamion → Flota (keš)
    assert m["200"] == "Iz Registra"            # nema u kešu → rezerva iz registra
    assert m["81"] == "Horvat Ivan"             # zadnje prikapčanje bez imena → vozač kamiona
    assert "90" not in m                        # prikolica bez prikapčanja → ništa
    assert "200" in flota._vozaci_trazeni       # kamion bez keša ide u red za dohvat


def test_ruta_vraca_mapu():
    from app.routers import vozila
    db = _session()
    db.add(RegistarVozila(gb="7", kategorija="kamion", vozac="Kovač Ana"))
    db.commit()
    assert vozila.zadnji_vozaci_svi(None, db) == {"7": "Kovač Ana"}
