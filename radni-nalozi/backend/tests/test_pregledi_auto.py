"""Test auto-operacija za periodične provjere: operacija se doda ~2 tjedna prije
roka, vidljiva je u nalogu i ne duplira se."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import pregledi_auto
from app.database import Base
from app.models import (
    Korisnik, Nalog, Operacija, RegistarVozila, StatusNaloga, StatusVozila, Uloga, Vozilo,
)


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _vozilo(db, gb):
    db.add(Vozilo(gb=gb, marka="MAN"))
    db.flush()


def test_dodaje_operaciju_za_rok_u_prozoru_i_ne_duplira():
    db = _session()
    db.add(Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj))
    _vozilo(db, "D1")
    # Registracija ističe za 5 dana → unutar praga (14).
    db.add(RegistarVozila(gb="D1", kategorija="kamion", status=StatusVozila.aktivno,
                          registracija_istek=date.today() + timedelta(days=5)))
    db.commit()

    assert pregledi_auto.tik(db) == 1
    n = db.query(Nalog).filter(Nalog.status.in_(pregledi_auto._AKTIVNI)).one()
    kategorije = [op.kategorija for op in n.operacije]
    assert "REGISTRACIJA" in kategorije
    op = next(o for o in n.operacije if o.kategorija == "REGISTRACIJA")
    assert op.zadaci and op.zadaci[0].opis.startswith("Produženje registracije")
    assert op.zadaci[0].radnici == []  # nitko dodijeljen → može se dodijeliti u planu
    assert n.plan_rang is not None       # mora biti U PLANU da se vidi

    assert pregledi_auto.tik(db) == 0  # drugi prolaz ne duplira
    db.refresh(n)
    assert n.plan_rang is not None       # i dalje u planu

    # Postojeća auto-operacija bez ranga (kao 20 iz prve verzije) → tik je vrati u plan.
    n.plan_rang = None
    db.commit()
    pregledi_auto.tik(db)
    db.refresh(n)
    assert n.plan_rang is not None


def test_periodicki_po_intervalu_i_daleki_rok_se_preskace():
    db = _session()
    db.add(Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj))
    _vozilo(db, "D2")
    _vozilo(db, "D3")
    # D2: periodički prije 85 dana, interval 3 mj → rok ≈ za 5 dana (u prozoru).
    db.add(RegistarVozila(gb="D2", kategorija="kamion", status=StatusVozila.aktivno,
                          periodicki_datum=date.today() - timedelta(days=85), periodicki_int=3))
    # D3: registracija za 60 dana → izvan prozora.
    db.add(RegistarVozila(gb="D3", kategorija="kamion", status=StatusVozila.aktivno,
                          registracija_istek=date.today() + timedelta(days=60)))
    db.commit()

    assert pregledi_auto.tik(db) == 1
    gbovi_s_nalogom = {
        n.vozilo.gb for n in db.query(Nalog).filter(Nalog.status.in_(pregledi_auto._AKTIVNI)).all()
    }
    assert gbovi_s_nalogom == {"D2"}  # samo D2 dobio nalog/operaciju


def test_bez_voditelja_ne_radi_nista():
    db = _session()
    _vozilo(db, "D4")
    db.add(RegistarVozila(gb="D4", kategorija="kamion", status=StatusVozila.aktivno,
                          registracija_istek=date.today()))
    db.commit()
    assert pregledi_auto.tik(db) == 0
    assert db.query(Nalog).count() == 0
