"""Test dispečera: login-less tok zadatka (token + vezanje uređaja + 3 akcije).

Pokriva: stanje veže prvi uređaj, tuđi uređaj → 403, Počinjem pokrene mjerač,
Gotovo završi zadatak (+ upis u povijest_rada) i vrati 'nema više zadataka'.
"""
import os
import sys
from pathlib import Path

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
    s3 = z_gotovo("tok123", UredjajIn(uredjaj="A"), db=db)
    assert s3.get("nema") is True
    db.refresh(z)
    assert z.gotovo is True
    assert db.query(PovijestRada).count() == 1


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


if __name__ == "__main__":
    test_tok_pocinjem_gotovo()
    test_ugaseni_link_ne_radi()
    test_zaliha_javi_kad_niska_i_ne_javi_kad_dovoljna()
    test_slanje_ugaseno_ne_salje_ni_ne_stvara_token()
    print("OK — dispečer testovi prošli")
