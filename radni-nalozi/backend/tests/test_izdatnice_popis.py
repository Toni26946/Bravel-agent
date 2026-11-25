"""Skladište → Izdatnice: skupni popis svih izdatnica po nalogu (25.11.2026.)."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Izdatnica, Korisnik, Nalog, StatusNaloga, Uloga, Vozilo
from app.routers.primke import izdatnice_sve


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_izdatnice_po_nalogu():
    db = _session()
    k = Korisnik(ime="Skl", korisnicko_ime="skl", lozinka_hash="x", uloga=Uloga.skladistar)
    v1, v2 = Vozilo(gb="45", marka="MAN"), Vozilo(gb="107", marka="DAF")
    db.add_all([k, v1, v2]); db.flush()
    n1 = Nalog(broj="RN-1", vozilo_id=v1.id, naslov="x", kreirao_id=k.id, status=StatusNaloga.u_radu)
    n2 = Nalog(broj="RN-2", vozilo_id=v2.id, naslov="y", kreirao_id=k.id, status=StatusNaloga.u_radu)
    db.add_all([n1, n2]); db.flush()
    db.add_all([
        Izdatnica(nalog_id=n1.id, vozilo_gb="45", artikl_naziv="Filter", kolicina=2, cijena=10.5,
                  kreirao_id=k.id, apross_broj=77),
        Izdatnica(nalog_id=n1.id, vozilo_gb="45", artikl_naziv="Ulje", kolicina=1, cijena=None, kreirao_id=k.id),
        Izdatnica(nalog_id=n2.id, vozilo_gb="107", artikl_naziv="Žarulja", kolicina=3, cijena=1, kreirao_id=k.id),
    ])
    db.commit()

    out = {g["gb"]: g for g in izdatnice_sve(_=k, db=db)}
    assert set(out) == {"45", "107"}
    g = out["45"]
    assert g["broj_naloga"] == "RN-1" and len(g["stavke"]) == 2
    assert g["iznos"] == 21.0 and g["neposlano"] == 1 and g["apross_brojevi"] == [77]
    assert out["107"]["iznos"] == 3.0 and out["107"]["stavke"][0]["kreirao"] == "Skl"


def test_prazno():
    db = _session()
    assert izdatnice_sve(_=None, db=db) == []
