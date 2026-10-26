"""Test „Nalog isplaniran" (jedan gumb): svakom mehaničaru pošalje PRVI zadatak
(ide na čekanje potvrde), a ostale zadatke ostavi u redu čekanja.

Slanje WhatsAppa je isključeno (dispecer_wa_on False) — provjeravamo samo da se
stanje zadataka posloži kako treba (ništa se ne šalje van)."""
import os
import sys
import types
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Korisnik, MehanicarLink, Nalog, Operacija, StatusNaloga, Uloga, Vozilo, Zadatak,
)
from app.routers.plan import isplaniraj


def _session():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def _nalog_s_dva(db, meh):
    voz = Vozilo(gb="T321", marka="MAN", model="TGS")
    db.add(voz); db.flush()
    n = Nalog(broj="RN-P-1", vozilo_id=voz.id, naslov="T", kreirao_id=meh.id, status=StatusNaloga.u_radu)
    db.add(n); db.flush()
    op1 = Operacija(nalog_id=n.id, kategorija="MOTOR", redoslijed=1)
    op2 = Operacija(nalog_id=n.id, kategorija="KOČNICE", redoslijed=2)
    db.add_all([op1, op2]); db.flush()
    z1 = Zadatak(operacija_id=op1.id, opis="prvi"); z1.radnici = [meh]
    z2 = Zadatak(operacija_id=op2.id, opis="drugi"); z2.radnici = [meh]
    db.add_all([z1, z2])
    db.add(MehanicarLink(radnik_id=meh.id, token="tokP", aktivan=True))
    db.commit()
    return n, z1, z2


def test_isplaniraj_salje_prvi_ostale_u_red():
    db = _session()
    meh = Korisnik(ime="Meh A", korisnicko_ime="meh.a", lozinka_hash="x", uloga=Uloga.radnik)
    db.add(meh); db.flush()
    n, z1, z2 = _nalog_s_dva(db, meh)

    req = types.SimpleNamespace(base_url="https://x/")
    r = isplaniraj(n.id, req, korisnik=meh, db=db)
    assert r["ok"] is True
    assert r["mehanicara"] == 1       # jedan mehaničar na nalogu
    assert r["poslano"] == 0          # slanje isključeno → ništa ne ode van

    db.refresh(z1); db.refresh(z2)
    assert z1.ceka_potvrdu is True    # prvi (po redoslijedu) ide na potvrdu/slanje
    assert z2.ceka_potvrdu is False   # drugi ostaje u redu čekanja
    assert z1.gotovo is False and z2.gotovo is False


if __name__ == "__main__":
    test_isplaniraj_salje_prvi_ostale_u_red()
    print("OK — isplaniraj test prošao")
