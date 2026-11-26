"""GB s cijelim opisom („498 YV2R… VOLVO FH64R  2019.") — isti kamion je bio dvaput
u programu (Davor 26.11.2026.: „duplo otvorene brojeve 503 i 498")."""
import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, RegistarVozila, StatusNaloga, StatusVozila, Uloga, Vozilo
from app.routers import vozila as v


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_cisti_gb():
    assert v.cisti_gb("498 YV2R002D3LA858297 VOLVO FH64R  2019.") == "498"
    assert v.cisti_gb("  503  DAF XF530FAT") == "503"
    assert v.cisti_gb("497") == "497"
    assert v.cisti_gb(None) == ""


def test_spoji_duplikate(monkeypatch):
    db = _session()
    k = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(k)
    db.add_all([
        RegistarVozila(gb="498 YV2R002D3LA858297 VOLVO FH64R  2019.", vrsta="Dizalica",
                       broj_sasije="YV2R002D3LA858297", status=StatusVozila.aktivno),
        RegistarVozila(gb="498  VOLVO FH64R", status=StatusVozila.aktivno),
        RegistarVozila(gb="503", vrsta="DIZALICA", status=StatusVozila.aktivno),
        RegistarVozila(gb="503  DAF XF530FAT", broj_sasije="XLRATH4300G397740", status=StatusVozila.aktivno),
    ])
    a = Vozilo(gb="498 YV2R002D3LA858297 VOLVO FH64R  2019.", marka="Kamion")
    b = Vozilo(gb="498  VOLVO FH64R")
    db.add_all([a, b]); db.flush()
    db.add(Nalog(broj="RN-1", vozilo_id=b.id, naslov="x", kreirao_id=k.id, status=StatusNaloga.otvoren))
    db.commit()

    assert v.popravi_gb_s_razmakom(db) > 0
    db.expire_all()
    assert sorted(r.gb for r in db.query(RegistarVozila).all()) == ["498", "503"]
    r503 = db.get(RegistarVozila, "503")
    assert r503.vrsta == "DIZALICA" and r503.broj_sasije == "XLRATH4300G397740"  # dopunjeno
    assert db.get(RegistarVozila, "498").broj_sasije == "YV2R002D3LA858297"
    vozila = db.query(Vozilo).all()
    assert [x.gb for x in vozila] == ["498"]
    assert db.query(Nalog).one().vozilo_id == vozila[0].id   # nalog prebačen, ništa izgubljeno
    assert v.popravi_gb_s_razmakom(db) == 0                  # drugi put nema posla


def test_sync_cisti_gb_iz_flote(monkeypatch):
    async def flota():
        return [{"gb": "499  MAN TGX 33.500  2018.", "tip": "Kamion", "vozilo": "MAN TGX 33.500"},
                {"gb": "498  VOLVO FH64R"}, {"gb": "498 YV2R VOLVO", "broj_sasije": "YV2R"}]
    monkeypatch.setattr(v.flota, "vozila_flota", flota)
    db = _session()
    assert asyncio.run(v._sync_registar(db))
    assert sorted(r.gb for r in db.query(RegistarVozila).all()) == ["498", "499"]
    assert db.get(RegistarVozila, "498").broj_sasije == "YV2R"


def _korisnik(db):
    k = Korisnik(ime="Davor", korisnicko_ime="davor", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(k); db.commit()
    return k


def test_novo_vozilo_ide_u_flotu(monkeypatch):
    poslano = []

    async def dodaj(p):
        poslano.append(p)
        return {"ok": True, "postoji": False}
    monkeypatch.setattr(v.flota, "dodaj_vozilo", dodaj)
    db = _session()
    k = _korisnik(db)
    rez = asyncio.run(v.novo_vozilo(v.NovoVoziloIn(gb="505", vrsta="Šlepa", vozilo="Schwarzmüller",
                                                   registracija="zg-1234 ab"), korisnik=k, db=db))
    assert rez == {"gb": "505", "u_floti": True}
    r = db.get(RegistarVozila, "505")
    assert r.tip == "PRIKLJUČNO VOZILO" and r.kategorija == "prikolica" and r.registracija == "ZG1234AB"
    assert r.flota_ceka is False
    assert db.query(Vozilo).filter(Vozilo.gb == "505").count() == 1     # odmah se mogu pisati nalozi
    assert poslano[0]["gb"] == "505" and poslano[0]["autor"] == "Davor"


def test_novo_vozilo_ceka_kad_flota_ne_radi_pa_posalje(monkeypatch):
    import pytest
    from fastapi import HTTPException

    async def ne_radi(p):
        return None
    monkeypatch.setattr(v.flota, "dodaj_vozilo", ne_radi)
    db = _session()
    k = _korisnik(db)
    rez = asyncio.run(v.novo_vozilo(v.NovoVoziloIn(gb="506", vrsta="Tegljač"), korisnik=k, db=db))
    assert rez["u_floti"] is False and db.get(RegistarVozila, "506").flota_ceka is True
    # isti GB ili s razmakom → odbijeno
    with pytest.raises(HTTPException) as e:
        asyncio.run(v.novo_vozilo(v.NovoVoziloIn(gb="506"), korisnik=k, db=db))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        asyncio.run(v.novo_vozilo(v.NovoVoziloIn(gb="507 MAN TGX"), korisnik=k, db=db))
    assert e.value.status_code == 400
    # Flota se vratila: sinkronizacija pošalje vozilo koje čeka
    poslano = []

    async def radi(p):
        poslano.append(p["gb"])
        return {"ok": True}

    async def flota():
        return [{"gb": "1", "tip": "KAMION"}]
    monkeypatch.setattr(v.flota, "dodaj_vozilo", radi)
    monkeypatch.setattr(v.flota, "vozila_flota", flota)
    assert asyncio.run(v._sync_registar(db))
    assert poslano == ["506"] and db.get(RegistarVozila, "506").flota_ceka is False
