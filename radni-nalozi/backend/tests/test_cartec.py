"""Cartec valjci: mjerenja s računala u radioni → testovi kočnica vezani uz nalog/GB."""
import os
import sys
from datetime import datetime, timedelta, timezone
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
from app.models import TestKocnica as _Test
from app.routers import cartec
from app.routers.cartec import MjerenjeIn, OdobriIn, PrijavaIn, VeziIn

T0 = datetime(2026, 11, 17, 13, 4, 47, tzinfo=timezone.utc)


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _okolina(db):
    vod = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vod)
    db.commit()
    tok = cartec.prijava_uredjaja(PrijavaIn(naziv="Valjci"), db=db)["token"]
    cartec.odobri_uredjaj(1, OdobriIn(odobren=True), db=db, _=vod)
    return vod, tok


def _nalog(db, vod, gb, broj, u_radu=False, kategorija="Servis"):
    v = Vozilo(gb=gb)
    db.add(v)
    db.flush()
    n = Nalog(broj=broj, vozilo_id=v.id, naslov="x", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(n)
    db.flush()
    op = Operacija(nalog_id=n.id, kategorija=kategorija)
    db.add(op)
    db.flush()
    db.add(Zadatak(operacija_id=op.id, opis="posao", zapoceto=(T0 if u_radu else None)))
    db.commit()
    return n


def _lista(db, k, status=None):
    return cartec.testovi(status=status, nalog_id=None, gb=None, limit=50, db=db, k=k)


def _m(osovina, l, d, t=T0, vrsta="radna", sesija="2026-11-17 14:01:29", otisak=None):
    return MjerenjeIn(sesija=sesija, osovina=osovina, vrsta=vrsta, vrijeme=t,
                      sila_lijevo=l, sila_desno=d, otisak=otisak or f"o{osovina}{vrsta}{l}{d}{t.timestamp()}")


def test_neodobren_uredjaj_odbijen():
    db = _db()
    tok = cartec.prijava_uredjaja(PrijavaIn(), db=db)["token"]
    with pytest.raises(HTTPException) as e:
        cartec.primi_mjerenje(_m(1, 100, 100), x_cartec_token=tok, db=db)
    assert e.value.status_code == 403


def test_veze_uz_nalog_u_radu_i_zadnje_mjerenje_vrijedi():
    db = _db()
    vod, tok = _okolina(db)
    n = _nalog(db, vod, "458", "RN-1", u_radu=True)
    _nalog(db, vod, "156", "RN-2", u_radu=False)
    r = cartec.primi_mjerenje(_m(1, 1849, 1721), x_cartec_token=tok, db=db)
    assert r["status"] == "vezan" and r["nalog_id"] == n.id and r["gb"] == "458"
    cartec.primi_mjerenje(_m(2, 4459, 4280, T0 + timedelta(minutes=3)), x_cartec_token=tok, db=db)
    # mehaničar ponovi osovinu 2
    cartec.primi_mjerenje(_m(2, 4614, 5681, T0 + timedelta(minutes=8)), x_cartec_token=tok, db=db)
    # isto mjerenje stiglo dvaput → ne duplicira
    dup = cartec.primi_mjerenje(_m(2, 4614, 5681, T0 + timedelta(minutes=8)), x_cartec_token=tok, db=db)
    assert dup.get("duplikat")
    [t] = _lista(db, vod)
    o2 = [m for m in t["mjerenja"] if m["osovina"] == 2]
    assert len(o2) == 2 and [m["vazece"] for m in o2] == [False, True]
    zadnje = [m for m in o2 if m["vazece"]][0]
    assert (zadnje["sila_lijevo"], zadnje["sila_desno"], zadnje["razlika_pct"]) == (4614, 5681, 18.8)
    assert t["osovina"] == 2


def test_vise_mogucih_vozila_nerazvrstan_i_blokira_zatvaranje():
    db = _db()
    vod, tok = _okolina(db)
    a = _nalog(db, vod, "458", "RN-1", u_radu=True)
    b = _nalog(db, vod, "156", "RN-2", u_radu=True)
    r = cartec.primi_mjerenje(_m(1, 500, 500), x_cartec_token=tok, db=db)
    assert r["status"] == "nerazvrstan" and r["nalog_id"] is None
    [t] = _lista(db, vod, "otvoreni")
    assert {x["id"] for x in t["kandidati"]} == {a.id, b.id}
    assert cartec.blokira_zatvaranje(db, a.id) is not None
    cartec.vezi_test(t["id"], VeziIn(nalog_id=b.id), db=db, k=vod)
    assert cartec.blokira_zatvaranje(db, a.id) is None
    t2 = db.get(_Test, t["id"])
    assert (t2.status, t2.gb) == ("vezan", "156")


def test_nova_sesija_je_novi_test():
    db = _db()
    vod, tok = _okolina(db)
    _nalog(db, vod, "458", "RN-1", u_radu=True)
    cartec.primi_mjerenje(_m(1, 500, 500), x_cartec_token=tok, db=db)
    cartec.primi_mjerenje(_m(1, 600, 600, T0 + timedelta(minutes=20), sesija="2026-11-17 14:30:00"),
                          x_cartec_token=tok, db=db)
    assert len(_lista(db, vod)) == 2


def test_vise_osovina_nego_prosli_put_trazi_potvrdu():
    db = _db()
    vod, tok = _okolina(db)
    n = _nalog(db, vod, "458", "RN-1", u_radu=True)
    for i in (1, 2):
        cartec.primi_mjerenje(_m(i, 500, 500, sesija="s1"), x_cartec_token=tok, db=db)
    kasnije = T0 + timedelta(days=30)
    r = None
    for i in (1, 2, 3):
        r = cartec.primi_mjerenje(_m(i, 500, 500, kasnije + timedelta(minutes=i), sesija="s2"),
                                  x_cartec_token=tok, db=db)
    assert r["status"] == "ceka_potvrdu"
    assert cartec.blokira_zatvaranje(db, n.id) is not None


def test_stanje_i_skripta_za_samoazuriranje():
    db = _db()
    tok = cartec.prijava_uredjaja(PrijavaIn(), db=db)["token"]
    # neodobren smije javiti stanje, ali ne smije dohvatiti skriptu
    r = cartec.javi_stanje(cartec.StanjeIn(verzija="2", dnevnik="red1\nred2"), x_cartec_token=tok, db=db)
    assert r == {"ok": True, "odobren": False}
    with pytest.raises(HTTPException):
        cartec.skripta(x_cartec_token=tok, db=db)
    vod = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vod)
    db.commit()
    cartec.odobri_uredjaj(1, OdobriIn(odobren=True), db=db, _=vod)
    s = cartec.skripta(x_cartec_token=tok, db=db)
    assert s["verzija"] and int(s["verzija"]) >= 2 and "AxleData" in s["sadrzaj"]
    [u] = cartec.uredjaji(db=db, _=vod)
    assert u["verzija"] == "2" and "red2" in u["stanje"]
