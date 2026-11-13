"""Popis prioriteta naloga (Plan radione): PUT /plan/prioriteti postavlja
prioritet_rang po redoslijedu (prvi = 0 = najhitniji), a nalozi izvan liste ga gube."""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, StatusNaloga, Uloga, Vozilo
from app.routers.plan import PrioritetiIn, prioriteti


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _nalog(db, vlasnik, gb, broj):
    voz = Vozilo(gb=gb, marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj=broj, vozilo_id=voz.id, naslov="T", kreirao_id=vlasnik.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    return n


def test_prioriteti_postavlja_i_cisti():
    db = _session()
    vlasnik = Korisnik(ime="Voditelj", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vlasnik); db.flush()
    n1 = _nalog(db, vlasnik, "100", "RN-1")
    n2 = _nalog(db, vlasnik, "200", "RN-2")
    n3 = _nalog(db, vlasnik, "300", "RN-3")
    db.commit()

    # Lista: n2 prvi (najhitniji), pa n1, pa n3
    prioriteti(PrioritetiIn(redoslijed=[n2.id, n1.id, n3.id]), _=vlasnik, db=db)
    db.refresh(n1); db.refresh(n2); db.refresh(n3)
    assert n2.prioritet_rang == 0 and n1.prioritet_rang == 1 and n3.prioritet_rang == 2

    # Nova lista bez n1 → n1 gubi prioritet, ostali se preslože
    prioriteti(PrioritetiIn(redoslijed=[n3.id, n2.id]), _=vlasnik, db=db)
    db.refresh(n1); db.refresh(n2); db.refresh(n3)
    assert n1.prioritet_rang is None
    assert n3.prioritet_rang == 0 and n2.prioritet_rang == 1

    # Prazna lista → svi bez prioriteta
    prioriteti(PrioritetiIn(redoslijed=[]), _=vlasnik, db=db)
    db.refresh(n2); db.refresh(n3)
    assert n2.prioritet_rang is None and n3.prioritet_rang is None
