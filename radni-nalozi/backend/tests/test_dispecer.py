"""Test dispečera: login-less tok zadatka (token + vezanje uređaja + 3 akcije).

Pokriva: stanje veže prvi uređaj, tuđi uređaj → 403, Počinjem pokrene mjerač,
Gotovo završi zadatak (+ upis u povijest_rada) i vrati 'nema više zadataka'.
"""
import os
import sys
import types
from pathlib import Path

_REQ = types.SimpleNamespace(base_url="https://x/")   # lažni Request za z_gotovo/z_dijelovi

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@contextmanager
def ocekuj_http(status):
    """Mali zamjenik za pytest.raises — radi i kao obična skripta i pod pytestom."""
    try:
        yield
    except HTTPException as e:
        assert e.status_code == status, f"očekivan {status}, dobiven {e.status_code}"
        return
    raise AssertionError(f"očekivana HTTPException {status}, nije podignuta")

from app.database import Base
from app.models import (
    Korisnik, MehanicarLink, Nalog, Operacija, PovijestRada, StatusNaloga, Uloga, Vozilo, Zadatak,
)
from app.routers.dispecer import UredjajIn, posalji_poveznicu, z_gotovo, z_pocinjem, z_stanje


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _priprema(db):
    meh = Korisnik(ime="Test Meh", korisnicko_ime="test.meh", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T777", registracija="ZG0000TT", marka="MAN", model="TGS")
    db.add_all([meh, voz]); db.flush()
    nalog = Nalog(broj="RN-D-1", vozilo_id=voz.id, naslov="Test", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(nalog); db.flush()
    op = Operacija(nalog_id=nalog.id, kategorija="KOČNICE")
    db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="Zamjena pločica", ceka_potvrdu=True)
    z.radnici = [meh]
    db.add(z)
    link = MehanicarLink(radnik_id=meh.id, token="tok123", aktivan=True)
    db.add(link); db.commit()
    return meh, z


def test_tok_pocinjem_gotovo():
    db = _session()
    meh, z = _priprema(db)

    # stanje — veže prvi uređaj "A" i vraća zadatak
    s = z_stanje("tok123", UredjajIn(uredjaj="A"), db=db)
    assert s["zadatak_id"] == z.id
    assert s["gb"] == "T777"
    assert s["stanje"] == "ceka"

    # tuđi uređaj "B" → 403
    with ocekuj_http(403):
        z_stanje("tok123", UredjajIn(uredjaj="B"), db=db)

    # Počinjem (uređaj A) → mjerač radi
    s2 = z_pocinjem("tok123", UredjajIn(uredjaj="A"), db=db)
    assert s2["stanje"] == "radu"

    # Gotovo → nema više zadataka + upis u povijest_rada
    s3 = z_gotovo("tok123", UredjajIn(uredjaj="A"), request=_REQ, db=db)
    assert s3.get("nema") is True
    db.refresh(z)
    assert z.gotovo is True
    assert db.query(PovijestRada).count() == 1


def test_pocinjem_ne_gubi_red_i_gotovo_vraca_sljedeci():
    """Kad mehaničar ima više dodijeljenih zadataka: Počinjem na prvom NE smije
    odjaviti radnika s ostalih (red čekanja), a Gotovo mora odmah vratiti sljedeći."""
    db = _session()
    meh = Korisnik(ime="Meh Q", korisnicko_ime="meh.q", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T2", marka="MAN"); db.add_all([meh, voz]); db.flush()
    n = Nalog(broj="RN-Q", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op1 = Operacija(nalog_id=n.id, kategorija="A", redoslijed=1)
    op2 = Operacija(nalog_id=n.id, kategorija="B", redoslijed=2); db.add_all([op1, op2]); db.flush()
    z1 = Zadatak(operacija_id=op1.id, opis="PRVI", ceka_potvrdu=True); z1.radnici = [meh]
    z2 = Zadatak(operacija_id=op2.id, opis="DRUGI"); z2.radnici = [meh]   # u redu
    db.add_all([z1, z2])
    db.add(MehanicarLink(radnik_id=meh.id, token="tq", aktivan=True)); db.commit()

    z_pocinjem("tq", UredjajIn(uredjaj="A"), db=db)
    db.refresh(z2)
    assert [r.id for r in z2.radnici] == [meh.id], "Počinjem ne smije odjaviti radnika iz reda"

    r = z_gotovo("tq", UredjajIn(uredjaj="A"), request=_REQ, db=db)
    assert r.get("nema") is not True
    assert r.get("opis") == "DRUGI", "Gotovo mora odmah vratiti sljedeći zadatak iz reda"


def test_test_posalji_odbija_bez_test_broja():
    """Sigurnost: probna poruka se NE šalje ako dispecer_test_broj nije postavljen
    (da nikad ne ode pravom mehaničaru)."""
    from app.config import settings as st
    from app.routers.dispecer import test_posalji
    db = _session()
    _priprema(db)
    staro = st.dispecer_test_broj
    st.dispecer_test_broj = ""
    try:
        with ocekuj_http(400):
            test_posalji(db=db)
    finally:
        st.dispecer_test_broj = staro


def test_test_posalji_salje_na_test_broj():
    """S postavljenim test brojem probna poruka ide kroz posalji_poveznicu
    (ne dira nijedan zadatak)."""
    from app.config import settings as st
    from app.routers.dispecer import test_posalji
    db = _session()
    _priprema(db)
    staro = (st.dispecer_test_broj, st.dispecer_wa_on, st.bravel_agent_url, st.bravel_agent_kljuc)
    st.dispecer_test_broj = "385911111111"
    st.dispecer_wa_on = True
    st.bravel_agent_url = "https://agent.example"
    st.bravel_agent_kljuc = "k"
    pozvano = {}
    import httpx as _httpx
    orig_post = _httpx.post

    def _fake_post(url, json=None, headers=None, timeout=None):
        pozvano["to"] = (json or {}).get("broj")

        class R:
            status_code = 200
            text = "ok"

            def json(self):
                return {"ok": True}
        return R()

    _httpx.post = _fake_post
    try:
        rez = test_posalji(db=db)
        assert rez["ok"] is True
        assert pozvano["to"] == "385911111111", "probna poruka mora ići na test broj"
        assert db.query(MehanicarLink).count() == 1, "test ne smije stvarati nove poveznice"
    finally:
        _httpx.post = orig_post
        st.dispecer_test_broj, st.dispecer_wa_on, st.bravel_agent_url, st.bravel_agent_kljuc = staro


def test_nije_gotovo_pauzira_i_cuva_vrijeme():
    """„Nije gotovo" (kraj smjene / promjena plana): zaustavi mjerač, zadatak OSTAJE
    nedovršen (pauza) s očuvanim vremenom — ne označava se gotovim."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from app.routers.dispecer import z_nije_gotovo
    db = _session()
    meh = Korisnik(ime="Meh P", korisnicko_ime="meh.p", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="TP", marka="MAN"); db.add_all([meh, voz]); db.flush()
    n = Nalog(broj="RN-P", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="RADIM", zapoceto=_dt.now(_tz.utc) - _td(minutes=5))
    z.radnici = [meh]; db.add(z)
    db.add(MehanicarLink(radnik_id=meh.id, token="tp", aktivan=True)); db.commit()

    r = z_nije_gotovo("tp", UredjajIn(uredjaj="A"), db=db)
    assert r.get("parkirano") is True
    db.refresh(z)
    assert z.gotovo is False, "nije-gotovo NE smije označiti zadatak gotovim"
    assert z.zapoceto is None, "mjerač mora biti zaustavljen"
    assert (z.utroseno_sek or 0) > 0, "utrošeno vrijeme mora biti spremljeno"


def test_nije_gotovo_promjena_plana_vraca_sljedeci():
    """Promjena plana tijekom dana: 'Nije gotovo' pauzira trenutni i prebaci na
    sljedeći zadatak (ne staje), a pauzirani ostaje nedovršen s očuvanim vremenom."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from app.routers.dispecer import z_nije_gotovo
    db = _session()
    meh = Korisnik(ime="Meh PP", korisnicko_ime="meh.pp", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="TPP", marka="MAN"); db.add_all([meh, voz]); db.flush()
    n = Nalog(broj="RN-PP", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op1 = Operacija(nalog_id=n.id, kategorija="A", redoslijed=1)
    op2 = Operacija(nalog_id=n.id, kategorija="B", redoslijed=2); db.add_all([op1, op2]); db.flush()
    z1 = Zadatak(operacija_id=op1.id, opis="TRENUTNI", zapoceto=_dt.now(_tz.utc) - _td(minutes=5))
    z1.radnici = [meh]
    z2 = Zadatak(operacija_id=op2.id, opis="SLJEDECI"); z2.radnici = [meh]
    db.add_all([z1, z2])
    db.add(MehanicarLink(radnik_id=meh.id, token="tpp", aktivan=True)); db.commit()

    r = z_nije_gotovo("tpp", UredjajIn(uredjaj="A"), db=db)
    assert r.get("opis") == "SLJEDECI", "nije-gotovo (promjena plana) mora prebaciti na sljedeći"
    db.refresh(z1)
    assert z1.gotovo is False and z1.zapoceto is None, "trenutni ostaje nedovršen i pauziran"
    assert (z1.utroseno_sek or 0) > 0, "vrijeme trenutnog mora biti spremljeno"


def _meh_s_pokrenutim(db, token="ts"):
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    meh = Korisnik(ime="Meh S", korisnicko_ime="meh.s", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="TS", marka="MAN"); db.add_all([meh, voz]); db.flush()
    n = Nalog(broj="RN-S", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="A"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="RADIM", zapoceto=_dt.now(_tz.utc) - _td(minutes=5))
    z.radnici = [meh]; db.add(z)
    db.add(MehanicarLink(radnik_id=meh.id, token=token, aktivan=True)); db.commit()
    return meh, z


def test_smjena_ostajem_ne_dira_zadatak():
    from app.routers.dispecer import SmjenaIn, z_smjena
    db = _session()
    meh, z = _meh_s_pokrenutim(db)
    r = z_smjena("ts", SmjenaIn(uredjaj="A", odgovor="ostajem"), db=db)
    assert r.get("zadatak_id") == z.id, "ostajem → vraća trenutni zadatak"
    db.refresh(z)
    assert z.zapoceto is not None and z.gotovo is False, "ostajem NE smije dirati zadatak"
    assert db.query(MehanicarLink).first().smjena_odgovor == "ostajem"


def test_smjena_gotov_zatvara_kao_nije_gotovo():
    from app.routers.dispecer import SmjenaIn, z_smjena
    db = _session()
    meh, z = _meh_s_pokrenutim(db)
    r = z_smjena("ts", SmjenaIn(uredjaj="A", odgovor="gotov"), db=db)
    assert r.get("gotov_za_danas") is True
    db.refresh(z)
    assert z.gotovo is False, "gotov za danas NE označava zadatak gotovim"
    assert z.zapoceto is None, "mjerač mora biti zaustavljen"
    assert (z.utroseno_sek or 0) > 0, "vrijeme mora biti spremljeno"
    assert db.query(MehanicarLink).first().smjena_odgovor == "gotov"


def test_kraj_sat_po_danu():
    from datetime import datetime
    from app.kraj_smjene import _kraj_sat
    assert _kraj_sat(datetime(2026, 10, 26, 10, 0)) == 15   # ponedjeljak
    assert _kraj_sat(datetime(2026, 10, 30, 10, 0)) == 15   # petak
    assert _kraj_sat(datetime(2026, 10, 31, 10, 0)) == 14   # subota
    assert _kraj_sat(datetime(2026, 11, 1, 10, 0)) is None  # nedjelja


def test_test_tok_slaze_tri_zadatka():
    """Probni tok: test mehaničar + 3 zadatka, prvi 'čeka potvrdu', bez diranja
    pravih naloga; poveznica ode na test broj."""
    from app.config import settings as st
    from app.routers.dispecer import _TEST_MEH_KIME, _red, test_tok
    db = _session()
    staro = (st.dispecer_test_broj, st.dispecer_wa_on, st.bravel_agent_url, st.bravel_agent_kljuc)
    st.dispecer_test_broj = "385911111111"; st.dispecer_wa_on = True
    st.bravel_agent_url = "https://a"; st.bravel_agent_kljuc = "k"
    import httpx as _h
    orig = _h.post
    _h.post = lambda *a, **k: type("R", (), {"status_code": 200, "text": "ok",
                                             "json": lambda s: {"ok": True}})()
    try:
        r = test_tok(request=_REQ, db=db)
        assert r["zadataka"] == 3
        meh = db.query(Korisnik).filter(Korisnik.korisnicko_ime == _TEST_MEH_KIME).first()
        red = _red(db, meh)
        assert len(red) == 3, "mehaničar mora imati 3 probna zadatka u redu"
        assert red[0][2].ceka_potvrdu is True, "prvi mora biti na 'čeka potvrdu'"
    finally:
        _h.post = orig
        st.dispecer_test_broj, st.dispecer_wa_on, st.bravel_agent_url, st.bravel_agent_kljuc = staro


def test_red_hitno_ide_odmah_iza_u_tijeku():
    """HITNO nalog gurne svoje zadatke ODMAH iza onoga u tijeku, ispred ostalih
    (u tijeku se ne dira)."""
    from datetime import datetime as _dt, timezone as _tz
    from app.routers.dispecer import _red
    db = _session()
    meh = Korisnik(ime="Meh H", korisnicko_ime="meh.h", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="TH", marka="MAN"); db.add_all([meh, voz]); db.flush()
    nA = Nalog(broj="RN-A", vozilo_id=voz.id, naslov="A", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    nB = Nalog(broj="RN-B", vozilo_id=voz.id, naslov="B", kreirao_id=meh.id, status=StatusNaloga.u_radu, plan_hitno=True)
    db.add_all([nA, nB]); db.flush()
    opA1 = Operacija(nalog_id=nA.id, kategorija="A", redoslijed=1)
    opA2 = Operacija(nalog_id=nA.id, kategorija="A", redoslijed=2)
    opB = Operacija(nalog_id=nB.id, kategorija="B", redoslijed=1)
    db.add_all([opA1, opA2, opB]); db.flush()
    z_run = Zadatak(operacija_id=opA1.id, opis="U_TIJEKU", zapoceto=_dt.now(_tz.utc)); z_run.radnici = [meh]
    z_norm = Zadatak(operacija_id=opA2.id, opis="OBICNI"); z_norm.radnici = [meh]
    z_hit = Zadatak(operacija_id=opB.id, opis="HITNI"); z_hit.radnici = [meh]
    db.add_all([z_run, z_norm, z_hit]); db.commit()

    red = _red(db, meh)
    assert [t[2].opis for t in red] == ["U_TIJEKU", "HITNI", "OBICNI"]


def test_ugaseni_link_ne_radi():
    db = _session()
    meh, z = _priprema(db)
    link = db.query(MehanicarLink).first()
    link.aktivan = False
    db.commit()
    with ocekuj_http(404):
        z_stanje("tok123", UredjajIn(uredjaj="A"), db=db)


def _meh_sa_zadacima(db, broj_pripreme):
    """Mehaničar s 1 započetim zadatkom + `broj_pripreme` nezapočetih (u pripremi)."""
    from datetime import datetime, timezone
    meh = Korisnik(ime="Meh Z", korisnicko_ime="meh.z", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T900", marka="MAN")
    db.add_all([meh, voz]); db.flush()
    nalog = Nalog(broj="RN-Z-1", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(nalog); db.flush()
    op = Operacija(nalog_id=nalog.id, kategorija="MOTOR"); db.add(op); db.flush()
    from datetime import datetime as _dt, timezone as _tz
    z0 = Zadatak(operacija_id=op.id, opis="radni", zapoceto=_dt.now(_tz.utc)); z0.radnici = [meh]
    db.add(z0)
    for i in range(broj_pripreme):
        zi = Zadatak(operacija_id=op.id, opis=f"priprema {i}"); zi.radnici = [meh]
        db.add(zi)
    db.commit()
    return meh


def test_zaliha_javi_kad_niska_i_ne_javi_kad_dovoljna():
    import app.routers.dispecer as d
    orig = d.obavijesti_ulogu
    # niska zaliha (1 u pripremi, prag 2) → javi jednom
    db = _session()
    meh = _meh_sa_zadacima(db, 1)
    pozivi = []
    d.obavijesti_ulogu = lambda *a, **k: pozivi.append(1)
    try:
        d.provjeri_zalihu(db, meh)
    finally:
        d.obavijesti_ulogu = orig
    assert len(pozivi) == 1, "niska zaliha mora javiti poslovođi"

    # dovoljna zaliha (2 u pripremi, prag 2) → ne javi
    db2 = _session()
    meh2 = _meh_sa_zadacima(db2, 2)
    pozivi2 = []
    d.obavijesti_ulogu = lambda *a, **k: pozivi2.append(1)
    try:
        d.provjeri_zalihu(db2, meh2)
    finally:
        d.obavijesti_ulogu = orig
    assert len(pozivi2) == 0, "dovoljna zaliha ne smije javljati"


def test_slanje_ugaseno_ne_salje_ni_ne_stvara_token():
    """Sigurnosna garancija: dok je dispecer_wa_on False, posalji_poveznicu NE šalje
    i NE stvara poveznicu (nijedan MehanicarLink)."""
    db = _session()
    meh = Korisnik(ime="Test Meh", korisnicko_ime="test.meh", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(meh); db.commit()
    rez = posalji_poveznicu(db, meh, "T777", "Zamjena pločica", "https://x/")
    assert rez["poslano"] is False
    assert db.query(MehanicarLink).count() == 0


def test_dio_stigao_vraca_zadatak():
    """Zadatak koji čeka dijelove → dio_stigao → izlazi iz 'čeka dijelove' i ide
    mehaničaru na potvrdu (ceka_potvrdu)."""
    import types
    from app.routers.dispecer import ceka_dijelove, dio_stigao
    db = _session()
    meh = Korisnik(ime="Meh D", korisnicko_ime="meh.d", lozinka_hash="x", uloga=Uloga.radnik)
    voz = Vozilo(gb="T555", marka="MAN")
    db.add_all([meh, voz]); db.flush()
    nalog = Nalog(broj="RN-D-9", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(nalog); db.flush()
    op = Operacija(nalog_id=nalog.id, kategorija="MOTOR"); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="Zamjena [naručen dio: filter]", razlog_prekida="dijelovi")
    z.radnici = [meh]
    db.add(z); db.commit()

    lista = ceka_dijelove(gb="T555", db=db)
    assert len(lista) == 1 and lista[0]["zadatak_id"] == z.id
    assert lista[0]["dio"] == "filter"

    dio_stigao(z.id, types.SimpleNamespace(base_url="https://x/"), db=db)
    db.refresh(z)
    assert z.razlog_prekida is None
    assert z.ceka_potvrdu is True


if __name__ == "__main__":
    test_tok_pocinjem_gotovo()
    test_ugaseni_link_ne_radi()
    test_zaliha_javi_kad_niska_i_ne_javi_kad_dovoljna()
    test_slanje_ugaseno_ne_salje_ni_ne_stvara_token()
    test_dio_stigao_vraca_zadatak()
    print("OK — dispečer testovi prošli")
