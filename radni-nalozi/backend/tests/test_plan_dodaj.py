"""Test „Dodaj vozilo" u plan (/plan/dodaj) — WhatsApp #394.

GB 162 je javljao „dodan u plan", a u planu ga nije bilo: od više aktivnih naloga
istog GB-a uzimao se prvi (stari, svi zadaci gotovi), a plan takav ne prikazuje."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.routers import plan as plan_mod
from app.routers.plan import DodajIn, dodaj_u_plan


@pytest.fixture(autouse=True)
def _bez_popune(monkeypatch):
    import app.auto_popuni as ap
    monkeypatch.setattr(ap, "popuni_tiho", lambda db: None)


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _nalog(db, vod, voz, broj, gotovo, status=StatusNaloga.u_radu):
    n = Nalog(broj=broj, vozilo_id=voz.id, naslov="x", kreirao_id=vod.id, status=status)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="GUME", redoslijed=0); db.add(op); db.flush()
    db.add(Zadatak(operacija_id=op.id, opis="z", gotovo=gotovo)); db.flush()
    return n


def _osnova():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    voz = Vozilo(gb="162", marka="MAN")
    db.add_all([vod, voz]); db.flush()
    return db, vod, voz


def test_bira_nalog_s_nedovrsenim_zadatkom():
    db, vod, voz = _osnova()
    stari = _nalog(db, vod, voz, "RN-1", gotovo=True)     # stari, sve gotovo
    novi = _nalog(db, vod, voz, "RN-2", gotovo=False)
    db.commit()
    rez = dodaj_u_plan(DodajIn(gb="162"), _=vod, db=db)
    db.refresh(stari); db.refresh(novi)
    assert rez["id"] == novi.id
    assert novi.plan_rang == 0 and stari.plan_rang is None


def test_sve_gotovo_javlja_gresku_umjesto_dodan():
    db, vod, voz = _osnova()
    n = _nalog(db, vod, voz, "RN-1", gotovo=True)
    db.commit()
    with pytest.raises(HTTPException) as e:
        dodaj_u_plan(DodajIn(gb="162"), _=vod, db=db)
    assert e.value.status_code == 409 and "gotovi" in e.value.detail
    db.refresh(n)
    assert n.plan_rang is None


def test_ceka_dijelove_napomena():
    db, vod, voz = _osnova()
    _nalog(db, vod, voz, "RN-1", gotovo=False, status=StatusNaloga.ceka_dijelove)
    db.commit()
    rez = dodaj_u_plan(DodajIn(gb="0162"), _=vod, db=db)
    assert rez["ok"] and "dijelove" in (rez["napomena"] or "")


def test_bez_zadataka_ide_u_plan():
    db, vod, voz = _osnova()
    n = Nalog(broj="RN-1", vozilo_id=voz.id, naslov="x", kreirao_id=vod.id, status=StatusNaloga.otvoren)
    db.add(n); db.commit()
    rez = dodaj_u_plan(DodajIn(gb="162"), _=vod, db=db)
    assert rez["id"] == n.id and rez["napomena"] is None
