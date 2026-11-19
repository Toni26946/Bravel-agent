"""Red zadataka mehaničara + ručni pomak u Radnicima (Toni 19.11.2026., stvarni slučajevi).

- Pomak strelicom daje ručni ključ SAMO pomaknutoj kartici; ostale ostaju po prioritetu
  (prije je jedan pomak „zaledio" cijeli redak → GB 197 je ostao zadnji iako je u prioritetima).
- Zajednička operacija koju je pokrenuo DRUGI mehaničar nije „u tijeku" za ovoga
  (prije se GB 210 kod Darija vraćao na prvo mjesto jer ga je radio Baček).
- Pomak na prvo mjesto dok mehaničar čeka potvrdu → stari poslani se poništi, nova poruka.
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak, ZadatakRadnikVrijeme,
)
from app.routers.dispecer import _red
from app.routers.plan import MehRedoslijedIn, PremjestiIn, meh_redoslijed, premjesti

_REQ = types.SimpleNamespace(base_url="https://x/")


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _meh(db, ime):
    m = Korisnik(ime=ime, korisnicko_ime=ime.lower(), lozinka_hash="x", uloga=Uloga.radnik)
    db.add(m); db.flush()
    return m


def _nalog(db, gb, kreirao, **kw):
    voz = Vozilo(gb=gb, marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj=f"RN-{gb}-{kw.get('plan_rang')}-{kw.get('prioritet_rang')}", vozilo_id=voz.id,
              naslov="T", kreirao_id=kreirao.id, status=StatusNaloga.u_radu, **kw)
    db.add(n); db.flush()
    return n


def _zad(db, n, opis, radnici, **kw):
    op = Operacija(nalog_id=n.id, kategorija="X"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis=opis, **kw)
    z.radnici = list(radnici)
    db.add(z); db.flush()
    return z


def _opisi(db, m):
    return [t[2].opis for t in _red(db, m)]


def _pomakni(db, m, zid, smjer, vlasnik):
    """Kao strelica ◀/▶ u Radnicima: zamijeni karticu sa susjedom i pošalji poredak."""
    red = [t[2].id for t in _red(db, m)]
    i = red.index(zid); j = i + smjer
    red[i], red[j] = red[j], red[i]
    return meh_redoslijed(MehRedoslijedIn(radnik_id=m.id, zadaci=red, pomaknut=zid),
                          request=_REQ, korisnik=vlasnik, db=db)


def test_dario_zajednicki_210_koji_radi_bacek_se_moze_pomaknuti():
    db = _session()
    vl = _meh(db, "Vlasnik")
    dario, bacek = _meh(db, "Dario"), _meh(db, "Bacek")
    n210 = _nalog(db, "210", vl, plan_rang=13, prioritet_rang=5)
    n200 = _nalog(db, "200", vl, plan_rang=36, prioritet_rang=8)
    n227 = _nalog(db, "227", vl, plan_rang=30)
    z210 = _zad(db, n210, "GB210", [dario, bacek], zapoceto=datetime.now(timezone.utc))
    db.add(ZadatakRadnikVrijeme(zadatak_id=z210.id, radnik_id=bacek.id,
                                zapoceto=datetime.now(timezone.utc) - timedelta(minutes=5)))
    db.add(ZadatakRadnikVrijeme(zadatak_id=z210.id, radnik_id=dario.id))
    z200 = _zad(db, n200, "GB200", [dario], utroseno_sek=600)
    _zad(db, n227, "GB227", [dario])
    db.commit()
    assert _opisi(db, dario) == ["GB210", "GB200", "GB227"], "po prioritetu (210 = prio 6, 200 = prio 9)"
    assert _opisi(db, bacek)[0] == "GB210", "Bačeku je 210 u tijeku"

    _pomakni(db, dario, z200.id, -1, vl)
    assert _opisi(db, dario) == ["GB200", "GB210", "GB227"], "pomak ostaje (ne vraća se)"
    assert _opisi(db, bacek)[0] == "GB210", "Bačekov redak se ne mijenja"


def test_pavliukh_197_u_prioritetu_nije_zadnji_nakon_pomaka():
    db = _session()
    vl = _meh(db, "Vlasnik")
    pav, gmit = _meh(db, "Pavliukh"), _meh(db, "Gmitrovic")
    n468 = _nalog(db, "468", vl, plan_rang=1)
    n197 = _nalog(db, "197", vl, plan_rang=20, prioritet_rang=3)
    a = _zad(db, n468, "468a", [pav])
    b = _zad(db, n468, "468b", [pav])
    c = _zad(db, n468, "468c", [pav])
    _zad(db, n197, "197", [pav, gmit])
    db.commit()
    assert _opisi(db, pav) == ["197", "468a", "468b", "468c"]
    # Toni zamijeni 468b i 468c → 197 i dalje prvi (prioritet), ostatak po njegovom pomaku
    _pomakni(db, pav, c.id, -1, vl)
    assert _opisi(db, pav) == ["197", "468a", "468c", "468b"]
    # Novi prioritetni zadatak ulazi ispred svih bez prioriteta
    n45 = _nalog(db, "45", vl, plan_rang=5, prioritet_rang=0)
    _zad(db, n45, "45", [pav])
    db.commit()
    assert _opisi(db, pav) == ["45", "197", "468a", "468c", "468b"]
    z197 = next(t[2] for t in _red(db, pav) if t[2].opis == "197")
    assert a.red_ruc is None and z197.red_ruc is None, "nepomaknute kartice ostaju po prioritetu"


def test_vise_operacija_istog_naloga_i_strelice_tamo_natrag():
    db = _session()
    vl = _meh(db, "Vlasnik")
    gm = _meh(db, "Gmitrovic")
    n45 = _nalog(db, "45", vl, prioritet_rang=0)
    z = [_zad(db, n45, f"45-{i}", [gm]) for i in range(4)]
    db.commit()
    assert _opisi(db, gm) == ["45-0", "45-1", "45-2", "45-3"]
    _pomakni(db, gm, z[3].id, -1, vl)
    assert _opisi(db, gm) == ["45-0", "45-1", "45-3", "45-2"]
    _pomakni(db, gm, z[3].id, -1, vl)
    assert _opisi(db, gm) == ["45-0", "45-3", "45-1", "45-2"]
    _pomakni(db, gm, z[3].id, -1, vl)
    assert _opisi(db, gm) == ["45-3", "45-0", "45-1", "45-2"]
    _pomakni(db, gm, z[0].id, -1, vl)
    assert _opisi(db, gm) == ["45-0", "45-3", "45-1", "45-2"]
    for _ in range(6):   # puno pomaka tamo-natrag ne smije pokvariti red
        _pomakni(db, gm, z[1].id, 1, vl)
        _pomakni(db, gm, z[1].id, -1, vl)
    assert _opisi(db, gm) == ["45-0", "45-3", "45-1", "45-2"]


def test_pomak_na_prvo_dok_ceka_potvrdu_salje_novu_poruku():
    db = _session()
    vl = _meh(db, "Vlasnik")
    ana = _meh(db, "Ana")
    n1 = _nalog(db, "1", vl, prioritet_rang=0)
    n2 = _nalog(db, "2", vl, plan_rang=0)
    p = _zad(db, n1, "P", [ana])
    x = _zad(db, n2, "X", [ana], ceka_potvrdu=True)   # poslan, vidi ga na mobitelu
    db.commit()
    assert _opisi(db, ana) == ["X", "P"], "poslani ostaje prvi dok ga Toni ne makne"
    r = _pomakni(db, ana, p.id, -1, vl)
    assert r["poslano"] is True
    assert _opisi(db, ana) == ["P", "X"]
    assert p.ceka_potvrdu is True and x.ceka_potvrdu is False
    r = _pomakni(db, ana, x.id, -1, vl)   # i natrag
    assert r["poslano"] is True and _opisi(db, ana) == ["X", "P"]
    # Poredak bez promjene prvog → nema nove poruke
    r = meh_redoslijed(MehRedoslijedIn(radnik_id=ana.id, zadaci=[x.id, p.id], pomaknut=p.id),
                       request=_REQ, korisnik=vl, db=db)
    assert r["poslano"] is False and _opisi(db, ana) == ["X", "P"]


def test_pomak_dok_radi_ne_salje_poruku():
    db = _session()
    vl = _meh(db, "Vlasnik")
    ana = _meh(db, "Ana")
    nr = _nalog(db, "9", vl, plan_rang=0)
    n1 = _nalog(db, "1", vl, prioritet_rang=0)
    n2 = _nalog(db, "2", vl, plan_rang=1)
    _zad(db, nr, "RADI", [ana], zapoceto=datetime.now(timezone.utc))
    p = _zad(db, n1, "P", [ana])
    x = _zad(db, n2, "X", [ana])
    db.commit()
    r = _pomakni(db, ana, x.id, -1, vl)
    assert r["poslano"] is False
    assert _opisi(db, ana) == ["RADI", "X", "P"]


def test_premjesti_na_drugog_samo_pomaknuti_dobiva_mjesto():
    db = _session()
    vl = _meh(db, "Vlasnik")
    a, b = _meh(db, "A"), _meh(db, "B")
    n1 = _nalog(db, "1", vl, prioritet_rang=0)
    n2 = _nalog(db, "2", vl, prioritet_rang=1)
    n3 = _nalog(db, "3", vl, plan_rang=0)
    b1 = _zad(db, n1, "B1", [b])
    b2 = _zad(db, n2, "B2", [b])
    s = _zad(db, n3, "SELI", [a])
    db.commit()
    premjesti(PremjestiIn(zadatak_id=s.id, s_radnika=a.id, na_radnika=b.id,
                          redoslijed=[b1.id, s.id, b2.id]), request=_REQ, korisnik=vl, db=db)
    assert _opisi(db, b) == ["B1", "SELI", "B2"]
    assert b1.red_ruc is None and b2.red_ruc is None


def test_pomak_ispred_poslanog_ostaje_i_kad_nova_poruka_ne_ode(monkeypatch):
    """WhatsApp #339/#340 (Baranov, GB 110): ◀ na drugoj kartici ispred „Čeka potvrdu" —
    ako nova poruka iz bilo kojeg razloga ne ode, kartica NE smije tiho skočiti natrag."""
    from app.routers import plan as plan_mod
    monkeypatch.setattr(plan_mod, "_novi_prvi_posalji", lambda *a, **k: False)
    db = _session()
    vl = _meh(db, "Vlasnik")
    bar = _meh(db, "Baranov")
    n = _nalog(db, "110", vl, plan_rang=3)
    brav = _zad(db, n, "bravarija", [bar], ceka_potvrdu=True)
    okr = _zad(db, n, "okretnica", [bar])
    db.commit()
    assert _opisi(db, bar) == ["bravarija", "okretnica"]
    r = _pomakni(db, bar, okr.id, -1, vl)
    assert _opisi(db, bar) == ["okretnica", "bravarija"], "ručni pomak ostaje"
    assert r["red"] == [okr.id, brav.id]
    assert brav.ceka_potvrdu is False
    # Pomak koji NE stavlja karticu na prvo mjesto ne dira poslani zadatak
    db2 = _session()
    vl2 = _meh(db2, "V"); m = _meh(db2, "M")
    n2 = _nalog(db2, "1", vl2, plan_rang=1)
    a = _zad(db2, n2, "A", [m], ceka_potvrdu=True)
    b = _zad(db2, n2, "B", [m]); c = _zad(db2, n2, "C", [m])
    db2.commit()
    _pomakni(db2, m, c.id, -1, vl2)
    assert _opisi(db2, m) == ["A", "C", "B"] and a.ceka_potvrdu is True
