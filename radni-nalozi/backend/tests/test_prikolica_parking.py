"""Prikolica prikačena na kamion se može otkačiti i ostaviti na parkingu (WhatsApp #297):
dnevnik dobije otkačeno s lokacijom, a registar vozila zapamti gdje stoji."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, RegistarVozila, Uloga
from app.routers.vozila import dodaj_dogadaj, prikapcanje_trenutno
from app.schemas import DogadajCreate


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_otkaci_na_parking_pamti_lokaciju():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add_all([vod, RegistarVozila(gb="458", kategorija="prikolica"),
                RegistarVozila(gb="156", kategorija="kamion")])
    db.commit()

    dodaj_dogadaj(DogadajCreate(prikolica_gb="458", vrsta="prikaceno", kamion_gb="156"), korisnik=vod, db=db)
    assert [x["prikolica_gb"] for x in prikapcanje_trenutno(korisnik=vod, db=db)] == ["458"]

    d = dodaj_dogadaj(DogadajCreate(prikolica_gb="458", vrsta="otkaceno", kamion_gb="156",
                                    lokacija="Parking Ludbreg"), korisnik=vod, db=db)
    assert d.lokacija == "Parking Ludbreg"
    assert prikapcanje_trenutno(korisnik=vod, db=db) == [], "više nije prikačena"
    assert db.get(RegistarVozila, "458").lokacija == "Parking Ludbreg"


def test_otkaci_bez_lokacije_ne_brise_staru():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add_all([vod, RegistarVozila(gb="250", kategorija="prikolica", lokacija="Stara")])
    db.commit()
    dodaj_dogadaj(DogadajCreate(prikolica_gb="250", vrsta="otkaceno"), korisnik=vod, db=db)
    assert db.get(RegistarVozila, "250").lokacija == "Stara"
