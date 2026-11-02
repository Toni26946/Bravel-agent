"""Samostalni rad (vulkanizer): sam otvori posao, sam se prijavi, pauzira i završi."""
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
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.routers.samostalno import NoviPosao, _samo_samostalni, gotovo, novi_posao, pauza, pocni, stanje


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _vulkanizer(db):
    k = Korisnik(ime="Vulk", korisnicko_ime="vulk", lozinka_hash="x", uloga=Uloga.radnik, moduli=["/samostalno"])
    db.add_all([k, Vozilo(gb="1003", marka="MAN")]); db.commit()
    return k


def test_pristup_samo_s_modulom():
    db = _session()
    obican = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(obican); db.commit()
    try:
        _samo_samostalni(obican)
        raise AssertionError("radnik bez modula ne smije u samostalni rad")
    except HTTPException as e:
        assert e.status_code == 403


def test_tok_novi_pauza_pocni_gotovo():
    db = _session()
    k = _vulkanizer(db)
    r = novi_posao(NoviPosao(gb="1.003", opis="krpanje gume"), k=k, db=db)
    z = db.get(Zadatak, r["zadatak_id"])
    assert z.zapoceto is not None, "mjerač mora odmah krenuti"
    assert [x.id for x in z.radnici] == [k.id]
    assert z.operacija.kategorija == "Gume"
    assert z.operacija.nalog.status == StatusNaloga.u_radu

    # drugi posao na istom kamionu ide u ISTI nalog i pauzira prvi
    r2 = novi_posao(NoviPosao(gb="1003", opis="balansiranje"), k=k, db=db)
    db.refresh(z)
    assert z.zapoceto is None, "prvi posao mora ići u pauzu"
    z2 = db.get(Zadatak, r2["zadatak_id"])
    assert z2.operacija.nalog_id == z.operacija.nalog_id
    assert db.query(Nalog).count() == 1

    pauza(z2.id, k=k, db=db)
    pocni(z.id, k=k, db=db)
    db.refresh(z)
    assert z.zapoceto is not None
    gotovo(z.id, k=k, db=db)
    db.refresh(z)
    assert z.gotovo is True and z.zavrseno is not None

    s = stanje(k=k, db=db)
    assert [x["opis"] for x in s["otvoreni"]] == ["balansiranje"]
    assert [x["opis"] for x in s["danas"]] == ["krpanje gume"]


def test_tudi_zadatak_ne_smije():
    db = _session()
    k = _vulkanizer(db)
    drugi = Korisnik(ime="Drugi", korisnicko_ime="drugi", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(drugi); db.flush()
    n = Nalog(broj="RN-X", vozilo_id=db.query(Vozilo).first().id, naslov="X", kreirao_id=drugi.id)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="tuđe"); z.radnici = [drugi]; db.add(z); db.commit()
    try:
        gotovo(z.id, k=k, db=db)
        raise AssertionError("ne smije završiti tuđi zadatak")
    except HTTPException as e:
        assert e.status_code == 404
