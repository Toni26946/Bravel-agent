"""Test klik-bonusa: SVI prisutni mehaničari se broje svako JUTRO kad je plan poslan.
Tko ne klikne (Počinjem/Gotovo) do deadline-a = prekršaj. Odsutni/teren se izuzimaju.
Pool se dijeli razmjerno disciplini; izgubljeni dio ide onima bez prekršaja."""
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
from app.norme import set_postavka
from app.routers.ucinak import KLJUC_KLIK_JUTRA, _hr_offset, _klik_bonus


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
    n = Nalog(broj=f"RN-{_brojac[0]}", vozilo_id=voz.id, naslov="x", kreirao_id=radnik.id,
              status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="MOTOR"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="x", zapoceto=zapoceto); z.radnici = [radnik]
    db.add(z); db.flush()


def test_klik_bonus_svi_prisutni_po_jutru():
    """Oba prisutna se broje za jutro d1; A kliknuo na vrijeme, B nije → prekršaj."""
    db = _session()
    a = Korisnik(ime="A", korisnicko_ime="a", lozinka_hash="x", uloga=Uloga.radnik)
    b = Korisnik(ime="B", korisnicko_ime="b", lozinka_hash="x", uloga=Uloga.radnik)
    db.add_all([a, b]); db.flush()
    d1 = (_NOW - timedelta(days=1)).date()
    set_postavka(db, KLJUC_KLIK_JUTRA, d1.isoformat())   # jutro odrađeno (marker)
    _zad(db, a, _hr(d1, 7, 0))                            # A kliknuo 07:00
    db.commit()                                          # B nije kliknuo

    out = _klik_bonus(db, dana=30, pool=100.0)
    red = {r["ime"]: r for r in out["redovi"]}
    assert red["A"]["ocekivano"] == 1 and red["A"]["prekrsaji"] == 0
    assert red["B"]["ocekivano"] == 1 and red["B"]["prekrsaji"] == 1
    assert red["A"]["bonus_eur"] == 100.0   # cijeli pool čistom (A)
    assert red["B"]["bonus_eur"] == 0.0


def test_klik_bonus_teren_i_odsutni_izuzeti():
    """Teren i godišnji (za taj dan) se NE broje u pool."""
    db = _session()
    a = Korisnik(ime="A", korisnicko_ime="a", lozinka_hash="x", uloga=Uloga.radnik)
    c = Korisnik(ime="C", korisnicko_ime="c", lozinka_hash="x", uloga=Uloga.radnik,
                 odsutnost_vrsta="teren")
    e = Korisnik(ime="E", korisnicko_ime="e", lozinka_hash="x", uloga=Uloga.radnik,
                 odsutnost_vrsta="godisnji")
    db.add_all([a, c, e]); db.flush()
    d1 = (_NOW - timedelta(days=1)).date()
    e.odsutnost_od = d1 - timedelta(days=1)
    e.odsutnost_do = d1 + timedelta(days=1)              # godišnji pokriva d1
    set_postavka(db, KLJUC_KLIK_JUTRA, d1.isoformat())
    _zad(db, a, _hr(d1, 7, 0))
    db.commit()

    out = _klik_bonus(db, dana=30, pool=90.0)
    assert {r["ime"] for r in out["redovi"]} == {"A"}    # C (teren) i E (godišnji) izuzeti
    assert out["redovi"][0]["bonus_eur"] == 90.0


def test_klik_bonus_jutro_iz_poslano():
    """Jutro se prepozna i iz KlikPoslano (poruka ≤ cutoff), ne samo iz markera."""
    db = _session()
    a = Korisnik(ime="A", korisnicko_ime="a", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(a); db.flush()
    d1 = (_NOW - timedelta(days=1)).date()
    db.add(KlikPoslano(radnik_id=a.id, poslano=_hr(d1, 6, 50)))
    _zad(db, a, _hr(d1, 7, 0))
    db.commit()

    out = _klik_bonus(db, dana=30, pool=50.0)
    red = {r["ime"]: r for r in out["redovi"]}
    assert red["A"]["ocekivano"] == 1 and red["A"]["na_vrijeme"] == 1
