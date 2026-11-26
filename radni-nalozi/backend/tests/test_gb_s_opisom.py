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
