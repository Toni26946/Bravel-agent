"""Test klik-bonusa: jutarnja disciplina klikanja + podjela poola.

Pravilo: poruka poslana do cutoff (07:00) → mora kliknuti (Počinjem/Gotovo) do
deadline (07:10). Kašnjenje = prekršaj. Pool se dijeli razmjerno disciplini;
izgubljeni dio ide onima bez prekršaja."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    KlikPoslano, Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak,
)
from app.routers.ucinak import _hr_offset, _klik_bonus


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


_NOW = datetime.now(timezone.utc)
_OFF = _hr_offset(_NOW)


def _hr(day, hh, mm):
    """HR wall-clock (day, hh:mm) → UTC timestamp koji _u_hr vrati natrag u to HR vrijeme."""
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc) - _OFF


_brojac = [0]


def _zad(db, radnik, zapoceto):
    _brojac[0] += 1
    voz = Vozilo(gb=f"V{_brojac[0]}", marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj=f"RN-{_brojac[0]}", vozilo_id=voz.id, naslov="x", kreirao_id=radnik.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="MOTOR"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="x", zapoceto=zapoceto); z.radnici = [radnik]
    db.add(z); db.flush()


def test_klik_bonus_prekrsaji_i_podjela():
    db = _session()
    a = Korisnik(ime="Ante", korisnicko_ime="ante", lozinka_hash="x", uloga=Uloga.radnik)
    b = Korisnik(ime="Bruno", korisnicko_ime="bruno", lozinka_hash="x", uloga=Uloga.radnik)
    db.add_all([a, b]); db.flush()

    d1 = (_NOW - timedelta(days=3)).date()
    d2 = (_NOW - timedelta(days=2)).date()

    # A: dva jutra očekivano (poruka 06:50). Dan1 klik 07:05 (na vrijeme), dan2 klik 07:30 (kasno).
    db.add(KlikPoslano(radnik_id=a.id, poslano=_hr(d1, 6, 50)))
    db.add(KlikPoslano(radnik_id=a.id, poslano=_hr(d2, 6, 50)))
    _zad(db, a, _hr(d1, 7, 5))
    _zad(db, a, _hr(d2, 7, 30))

    # B: jedno jutro, klik 07:00 (na vrijeme) → bez prekršaja.
    db.add(KlikPoslano(radnik_id=b.id, poslano=_hr(d1, 6, 50)))
    _zad(db, b, _hr(d1, 7, 0))

    # Poruka POSLIJE cutoffa (09:00) ne stvara očekivano jutro.
    db.add(KlikPoslano(radnik_id=b.id, poslano=_hr(d2, 9, 0)))
    db.commit()

    out = _klik_bonus(db, dana=30, pool=100.0)
    red = {r["ime"]: r for r in out["redovi"]}

    assert red["Ante"]["ocekivano"] == 2
    assert red["Ante"]["na_vrijeme"] == 1
    assert red["Ante"]["prekrsaji"] == 1
    assert red["Bruno"]["ocekivano"] == 1      # 09:00 poruka se ne broji
    assert red["Bruno"]["prekrsaji"] == 0

    # base = 100/2 = 50. A: 50×(1/2)=25. B: 50×1=50. Ostatak 25 → čistom (Bruno).
    assert red["Ante"]["bonus_eur"] == 25.0
    assert red["Bruno"]["bonus_eur"] == 75.0
    # Bruno (bez prekršaja, veći bonus) je prvi.
    assert red["Bruno"]["mjesto"] == 1
