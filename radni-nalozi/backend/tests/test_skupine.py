"""Skupine poslova — „što tko radi" (Toni 20.11.2026.): perač ne dobiva elektriku.

- kategorija operacije → skupina (9 skupina, zavarivanje zasebno od 23.11.2026.; RAZNO/TEREN → None = samo ručno);
- auto-popunjavanje daje majstoru SAMO poslove iz njegovih označenih skupina;
- početne kućice iz povijesti rada (udio ≥ 15 % i ≥ 15 zapisa).
"""
import os
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import skupine
from app.auto_popuni import popuni
from app.database import Base
from app.models import Korisnik, Nalog, Operacija, PovijestRada, StatusNaloga, Uloga, Vozilo, Zadatak


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _meh(db, ime, sk=None):
    m = Korisnik(ime=ime, korisnicko_ime=ime.lower().replace(" ", "."), lozinka_hash="x",
                 uloga=Uloga.radnik, skupine_poslova=sk)
    db.add(m); db.flush()
    return m


def _zad(db, gb, kat, kreirao, prio):
    voz = Vozilo(gb=gb, marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj=f"RN-{gb}", vozilo_id=voz.id, naslov="T", kreirao_id=kreirao.id,
              status=StatusNaloga.u_radu, prioritet_rang=prio)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija=kat); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis=kat.lower()); db.add(z); db.flush()
    return z


@pytest.mark.parametrize("kat,sk", [
    ("PRANJE VOZILA", "pranje"), ("Pranje hladnjaka", "pranje"), ("ČIŠĆENJE KAMIONA", "pranje"),
    ("ELEKTRIKA 3", "elektrika"), ("DIJAGNOSTIKA-ELEKTRIKA", "elektrika"), ("KLIMA", "elektrika"),
    ("ABS/EBS", "elektrika"), ("Gume", "gume"), ("vulkanizer", "gume"),
    ("KOČNICE 2. OSOVINA", "podvozje"), ("PNEUMATIKA", "podvozje"), ("KOTAČI", "podvozje"),
    ("DIJELOVI OVJESA, GIBNJEVI, ZRAČNI JASTUCI", "podvozje"),
    ("REPARATURA SEDLA, VUČNE KUKE, RUDE", "podvozje"),
    ("HIDRAULIKA 2", "hidraulika"), ("DIJELOVI DIZALICE", "hidraulika"),
    ("IZRADA HIDRAULIČNIH CRIJEVA", "hidraulika"),
    ("MOTOR", "motor"), ("GETRIBA", "motor"), ("AD-BLUE", "motor"), ("HLADNJAK VODE I INTERCOOLER", "motor"),
    ("JASTUCI I ŠTICE", "limarija"), ("LIMARIJA2", "limarija"), ("BOJANJE", "limarija"),
    ("BRAVARIJA", "zavarivanje"), ("Bravarija 2", "zavarivanje"), ("ZAVARIVANJE", "zavarivanje"),
    ("ŠASIJA 3", "limarija"),
    ("SERVIS", "servis"), ("PODMAZIVANJE", "servis"),
    ("RAZNO", None), ("TEREN Bad Soden", None), ("Prikopčavanje, otkopčavanje, dovažanje i odvažanje", None),
    ("", None), (None, None),
])
def test_skupina_kategorije(kat, sk):
    assert skupine.skupina_kategorije(kat) == sk


def test_perac_ne_dobiva_elektriku():
    db = _session()
    perac = _meh(db, "Ivan Serniak", "pranje")
    elek = _meh(db, "Zlatko Kuzmic", "elektrika")
    for i in range(4):   # električar već ima posla (perač ima manje)
        _zad(db, f"9{i}", "MOTOR", elek, None).radnici = [elek]
    z_el = _zad(db, "10", "ELEKTRIKA", elek, 0)
    z_pr = _zad(db, "11", "PRANJE VOZILA", elek, 1)
    z_raz = _zad(db, "12", "RAZNO", elek, 2)
    db.commit()
    popuni(db)
    assert [r.id for r in z_el.radnici] == [elek.id], "elektrika električaru iako ima više posla"
    assert [r.id for r in z_pr.radnici] == [perac.id]
    assert not z_raz.radnici, "RAZNO ne ide automatski nikome"


def test_nitko_nema_skupinu_ostaje_u_planu():
    db = _session()
    perac = _meh(db, "Perac", "pranje")
    _meh(db, "Novi")                     # bez kućica (None) → ne dobiva ništa
    z = _zad(db, "20", "HIDRAULIKA", perac, 0)
    db.commit()
    assert popuni(db) == [] and not z.radnici


def test_popuni_iz_povijesti():
    db = _session()
    from app.routers.plan import SkupineIn, postavi_skupine
    perac = _meh(db, "Serniak Ivan")            # u aplikaciji obrnuto nego u povijesti
    elek = _meh(db, "Zlatko Kuzmić")
    vec = _meh(db, "Već Postavljen")
    postavi_skupine(SkupineIn(radnik_id=vec.id, skupine=["motor"]), _=vec, db=db)   # ručno
    voz = Vozilo(gb="1", marka="MAN"); db.add(voz); db.flush()
    d = date.today()

    def zapis(ime, kat, n):
        for _ in range(n):
            db.add(PovijestRada(vozilo_id=voz.id, datum=d, radnik=ime, operacija=kat))
    zapis("Ivan Serniak", "Pranje Vozila", 80)
    zapis("Ivan Serniak", "Limarija", 12)     # 13 % → ispod praga
    zapis("Ivan Serniak", "Motor", 5)
    zapis("Zlatko Kuzmic", "Elektrika", 60)   # bez kvačice u povijesti → svejedno se spoji
    zapis("Zlatko Kuzmic", "Motor", 20)
    zapis("Zlatko Kuzmic", "Razno", 500)      # bez skupine → ne računa se u udio
    zapis("Već Postavljen", "Pranje Vozila", 100)
    db.commit()
    skupine.jednokratno_popuni(db)
    assert perac.skupine_poslova == "pranje"
    assert elek.skupine_poslova == "elektrika,motor"
    assert vec.skupine_poslova == "motor", "ručno postavljene kućice se ne diraju"
    perac.skupine_poslova = "pranje,gume"; db.commit()
    skupine.jednokratno_popuni(db)            # drugi put ne radi ništa
    assert perac.skupine_poslova == "pranje,gume"


def test_razdvoji_zavarivanje():
    """#365: tko je imao „limarija" dobiva i „zavarivanje" samo ako je zavarivao (ili nema povijesti)."""
    db = _session()
    bravar = _meh(db, "Bravar Ivo", "limarija")
    lakirer = _meh(db, "Lakirer Ante", "limarija,pranje")
    novi = _meh(db, "Novi Majstor", "limarija")         # bez povijesti → zadrži dosadašnje
    perac = _meh(db, "Perac Pero", "pranje")             # nije limar → ne dira se
    voz = Vozilo(gb="1", marka="MAN"); db.add(voz); db.flush()
    d = date.today()
    for ime, kat, n in [("Bravar Ivo", "Bravarija", 40), ("Bravar Ivo", "Limarija", 30),
                        ("Lakirer Ante", "Limarija", 50), ("Lakirer Ante", "Bravarija", 3)]:
        for _ in range(n):
            db.add(PovijestRada(vozilo_id=voz.id, datum=d, radnik=ime, operacija=kat))
    db.commit()
    skupine.jednokratno_razdvoji_zavarivanje(db)
    assert bravar.skupine_poslova == "zavarivanje,limarija"
    assert lakirer.skupine_poslova == "limarija,pranje"
    assert novi.skupine_poslova == "zavarivanje,limarija"
    assert perac.skupine_poslova == "pranje"
    lakirer.skupine_poslova = "limarija"; db.commit()
    skupine.jednokratno_razdvoji_zavarivanje(db)        # drugi put ne radi ništa
    assert lakirer.skupine_poslova == "limarija"


@pytest.mark.parametrize("a,b,isto", [
    ("Antony Jeffin", "Jeffin Antony", True),
    ("Liushnenko Miykhailo", "Mykhailo Liushnenko", True),
    ("Ankudy Midhun Hari", "Midhun Hari Ankudy", True),
    ("Baček Matija", "Matija Bacek", True),
    ("Kovačević Dario", "Dario Šebec", False),
    ("Ivan", "Ivan Serniak", False),
])
def test_isto_ime(a, b, isto):
    assert skupine.isto_ime(a, b) is isto


def test_api_postavi_skupine():
    from app.routers.plan import SkupineIn, postavi_skupine
    db = _session()
    m = _meh(db, "Ana")
    r = postavi_skupine(SkupineIn(radnik_id=m.id, skupine=["motor", "pranje", "nepoznato"]), _=m, db=db)
    assert r["skupine"] == ["motor", "pranje"]
    assert m.skupine_poslova == "pranje,motor"
