"""Cartec valjci: mjerenja s računala u radioni → testovi kočnica vezani uz nalog/GB."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.models import TestKocnica as _Test
from app.routers import cartec
from app.routers.cartec import MjerenjeIn, OdobriIn, PrijavaIn, VeziIn

T0 = datetime(2026, 11, 17, 13, 4, 47, tzinfo=timezone.utc)
cartec._UPOZORENJE_U_POZADINI = False   # u testu bez pozadinske niti (jedna in-memory baza)


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _okolina(db):
    vod = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vod)
    db.commit()
    tok = cartec.prijava_uredjaja(PrijavaIn(naziv="Valjci"), db=db)["token"]
    cartec.odobri_uredjaj(1, OdobriIn(odobren=True), db=db, _=vod)
    return vod, tok


def _nalog(db, vod, gb, broj, u_radu=False, kategorija="Servis"):
    v = Vozilo(gb=gb)
    db.add(v)
    db.flush()
    n = Nalog(broj=broj, vozilo_id=v.id, naslov="x", kreirao_id=vod.id, status=StatusNaloga.u_radu)
    db.add(n)
    db.flush()
    op = Operacija(nalog_id=n.id, kategorija=kategorija)
    db.add(op)
    db.flush()
    db.add(Zadatak(operacija_id=op.id, opis="posao", zapoceto=(T0 if u_radu else None)))
    db.commit()
    return n


def _lista(db, k, status=None):
    return cartec.testovi(status=status, nalog_id=None, gb=None, limit=50, db=db, k=k)


def _m(osovina, l, d, t=T0, vrsta="radna", sesija="2026-11-17 14:01:29", otisak=None):
    return MjerenjeIn(sesija=sesija, osovina=osovina, vrsta=vrsta, vrijeme=t,
                      sila_lijevo=l, sila_desno=d, otisak=otisak or f"o{osovina}{vrsta}{l}{d}{t.timestamp()}")


def test_neodobren_uredjaj_odbijen():
    db = _db()
    tok = cartec.prijava_uredjaja(PrijavaIn(), db=db)["token"]
    with pytest.raises(HTTPException) as e:
        cartec.primi_mjerenje(_m(1, 100, 100), x_cartec_token=tok, db=db)
    assert e.value.status_code == 403


def test_veze_uz_nalog_u_radu_i_zadnje_mjerenje_vrijedi():
    db = _db()
    vod, tok = _okolina(db)
    n = _nalog(db, vod, "458", "RN-1", u_radu=True)
    _nalog(db, vod, "156", "RN-2", u_radu=False)
    r = cartec.primi_mjerenje(_m(1, 1849, 1721), x_cartec_token=tok, db=db)
    assert r["status"] == "vezan" and r["nalog_id"] == n.id and r["gb"] == "458"
    cartec.primi_mjerenje(_m(2, 4459, 4280, T0 + timedelta(minutes=3)), x_cartec_token=tok, db=db)
    # mehaničar ponovi osovinu 2
    cartec.primi_mjerenje(_m(2, 4614, 5681, T0 + timedelta(minutes=8)), x_cartec_token=tok, db=db)
    # isto mjerenje stiglo dvaput → ne duplicira
    dup = cartec.primi_mjerenje(_m(2, 4614, 5681, T0 + timedelta(minutes=8)), x_cartec_token=tok, db=db)
    assert dup.get("duplikat")
    [t] = _lista(db, vod)
    o2 = [m for m in t["mjerenja"] if m["osovina"] == 2]
    assert len(o2) == 2 and [m["vazece"] for m in o2] == [False, True]
    zadnje = [m for m in o2 if m["vazece"]][0]
    assert (zadnje["sila_lijevo"], zadnje["sila_desno"], zadnje["razlika_pct"]) == (4614, 5681, 18.8)
    assert t["osovina"] == 2


def test_vise_mogucih_vozila_nerazvrstan_i_blokira_zatvaranje():
    db = _db()
    vod, tok = _okolina(db)
    a = _nalog(db, vod, "458", "RN-1", u_radu=True)
    b = _nalog(db, vod, "156", "RN-2", u_radu=True)
    r = cartec.primi_mjerenje(_m(1, 500, 500), x_cartec_token=tok, db=db)
    assert r["status"] == "nerazvrstan" and r["nalog_id"] is None
    [t] = _lista(db, vod, "otvoreni")
    assert {x["id"] for x in t["kandidati"]} == {a.id, b.id}
    assert cartec.blokira_zatvaranje(db, a.id) is not None
    # Vozilo za test bira samo voditelj/poslovođa — mehaničar ne.
    meh = Korisnik(ime="Meho", korisnicko_ime="meho", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(meh)
    db.commit()
    try:
        cartec.vezi_test(t["id"], VeziIn(nalog_id=b.id), db=db, k=meh)
        assert False, "mehaničar ne smije vezati test"
    except HTTPException as e:
        assert e.status_code == 403
    cartec.vezi_test(t["id"], VeziIn(nalog_id=b.id), db=db, k=vod)
    assert cartec.blokira_zatvaranje(db, a.id) is None
    t2 = db.get(_Test, t["id"])
    assert (t2.status, t2.gb) == ("vezan", "156")


def test_poveznica_bez_prijave_upis_gb():
    db = _db()
    vod, tok = _okolina(db)
    a = _nalog(db, vod, "458", "RN-1", u_radu=True)
    _nalog(db, vod, "156", "RN-2", u_radu=True)
    cartec.primi_mjerenje(_m(1, 500, 500), x_cartec_token=tok, db=db)
    [t] = _lista(db, vod, "otvoreni")
    oznaka = cartec.poveznica_testa(t["id"], db=db, k=vod)["putanja"].rsplit("/", 1)[1]
    assert len(oznaka) >= 20
    j = cartec.javni_test(oznaka, db=db)
    assert j["status"] == "nerazvrstan" and len(j["mjerenja"]) == 1 and "kandidati" not in j
    # Kriva oznaka i nepoznat GB se odbijaju.
    for poziv in (lambda: cartec.javni_test("nema-takve", db=db),
                  lambda: cartec.javni_upis_gb(oznaka, cartec.JavnoGbIn(gb="99999"), db=db)):
        try:
            poziv()
            assert False
        except HTTPException as e:
            assert e.status_code == 404
    r = cartec.javni_upis_gb(oznaka, cartec.JavnoGbIn(gb="458"), db=db)
    assert (r["test"]["status"], r["test"]["gb"], r["test"]["nalog"]["id"]) == ("vezan", "458", a.id)
    # Ručni upis je konačan — iduća osovina ga ne mijenja.
    r2 = cartec.primi_mjerenje(_m(2, 600, 600), x_cartec_token=tok, db=db)
    assert (r2["status"], r2["gb"]) == ("vezan", "458")
    # Vozilo bez otvorenog naloga: veže se samo uz GB.
    db.add(Vozilo(gb="777"))
    db.commit()
    r3 = cartec.javni_upis_gb(oznaka, cartec.JavnoGbIn(gb="777"), db=db)
    assert (r3["test"]["gb"], r3["test"]["nalog"]) == ("777", None)
    # Brisanje vozila: test je opet prazan.
    r4 = cartec.javni_ponisti_gb(oznaka, db=db)
    assert (r4["test"]["status"], r4["test"]["gb"], r4["test"]["nalog"]) == ("nerazvrstan", None, None)


def test_broj_iz_imenika_po_dijelu_imena():
    zapisi = [{"ime": "JENDRIŠ TONI", "broj": "0911"}, {"ime": "JENDRIŠ NIKOLA", "broj": "0922"},
              {"ime": "MARKO KOVAČ", "broj": "0933"}, {"ime": "MARKO HORVAT", "broj": "0944"}]
    assert cartec._broj_iz_zapisa("Toni", zapisi) == "0911"
    assert cartec._broj_iz_zapisa("Kovač Marko", zapisi) == "0933"
    assert cartec._broj_iz_zapisa("Marko", zapisi) is None        # dvojica — ne pogađamo
    assert cartec._broj_iz_zapisa("Pero", zapisi) is None


def test_obavijest_tek_kad_vozilo_sidje(monkeypatch):
    db = _db()
    vod, tok = _okolina(db)
    poslano = []
    monkeypatch.setattr(cartec, "_obavijesti_kraj", lambda db, t: poslano.append(t.id))
    for i in (1, 2):
        cartec.primi_mjerenje(_m(i, 500, 500, T0 + timedelta(minutes=i)), x_cartec_token=tok, db=db)
    assert poslano == []                       # dok traje test — ništa
    r = cartec.kraj_testa(cartec.KrajIn(vrijeme=T0 + timedelta(minutes=3)), x_cartec_token=tok, db=db)
    assert r["poslano"] and poslano == [r["test_id"]]
    # drugi znak kraja istog testa i rezerva (/stanje) ne šalju ponovno
    cartec.kraj_testa(cartec.KrajIn(vrijeme=T0 + timedelta(minutes=4)), x_cartec_token=tok, db=db)
    assert len(poslano) == 1
    # znak kraja bez svježeg testa (valjci vrtjeli prazni) — ništa
    r2 = cartec.kraj_testa(cartec.KrajIn(vrijeme=T0 + timedelta(hours=2)), x_cartec_token=tok, db=db)
    assert r2["test_id"] is None and len(poslano) == 1
    # vozilo se vratilo na valjke (ista Cartec sesija) → nakon novog kraja opet poruka
    t = db.get(_Test, r["test_id"])
    t.obavijesteno = T0 + timedelta(minutes=3)
    db.commit()
    cartec.primi_mjerenje(_m(3, 500, 500, T0 + timedelta(minutes=10)), x_cartec_token=tok, db=db)
    cartec.kraj_testa(cartec.KrajIn(vrijeme=T0 + timedelta(minutes=11)), x_cartec_token=tok, db=db)
    assert len(poslano) == 2


def test_rezervna_obavijest_bez_znaka_kraja(monkeypatch):
    db = _db()
    vod, tok = _okolina(db)
    poslano = []
    monkeypatch.setattr(cartec, "_obavijesti_kraj", lambda db, t: poslano.append(t.id))
    sad = datetime.now(timezone.utc)
    cartec.primi_mjerenje(_m(1, 500, 500, sad - timedelta(minutes=2)), x_cartec_token=tok, db=db)
    cartec.javi_stanje(cartec.StanjeIn(verzija="3"), x_cartec_token=tok, db=db)
    assert poslano == []                       # zadnja osovina prije 2 min — možda ide još koja
    t = db.query(_Test).one()
    t.kraj = sad - timedelta(minutes=6)
    db.commit()
    cartec.javi_stanje(cartec.StanjeIn(verzija="3"), x_cartec_token=tok, db=db)
    cartec.javi_stanje(cartec.StanjeIn(verzija="3"), x_cartec_token=tok, db=db)
    assert poslano == [t.id]


def test_nova_sesija_je_novi_test():
    db = _db()
    vod, tok = _okolina(db)
    _nalog(db, vod, "458", "RN-1", u_radu=True)
    cartec.primi_mjerenje(_m(1, 500, 500), x_cartec_token=tok, db=db)
    cartec.primi_mjerenje(_m(1, 600, 600, T0 + timedelta(minutes=20), sesija="2026-11-17 14:30:00"),
                          x_cartec_token=tok, db=db)
    assert len(_lista(db, vod)) == 2


def test_vise_osovina_nego_prosli_put_trazi_potvrdu():
    db = _db()
    vod, tok = _okolina(db)
    n = _nalog(db, vod, "458", "RN-1", u_radu=True)
    for i in (1, 2):
        cartec.primi_mjerenje(_m(i, 500, 500, sesija="s1"), x_cartec_token=tok, db=db)
    kasnije = T0 + timedelta(days=30)
    r = None
    for i in (1, 2, 3):
        r = cartec.primi_mjerenje(_m(i, 500, 500, kasnije + timedelta(minutes=i), sesija="s2"),
                                  x_cartec_token=tok, db=db)
    assert r["status"] == "ceka_potvrdu"
    assert cartec.blokira_zatvaranje(db, n.id) is not None


def test_stanje_i_skripta_za_samoazuriranje():
    db = _db()
    tok = cartec.prijava_uredjaja(PrijavaIn(), db=db)["token"]
    # neodobren smije javiti stanje, ali ne smije dohvatiti skriptu
    r = cartec.javi_stanje(cartec.StanjeIn(verzija="2", dnevnik="red1\nred2"), x_cartec_token=tok, db=db)
    assert r == {"ok": True, "odobren": False}
    with pytest.raises(HTTPException):
        cartec.skripta(x_cartec_token=tok, db=db)
    vod = Korisnik(ime="Toni", korisnicko_ime="toni", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vod)
    db.commit()
    cartec.odobri_uredjaj(1, OdobriIn(odobren=True), db=db, _=vod)
    s = cartec.skripta(x_cartec_token=tok, db=db)
    assert s["verzija"] and int(s["verzija"]) >= 2 and "AxleData" in s["sadrzaj"]
    [u] = cartec.uredjaji(db=db, _=vod)
    assert u["verzija"] == "2" and "red2" in u["stanje"]


def test_skripta_ima_red_neposlanih():
    # v8: mjerenje koje ne ode (pukla veza) ide u trajni red i šalje se kasnije.
    put = cartec._skripta_put()
    tekst = put.read_text(encoding="utf-8-sig")
    assert int(cartec._verzija_skripte(tekst)) >= 8
    assert "red.txt" in tekst and "function PosaljiRed" in tekst and "URed $tijelo" in tekst
