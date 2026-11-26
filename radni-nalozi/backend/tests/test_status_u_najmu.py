"""Status vozila „U najmu" (Veljko 26.11.2026., WhatsApp #432): vozilo iznajmljeno drugoj
firmi se u matičnom popisu označi ručno; na Postgresu se vrijednost mora dodati u enum."""
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.migrate import migrate
from app.models import Korisnik, RegistarVozila, StatusVozila, Uloga
from app.podsjetnici import _rijeseno
from app.routers import vozila as v
from app.schemas import RegistarStatusUpdate


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_rucno_postavi_u_najmu():
    db = _session()
    k = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(k)
    db.add(RegistarVozila(gb="77", kategorija="kamion", status=StatusVozila.aktivno))
    db.commit()
    out = v.registar_status("77", RegistarStatusUpdate(status="u_najmu"), korisnik=k, db=db)
    assert out.status == "u_najmu"
    r = db.get(RegistarVozila, "77")
    assert r.status == StatusVozila.u_najmu and r.rucno is True


def test_slepa_u_najmu_ne_trazi_upis_spremnosti():
    r = RegistarVozila(gb="15", kategorija="prikolica", status=StatusVozila.u_najmu)
    assert _rijeseno(r)


_PG = (os.environ.get("TEST_DATABASE_URL") or "").strip()


@pytest.mark.skipif(not _PG, reason="Samo uz TEST_DATABASE_URL (pravi Postgres u CI-ju)")
def test_postgres_migracija_dodaje_u_najmu():
    """Produkcijska baza ima enum bez „u_najmu" → migrate ga mora dodati, pa upis prolazi."""
    url = _PG.replace("postgres://", "postgresql://", 1) if _PG.startswith("postgres://") else _PG
    eng = create_engine(url)
    with eng.begin() as c:
        c.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        c.exec_driver_sql("CREATE SCHEMA public")
    Base.metadata.create_all(eng)
    # Simuliraj staru bazu: enum bez nove vrijednosti.
    with eng.begin() as c:
        c.exec_driver_sql("ALTER TABLE registar_vozila ALTER COLUMN status TYPE VARCHAR(20)")
        c.exec_driver_sql("DROP TYPE statusvozila")
        c.exec_driver_sql("CREATE TYPE statusvozila AS ENUM "
                          "('aktivno','u_radionici','pokvareno','prodano','nezaduzeno','spremno')")
        c.exec_driver_sql("ALTER TABLE registar_vozila ALTER COLUMN status TYPE statusvozila "
                          "USING status::statusvozila")
    migrate(eng)
    migrate(eng)  # idempotentno
    db = sessionmaker(bind=eng, autoflush=False)()
    try:
        db.add(RegistarVozila(gb="88", status=StatusVozila.u_najmu))
        db.commit()
        assert db.get(RegistarVozila, "88").status == StatusVozila.u_najmu
    finally:
        db.close()
        eng.dispose()
