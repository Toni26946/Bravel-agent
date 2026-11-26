"""Plan radione: uz GB zadnji vozač (Veljko 26.11.2026., WhatsApp #433).
Kamion → zadnji vozač iz Flota OS-a (keš); priključno vozilo → zadnje prikapčanje."""
import asyncio
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import flota
from app.database import Base
from app.models import (DnevnikPrikapcanja, Korisnik, Nalog, Operacija, RegistarVozila, StatusNaloga,
                        StatusVozila, Uloga, Vozilo, VrstaDogadaja, Zadatak)
from app.routers import plan as plan_mod


@pytest.fixture(autouse=True)
def _cisti_kes():
    flota._vozaci_kes.clear()
    flota._vozaci_trazeni.clear()
    yield
    flota._vozaci_kes.clear()
    flota._vozaci_trazeni.clear()


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _nalog(db, vod, gb, broj):
    voz = Vozilo(gb=gb, registracija="ZG" + gb)
    db.add(voz); db.flush()
    n = Nalog(broj=broj, vozilo_id=voz.id, naslov="x", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="GUME", redoslijed=0); db.add(op); db.flush()
    db.add(Zadatak(operacija_id=op.id, opis="z")); db.flush()
    return n


def test_kes_bez_mreze_i_red_za_dohvat():
    assert flota.zadnji_vozac("134") is None
    assert "134" in flota._vozaci_trazeni          # traženo → ide u red pozadinske petlje
    flota._vozaci_kes["134"] = (time.monotonic(), "Horvat Ivan")
    flota._vozaci_trazeni.clear()
    assert flota.zadnji_vozac("134") == "Horvat Ivan"
    assert not flota._vozaci_trazeni               # svjež keš → nema ponovnog dohvata


def test_osvjezi_puni_kes(monkeypatch):
    class Odg:
        status_code = 200
        def __init__(self, gb): self.gb = gb
        def json(self): return {"gb": self.gb, "vozac": "Novak Marko" if self.gb == "7" else None}

    class Klijent:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, put, params=None, headers=None): return Odg(params["gb"])

    monkeypatch.setattr(flota.httpx, "AsyncClient", Klijent)
    monkeypatch.setattr(flota.settings, "flota_service_key", "x")
    flota._vozaci_trazeni.update({"7", "8"})
    assert asyncio.run(flota.osvjezi_zadnje_vozace()) == 2
    assert flota.zadnji_vozac("7") == "Novak Marko"
    assert flota.zadnji_vozac("8") is None and "8" not in flota._vozaci_trazeni


def test_plan_vraca_vozaca_za_kamion_i_prikolicu():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vod); db.flush()
    db.add_all([
        RegistarVozila(gb="134", kategorija="kamion", status=StatusVozila.aktivno),
        RegistarVozila(gb="501", kategorija="prikolica", status=StatusVozila.aktivno),
        RegistarVozila(gb="502", kategorija="prikolica", status=StatusVozila.aktivno),
    ])
    n1 = _nalog(db, vod, "134", "RN-1")
    n2 = _nalog(db, vod, "501", "RN-2")
    n3 = _nalog(db, vod, "502", "RN-3")
    sad = datetime.now(timezone.utc)
    db.add_all([
        # 501: starije prikapčanje s imenom, novije bez imena → ime zadnjeg vozača kamiona 134
        DnevnikPrikapcanja(prikolica_gb="501", kamion_gb="99", vozac="Stari Vozač",
                           vrsta=VrstaDogadaja.prikaceno, vrijeme=sad - timedelta(days=3)),
        DnevnikPrikapcanja(prikolica_gb="501", kamion_gb="134", vozac=None,
                           vrsta=VrstaDogadaja.prikaceno, vrijeme=sad - timedelta(days=1)),
        DnevnikPrikapcanja(prikolica_gb="502", kamion_gb="55", vozac="Kovač Ante",
                           vrsta=VrstaDogadaja.prikaceno, vrijeme=sad - timedelta(days=2)),
        DnevnikPrikapcanja(prikolica_gb="502", vrsta=VrstaDogadaja.otkaceno, vrijeme=sad),
    ])
    db.commit()
    flota._vozaci_kes["134"] = (time.monotonic(), "Horvat Ivan")
    reg_map = {r.gb: r for r in db.query(RegistarVozila).all()}
    out = plan_mod._zadnji_vozaci(db, [n1, n2, n3], reg_map)
    assert out == {"134": "Horvat Ivan", "501": "Horvat Ivan", "502": "Kovač Ante"}
