"""Test jutarnjeg auto-slanja plana: jezgra 'Pošalji sve' (preskače odsutne, vec_poslano),
zakazivanje termina (danas/sutra) i pozadinski tik (okida na vrijeme, propušteno ne šalje).

Slanje WhatsAppa je isključeno (dispecer_wa_on False) — provjeravamo samo logiku i stanje."""
import os
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import auto_slanje as auto_mod
from app import norme
from app.database import Base
from app.models import Korisnik, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak
from app.routers.plan import (
    AutoSlanjeIn, KLJUC_AUTO_DATUM, KLJUC_AUTO_HHMM, auto_slanje as arm_auto,
    posalji_sve_plan, _hr_now,
)


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _plan_nalog(db, meh, broj="RN-A-1", gb="TA1", rang=1):
    voz = Vozilo(gb=gb, marka="MAN"); db.add(voz); db.flush()
    n = Nalog(broj=broj, vozilo_id=voz.id, naslov="T", kreirao_id=meh.id,
              status=StatusNaloga.u_radu, plan_rang=rang)
    db.add(n); db.flush()
    op = Operacija(nalog_id=n.id, kategorija="MOTOR", redoslijed=1); db.add(op); db.flush()
    z = Zadatak(operacija_id=op.id, opis="posao"); z.radnici = [meh]
    db.add(z); db.commit()
    return n, z


def test_posalji_sve_preskace_odsutne():
    """Odsutan mehaničar se preskače; prisutnom se prvi zadatak stavi na čekanje."""
    db = _session()
    pris = Korisnik(ime="Prisutni", korisnicko_ime="pris", lozinka_hash="x", uloga=Uloga.radnik)
    ods = Korisnik(ime="Odsutni", korisnicko_ime="ods", lozinka_hash="x", uloga=Uloga.radnik,
                   odsutnost_vrsta="godisnji")
    db.add_all([pris, ods]); db.flush()
    _n1, z1 = _plan_nalog(db, pris, broj="RN-A-1", gb="TA1", rang=1)
    _n2, z2 = _plan_nalog(db, ods, broj="RN-A-2", gb="TA2", rang=2)

    rez = posalji_sve_plan(db, "https://x/")
    assert rez["mehanicara"] == 2
    assert rez["odsutni"] == 1
    db.refresh(z1); db.refresh(z2)
    assert z1.ceka_potvrdu is True      # prisutni → na čekanje
    assert z2.ceka_potvrdu is False     # odsutni → preskočen


def test_posalji_sve_ne_duplira():
    """Drugi poziv ne dira onoga kome je već poslano (ceka_potvrdu)."""
    db = _session()
    meh = Korisnik(ime="Meh", korisnicko_ime="meh", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(meh); db.flush()
    _n, z = _plan_nalog(db, meh)

    r1 = posalji_sve_plan(db, "https://x/")
    assert r1["vec_poslano"] == 0
    r2 = posalji_sve_plan(db, "https://x/")
    assert r2["vec_poslano"] == 1       # drugi put preskočen (već poslano)


def test_arm_racuna_datum():
    """Zakazivanje: ako je vrijeme danas prošlo → sutra; inače danas."""
    db = _session()
    vlasnik = Korisnik(ime="Vlasnik", korisnicko_ime="vl", lozinka_hash="x", uloga=Uloga.voditelj)
    db.add(vlasnik); db.flush()
    now = _hr_now()
    # vrijeme sigurno PROŠLO danas (00:00, osim u ponoćnoj minuti) → sutra
    if (now.hour, now.minute) > (0, 0):
        r = arm_auto(AutoSlanjeIn(ukljuceno=True, ura="00:00"), _=vlasnik, db=db)
        assert r["ura"] == "00:00"
        assert r["datum"] == (now.date() + timedelta(days=1)).isoformat()
    assert norme.get_postavka(db, KLJUC_AUTO_HHMM) == "00:00" or now.hour == 0
    # gašenje čisti postavke
    arm_auto(AutoSlanjeIn(ukljuceno=False), _=vlasnik, db=db)
    assert not norme.get_postavka(db, KLJUC_AUTO_HHMM)
    assert not norme.get_postavka(db, KLJUC_AUTO_DATUM)


def test_tik_salje_kad_dodje_vrijeme():
    """Zakazano za danas u 00:00 (prošlo) → tik okine i očisti zakazano."""
    db = _session()
    meh = Korisnik(ime="Meh T", korisnicko_ime="meht", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(meh); db.flush()
    _n, z = _plan_nalog(db, meh)
    norme.set_postavka(db, KLJUC_AUTO_HHMM, "00:00")
    norme.set_postavka(db, KLJUC_AUTO_DATUM, _hr_now().date().isoformat())
    db.commit()

    auto_mod._tik(db)
    db.refresh(z)
    assert z.ceka_potvrdu is True                       # okinulo slanje (stanje posloženo)
    assert not norme.get_postavka(db, KLJUC_AUTO_HHMM)  # jednokratno → očišćeno
    assert not norme.get_postavka(db, KLJUC_AUTO_DATUM)


def test_tik_ne_salje_propusteno():
    """Zakazani dan je PROŠAO (server bio dolje) → ne šalje naknadno, samo očisti."""
    db = _session()
    meh = Korisnik(ime="Meh P", korisnicko_ime="mehp", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(meh); db.flush()
    _n, z = _plan_nalog(db, meh)
    norme.set_postavka(db, KLJUC_AUTO_HHMM, "06:45")
    norme.set_postavka(db, KLJUC_AUTO_DATUM, (date.today() - timedelta(days=2)).isoformat())
    db.commit()

    auto_mod._tik(db)
    db.refresh(z)
    assert z.ceka_potvrdu is False                      # NIŠTA nije poslano
    assert not norme.get_postavka(db, KLJUC_AUTO_DATUM)  # očišćeno


if __name__ == "__main__":
    test_posalji_sve_preskace_odsutne()
    test_posalji_sve_ne_duplira()
    test_arm_racuna_datum()
    test_tik_salje_kad_dodje_vrijeme()
    test_tik_ne_salje_propusteno()
    print("OK — auto-slanje testovi prošli")
