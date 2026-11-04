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
    Korisnik, Nalog, Operacija, RegistarVozila, StatusNaloga, StatusVozila, Uloga, Vozilo, Zadatak,
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
    # Pregledar (Karthik) — auto-pregled mora odmah doći dodijeljen njemu.
    db.add(Korisnik(ime="Karthik Raju", korisnicko_ime=pregledi_auto.PREGLEDI_KIME,
                    lozinka_hash="x", uloga=Uloga.radnik, prijavljuje_se=False))
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
    z = op.zadaci[0]
    assert [r.korisnicko_ime for r in z.radnici] == [pregledi_auto.PREGLEDI_KIME]  # odmah dodijeljen pregledaru
    assert z.zapoceto is None     # mjerač NE kreće
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


def test_dispatch_preskace_pregledara():
    """'Pošalji sve' NE šalje pregledaru (prijavljuje_se=False) — on radi preglede, ne prima poveznice."""
    from app.routers.plan import posalji_sve_plan
    db = _session()
    kar = Korisnik(ime="Karthik Raju", korisnicko_ime=pregledi_auto.PREGLEDI_KIME,
                   lozinka_hash="x", uloga=Uloga.radnik, prijavljuje_se=False)
    db.add(kar)
    db.add(Vozilo(gb="E1", marka="MAN"))
    db.flush()
    voz = db.query(Vozilo).filter(Vozilo.gb == "E1").one()
    n = Nalog(broj="RN-E1", vozilo_id=voz.id, naslov="E1", kreirao_id=kar.id,
              status=StatusNaloga.u_radu, plan_rang=0)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="REGISTRACIJA"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="Produženje registracije — rok 07.11.2026"); z.radnici = [kar]
    db.add(z); db.commit()

    rez = posalji_sve_plan(db, "https://x/")
    assert rez["mehanicara"] == 0  # Karthik preskočen


def _nalog_s_pregledom(db, gb, broj):
    kar = db.query(Korisnik).filter(Korisnik.korisnicko_ime == pregledi_auto.PREGLEDI_KIME).first()
    db.add(Vozilo(gb=gb, marka="MAN")); db.flush()
    voz = db.query(Vozilo).filter(Vozilo.gb == gb).one()
    n = Nalog(broj=broj, vozilo_id=voz.id, naslov=gb, kreirao_id=kar.id,
              status=StatusNaloga.u_radu, plan_rang=0)
    db.add(n); db.flush()
    opp = Operacija(nalog_id=n.id, kategorija="REGISTRACIJA"); db.add(opp); db.flush()
    zp = Zadatak(operacija_id=opp.id, opis="Produženje registracije — rok 07.11.2026"); zp.radnici = [kar]
    db.add(zp); db.flush()
    return n, zp


def test_obavijest_salje_kad_ostalo_samo_njegovo():
    """Sve tuđe gotovo (ostalo ≤1) → pregledar dobije poruku (ceka_potvrdu); drugi put ne."""
    from datetime import datetime, timezone
    db = _session()
    db.add(Korisnik(ime="Karthik Raju", korisnicko_ime=pregledi_auto.PREGLEDI_KIME,
                    lozinka_hash="x", uloga=Uloga.radnik, prijavljuje_se=False))
    db.flush()
    n, zp = _nalog_s_pregledom(db, "F1", "RN-F1")
    # jedna tuđa operacija — GOTOVA
    op2 = Operacija(nalog_id=n.id, kategorija="MOTOR"); db.add(op2); db.flush()
    db.add(Zadatak(operacija_id=op2.id, opis="servis", gotovo=True, zavrseno=datetime.now(timezone.utc)))
    db.commit()

    assert pregledi_auto.obavijesti_pregledara(db, "https://x/") == 1
    db.refresh(zp)
    assert zp.ceka_potvrdu is True
    assert pregledi_auto.obavijesti_pregledara(db, "https://x/") == 0  # već poslano


def test_obavijest_ne_salje_dok_ima_tudjeg_posla():
    db = _session()
    db.add(Korisnik(ime="Karthik Raju", korisnicko_ime=pregledi_auto.PREGLEDI_KIME,
                    lozinka_hash="x", uloga=Uloga.radnik, prijavljuje_se=False))
    db.flush()
    n, zp = _nalog_s_pregledom(db, "F2", "RN-F2")
    # dvije tuđe operacije NISU gotove (> PRAG_OSTALE)
    for i, kat in enumerate(("MOTOR", "ELEKTRIKA")):
        op = Operacija(nalog_id=n.id, kategorija=kat); db.add(op); db.flush()
        db.add(Zadatak(operacija_id=op.id, opis=f"posao{i}"))
    db.commit()

    assert pregledi_auto.obavijesti_pregledara(db, "https://x/") == 0
    db.refresh(zp)
    assert zp.ceka_potvrdu is False


def test_bez_voditelja_ne_radi_nista():
    db = _session()
    _vozilo(db, "D4")
    db.add(RegistarVozila(gb="D4", kategorija="kamion", status=StatusVozila.aktivno,
                          registracija_istek=date.today()))
    db.commit()
    assert pregledi_auto.tik(db) == 0
    assert db.query(Nalog).count() == 0
