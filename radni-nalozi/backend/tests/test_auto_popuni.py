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
from app.skupine import KLJUCEVI


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _meh(db, ime, **kw):
    kw.setdefault("skupine_poslova", ",".join(KLJUCEVI))   # zadano: smije sve skupine
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
    n_x = _nalog(db, "50", ana, plan_rang=4)
    n_y = _nalog(db, "51", ana, plan_rang=5)
    z_x = _zad(db, n_x, "GUME", "x")
    z_y = _zad(db, n_y, "GUME", "y")
    # već radi na jednom (računa se u 5)
    n_r = _nalog(db, "52", ana, plan_rang=9)
    _zad(db, n_r, "GUME", "radi", radnici=[ana], zapoceto=datetime.now(timezone.utc))
    db.commit()

    out = popuni(db)
    # min 5 u redu: 1 već radi + 4 nova — HITNO, prioritet 1, prioritet 2, pa po planu
    assert [d["zadatak_id"] for d in out] == [z_h.id, z_p1.id, z_p2.id, z_bez.id]
    assert not z_x.radnici and not z_y.radnici
    # opet → ništa (ima 5)
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
    # Od 25.11.2026. automatika samo PREDLAŽE (dodjela tek kad poslovođa prihvati).
    assert not z_hid.radnici and not z_gum.radnici, "ništa se ne dodjeljuje samo"
    assert z_hid.prijedlog_radnik_id == bob.id, "hidraulika ide onome tko ju je radio"
    assert z_gum.prijedlog_radnik_id == ana.id, "ostalo onome s najmanje posla"


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
    # Od 25.11.2026. i nalog izvan plana dobiva prijedlog, ali IZA prioritetnog.
    assert [d["zadatak_id"] for d in out] == [z_ok.id, z_van.id]
    assert all(d["radnik"] == "Ana" for d in out), "odsutni ne dobiva posao"
    for z in (z_dij, z_odg, z_preg):
        assert not z.radnici and z.prijedlog_radnik_id is None


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
    assert not z_krivo.radnici and z_krivo.prijedlog_radnik_id == ana.id, "vraćen s testnog i predložen pravom"
    assert not z_test.radnici, "probni nalog se ne dodjeljuje"
    assert all(d["radnik_id"] != test.id for d in out)


def test_skladistar_ne_dobiva_i_vraca_se():
    db = _session()
    sk = Korisnik(ime="Akshay", korisnicko_ime="akshay", lozinka_hash="x",
                  uloga=Uloga.skladistar, radi_na_nalozima=True)
    db.add(sk); db.flush()
    ana = _meh(db, "Ana")
    n = _nalog(db, "61", ana, prioritet_rang=0)
    z_rucno = _zad(db, n, "GUME", "rucno", radnici=[sk])   # ručno mu dano
    z_novi = _zad(db, n, "GUME", "novi")
    db.commit()
    out = popuni(db)
    assert all(d["radnik_id"] != sk.id for d in out)
    assert sk.id not in [r.id for r in z_rucno.radnici]
    assert z_novi.prijedlog_radnik_id == ana.id


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


def test_poslani_ostaje_prvi():
    db = _session()
    ana = _meh(db, "Ana")
    n_p1 = _nalog(db, "31", ana, prioritet_rang=0)
    n_bez = _nalog(db, "32", ana, plan_rang=0)
    _zad(db, n_bez, "GUME", "poslan", radnici=[ana], ceka_potvrdu=True)
    _zad(db, n_p1, "GUME", "p1", radnici=[ana])
    db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["poslan", "p1"]


def test_stari_cekaju_potvrdu_ne_blokiraju_prioritet():
    """Radi na nečemu → stare oznake „čeka potvrdu" ne smiju biti ispred prioriteta;
    ne radi ništa → ispred ostaje samo JEDAN poslani (onaj koji vidi)."""
    db = _session()
    ana = _meh(db, "Ana")
    n_p1 = _nalog(db, "51", ana, prioritet_rang=0)
    n_a = _nalog(db, "52", ana, plan_rang=0)
    n_b = _nalog(db, "53", ana, plan_rang=1)
    n_r = _nalog(db, "54", ana, plan_rang=2)
    _zad(db, n_a, "GUME", "staroA", radnici=[ana], ceka_potvrdu=True)
    _zad(db, n_b, "GUME", "staroB", radnici=[ana], ceka_potvrdu=True)
    _zad(db, n_p1, "GUME", "p1", radnici=[ana])
    radi = _zad(db, n_r, "GUME", "radi", radnici=[ana], zapoceto=datetime.now(timezone.utc))
    db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["radi", "p1", "staroA", "staroB"]
    radi.zapoceto = None; radi.gotovo = True; db.commit()
    assert [t[2].opis for t in _red(db, ana)] == ["staroA", "p1", "staroB"]


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


def test_zapoceti_posao_ide_onome_tko_ga_je_radio():
    """23.11.2026.: Pavliukhov AdBlue (18 h) dobio je drugi majstor. Započeti zadatak bez
    dodjele ide prisutnom majstoru koji je na njemu radio; ako mu je red pun, čeka ga;
    ako je odsutan, ide po normalnim pravilima."""
    from app.models import ZadatakRadnikVrijeme
    db = _session()
    pav = _meh(db, "Pavliukh")
    sca = _meh(db, "Scancar")
    odsutni = _meh(db, "Borovyk", odsutnost_vrsta="godisnji")
    n1 = _nalog(db, "488", pav, prioritet_rang=0)
    n2 = _nalog(db, "501", pav, prioritet_rang=1)
    z_adblue = _zad(db, n1, "DIJAGNOSTIKA-ELEKTRIKA", "adblue")
    z_ploca = _zad(db, n2, "ŠASIJA", "ploča")
    db.add(ZadatakRadnikVrijeme(zadatak_id=z_adblue.id, radnik_id=pav.id, utroseno_sek=18 * 3600))
    db.add(ZadatakRadnikVrijeme(zadatak_id=z_ploca.id, radnik_id=odsutni.id, utroseno_sek=8 * 3600))
    # Pavliukh ima više posla od Ščanćara — po staroj logici AdBlue bi dobio Ščanćar
    for i in range(3):
        _zad(db, _nalog(db, f"7{i}", pav, plan_rang=9), "GUME", f"g{i}", radnici=[pav])
    db.commit()
    popuni(db)
    assert z_adblue.prijedlog_radnik_id == pav.id
    assert z_ploca.prijedlog_radnik_id not in (None, odsutni.id), "odsutni → drugome"


def test_zapoceti_posao_ceka_majstora_s_punim_redom():
    from app.models import ZadatakRadnikVrijeme
    db = _session()
    pav = _meh(db, "Pavliukh")
    sca = _meh(db, "Scancar")
    for i in range(5):
        _zad(db, _nalog(db, f"8{i}", pav, plan_rang=9), "GUME", f"g{i}", radnici=[pav])
    z = _zad(db, _nalog(db, "488", pav, prioritet_rang=0), "MOTOR", "adblue")
    db.add(ZadatakRadnikVrijeme(zadatak_id=z.id, radnik_id=pav.id, utroseno_sek=3600))
    db.commit()
    popuni(db)
    assert not z.radnici and z.prijedlog_radnik_id is None, "red mu je pun — posao čeka njega, ne ide Ščanćaru"


# --- Prijedlozi (Toni 25.11.2026.): automatika predlaže, poslovođa prihvaća/odbija/seli ---
def test_prijedlog_prihvati_odbij_premjesti():
    from app.routers import plan as plan_r
    db = _session()
    sef = Korisnik(ime="Šef", korisnicko_ime="sef", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(sef); db.flush()
    ana = _meh(db, "Ana")
    bob = _meh(db, "Bob")
    for i in range(4):   # Bob ima 4 → dobiva prijedloge tek do 5
        _zad(db, _nalog(db, f"9{i}", ana, plan_rang=9), "GUME", f"b{i}", radnici=[bob])
    z1 = _zad(db, _nalog(db, "61", ana, prioritet_rang=0), "GUME", "jedan")
    z2 = _zad(db, _nalog(db, "62", ana, prioritet_rang=1), "GUME", "dva")
    db.commit()

    popuni(db)
    assert {z1.prijedlog_radnik_id, z2.prijedlog_radnik_id} <= {ana.id, bob.id}
    assert not z1.radnici and not z2.radnici

    # Odbij → tom mehaničaru se više ne predlaže
    odbijen = z1.prijedlog_radnik_id
    plan_r.prijedlog_odbij(z1.id, korisnik=sef, db=db)
    assert z1.prijedlog_radnik_id is None
    popuni(db)
    assert z1.prijedlog_radnik_id not in (odbijen,)

    # Premjesti prijedlog drugome, pa prihvati → tek tada je dodijeljen
    drugi = bob if z2.prijedlog_radnik_id == ana.id else ana
    plan_r.prijedlog_premjesti(z2.id, plan_r.PrijedlogPremjestiIn(na_radnika=drugi.id), korisnik=sef, db=db)
    assert z2.prijedlog_radnik_id == drugi.id and not z2.radnici
    plan_r.prijedlog_prihvati(z2.id, korisnik=sef, db=db)
    assert [r.id for r in z2.radnici] == [drugi.id] and z2.prijedlog_radnik_id is None


def test_prihvati_sve_i_gasenje():
    from app.routers import plan as plan_r
    db = _session()
    sef = Korisnik(ime="Šef", korisnicko_ime="sef", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(sef); db.flush()
    ana = _meh(db, "Ana")
    zz = [_zad(db, _nalog(db, f"7{i}", ana, prioritet_rang=i), "GUME", f"z{i}") for i in range(3)]
    db.commit()
    popuni(db)
    assert all(z.prijedlog_radnik_id == ana.id for z in zz)
    r = plan_r.prijedlozi_prihvati_sve(plan_r.PrihvatiSveIn(radnik_id=ana.id), korisnik=sef, db=db)
    assert r["prihvaceno"] == 3 and all([x.id for x in z.radnici] == [ana.id] for z in zz)


def test_danasnje_auto_dodjele_postaju_prijedlozi():
    from datetime import date
    from app.auto_popuni import jednokratno_dodjele_u_prijedloge
    from app.models import PlanDogadaj
    db = _session()
    ana = _meh(db, "Ana")
    n = _nalog(db, "80", ana, prioritet_rang=0)
    z_auto = _zad(db, n, "GUME", "auto", radnici=[ana])
    z_poslan = _zad(db, n, "GUME", "poslan", radnici=[ana], ceka_potvrdu=True)
    for z in (z_auto, z_poslan):
        db.add(PlanDogadaj(tip="auto-dodjela", opis="x", nalog_id=n.id, zadatak_id=z.id,
                           radnik_id=ana.id, datum=date(2026, 11, 25)))
    db.commit()
    jednokratno_dodjele_u_prijedloge(db)
    assert not z_auto.radnici and z_auto.prijedlog_radnik_id == ana.id
    assert [r.id for r in z_poslan.radnici] == [ana.id], "već poslan mehaničaru ostaje dodijeljen"


def test_bez_gps_nema_prijedloga_a_daleko_vozilo_gubi_prijedlog(monkeypatch):
    """25.11.2026.: nakon objave GPS keš je prazan → GB 298 (47 km) dobio prijedlog.
    Dok GPS nije učitan nema novih prijedloga; vozilo vani gubi postojeći prijedlog."""
    from app import auto_popuni as ap
    db = _session()
    ana = _meh(db, "Ana")
    z_tu = _zad(db, _nalog(db, "399", ana, prioritet_rang=0), "GUME", "u radioni")
    z_vani = _zad(db, _nalog(db, "298", ana, prioritet_rang=1), "GUME", "vani")
    db.commit()
    udalj = {"399": 90, "298": 47000}
    monkeypatch.setattr(ap.flota, "udaljenost_od_radione", lambda gb: udalj.get(gb))

    monkeypatch.setattr(ap.flota, "gps_ucitan", lambda: False)
    assert popuni(db) == [] and z_tu.prijedlog_radnik_id is None, "bez GPS-a ništa"

    monkeypatch.setattr(ap.flota, "gps_ucitan", lambda: True)
    popuni(db)
    assert z_tu.prijedlog_radnik_id == ana.id and z_vani.prijedlog_radnik_id is None

    # prijedlog od prije (npr. dok GPS nije bio učitan) za vozilo koje je vani → pada
    z_vani.prijedlog_radnik_id = ana.id
    db.commit()
    popuni(db)
    assert z_vani.prijedlog_radnik_id is None


def test_izvan_plana_tek_kad_nema_prioritetnih():
    """Toni 25.11.2026.: do 5 zadataka s prijedlozima; prioritetna vozila imaju prednost
    pred nalozima koji nisu u planu."""
    db = _session()
    ana = _meh(db, "Ana")
    van = [_zad(db, _nalog(db, f"6{i}", ana), "GUME", f"van{i}") for i in range(4)]   # izvan plana
    pri = [_zad(db, _nalog(db, f"7{i}", ana, prioritet_rang=i), "GUME", f"p{i}") for i in range(3)]
    db.commit()
    out = popuni(db)
    ids = [d["zadatak_id"] for d in out]
    assert len(ids) == 5, "do 5 s prijedlozima"
    assert ids[:3] == [z.id for z in pri], "prvo prioritetni"
    assert ids[3:] == [van[0].id, van[1].id], "pa izvan plana (stariji prvi)"
