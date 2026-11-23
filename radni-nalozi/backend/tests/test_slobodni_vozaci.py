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
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import imenik
from app.database import Base
from app.models import Korisnik, Nalog, RegistarVozila, SlobodanVozac, StatusNaloga, Uloga, Vozilo
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


class _LaznaFlota:
    """Flota OS u memoriji: ista pravila kao prava (dvojnik → 400, zatvaranje zatvorenog → 400)."""

    def __init__(self):
        self.z, self.n = [], 0

    def __call__(self, metoda, putanja, json=None, params=None):
        if metoda == "GET":
            sve = (params or {}).get("sve") == "true"
            return {"zapisi": [dict(x) for x in self.z if sve or x["aktivan"]]}
        if putanja.endswith("/zatvori"):
            rid = int(putanja.split("/")[1])
            x = next((x for x in self.z if x["id"] == rid and x["aktivan"]), None)
            if not x:
                raise HTTPException(status_code=422, detail="Zapis ne postoji ili je već zatvoren.")
            x.update(aktivan=False, zatvoreno=1795000000.0, zatvorio=f"Radni nalozi · {params['korisnik_rn']}")
            return {"ok": True}
        d = dict(json)
        if any(x["aktivan"] and x["vozac"].lower() == d["vozac"].lower() and x["id"] != d.get("id") for x in self.z):
            raise HTTPException(status_code=409, detail=f"{d['vozac']} je već na popisu slobodnih.")
        autor = f"Radni nalozi · {d.pop('korisnik', None)}"
        if d.get("id"):
            x = next(x for x in self.z if x["id"] == d["id"])
            x.update({**d, "autor": autor})
            return {"ok": True, "id": x["id"]}
        self.n += 1
        self.z.append({**d, "id": self.n, "aktivan": True, "autor": autor, "prijavljeno": 1795000000.0,
                       "zatvoreno": None, "zatvorio": None})
        return {"ok": True, "id": self.n}


def test_upis_veza_po_gb_dvojnik_i_zatvaranje(monkeypatch):
    db = _db()
    vod = _okolina(db, monkeypatch)
    fl = _LaznaFlota()
    monkeypatch.setattr(sv, "_flota", fl)

    z = sv.dodaj(sv.SlobodanIn(vozac="  Ivić   Ivo ", gb=" 0433", razlog="popravak", napomena="kočnice"),
                 db=db, k=vod)
    assert z["vozac"] == "Ivić Ivo" and z["gb"] == "433" and z["razlog"] == "POPRAVAK"
    assert z["od"] == date.today().isoformat() and z["autor"] == "Radni nalozi · Veljko"
    assert z["vozilo"]["vozilo"] == "VOLVO FH 460" and z["vozilo"]["nalog"]["broj"] == "RN-7"
    assert z["prijavljeno"].startswith("2026-")

    # Isti vozač ne smije imati dvije aktivne prijave (Flota odbija → 409).
    with pytest.raises(HTTPException) as e:
        sv.dodaj(sv.SlobodanIn(vozac="ivić ivo", razlog="SLOBODAN"), db=db, k=vod)
    assert e.value.status_code == 409

    # Krivi razlog i datum „do" prije „od" se odbijaju već ovdje.
    with pytest.raises(HTTPException):
        sv.dodaj(sv.SlobodanIn(vozac="Anić Ana", razlog="GODIŠNJI"), db=db, k=vod)
    with pytest.raises(HTTPException):
        sv.dodaj(sv.SlobodanIn(vozac="Anić Ana", razlog="SLOBODAN", od=date(2026, 11, 19),
                               do=date(2026, 11, 18)), db=db, k=vod)

    sv.dodaj(sv.SlobodanIn(vozac="Anić Ana", razlog="SLOBODAN"), db=db, k=vod)
    p = sv.popis(sve=False, db=db)
    assert {x["vozac"] for x in p["zapisi"]} == {"Ivić Ivo", "Anić Ana"}
    assert p["gbovi"] == ["433"]                                         # samo kamioni
    assert p["vozaci"] == ["Ivić Ivo", "Anić Ana"]

    # Izmjena: ostaje isti zapis.
    u = sv.uredi(z["id"], sv.SlobodanIn(vozac="Ivić Ivo", gb="433", razlog="POPRAVAK",
                                        do=date(2030, 1, 1)), db=db, k=vod)
    assert u["id"] == z["id"] and u["do"] == "2030-01-01"

    # Opet vozi → ispada iz aktivnih, ostaje u povijesti; tada ga se smije ponovno upisati.
    zat = sv.zatvori(z["id"], db=db, k=vod)
    assert zat["aktivan"] is False and zat["zatvorio"] == "Radni nalozi · Veljko"
    assert [x["vozac"] for x in sv.popis(sve=False, db=db)["zapisi"]] == ["Anić Ana"]
    assert len(sv.popis(sve=True, db=db)["zapisi"]) == 2
    with pytest.raises(HTTPException) as e:
        sv.zatvori(z["id"], db=db, k=vod)
    assert e.value.status_code == 404
    sv.dodaj(sv.SlobodanIn(vozac="Ivić Ivo", razlog="SLOBODAN"), db=db, k=vod)


def test_stare_lokalne_prijave_se_prenesu_u_flotu(monkeypatch):
    """#363/#364: lokalna tablica se jednom prenese u Flotu; vozač kojeg Flota već ima se ne duplicira."""
    db = _db()
    _okolina(db, monkeypatch)
    fl = _LaznaFlota()
    monkeypatch.setattr(sv, "_flota", fl)
    fl("POST", "", json={"vozac": "Khatiwada Chudamani", "gb": "472", "razlog": "POPRAVAK", "korisnik": "Marko"})
    db.add_all([
        SlobodanVozac(vozac="CHUDAMANI KHATIWADA", gb="472", razlog="POPRAVAK", datum_od=date(2026, 11, 20),
                      aktivan=True, autor="Velimir Jendriš"),
        SlobodanVozac(vozac="ZHYLOVSKYI VOLODYMYR", gb="447", razlog="SLOBODAN", datum_od=date(2026, 11, 20),
                      napomena="ispucao dvotjednu vožnju", aktivan=True, autor="Velimir Jendriš"),
    ])
    db.commit()

    p = sv.popis(sve=False, db=db)
    assert sorted(x["vozac"] for x in p["zapisi"]) == ["Khatiwada Chudamani", "ZHYLOVSKYI VOLODYMYR"]
    zh = next(x for x in p["zapisi"] if x["gb"] == "447")
    assert zh["od"] == "2026-11-20" and zh["autor"] == "Radni nalozi · Velimir Jendriš"
    # lokalni zapisi su zatvoreni (ništa obrisano), drugi poziv ništa ne duplicira
    lok = db.execute(select(SlobodanVozac)).scalars().all()
    assert len(lok) == 2 and all(not z.aktivan and z.zatvorio == "Preneseno u Flota OS" for z in lok)
    assert len(sv.popis(sve=False, db=db)["zapisi"]) == 2


def test_flota_nedostupna(monkeypatch):
    db = _db()
    _okolina(db, monkeypatch)
    monkeypatch.setattr(sv.settings, "imenik_kljuc", "")
    with pytest.raises(HTTPException) as e:
        sv.popis(sve=False, db=db)
    assert e.value.status_code == 503


def test_pristup():
    rad = Korisnik(ime="M", korisnicko_ime="m", lozinka_hash="x", uloga=Uloga.radnik)
    assert not sv.ima_pristup(rad)
    rad.moduli = ["/slobodni-vozaci"]
    assert sv.ima_pristup(rad)
    assert sv.ima_pristup(Korisnik(ime="V", korisnicko_ime="v", lozinka_hash="x", uloga=Uloga.voditelj))
