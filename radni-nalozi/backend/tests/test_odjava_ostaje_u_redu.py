"""Odjava radnika (Tekući radovi → Odjavi) zaustavlja mjerač, ali zadatak OSTAJE
u redu tog radnika u planu radione (#285)."""
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
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.routers.dispecer import _red
from app.routers.nalozi import odjava_radnika


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def test_odjava_zaustavi_mjerac_a_zadatak_ostaje_u_redu():
    db = _session()
    vod = Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj)
    a = Korisnik(ime="Meh A", korisnicko_ime="meh.a", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T77", marka="MAN"); db.add_all([vod, a, voz]); db.flush()
    n = Nalog(broj="RN-O", vozilo_id=voz.id, naslov="T", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="KOČNICE"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="Pločice", utroseno_sek=0,
                zapoceto=datetime.now(timezone.utc) - timedelta(hours=2))
    z.radnici = [a]
    db.add(z); db.commit()

    odjava_radnika(n.id, z.id, korisnik=vod, db=db)
    db.refresh(z)
    assert z.zapoceto is None, "mjerač mora stati"
    assert z.utroseno_sek >= 7000, "odrađeno vrijeme se čuva"
    assert [r.id for r in z.radnici] == [a.id], "radnik ostaje dodijeljen"
    assert not z.gotovo
    assert [t[2].opis for t in _red(db, a)] == ["Pločice"], "zadatak ostaje u redu radnika"
