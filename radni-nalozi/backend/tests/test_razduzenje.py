"""Razduženje kamiona/prikolice (Toni 19.11.2026.): povratni obrazac uz zaduženje —
ista vozila, vozač i oprema; uz stavku ostaje što je PREDANO, a bilježi se što je VRAĆENO."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Uloga
from app.routers.zaduzenja import azuriraj, dohvati, kreiraj, popis, razduzi
from app.schemas import ZaduzenjeCreate, ZaduzenjeStavka, ZaduzenjeUpdate


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _vod(db):
    k = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(k); db.flush()
    return k


def test_razduzenje_iz_zaduzenja():
    db = _session()
    vod = _vod(db)
    z = kreiraj(ZaduzenjeCreate(kamion_registracija="ZG1111AA", kamion_gb="210",
                                prikolica_registracija="ZG2222BB", vozac="Ivo Ivić"), db=db, korisnik=vod)
    # predano: prve dvije stavke DA, treća NE
    st = [ZaduzenjeStavka(**s.model_dump()) for s in z.stavke]
    st[0].stanje, st[0].kolicina = "da", 1
    st[1].stanje, st[1].kolicina = "da", 1
    st[2].stanje = "ne"
    azuriraj(z.id, ZaduzenjeUpdate(stavke=st, status="zavrseno"), db=db, _=vod)

    r = razduzi(z.id, db=db, korisnik=vod)
    assert r.vrsta == "razduzenje" and r.zaduzenje_id == z.id
    assert r.kamion_registracija == "ZG1111AA" and r.kamion_gb == "210" and r.vozac == "Ivo Ivić"
    assert r.predao == "Ivo Ivić", "kod razduženja vozilo predaje vozač"
    assert r.status == "u_tijeku"
    assert [s.predano_stanje for s in r.stavke[:3]] == ["da", "da", "ne"]
    assert all(s.stanje == "" for s in r.stavke), "vraćeno se tek označava"
    assert len(r.stavke) == len(z.stavke)

    # zaduženje sad pokazuje svoje razduženje; ponovni klik ne radi duplikat
    assert dohvati(z.id, db=db, _=vod).razduzenje_id == r.id
    assert razduzi(z.id, db=db, korisnik=vod).id == r.id
    assert sum(1 for x in popis(db=db, _=vod) if x.vrsta == "razduzenje") == 1

    # označi vraćeno — predano ostaje sačuvano
    rs = [ZaduzenjeStavka(**s.model_dump()) for s in r.stavke]
    rs[0].stanje = "da"
    rs[1].stanje = "ne"   # fali
    r2 = azuriraj(r.id, ZaduzenjeUpdate(stavke=rs), db=db, _=vod)
    assert r2.stavke[1].stanje == "ne" and r2.stavke[1].predano_stanje == "da"


def test_razduzenje_od_razduzenja_ne_moze():
    db = _session()
    vod = _vod(db)
    z = kreiraj(ZaduzenjeCreate(kamion_registracija="A", prikolica_registracija="B", vozac="V"), db=db, korisnik=vod)
    r = razduzi(z.id, db=db, korisnik=vod)
    try:
        razduzi(r.id, db=db, korisnik=vod)
        assert False, "očekivana greška"
    except HTTPException as e:
        assert e.status_code == 400


def test_samostalno_razduzenje():
    db = _session()
    vod = _vod(db)
    r = kreiraj(ZaduzenjeCreate(kamion_registracija="A", prikolica_registracija="B", vozac="V",
                                vrsta="razduzenje"), db=db, korisnik=vod)
    assert r.vrsta == "razduzenje" and r.zaduzenje_id is None and len(r.stavke) > 0
