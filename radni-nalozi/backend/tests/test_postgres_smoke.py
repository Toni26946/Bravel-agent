"""Postgres smoke-test — vrti VRUĆE putanje na PRAVOM Postgresu (ne SQLiteu).

Zašto postoji: produkcija je Postgres, a ostali testovi rade na in-memory SQLiteu.
SQLite je popustljiv pa propušta greške koje Postgres odbija — npr. `SELECT DISTINCT`
nad tablicom koja ima `json` stupac („could not identify an equality operator for
type json"). Takva je greška 12.11.2026. srušila prijavu mehaničara (500) iako je
svih 83 SQLite testa prolazilo.

Pokreće se SAMO kad je postavljen `TEST_DATABASE_URL` (pravi Postgres u GitHub
Actionsu). Lokalno bez njega se preskače, pa `pytest` ostaje brz.

Pokriva obje prijavljene putanje koje su pucale:
  • mehaničar sam klikne „Počinjem"  → z_pocinjem
  • dispečer ga ručno prijavi         → prijavi_rucno
Obje idu kroz _pokreni_mjerac → _zaustavi_druge_mjerace (upit koji je rušio),
a mehaničar ima DRUGI već-pokrenuti zadatak s popunjenim `dijelovi_foto` (JSON)
— točno uvjet pod kojim je stari DISTINCT pucao.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_PG = (os.environ.get("TEST_DATABASE_URL") or "").strip()
# App gradi svoj modul-level engine iz DATABASE_URL pri importu; postavimo ga na
# bezopasan sqlite (ne koristimo ga — za Postgres gradimo vlastiti engine dolje).
os.environ.setdefault("DATABASE_URL", "sqlite://")

pytestmark = pytest.mark.skipif(
    not _PG, reason="Samo uz TEST_DATABASE_URL (pravi Postgres u CI-ju)"
)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401  — registriraj sve tablice/enume na Base.metadata
from app.models import (
    Korisnik, KlikRucno, MehanicarLink, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak,
)


def _engine():
    url = _PG
    if url.startswith("postgres://"):   # fly/heroku stil → SQLAlchemy 2.0 traži postgresql://
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _svjeza_sesija():
    """Čista baza na Postgresu za svaki test (serijski, prethodna sesija se zatvori).

    Resetiramo cijelu `public` shemu umjesto `Base.metadata.drop_all` jer modeli imaju
    međusobni FK ciklus (nalozi ↔ prijave) koji SQLAlchemyjev uredni drop ne zna složiti
    (CircularDependencyError). `DROP SCHEMA ... CASCADE` to zaobiđe i pobriše i enum tipove."""
    eng = _engine()
    with eng.begin() as c:
        c.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        c.exec_driver_sql("CREATE SCHEMA public")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _priprema(db):
    """Mehaničar s DVA zadatka: jedan već pokrenut (nosi dijelovi_foto JSON) i jedan
    koji čeka potvrdu (njega pokrećemo). Vrati (voditelj, mehaničar, z_ceka, z_pokrenut)."""
    vod = Korisnik(ime="Voditelj", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    meh = Korisnik(ime="Miloš Test", korisnicko_ime="milos.test", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="491", registracija="ZG0491TT", marka="MAN", model="TGS")
    db.add_all([vod, meh, voz]); db.flush()
    nalog = Nalog(broj="RN-PG-1", vozilo_id=voz.id, naslov="Smoke", kreirao_id=vod.id,
                  status=StatusNaloga.u_radu)
    db.add(nalog); db.flush()
    op1 = Operacija(nalog_id=nalog.id, kategorija="KOČNICE", redoslijed=1)
    op2 = Operacija(nalog_id=nalog.id, kategorija="MOTOR", redoslijed=2)
    db.add_all([op1, op2]); db.flush()
    # Zadatak koji pokrećemo (čeka potvrdu).
    z_ceka = Zadatak(operacija_id=op1.id, opis="Zamjena pločica", ceka_potvrdu=True)
    z_ceka.radnici = [meh]
    # DRUGI zadatak — već pokrenut, s popunjenim JSON stupcem dijelovi_foto.
    # Upravo ovaj redak je stari `SELECT DISTINCT` pokušavao usporediti → 500 na Postgresu.
    z_pokrenut = Zadatak(operacija_id=op2.id, opis="Nešto drugo",
                         zapoceto=datetime.now(timezone.utc) - timedelta(minutes=5),
                         dijelovi_foto=["/foto/dio1.jpg", "/foto/dio2.jpg"])
    z_pokrenut.radnici = [meh]
    db.add_all([z_ceka, z_pokrenut])
    db.add(MehanicarLink(radnik_id=meh.id, token="smoke-tok", aktivan=True))
    db.commit()
    return vod, meh, z_ceka, z_pokrenut


def test_pocinjem_na_postgresu_ne_pukne():
    """Mehaničar klikne „Počinjem" — na Postgresu NE smije pući (bivši 500)."""
    from app.routers.dispecer import UredjajIn, z_pocinjem
    db = _svjeza_sesija()
    try:
        _, _, z_ceka, z_pokrenut = _priprema(db)
        # Da nije popravljeno, interni upit (_zaustavi_druge_mjerace: join nad zadacima
        # koji nose dijelovi_foto JSON) bi na Postgresu pukao s 500 → test bi se srušio.
        rez = z_pocinjem("smoke-tok", UredjajIn(uredjaj="A"), db=db)
        assert rez["stanje"] == "radu", "Počinjem mora pokrenuti mjerač"
        db.refresh(z_ceka)
        assert z_ceka.zapoceto is not None, "mjerač pokrenutog zadatka mora teći"
    finally:
        db.close()


def test_prijavi_rucno_na_postgresu_ne_pukne():
    """Dispečer ručno prijavi mehaničara — na Postgresu NE smije pući (bivši 500)."""
    from app.routers.plan import PrijaviRucnoIn, prijavi_rucno
    db = _svjeza_sesija()
    try:
        vod, meh, z_ceka, z_pokrenut = _priprema(db)
        rez = prijavi_rucno(z_ceka.id, PrijaviRucnoIn(radnik_id=meh.id), korisnik=vod, db=db)
        assert rez["ok"] is True
        db.refresh(z_ceka)
        assert z_ceka.zapoceto is not None, "ručna prijava mora pokrenuti mjerač"
        assert db.query(KlikRucno).count() == 1, "ručna prijava se bilježi (klik-bonus)"
    finally:
        db.close()
