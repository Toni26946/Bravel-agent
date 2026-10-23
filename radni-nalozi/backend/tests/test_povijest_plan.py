"""Test: mehaničarsko 'Gotovo' iz Plana radione upisuje zadatak u povijest_rada.

Ranije je plan.prekini(razlog='gotovo') samo postavio z.gotovo=True i commitao,
a NIJE zvao _auto_status_naloga / _sync_povijest — pa dovršeni zadaci iz Plana
nisu ulazili u povijest_rada (AI Poslovođa je računala iz ustajalih podataka).
Ovaj test osigurava da gotov zadatak odmah dobije zapis u povijest_rada.
"""
import os
import sys
from pathlib import Path

# backend/ (sadrži paket 'app') na sys.path
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
# Izoliraj od lokalne/prod baze — koristimo in-memory SQLite u testu.
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (  # noqa: E402  (import nakon sys.path)
    Korisnik, Nalog, Operacija, PovijestRada, StatusNaloga, Uloga, Vozilo, Zadatak,
)
from app.routers.plan import PrekiniIn, prekini


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _priprema(db):
    meh = Korisnik(ime="Test Mehaničar", korisnicko_ime="test.meh", lozinka_hash="x", uloga=Uloga.voditelj)
    voz = Vozilo(gb="T999", registracija="ZG0000TT", marka="MAN")
    db.add_all([meh, voz]); db.flush()
    nalog = Nalog(broj="RN-TEST-1", vozilo_id=voz.id, naslov="Test nalog",
                  kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(nalog); db.flush()
    op = Operacija(nalog_id=nalog.id, kategorija="MOTOR")
    db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="Zamjena filtera", utroseno_sek=1800)  # 30 min
    z.radnici = [meh]
    db.add(z); db.commit()
    meh.ai_poslovodja = True  # izvedeni atribut (postavlja auth u prod); za _smije_meh
    return meh, voz, nalog, z


def test_gotovo_iz_plana_upisuje_povijest():
    db = _session()
    meh, voz, nalog, z = _priprema(db)
    assert db.query(PovijestRada).count() == 0

    prekini(z.id, PrekiniIn(razlog="gotovo"), korisnik=meh, db=db)

    rows = db.query(PovijestRada).all()
    assert len(rows) == 1, "gotov zadatak mora dati točno jedan zapis u povijest_rada"
    r = rows[0]
    assert r.opis == "Zamjena filtera"
    assert r.operacija == "MOTOR"
    assert r.vozilo_id == voz.id
    assert r.nalog_id == nalog.id
    assert r.minute == 30
    assert r.izvor == "nalog"
    db.refresh(z)
    assert z.gotovo is True
    assert db.get(Nalog, nalog.id).status == StatusNaloga.gotov  # svi zadaci gotovi → nalog gotov


def test_dijelovi_iz_plana_ne_upisuje_povijest():
    """'Nemam dijelova' nije dovršen posao → ne smije ući u povijest_rada."""
    db = _session()
    meh, voz, nalog, z = _priprema(db)

    prekini(z.id, PrekiniIn(razlog="dijelovi"), korisnik=meh, db=db)

    assert db.query(PovijestRada).count() == 0
    db.refresh(z)
    assert z.gotovo is False
    assert z.razlog_prekida == "dijelovi"


if __name__ == "__main__":
    test_gotovo_iz_plana_upisuje_povijest()
    test_dijelovi_iz_plana_ne_upisuje_povijest()
    print("OK — svi testovi prošli")
