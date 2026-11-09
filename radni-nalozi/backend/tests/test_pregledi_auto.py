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


def test_obavijest_preskace_pregled_only_i_cisti():
    """Nalog koji ima SAMO pregled (nema drugog posla) → ne šalje; poništi pogrešan čeka-potvrdu."""
    db = _session()
    db.add(Korisnik(ime="Karthik Raju", korisnicko_ime=pregledi_auto.PREGLEDI_KIME,
                    lozinka_hash="x", uloga=Uloga.radnik, prijavljuje_se=False))
    db.flush()
    n, zp = _nalog_s_pregledom(db, "F3", "RN-F3")
    zp.ceka_potvrdu = True   # simulira pogrešno poslano iz prvog burst-a
    db.commit()

    assert pregledi_auto.obavijesti_pregledara(db, "https://x/") == 0
    db.refresh(zp)
    assert zp.ceka_potvrdu is False   # poništeno jer nema drugog posla


def test_ne_dodaje_za_ne_kamion():
    """Mali auto / prikolica / bez kategorije → NE dobiva auto-pregled (samo kamioni)."""
    db = _session()
    db.add(Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj))
    _vozilo(db, "A1")
    _vozilo(db, "A2")
    _vozilo(db, "A3")
    db.add(RegistarVozila(gb="A1", kategorija="osobni", status=StatusVozila.aktivno,
                          registracija_istek=date.today() + timedelta(days=5)))
    db.add(RegistarVozila(gb="A2", kategorija="prikolica", status=StatusVozila.aktivno,
                          registracija_istek=date.today() + timedelta(days=5)))
    db.add(RegistarVozila(gb="A3", kategorija=None, status=StatusVozila.aktivno,
                          registracija_istek=date.today() + timedelta(days=5)))
    db.commit()

    assert pregledi_auto.tik(db) == 0
    assert db.query(Nalog).count() == 0


def test_ocisti_ne_kamione_mice_stare_preglede():
    """Postojeći auto-pregled na malom autu se počisti; na kamionu ostaje."""
    import os
    import tempfile
    from app.config import settings

    db = _session()
    db.add(Korisnik(ime="Karthik Raju", korisnicko_ime=pregledi_auto.PREGLEDI_KIME,
                    lozinka_hash="x", uloga=Uloga.radnik, prijavljuje_se=False))
    db.flush()
    # Mali auto s auto-pregledom (prazan nalog samo za pregled) → mora nestati.
    db.add(RegistarVozila(gb="A9", kategorija="osobni", status=StatusVozila.aktivno))
    n_auto, _ = _nalog_s_pregledom(db, "A9", "RN-A9")
    # Kamion s auto-pregledom → mora ostati.
    db.add(RegistarVozila(gb="K9", kategorija="kamion", status=StatusVozila.aktivno))
    n_kam, _ = _nalog_s_pregledom(db, "K9", "RN-K9")
    db.commit()

    # Zastavica u izoliranom temp dir-u da se čišćenje uopće izvrši.
    stari = settings.upload_dir
    d = tempfile.mkdtemp()
    settings.upload_dir = os.path.join(d, "up")
    try:
        pregledi_auto.ocisti_ne_kamione(db)
    finally:
        settings.upload_dir = stari

    assert db.get(Nalog, n_auto.id) is None          # prazan nalog malog auta obrisan
    assert db.get(Nalog, n_kam.id) is not None        # kamionov nalog ostaje
    kam_kat = [op.kategorija for op in db.get(Nalog, n_kam.id).operacije]
    assert "REGISTRACIJA" in kam_kat


def test_bez_voditelja_ne_radi_nista():
    db = _session()
    _vozilo(db, "D4")
    db.add(RegistarVozila(gb="D4", kategorija="kamion", status=StatusVozila.aktivno,
                          registracija_istek=date.today()))
    db.commit()
    assert pregledi_auto.tik(db) == 0
    assert db.query(Nalog).count() == 0


def test_servis_dospio_dodaje_operaciju_u_plan():
    """Kad servis dospije (zadnji + 12 mj prošlo), auto se doda operacija SERVIS u plan,
    bez dodijeljenog radnika, s kratkim opisom (zadnji datum + koliko do servisa)."""
    db = _session()
    db.add(Korisnik(ime="Vod", korisnicko_ime="vod", lozinka_hash="x", uloga=Uloga.voditelj))
    _vozilo(db, "S1")
    db.add(RegistarVozila(gb="S1", kategorija="kamion", status=StatusVozila.aktivno,
                          servis_zadnji=date.today() - timedelta(days=400)))  # 12 mj prošlo → dospio
    db.commit()

    assert pregledi_auto.tik(db) == 1
    n = db.query(Nalog).filter(Nalog.status.in_(pregledi_auto._AKTIVNI)).one()
    op = next(o for o in n.operacije if o.kategorija == "SERVIS")
    assert op.zadaci[0].opis.startswith("Servis — zadnji")
    assert op.zadaci[0].radnici == []     # servis NIJE pregledarov posao (bez radnika)
    assert n.plan_rang is not None         # u planu

    assert pregledi_auto.tik(db) == 0      # drugi prolaz ne duplira
