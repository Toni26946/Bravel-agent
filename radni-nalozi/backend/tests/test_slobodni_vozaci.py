"""Slobodni vozači (WhatsApp #328/#331): upis, veza na vozilo po GB-u, dvojnik, zatvaranje, pristup."""
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import imenik
from app.database import Base
from app.models import Korisnik, Nalog, RegistarVozila, StatusNaloga, Uloga, Vozilo
from app.routers import slobodni_vozaci as sv


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _okolina(db, monkeypatch):
    monkeypatch.setattr(imenik, "vozaci_imena", lambda: ["Ivić Ivo", "Anić Ana"])
    vod = Korisnik(ime="Veljko", korisnicko_ime="veljko", lozinka_hash="x", uloga=Uloga.poslovodja)
    db.add(vod)
    db.add_all([RegistarVozila(gb="433", kategorija="kamion", vozilo="VOLVO FH 460"),
                RegistarVozila(gb="200", kategorija="prikolica")])
    v = Vozilo(gb="433")
    db.add(v)
    db.flush()
    db.add(Nalog(broj="RN-7", vozilo_id=v.id, naslov="kvar", kreirao_id=vod.id, status=StatusNaloga.u_radu))
    db.commit()
    return vod


def test_upis_veza_po_gb_dvojnik_i_zatvaranje(monkeypatch):
    db = _db()
    vod = _okolina(db, monkeypatch)

    z = sv.dodaj(sv.SlobodanIn(vozac="  Ivić   Ivo ", gb=" 0433", razlog="popravak", napomena="kočnice"),
                 db=db, k=vod)
    assert z["vozac"] == "Ivić Ivo" and z["gb"] == "433" and z["razlog"] == "POPRAVAK"
    assert z["od"] == date.today().isoformat() and z["autor"] == "Veljko"
    assert z["vozilo"]["vozilo"] == "VOLVO FH 460" and z["vozilo"]["nalog"]["broj"] == "RN-7"

    # Isti vozač ne smije imati dvije aktivne prijave.
    with pytest.raises(HTTPException) as e:
        sv.dodaj(sv.SlobodanIn(vozac="ivić ivo", razlog="SLOBODAN"), db=db, k=vod)
    assert e.value.status_code == 409

    # Krivi razlog i datum „do" prije „od" se odbijaju.
    with pytest.raises(HTTPException):
        sv.dodaj(sv.SlobodanIn(vozac="Anić Ana", razlog="GODIŠNJI"), db=db, k=vod)
    with pytest.raises(HTTPException):
        sv.dodaj(sv.SlobodanIn(vozac="Anić Ana", razlog="SLOBODAN", od=date(2026, 11, 19),
                               do=date(2026, 11, 18)), db=db, k=vod)

    sv.dodaj(sv.SlobodanIn(vozac="Anić Ana", razlog="SLOBODAN"), db=db, k=vod)
    p = sv.popis(sve=False, db=db)
    assert [x["vozac"] for x in p["zapisi"]] == ["Ivić Ivo", "Anić Ana"]   # popravak prije slobodnih
    assert p["gbovi"] == ["433"]                                         # samo kamioni
    assert p["vozaci"] == ["Ivić Ivo", "Anić Ana"]

    # Izmjena: ostaje isti zapis.
    u = sv.uredi(z["id"], sv.SlobodanIn(vozac="Ivić Ivo", gb="433", razlog="POPRAVAK",
                                        do=date(2030, 1, 1)), db=db, k=vod)
    assert u["id"] == z["id"] and u["do"] == "2030-01-01"

    # Opet vozi → ispada iz aktivnih, ostaje u povijesti; tada ga se smije ponovno upisati.
    zat = sv.zatvori(z["id"], db=db, k=vod)
    assert zat["aktivan"] is False and zat["zatvorio"] == "Veljko"
    assert [x["vozac"] for x in sv.popis(sve=False, db=db)["zapisi"]] == ["Anić Ana"]
    assert len(sv.popis(sve=True, db=db)["zapisi"]) == 2
    with pytest.raises(HTTPException):
        sv.zatvori(z["id"], db=db, k=vod)
    sv.dodaj(sv.SlobodanIn(vozac="Ivić Ivo", razlog="SLOBODAN"), db=db, k=vod)


def test_pristup():
    rad = Korisnik(ime="M", korisnicko_ime="m", lozinka_hash="x", uloga=Uloga.radnik)
    assert not sv.ima_pristup(rad)
    rad.moduli = ["/slobodni-vozaci"]
    assert sv.ima_pristup(rad)
    assert sv.ima_pristup(Korisnik(ime="V", korisnicko_ime="v", lozinka_hash="x", uloga=Uloga.voditelj))
