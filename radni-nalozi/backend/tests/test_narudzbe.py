"""Narudžbe dijelova: upis iz naloga → skladištar vidi skupno → status prelazi
trazeno → naruceno → stiglo."""
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
from app.routers.narudzbe import NarudzbaIn, StatusIn, dodaj, popis, popis_naloga, postavi_status


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _postavi(db):
    meh = Korisnik(ime="Meh", korisnicko_ime="meh.n", lozinka_hash="x", uloga=Uloga.radnik)
    skl = Korisnik(ime="Skladištar", korisnicko_ime="skl.n", lozinka_hash="x", uloga=Uloga.skladistar)
    db.add_all([meh, skl]); db.flush()
    voz = Vozilo(gb="T777", marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj="RN-N-1", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.commit()
    return meh, skl, n


def test_upis_i_skladistar_vidi():
    db = _session()
    meh, skl, n = _postavi(db)
    r = dodaj(n.id, NarudzbaIn(naziv="Filter ulja", kataloski="W712", kolicina=2, jmj="kom",
                               napomena="hitno", fotografije=["/uploads/a.jpg"]),
              korisnik=meh, db=db)
    assert r["status"] == "trazeno"
    assert r["vozilo_gb"] == "T777"
    assert r["fotografije"] == ["/uploads/a.jpg"]

    # mehaničar vidi za svoj nalog
    assert len(popis_naloga(n.id, korisnik=meh, db=db)) == 1
    # skladištar vidi skupno
    svi = popis(status=None, _=skl, db=db)
    assert len(svi) == 1 and svi[0]["naziv"] == "Filter ulja"


def test_naziv_nije_obavezan_ali_treba_nesto():
    from fastapi import HTTPException
    db = _session()
    meh, skl, n = _postavi(db)
    # Bez naziva, ali sa slikom → prolazi
    r = dodaj(n.id, NarudzbaIn(naziv="", fotografije=["/uploads/x.jpg"]), korisnik=meh, db=db)
    assert r["status"] == "trazeno" and r["naziv"] == "" and r["fotografije"] == ["/uploads/x.jpg"]
    # Bez naziva, samo kataloški → prolazi
    r2 = dodaj(n.id, NarudzbaIn(kataloski="W712"), korisnik=meh, db=db)
    assert r2["kataloski"] == "W712"
    # Sve prazno → 400
    try:
        dodaj(n.id, NarudzbaIn(), korisnik=meh, db=db)
        assert False, "očekivan 400 za potpuno prazan unos"
    except HTTPException as e:
        assert e.status_code == 400


def test_status_prelazi():
    db = _session()
    meh, skl, n = _postavi(db)
    r = dodaj(n.id, NarudzbaIn(naziv="Remen"), korisnik=meh, db=db)
    nid = r["id"]

    r2 = postavi_status(nid, StatusIn(status="naruceno"), korisnik=skl, db=db)
    assert r2["status"] == "naruceno" and r2["naruceno"] is not None and r2["stiglo"] is None
    assert r2["obradio"] == "Skladištar"

    r3 = postavi_status(nid, StatusIn(status="stiglo"), korisnik=skl, db=db)
    assert r3["status"] == "stiglo" and r3["stiglo"] is not None

    # filter po statusu
    assert len(popis(status="stiglo", _=skl, db=db)) == 1
    assert len(popis(status="trazeno", _=skl, db=db)) == 0


if __name__ == "__main__":
    test_upis_i_skladistar_vidi()
    test_status_prelazi()
    print("OK — narudžbe testovi prošli")
