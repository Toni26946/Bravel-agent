"""Automatsko popunjavanje reda mehaničara + red po prioritetima (19.11.2026.).

- popuni(): mehaničaru s < 2 zadatka u pripremi dodijeli nedodijeljene operacije iz plana,
  redom HITNO → lista prioriteta → plan; kome: iskustvo, pa najmanje posla.
- _red(): HITNO ispred prioriteta, prioriteti po rangu, ostali iza; ručni red pobjeđuje,
  a zadaci bez ručnog mjesta se umeću po prioritetu.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import norme
from app.auto_popuni import KLJUC, jednokratno_ocisti_rucni_red, popuni
from app.database import Base
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.routers.dispecer import _red


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _meh(db, ime, **kw):
    m = Korisnik(ime=ime, korisnicko_ime=ime.lower(), lozinka_hash="x", uloga=Uloga.radnik, **kw)
    db.add(m); db.flush()
    return m


def _nalog(db, gb, kreirao, **kw):
    voz = Vozilo(gb=gb, marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj=f"RN-{gb}", vozilo_id=voz.id, naslov="T", kreirao_id=kreirao.id,
              status=kw.pop("status", StatusNaloga.u_radu), **kw)
    db.add(n); db.flush()
    return n


def _zad(db, n, kat, opis, radnici=(), **kw):
    op = Operacija(nalog_id=n.id, kategorija=kat); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis=opis, **kw)
    z.radnici = list(radnici)
    db.add(z); db.flush()
    return z


def test_popuni_po_prioritetu_do_dva():
    db = _session()
    ana = _meh(db, "Ana")
    n_bez = _nalog(db, "10", ana, plan_rang=0)                    # u planu, bez prioriteta
    n_p2 = _nalog(db, "20", ana, plan_rang=1, prioritet_rang=1)   # prioritet 2
    n_p1 = _nalog(db, "30", ana, plan_rang=2, prioritet_rang=0)   # prioritet 1
    n_h = _nalog(db, "40", ana, plan_rang=3, plan_hitno=True)     # hitno
    z_bez = _zad(db, n_bez, "GUME", "bez")
    z_p2 = _zad(db, n_p2, "GUME", "p2")
    z_p1 = _zad(db, n_p1, "GUME", "p1")
    z_h = _zad(db, n_h, "GUME", "hitno")
    db.commit()

    out = popuni(db)
    # dvije dodjele (prag 2): HITNO pa prioritet 1
    assert [d["zadatak_id"] for d in out] == [z_h.id, z_p1.id]
    assert [r.id for r in z_h.radnici] == [ana.id] and [r.id for r in z_p1.radnici] == [ana.id]
    assert not z_p2.radnici and not z_bez.radnici
    # opet → ništa (ima 2 u pripremi)
    assert popuni(db) == []


def test_popuni_iskustvo_pa_najmanje_posla():
    db = _session()
    ana = _meh(db, "Ana")
    bob = _meh(db, "Bob")
    # Bob je dosad završio hidrauliku
    stari = _nalog(db, "1", ana, status=StatusNaloga.zatvoren)
    _zad(db, stari, "HIDRAULIKA", "staro", radnici=[bob], gotovo=True)
    n1 = _nalog(db, "50", ana, prioritet_rang=0)
    n2 = _nalog(db, "60", ana, prioritet_rang=1)
    z_hid = _zad(db, n1, "HIDRAULIKA", "hid")
    z_gum = _zad(db, n2, "GUME", "gum")
    db.commit()
    popuni(db)
    assert [r.id for r in z_hid.radnici] == [bob.id], "hidraulika ide onome tko ju je radio"
    assert [r.id for r in z_gum.radnici] == [ana.id], "ostalo onome s najmanje posla"


def test_popuni_preskace():
    db = _session()
    ana = _meh(db, "Ana")
    _meh(db, "Odsutni", odsutnost_vrsta="godisnji")
    n_van = _nalog(db, "70", ana)                                   # nije u planu
    n_dij = _nalog(db, "80", ana, prioritet_rang=0, status=StatusNaloga.ceka_dijelove)
    n_ok = _nalog(db, "90", ana, prioritet_rang=1)
    z_van = _zad(db, n_van, "GUME", "van")
    z_dij = _zad(db, n_dij, "GUME", "dij")
    z_odg = _zad(db, n_ok, "GUME", "odg", razlog_prekida="dijelovi")
    z_preg = _zad(db, n_ok, "PERIODIČKI PREGLED", "pregled")
    z_ok = _zad(db, n_ok, "GUME", "ok")
    db.commit()
    out = popuni(db)
    assert [d["zadatak_id"] for d in out] == [z_ok.id]
    assert all(d["radnik"] == "Ana" for d in out), "odsutni ne dobiva posao"
    for z in (z_van, z_dij, z_odg, z_preg):
        assert not z.radnici


def test_testni_mehanicar_ne_dobiva_i_vraca_se():
    from app.models import PlanDogadaj
    db = _session()
    test = Korisnik(ime="🧪 TEST Mehaničar", korisnicko_ime="test.meh.tok", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(test); db.flush()
    ana = _meh(db, "Ana")
    n = _nalog(db, "12", ana, prioritet_rang=0)
    # ranije (prije popravka) krivo dano testnom
    z_krivo = _zad(db, n, "GUME", "krivo", radnici=[test])
    db.add(PlanDogadaj(tip="auto-dodjela", opis="x", nalog_id=n.id, zadatak_id=z_krivo.id, radnik_id=test.id))
    n_test = _nalog(db, "TEST", ana, prioritet_rang=1)
    n_test.broj = "RN-TEST-TOK"
    z_test = _zad(db, n_test, "GUME", "probni")
    db.commit()
    out = popuni(db)
    assert [r.id for r in z_krivo.radnici] == [ana.id], "vraćen s testnog i dan pravom"
    assert not z_test.radnici, "probni nalog se ne dodjeljuje"
    assert all(d["radnik_id"] != test.id for d in out)


def test_popuni_ugaseno():
    db = _session()
    ana = _meh(db, "Ana")
    n = _nalog(db, "11", ana, prioritet_rang=0)
    z = _zad(db, n, "GUME", "x")
    norme.set_postavka(db, KLJUC, "0"); db.commit()
    assert popuni(db) == [] and not z.radnici


def test_red_po_prioritetu_i_hitno_ispred():
    db = _session()
    ana = _meh(db, "Ana")
    n_bez = _nalog(db, "12", ana, plan_rang=0)
    n_p2 = _nalog(db, "13", ana, plan_rang=1, prioritet_rang=1)
    n_p1 = _nalog(db, "14", ana, plan_rang=2, prioritet_rang=0)
    n_h = _nalog(db, "15", ana, plan_rang=3, plan_hitno=True)
    n_radi = _nalog(db, "16", ana, plan_rang=4)
    for n, o in ((n_bez, "bez"), (n_p2, "p2"), (n_p1, "p1"), (n_h, "hitno")):
        _zad(db, n, "GUME", o, radnici=[ana])
    _zad(db, n_radi, "GUME", "radi", radnici=[ana], zapoceto=datetime.now(timezone.utc) - timedelta(minutes=3))
    db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["radi", "hitno", "p1", "p2", "bez"]


def test_rucni_red_pobjeduje_a_novi_ulazi_po_prioritetu():
    db = _session()
    ana = _meh(db, "Ana")
    n_p1 = _nalog(db, "21", ana, prioritet_rang=0)
    n_p2 = _nalog(db, "22", ana, prioritet_rang=1)
    n_p3 = _nalog(db, "23", ana, prioritet_rang=2)
    n_bez = _nalog(db, "24", ana, plan_rang=0)
    # Ručno: bez prioriteta ispred p3 (Toni pomaknuo strelicom)
    _zad(db, n_bez, "GUME", "bez", radnici=[ana], red_ruc=0)
    _zad(db, n_p3, "GUME", "p3", radnici=[ana], red_ruc=1)
    db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["bez", "p3"], "ručni red pobjeđuje prioritet"
    # Novo dodijeljeni (bez ručnog mjesta) ulaze po prioritetu: p1 i p2 ispred ručnih jer su bolji
    _zad(db, n_p1, "GUME", "p1", radnici=[ana])
    _zad(db, n_p2, "GUME", "p2", radnici=[ana])
    db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["p1", "p2", "bez", "p3"]


def test_poslani_ostaje_prvi():
    db = _session()
    ana = _meh(db, "Ana")
    n_p1 = _nalog(db, "31", ana, prioritet_rang=0)
    n_bez = _nalog(db, "32", ana, plan_rang=0)
    _zad(db, n_bez, "GUME", "poslan", radnici=[ana], ceka_potvrdu=True)
    _zad(db, n_p1, "GUME", "p1", radnici=[ana])
    db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["poslan", "p1"]


def test_jednokratno_ocisti_rucni_red():
    db = _session()
    ana = _meh(db, "Ana")
    n = _nalog(db, "41", ana)
    z = _zad(db, n, "GUME", "a", radnici=[ana], red_ruc=3)
    zg = _zad(db, n, "GUME", "g", radnici=[ana], red_ruc=2, gotovo=True)
    db.commit()
    jednokratno_ocisti_rucni_red(db)
    db.refresh(z); db.refresh(zg)
    assert z.red_ruc is None and zg.red_ruc == 2
    z.red_ruc = 5; db.commit()
    jednokratno_ocisti_rucni_red(db)   # drugi put ne dira
    db.refresh(z)
    assert z.red_ruc == 5
